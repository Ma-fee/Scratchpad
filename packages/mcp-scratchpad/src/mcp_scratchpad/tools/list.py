"""List tool registration and helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from ..models import FileRecord
from ..path_resolver import build_uri
from ..utils import build_error_xml, build_file_list_xml, create_tool_result_xml

if TYPE_CHECKING:
    from ..fs import SessionFileSystemManager

logger = logging.getLogger(__name__)


def _file_info_to_record(file_path: str, info: dict[str, Any]) -> FileRecord:
    """Convert filesystem info dict to FileRecord."""
    from datetime import datetime, timezone

    name = file_path.split("/")[-1] if "/" in file_path else file_path
    mtime = info.get("mtime") or info.get("modified")
    updated_at = (
        datetime.fromtimestamp(mtime, tz=timezone.utc)
        if mtime
        else datetime.now(timezone.utc)
    )
    size = info.get("size", 0) or 0
    layer = info.get("_layer", 0)
    is_writable = layer == 0

    return FileRecord(
        file_path=file_path,
        name=name,
        content="",
        persistent=False,
        permission="read_write" if is_writable else "read",
        created_at=updated_at,
        updated_at=updated_at,
        size=size,
        version=1,
    )


async def _list_files_tool(  # noqa: C901
    ctx: Context,
    session_manager: SessionFileSystemManager | None,
    persistent: bool | None = None,
    keyword: str | None = None,
    session_id: str | None = None,
) -> ToolResult:
    """List files from the current session overlay filesystem."""
    logger.info("Listing files")
    await ctx.info("Listing files")
    await ctx.report_progress(25, 100, "Fetching file list")

    if not session_id:
        raise ValueError("session_id is required")
    if session_manager is None:
        raise ValueError("session_manager is required")

    session_manager.ensure_session(session_id)
    session_fs = session_manager.get_session_fs(session_id)
    if session_fs is None:
        raise ValueError(f"Session not found: {session_id}")

    all_records: list[FileRecord] = []
    extra_metadata: dict[str, dict[str, Any]] = {}

    await ctx.report_progress(50, 100, "Scanning session overlay filesystem")

    try:
        overlay_files = _list_overlay_files_recursive(session_fs, "/")
        for file_path, info in overlay_files.items():
            record = _file_info_to_record(file_path, info)
            extra_metadata[record.file_path] = {
                "uri": build_uri(record.file_path, session_id=session_id),
            }

            if persistent is True:
                continue
            if keyword and keyword not in record.name:
                continue

            all_records.append(record)
    except Exception as e:
        logger.warning("Failed to list overlay files: %s", e)

    await ctx.report_progress(75, 100, "Processing results")
    all_records.sort(key=lambda r: r.updated_at, reverse=True)

    structured_files = []
    for record in all_records:
        metadata = record.to_metadata()
        if record.file_path in extra_metadata:
            extra = extra_metadata[record.file_path]
            if extra.get("line_count", 0) > 0:
                metadata["line_count"] = extra["line_count"]
            if extra.get("uri"):
                metadata["uri"] = extra["uri"]
        structured_files.append(metadata)

    await ctx.report_progress(100, 100, "File listing completed")

    metadata = {
        "total_files": len(all_records),
        "persistent_filter": persistent,
        "keyword_filter": keyword,
    }
    xml_contents = build_file_list_xml(structured_files, metadata)
    return create_tool_result_xml(xml_contents=xml_contents, structured_data=metadata)


def _list_overlay_files_recursive(
    fs: Any,
    path: str,
    result: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Recursively list all files visible in an overlay filesystem."""
    if result is None:
        result = {}

    try:
        normalized_path = path if path.startswith("/") else f"/{path.lstrip('/')}"
        entries = fs.ls(normalized_path, detail=True)

        for entry in entries:
            if isinstance(entry, dict):
                entry_name = entry.get("name", "")
                basename = (
                    entry_name.split("/")[-1] if "/" in entry_name else entry_name
                )
                full_path = (
                    f"{normalized_path.rstrip('/')}/{basename}"
                    if normalized_path != "/"
                    else f"/{basename}"
                )
                is_dir = entry.get("type") == "directory" or entry.get(
                    "is_directory", False
                )
                info = dict(entry)
                info["name"] = full_path
            else:
                basename = str(entry).split("/")[-1]
                full_path = (
                    f"{normalized_path.rstrip('/')}/{basename}"
                    if normalized_path != "/"
                    else f"/{basename}"
                )
                is_dir = fs.isdir(full_path)
                try:
                    info = fs.info(full_path)
                except Exception:
                    info = {"name": full_path, "size": 0}

            if basename.startswith("."):
                continue

            if is_dir:
                _list_overlay_files_recursive(fs, full_path, result)
            else:
                rel_path = full_path.lstrip("/")
                if rel_path:
                    result[rel_path] = info
    except Exception as e:
        logger.debug("Error listing overlay path %s: %s", path, e)

    return result


def register_list(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    """Register the list tool."""

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
        session_id: Annotated[
            str,
            Field(description="Session ID for overlay filesystem access"),
        ],
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
