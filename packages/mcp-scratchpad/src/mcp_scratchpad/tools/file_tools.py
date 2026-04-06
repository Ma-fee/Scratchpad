"""
FastMCP file operation tools implementation with enhanced error handling
Refactored from existing handler functions using decorator pattern
"""

from __future__ import annotations

import datetime
import hashlib
import logging
from typing import TYPE_CHECKING, Annotated, Any

# from deepagents import create_deep_agent
from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import BaseModel, Field

from ..config import config
from ..diff_utils import apply_unified_diff
from ..exceptions import (
    FileTooLargeError,
    PermissionDeniedError,
    ScratchpadFileNotFoundError,
    ValidationError,
)
from ..models import (
    FileReadSlice,
    ReadFileRequest,
    RemoveFileRequest,
    WriteFileRequest,
)
from ..path_resolver import (
    PathResolutionError,
    build_uri,
    get_path_description,
    resolve_file_path,
)
from ..storage import FileRecord, get_store
from ..utils import (
    build_error_xml,
    build_file_content_xml,
    build_file_list_xml,
    build_file_operation_xml,
    create_tool_result_xml,
    normalize_path,
)
from .apply_diff import register_apply_diff
from .edit import register_edit
from .read import register_read

if TYPE_CHECKING:
    from ..fs import SessionFileSystemManager

logger = logging.getLogger(__name__)


class FileRequest(BaseModel):
    file_path: str = Field(description="The full path of the file to be read.")
    start_line: int | None = Field(
        default=None,
        description="Start line anchor for partial reading, defaults to the first line if not provided.",
    )
    end_line: int | None = Field(
        default=None,
        description="End line anchor for partial reading, defaults to the end of the file if not provided.",
    )


def _validate_list_inputs(session_id: str) -> None:
    """Validate inputs for list_files operation"""
    if not session_id or not session_id.strip():
        raise ValidationError("Session ID cannot be empty")


def _build_list_summary(records: list) -> str:
    """Build summary string for file listing"""
    summary_lines = [f"Found {len(records)} files"]

    if records:
        summary_lines.extend(
            [
                "ID | Path | Permission | Persistent | Version | Updated",
                "-- | ---- | --------- | --------- | ------- | ------",
            ]
        )
        preview_limit = min(len(records), 10)
        for idx, record in enumerate(records[:preview_limit], start=1):
            summary_lines.append(
                f"{idx} | {record.file_path} | {record.permission} | {'Yes' if record.persistent else 'No'} | v{record.version} | {record.updated_at.isoformat()}Z"
            )

    return "\n".join(summary_lines)


def _validate_read_session(session_id: str) -> None:
    """Validate session ID for read operations"""
    if not session_id or not session_id.strip():
        raise ValidationError("Session ID cannot be empty")


def _convert_file_requests(
    file_requests: list[dict[str, Any]] | None,
) -> list[FileReadSlice] | None:
    """Convert file_requests from Dict to FileReadSlice"""
    if not file_requests:
        return None
    return [
        FileReadSlice(**req) if isinstance(req, dict) else req for req in file_requests
    ]


def _validate_and_normalize_paths(requests: list[FileReadSlice]) -> list[str]:
    """Validate and normalize file paths"""
    normalized_paths = []
    for req in requests:
        try:
            normalized_paths.append(normalize_path(req.file_path))
        except ValueError as exc:
            raise ValidationError(
                f"Invalid file path '{req.file_path}': {exc}"
            ) from exc
    return normalized_paths


def _process_file_results(
    requests: list[FileReadSlice],
    normalized_paths: list[str],
    ok_records: list,
    failed: list,
) -> tuple[list, list]:
    """Process file read results and build response structures

    Raises:
        ScratchpadFileNotFoundError: When any requested file is not found or failed to read
    """
    record_map = {record.file_path: record for record in ok_records}
    failed_set = set(failed)

    structured_files = []

    for _idx, (req, normalized) in enumerate(
        zip(requests, normalized_paths, strict=False), start=1
    ):
        if not normalized or normalized in failed_set:
            error_msg = (
                f"File not found: {req.file_path}"
                if normalized
                else f"Invalid file name: {req.file_path}"
            )
            raise ScratchpadFileNotFoundError(error_msg)

        record = record_map.get(normalized)
        if not record:
            raise ScratchpadFileNotFoundError(f"File missing: {normalized}")

        # Extract content slice
        snippet, (start, end) = _extract_content_slice(
            record.content, req.start_line, req.end_line
        )

        meta = record.to_metadata()
        meta.update(
            {
                "status": "ok",
                "requested_start_line": req.start_line,
                "requested_end_line": req.end_line,
                "start_line": start,
                "end_line": end,
                "content": snippet,  # 直接添加内容，不使用 build_file_block
            }
        )
        structured_files.append(meta)

    return (
        [],
        structured_files,
    )  # 返回空的 content_blocks，因为内容已经包含在 structured_files 中


def _file_info_to_record(file_path: str, info: dict[str, Any]) -> FileRecord:
    """Convert filesystem info dict to FileRecord.

    Args:
        file_path: The file path within the session.
        info: Filesystem info dict from fsspec.

    Returns:
        FileRecord with available metadata.
    """
    from datetime import datetime, timezone

    # Extract name from path
    name = file_path.split("/")[-1] if "/" in file_path else file_path

    # Get modification time
    mtime = info.get("mtime") or info.get("modified")
    updated_at = (
        datetime.fromtimestamp(mtime, tz=timezone.utc)
        if mtime
        else datetime.now(timezone.utc)
    )
    created_at = updated_at  # Use updated as fallback

    # Get size
    size = info.get("size", 0) or 0

    # Determine layer (0 = upper/writable, 1+ = lower/readonly)
    layer = info.get("_layer", 0)
    is_writable = layer == 0

    # For overlay files, we can't easily determine persistent/permission
    # without additional metadata. Default to non-persistent, read_write.
    # Store uri in a special marker (returned via extra_data in to_metadata)
    record = FileRecord(
        file_path=file_path,
        name=name,
        content="",  # Not loaded for listing
        persistent=False,  # Overlay files are not tracked as persistent
        permission="read_write" if is_writable else "read",
        created_at=created_at,
        updated_at=updated_at,
        size=size,
        version=1,  # Overlay doesn't track versions
    )

    return record


async def _list_files_tool(
    ctx: Context,
    session_manager: SessionFileSystemManager | None,
    persistent: bool | None = None,
    keyword: str | None = None,
    session_id: str | None = None,
) -> ToolResult:
    """List files with various filtering options from overlay filesystem.

    Lists files from both the overlay filesystem (including all mounted layers)
    and the FileSystemStore workspace.
    """
    logger.info("Listing files")
    await ctx.info("Listing files")

    await ctx.report_progress(25, 100, "Fetching file list")

    all_records: list[FileRecord] = []
    effective_session_id = session_id or get_store().session_id
    # Store extra metadata for overlay files: file_path -> {line_count, uri}
    extra_metadata: dict[str, dict[str, Any]] = {}

    # 1. First, get files from FileSystemStore (writable workspace)
    store = get_store()
    if store and hasattr(store, "list_files"):
        store_records = store.list_files(
            persistent=persistent,
            keyword=keyword,
            namespace=None,
            agent_name=None,
        )
        all_records.extend(store_records)

    await ctx.report_progress(50, 100, "Scanning overlay filesystem")

    # 2. Get files from overlay filesystem (all layers)
    if session_manager:
        try:
            # List files from all configured mounts
            for mount in session_manager.config.mounts:
                if mount.name not in session_manager._mounts:
                    continue

                fs = session_manager._mounts[mount.name]
                # Get mount path from the separate dict (LocalFileSystem is singleton)
                mount_path = session_manager._mount_paths.get(mount.name)
                if not mount_path:
                    continue

                # Scan this mount's filesystem
                mount_files = _list_local_fs_recursive(
                    fs, mount_path, mount.mount_point, effective_session_id
                )

                # Convert to FileRecord objects
                for file_path, info in mount_files.items():
                    # Skip metadata files
                    if ".metadata.json" in file_path:
                        continue

                    record = _file_info_to_record(file_path, info)
                    record.permission = "read" if mount.mode == "ro" else "read_write"

                    # Store extra metadata for this overlay file
                    extra_metadata[record.file_path] = {
                        "line_count": info.get("line_count", 0),
                        "uri": info.get("uri"),
                    }

                    # Filter by keyword if specified
                    if keyword and keyword not in record.name:
                        continue

                    # Check if already exists in store_records (avoid duplicates)
                    existing = next(
                        (r for r in all_records if r.file_path == record.file_path),
                        None,
                    )
                    if not existing:
                        all_records.append(record)

        except Exception as e:
            logger.warning(f"Failed to list overlay files: {e}")

    await ctx.report_progress(75, 100, "Processing results")

    # Sort by updated_at (most recent first)
    all_records.sort(key=lambda r: r.updated_at, reverse=True)

    # Build response with extra overlay metadata
    structured_files = []
    for record in all_records:
        metadata = record.to_metadata()
        # Add overlay-specific metadata if available
        if record.file_path in extra_metadata:
            extra = extra_metadata[record.file_path]
            if extra.get("line_count", 0) > 0:
                metadata["line_count"] = extra["line_count"]
            if extra.get("uri"):
                metadata["uri"] = extra["uri"]
        structured_files.append(metadata)

    await ctx.report_progress(100, 100, "File listing completed")

    # 构建元数据
    metadata = {
        "total_files": len(all_records),
        "persistent_filter": persistent,
        "keyword_filter": keyword,
    }

    # 为每个文件生成独立的 XML 片段
    xml_contents = build_file_list_xml(structured_files, metadata)

    # 创建并返回 ToolResult，每个文件作为独立的 TextContent
    return create_tool_result_xml(xml_contents=xml_contents, structured_data=metadata)


def _list_overlay_files_recursive(
    fs: Any,
    path: str,
    result: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Recursively list all files in the overlay filesystem.

    Args:
        fs: The fsspec filesystem instance.
        path: The current path to scan.
        result: Accumulator dict mapping file_path -> info.

    Returns:
        Dict mapping file paths to their info dicts.
    """
    if result is None:
        result = {}

    try:
        # Get directory listing with details
        entries = fs.ls(path, detail=True)

        for entry in entries:
            # Handle both dict and string formats
            if isinstance(entry, dict):
                name = entry.get("name", "")
                is_dir = entry.get("type") == "directory" or entry.get(
                    "is_directory", False
                )
            else:
                name = str(entry)
                is_dir = fs.isdir(name)

            # Skip hidden/system files
            basename = name.split("/")[-1] if "/" in name else name
            if basename.startswith("."):
                continue

            if is_dir:
                # Recurse into subdirectory
                _list_overlay_files_recursive(fs, name, result)
            else:
                # It's a file - store its info
                # Get info if not already a dict
                if isinstance(entry, dict):
                    info = entry
                else:
                    try:
                        info = fs.info(name)
                    except Exception:
                        info = {"name": name, "size": 0}

                # Store relative path (remove leading /)
                rel_path = name.lstrip("/")
                if rel_path:
                    result[rel_path] = info

    except Exception as e:
        logger.debug(f"Error listing overlay path {path}: {e}")

    return result


def _list_local_fs_recursive(
    fs: Any, base_path: str, mount_point: str, session_id: str | None = None
) -> dict[str, dict[str, Any]]:
    """List files from a local filesystem mount.

    Args:
        fs: The fsspec filesystem (not used for local, but kept for API consistency)
        base_path: The local directory path
        mount_point: The mount point in the overlay (e.g., "/.claude/skills")

    Returns:
        Dict mapping file paths to info dicts
    """
    result: dict[str, dict[str, Any]] = {}

    try:
        from pathlib import Path

        base = Path(base_path)
        if not base.exists():
            return result

        for path in base.rglob("*"):
            if path.is_file() and path.name != ".metadata.json":
                # Calculate relative path within mount
                rel_path = path.relative_to(base).as_posix()

                # Build full path with mount_point
                if mount_point and mount_point != "/":
                    full_path = f"{mount_point}/{rel_path}"
                else:
                    full_path = f"/{rel_path}"

                # Read content to calculate line_count (for small files only)
                line_count = 0
                try:
                    if path.stat().st_size < 1024 * 1024:  # Only for files < 1MB
                        content = path.read_text(encoding="utf-8", errors="ignore")
                        line_count = content.count("\n") + 1 if content else 1
                except Exception:
                    pass

                # Build canonical URI
                effective_session_id = session_id or get_store().session_id
                uri = build_uri(full_path, session_id=effective_session_id)

                result[full_path] = {
                    "name": str(path),
                    "size": path.stat().st_size,
                    "mtime": path.stat().st_mtime,
                    "type": "file",
                    "line_count": line_count,
                    "uri": uri,
                }
    except Exception as e:
        logger.debug(f"Error listing local fs {base_path}: {e}")

    return result


async def _read_file_tool(
    ctx: Context,
    file_paths: list[str] | None = None,
    file_requests: list[dict[str, Any]] | None = None,
) -> ToolResult:
    """Read file content, supporting single or multiple files"""
    logger.info("Reading file content")
    await ctx.info("Reading file content")

    # Build request object
    converted_file_requests = _convert_file_requests(file_requests)
    request = ReadFileRequest(
        file_paths=file_paths,
        file_requests=converted_file_requests,
    )

    await ctx.report_progress(25, 100, "Validating file paths")

    # Parse requests and validate paths
    requests = _resolve_requests(request)
    normalized_paths = _validate_and_normalize_paths(requests)

    await ctx.report_progress(50, 100, "Reading files")

    # Read files
    valid_unique_paths = _deduplicate([p for p in normalized_paths if p])
    ok_records, failed = get_store().read_files(valid_unique_paths)

    await ctx.report_progress(75, 100, "Processing results")

    # Process results
    content_blocks, structured_files = _process_file_results(
        requests, normalized_paths, ok_records, failed
    )

    await ctx.report_progress(100, 100, "File reading completed")

    # 构建元数据
    metadata = {
        "total_files": len(structured_files),
        "file_paths": file_paths,
        "file_requests_count": len(file_requests) if file_requests else 0,
    }

    # 为每个文件生成独立的 XML 片段
    xml_contents = build_file_content_xml(structured_files, metadata)

    # 创建并返回 ToolResult，每个文件作为独立的 TextContent
    return create_tool_result_xml(xml_contents=xml_contents, structured_data=metadata)


async def _write_file_tool(
    ctx: Context,
    file_path: str,
    content: str = "",
    expected_version: int | None = None,
    permission: str | None = None,
    overwrite: bool = True,
    persistent: bool = False,
) -> ToolResult:
    """Write file content"""
    logger.info(f"Writing file: {file_path}")
    await ctx.info(f"Writing file: {file_path}")

    # Validate inputs
    if not file_path or not file_path.strip():
        raise ValidationError("file_path is required")

    # Check file size
    content_size = len(content.encode("utf-8"))
    if content_size > config.max_file_size:
        raise FileTooLargeError(
            f"File size {content_size} exceeds maximum allowed size {config.max_file_size}"
        )

    await ctx.report_progress(25, 100, "Preparing to write")

    # Build request object
    request = WriteFileRequest(
        file_path=file_path,
        content=content,
        expected_version=expected_version,
        permission=permission,
        overwrite=overwrite,
        persistent=persistent,
    )

    # Determine target path using path_resolver
    try:
        resolved_path = resolve_file_path(
            request.file_path, get_store(), allow_absolute=True
        )
        target_path = str(resolved_path.relative_to(get_store()._session_dir()))
    except PathResolutionError as e:
        raise ValidationError(f"Invalid file path: {e}") from e

    await ctx.report_progress(50, 100, "Writing file")

    # Write file
    record = get_store().write_file(
        file_path=target_path,
        content=request.content,
        overwrite=request.overwrite,
        persistent=request.persistent,
        expected_version=request.expected_version,
        permission=request.permission,
    )

    await ctx.report_progress(100, 100, "File writing completed")

    operation = "created" if record.version == 1 else "updated"
    structured = record.to_metadata()
    structured.update({"operation": operation})

    # Add URI for the written file
    structured["uri"] = build_uri(record.file_path, session_id=get_store().session_id)

    # 转换为 XML
    xml_content = build_file_operation_xml(structured, "write")

    # 创建并返回 ToolResult
    return create_tool_result_xml(xml_contents=xml_content, structured_data=structured)


async def _remove_file_tool(
    ctx: Context,
    file_path: str,
    expected_version: int | None = None,
    force: bool = False,
) -> ToolResult:
    """Remove file"""
    logger.info(f"Removing file: {file_path}")
    await ctx.info(f"Removing file: {file_path}")

    # Validate inputs
    if not file_path or not file_path.strip():
        raise ValidationError("File path cannot be empty")

    # Resolve file path using path_resolver
    try:
        resolved_path = resolve_file_path(file_path, get_store(), allow_absolute=True)
        normalized_path = str(resolved_path.relative_to(get_store()._session_dir()))
    except PathResolutionError as e:
        raise ValidationError(f"Invalid file path: {e}") from e

    await ctx.report_progress(25, 100, "Validating permissions")

    # Check if trying to delete persistent file without force
    if not force:
        try:
            records, _ = get_store().read_files([normalized_path])
            if records and records[0].persistent:
                raise PermissionDeniedError(
                    f"Cannot delete persistent file '{file_path}' without force=True"
                )
        except Exception:
            # File might not exist, let the remove_file handle it
            pass

    await ctx.report_progress(50, 100, "Removing file")

    # Build request object
    request = RemoveFileRequest(
        file_path=normalized_path,
        expected_version=expected_version,
        force=force,
    )

    # Remove file
    removed = get_store().remove_file(
        path=request.file_path,
        expected_version=request.expected_version,
        force=request.force,
    )

    await ctx.report_progress(100, 100, "File removal completed")

    # Build response
    import datetime

    deleted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat() + "Z"

    result_data = {
        "file_path": removed.file_path,
        "name": removed.name,
        "deleted_at": deleted_at,
        "deleted_by": "user",
        "persistent_before": removed.persistent,
        "version": removed.version,
        "uri": build_uri(removed.file_path, session_id=get_store().session_id),
    }

    # 转换为 XML
    xml_content = build_file_operation_xml(result_data, "remove")

    # 创建并返回 ToolResult
    return create_tool_result_xml(xml_contents=xml_content, structured_data=result_data)


async def _apply_diff_tool(
    ctx: Context,
    file_path: str | None = None,
    diff: str | None = None,
    expected_version: int | None = None,
    validate_only: bool = False,
    file_patches: list[dict[str, Any]] | None = None,
    max_diff_lines: int | None = None,
) -> ToolResult:
    """Apply one or more unified diffs to existing files with optimistic locking."""
    patches = _normalize_patch_inputs(file_patches, file_path, diff)
    line_limit = config.max_diff_lines
    if max_diff_lines is not None:
        line_limit = (
            min(max_diff_lines, config.max_diff_lines)
            if config.max_diff_lines
            else max_diff_lines
        )
    byte_limit = config.max_diff_bytes

    xml_results: list[str] = []
    structured_files: list[dict[str, Any]] = []

    for patch in patches:
        xml_payload, structured_entry = await _process_single_diff(
            ctx=ctx,
            patch=patch,
            global_expected_version=expected_version,
            validate_only=validate_only,
            max_diff_lines=line_limit,
            max_diff_bytes=byte_limit,
        )
        xml_results.append(xml_payload)
        structured_files.append(structured_entry)

    structured_data = {
        "files": structured_files,
        "total_files": len(structured_files),
        "validate_only": validate_only,
        "max_diff_lines": line_limit,
    }

    return create_tool_result_xml(
        xml_contents=xml_results, structured_data=structured_data
    )


def register_file_tools(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    """Register all file operation tools to FastMCP server.

    Args:
        mcp: The FastMCP server instance.
        session_manager: Optional session manager for overlay filesystem access.
            If provided, list_files will include files from overlay mounts.
    """
    register_read(mcp, session_manager=session_manager)
    register_edit(mcp)
    register_apply_diff(mcp)

    @mcp.tool(
        name="list",
        description=(
            "List files with optional filtering. "
            "You can optionally set persistent to filter temporary or persistent files."
            "You can optionally provide a keyword to fuzzy query (partial match)"
        ),
    )
    async def list(
        ctx: Context,
        persistent: Annotated[
            bool | None,
            Field(
                description="Filter flag. `true` returns only persistent files, `false` returns only temporary files, and `null` returns all files"
            ),
        ] = None,
        keyword: Annotated[
            str | None,
            Field(description="Filter keyword, supporting fuzzy query (partial match)"),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(description="Session ID for overlay filesystem access (optional)"),
        ] = None,
    ) -> ToolResult:
        try:
            return await _list_files_tool(
                ctx=ctx,
                session_manager=session_manager,
                persistent=persistent,
                keyword=keyword,
                session_id=session_id,
            )
        except Exception as exc:
            error_xml = build_error_xml(str(exc), "list")
            return create_tool_result_xml(error_xml, {"error": str(exc)})

    # @mcp.tool(
    #     name="scratchpad_read_file",
    #     description=(
    #         "Read a file from the scratchpad in a given session. "
    #         "Assume this tool is able to read all files in the scratchpad. If the User provides a path to a file assume that path is valid. "
    #         "It is okay to read a file that does not exist; an error will be returned.\n\n"
    #         "Usage:\n"
    #         "- The filePath parameter must be an absolute path, not a relative path\n"
    #         "- By default, it reads up to 2000 lines starting from the beginning of the file\n"
    #         "- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters\n"
    #         "- Any lines longer than 2000 characters will be truncated\n"
    #         "- Results are returned using cat -n format, with line numbers starting at 1\n"
    #         "- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.\n"
    #         "- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.\n"
    #         "- You can read image files using this tool."
    #     ),
    # )
    # async def read_file(
    #     ctx: Context,
    #     session_id: Annotated[str, Field(description="The unique identifier of the session, formatted as `user_id-agent_id-timestamp`")],
    #     file_path: Annotated[Optional[str], Field(
    #         description="List of file paths to read the entire content of. If provided, it works as an either/or option with `file_requests`, and the entire file content will be returned by default for each path.",
    #         # default=None
    #     )],
    #     offset: Optional[int] = Field(default=None, description="The line number to start reading from (0-based)"),
    #     limit: Optional[int] = Field(default=None, description="The number of lines to read (defaults to 2000)"),
    #     # file_request: Annotated[Optional[dict[str, Any]], Field(
    #     #     description="List of structured file request objects for partial file reading. If provided, it works as an either/or option with `file_paths`.",
    #     #     default=None
    #     # )]
    # )-> ToolResult:
    #     try:
    #         file_paths=[file_path]
    #         file_requests=[
    #             {
    #                 'file_path':file_path,
    #                 'start_line':offset,
    #                 'end_line':offset+limit-1
    #             }
    #         ]
    #         return await _read_file_tool(ctx, session_id, file_paths, file_requests)
    #     except Exception as exc:
    #         error_xml = build_error_xml(str(exc), "read_file")
    #         return create_tool_result_xml(error_xml, {"error": str(exc)})

    @mcp.tool(
        name="write",
        description=(
            "Write content to a file.\n\n"
            "Usage:\n"
            "- You must use `list` tool at least once in the conversation before any other operation."
            "- This tool will fail if there is one at provided path.\n"
        ),
    )
    async def write(
        ctx: Context,
        content: Annotated[str, Field(description="The content to write to file")],
        file_path: Annotated[
            str,
            Field(description=get_path_description()),
        ],
        expected_version: Annotated[
            int | None,
            Field(
                description="The version number during the last read, used for optimistic locking to avoid overwriting other modifications."
            ),
        ] = None,
        permission: Annotated[
            str | None,
            Field(
                description="The permission to set for the file, only supports `read` or `read_write`."
            ),
        ] = None,
        overwrite: Annotated[
            bool,
            Field(
                description="Whether to allow overwriting an existing file with the same name, defaults to True to permit overwriting."
            ),
        ] = True,
        persistent: Annotated[
            bool,
            Field(
                description="Whether to persist the file permanently, only the file creator can set this to True, defaults to False (temporary file)."
            ),
        ] = False,
    ) -> ToolResult:
        try:
            return await _write_file_tool(
                ctx,
                file_path.lstrip("/"),
                content,
                expected_version,
                permission,
                overwrite,
                persistent,
            )
        except Exception as exc:
            error_xml = build_error_xml(str(exc), "write")
            return create_tool_result_xml(error_xml, {"error": str(exc)})

    @mcp.tool(
        name="remove",
        description=(
            "Delete a file. "
            "Use expected_version for optimistic locking and force=true when removing persistent files."
        ),
    )
    async def remove(
        ctx: Context,
        file_path: Annotated[str, Field(description=get_path_description())],
        expected_version: Annotated[
            int | None,
            Field(
                description="The file version number recorded by the client during the last read, used for optimistic locking. Deletion will fail if it is inconsistent with the current server version."
            ),
        ] = None,
        force: Annotated[
            bool,
            Field(
                description="Whether to force the deletion of persistent files. Only the file creator can set this to True, defaults to False (rejects deleting persistent files)."
            ),
        ] = False,
    ) -> ToolResult:
        try:
            return await _remove_file_tool(ctx, file_path, expected_version, force)
        except Exception as exc:
            error_xml = build_error_xml(str(exc), "remove")
            return create_tool_result_xml(error_xml, {"error": str(exc)})

    # @mcp.tool(
    #     name="scratchpad_apply_diff",
    #     description=apply_diff_description_prompt
    # )
    # async def scratchpad_apply_diff(
    #     ctx: Context,
    #     session_id: Annotated[str, Field(description="The unique identifier of the session, formatted as `user_id-agent_id-timestamp`. All incremental diff operations are bound to this session.")],
    #     file_path: Annotated[Optional[str], Field(description="The full path of the target existing file to be modified incrementally. Must be consistent with the path in the diff header if provided.")] ,
    #     diff: Annotated[Optional[str], Field(description="The incremental modification content in unified diff format (UTF-8 encoded).")] ,
    #     expected_version: Annotated[Optional[int], Field(description="The file version number recorded by the client during the last read, used for optimistic locking to avoid overwriting modifications from other Agents.")] = None,
    #     validate_only: Annotated[bool, Field(description="Whether to only perform diff parsing and conflict checking without actual file writing. Defaults to False (execute actual incremental modification if verification passes).")] = False,
    #     max_diff_lines: Annotated[Optional[int], Field(description="The maximum allowed number of lines for the incoming diff content. Defaults to 1000 lines if not provided, and returns an error if the diff exceeds this limit.")] = None
    # ) -> ToolResult:
    #     try:
    #         return await _apply_diff_tool(
    #             ctx=ctx,
    #             session_id=session_id,
    #             file_path=file_path,
    #             diff=diff,
    #             expected_version=expected_version,
    #             validate_only=validate_only,
    #             file_patches=None,
    #             max_diff_lines=max_diff_lines,
    #         )
    #     except Exception as exc:
    #         error_xml = build_error_xml(str(exc), "scratchpad_apply_diff")
    #         return create_tool_result_xml(error_xml, {"error": str(exc)})


# Helper functions (ported from existing handlers)
def _resolve_requests(payload: ReadFileRequest) -> list[FileReadSlice]:
    """Convert various input formats to unified file_requests list"""
    if payload.file_requests:
        return payload.file_requests
    if payload.file_paths:
        return [
            FileReadSlice(file_path=path, start_line=None, end_line=None)
            for path in payload.file_paths
        ]
    raise ValueError("file_requests or file_paths cannot be empty")


def _deduplicate(paths: list[str]) -> list[str]:
    """Remove duplicates while preserving order"""
    seen = set()
    ordered = []
    for path in paths:
        if path not in seen:
            ordered.append(path)
            seen.add(path)
    return ordered


def _extract_content_slice(text: str, start_line: int | None, end_line: int | None):
    """Extract text content based on requested line range"""
    lines = text.splitlines()
    total = len(lines)
    start_idx = max((start_line or 1) - 1, 0)
    end_idx = end_line if end_line else total
    end_idx = min(end_idx, total)
    selected = lines[start_idx:end_idx]
    numbered = [
        f"  {idx + start_idx + 1} | {line}" for idx, line in enumerate(selected)
    ]
    snippet = "\n".join(numbered)
    actual_start = start_idx + 1
    actual_end = start_idx + len(selected)
    return snippet, (actual_start, actual_end)


def _normalize_update_path(file_path: str) -> str:
    """Validate and normalize file path"""
    normalized = normalize_path(file_path)
    return normalized


def _serialize_chunks(chunks) -> list[dict[str, Any]]:
    """Convert chunk dataclasses to serializable dictionaries."""
    serialized = []
    for chunk in chunks:
        serialized.append(
            {
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": list(chunk.content),
            }
        )
    return serialized


def _hash_content(content: str) -> str:
    """Generate a SHA256 hash for preview metadata."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_patch_inputs(
    file_patches: list[dict[str, Any]] | None,
    file_path: str | None,
    diff: str | None,
) -> list[dict[str, Any]]:
    """Normalize patch payloads from either array input or legacy single-file arguments."""
    patches: list[dict[str, Any]] = []

    if file_patches:
        if not isinstance(file_patches, list):
            raise ValidationError("file_patches must be a list of patch objects")
        for idx, raw_patch in enumerate(file_patches, start=1):
            if not isinstance(raw_patch, dict):
                raise ValidationError(
                    f"Patch #{idx} must be an object with file_path and diff"
                )
            patch_path = raw_patch.get("file_path")
            patch_diff = raw_patch.get("diff")
            if not patch_path or not isinstance(patch_path, str):
                raise ValidationError(f"Patch #{idx} is missing a valid file_path")
            if not patch_diff or not isinstance(patch_diff, str):
                raise ValidationError(f"Patch #{idx} is missing diff content")
            patches.append(
                {
                    "file_path": patch_path,
                    "diff": patch_diff,
                    "expected_version": raw_patch.get("expected_version"),
                }
            )

    if not patches and file_path and diff:
        patches.append(
            {
                "file_path": file_path,
                "diff": diff,
                "expected_version": None,
            }
        )

    if not patches:
        raise ValidationError(
            "Either file_patches or file_path + diff must be provided"
        )

    return patches


def _enforce_diff_limits(
    diff_text: str,
    max_lines: int | None,
    max_bytes: int | None,
    file_path: str,
) -> None:
    """Ensure incoming diff stays within configured limits."""
    if not diff_text or not diff_text.strip():
        raise ValidationError("diff content cannot be empty")

    if max_lines:
        line_count = diff_text.count("\n") + 1
        if line_count > max_lines:
            raise ValidationError(
                f"Diff too large for {file_path}: {line_count} lines exceeds limit {max_lines}. "
                "Split the patch or use write_file."
            )

    if max_bytes:
        byte_count = len(diff_text.encode("utf-8"))
        if byte_count > max_bytes:
            raise ValidationError(
                f"Diff too large for {file_path}: {byte_count} bytes exceeds limit {max_bytes}. "
                "Split the patch or use write_file."
            )


async def _process_single_diff(
    ctx: Context,
    patch: dict[str, Any],
    global_expected_version: int | None,
    validate_only: bool,
    max_diff_lines: int | None,
    max_diff_bytes: int | None,
) -> tuple[str, dict[str, Any]]:
    """Apply a single diff payload and return its XML + structured metadata."""
    file_path = patch["file_path"]
    diff_text = patch["diff"]
    patch_expected_version = patch.get("expected_version") or global_expected_version

    normalized_path = _normalize_update_path(file_path)

    _enforce_diff_limits(diff_text, max_diff_lines, max_diff_bytes, normalized_path)

    logger.info("Applying diff to %s", normalized_path)
    await ctx.info(f"Applying diff to {normalized_path}")
    await ctx.report_progress(10, 100, f"Loading {normalized_path}")

    ok_records, failed = get_store().read_files([normalized_path])
    if failed:
        raise ScratchpadFileNotFoundError(f"File not found: {normalized_path}")

    record = ok_records[0]
    base_version = record.version
    base_hash = _hash_content(record.content or "")

    await ctx.report_progress(45, 100, f"Applying diff to {normalized_path}")
    try:
        outcome = apply_unified_diff(diff_text, record.content, normalized_path)
    except ValidationError as exc:
        raise ValidationError(
            f"Failed to apply diff to {normalized_path}: {exc}"
        ) from exc

    updated_content = outcome.new_content
    updated_size = len(updated_content.encode("utf-8"))
    if updated_size > config.max_file_size:
        raise FileTooLargeError(
            f"Updated file size {updated_size} exceeds maximum allowed size {config.max_file_size}"
        )

    predicted_version = base_version + 1
    predicted_updated_at = (
        datetime.datetime.now(tz=datetime.timezone.utc).isoformat() + "Z"
    )

    if not validate_only:
        await ctx.report_progress(
            70, 100, f"Persisting diff result for {normalized_path}"
        )
        updated_record = get_store().write_file(
            file_path=normalized_path,
            content=updated_content,
            overwrite=True,
            persistent=record.persistent,
            expected_version=base_version,
            permission=record.permission,
        )
        final_version = updated_record.version
        final_updated_at = updated_record.updated_at.isoformat() + "Z"
        final_size = updated_record.size
        status = "applied"
    else:
        final_version = predicted_version
        final_updated_at = predicted_updated_at
        final_size = updated_size
        status = "validated"

    await ctx.report_progress(
        100, 100, f"Diff processing completed for {normalized_path}"
    )

    added_chunks = _serialize_chunks(outcome.added_chunks)
    removed_chunks = _serialize_chunks(outcome.removed_chunks)
    version_label = f"v{final_version}" + (" (preview)" if validate_only else "")
    summary_text = (
        f"Diff {status}: {normalized_path}\n"
        f"Lines added: {outcome.lines_added} | Lines removed: {outcome.lines_removed} | Final version: {version_label}"
    )

    xml_payload = build_file_operation_xml(
        {
            "file_path": normalized_path,
            "status": status,
            "lines_added": outcome.lines_added,
            "lines_removed": outcome.lines_removed,
            "final_version": final_version,
            "final_size": final_size,
            "validate_only": str(validate_only).lower(),
            "summary": summary_text,
            "base_version": base_version,
            "expected_version": patch_expected_version or "",
        },
        "apply_diff",
    )

    structured_entry = {
        "file_path": normalized_path,
        "base_version": base_version,
        "base_hash": base_hash,
        "expected_version": patch_expected_version,
        "added_chunks": added_chunks,
        "removed_chunks": removed_chunks,
        "updated_at": final_updated_at,
        "lines_added": outcome.lines_added,
        "lines_removed": outcome.lines_removed,
        "final_version": final_version,
        "final_size": final_size,
        "validate_only": validate_only,
    }

    return xml_payload, structured_entry
