"""Write tool registration and helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from ..config import config
from ..exceptions import FileTooLargeError, ValidationError
from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..models import WriteFileRequest
from ..path_resolver import build_uri, get_path_description
from ..storage import get_store
from ..utils import (
    build_error_xml,
    build_file_operation_xml,
    create_tool_result_xml,
    normalize_path,
)

if TYPE_CHECKING:
    from ..fs import SessionFileSystemManager

logger = logging.getLogger(__name__)


def _build_adapter(
    session_manager: SessionFileSystemManager | None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> UnifiedSessionFSAdapter:
    if adapter is not None:
        return adapter
    return UnifiedSessionFSAdapter(
        session_manager=session_manager,
        store=get_store(),
        unified_enabled=True,
    )


def apply_write_with_session(
    *,
    session_id: str | None,
    file_path: str,
    content: str,
    overwrite: bool = True,
    permission: str | None = None,
    persistent: bool = False,
    session_manager: SessionFileSystemManager | None = None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> dict[str, object]:
    """Write text through the unified adapter for a session-scoped path."""
    if not session_id:
        raise ValueError("session_id is required")

    request = WriteFileRequest(
        file_path=file_path,
        content=content,
        expected_version=None,
        permission=permission,
        overwrite=overwrite,
        persistent=persistent,
    )
    content_size = len(content.encode("utf-8"))
    if content_size > config.max_file_size:
        raise FileTooLargeError(
            f"File size {content_size} exceeds maximum allowed size {config.max_file_size}"
        )

    active_adapter = _build_adapter(session_manager, adapter)
    normalized_path = normalize_path(request.file_path)
    absolute_path = f"/{normalized_path.lstrip('/')}"
    manager = active_adapter._session_manager
    if manager is not None:
        manager.ensure_session(session_id)
    session_fs = manager.get_session_fs(session_id) if manager is not None else None
    if session_fs is None:
        raise ValueError(f"Session not found: {session_id}")

    existed = session_fs.exists(absolute_path)
    if existed and not request.overwrite:
        raise ValidationError(f"File already exists: {normalized_path}")

    active_adapter.write_text(session_id, normalized_path, request.content)
    return {
        "file_path": normalized_path,
        "name": Path(normalized_path).name,
        "size": content_size,
        "permission": request.permission or "read_write",
        "persistent": request.persistent,
        "version": None,
        "operation": "updated" if existed else "created",
        "uri": build_uri(normalized_path, session_id=session_id),
    }
def register_write(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    """Register the write tool."""

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
        session_id: Annotated[
            str,
            Field(description="Session ID for session-scoped write operations"),
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
            if session_manager is None:
                raise ValidationError("session_manager is required")
            if expected_version is not None:
                logger.debug("expected_version is ignored for overlay-only write")

            await ctx.report_progress(25, 100, "Preparing to write")
            structured = apply_write_with_session(
                session_id=session_id,
                file_path=file_path,
                content=content,
                overwrite=overwrite,
                permission=permission,
                persistent=persistent,
                session_manager=session_manager,
            )
            await ctx.report_progress(100, 100, "File writing completed")
            xml_content = build_file_operation_xml(structured, "write")
            return create_tool_result_xml(
                xml_contents=xml_content, structured_data=structured
            )
        except Exception as exc:
            error_xml = build_error_xml(str(exc), "write")
            return create_tool_result_xml(error_xml, {"error": str(exc)})
