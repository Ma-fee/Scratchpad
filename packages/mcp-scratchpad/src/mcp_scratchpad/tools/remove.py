"""Remove tool registration and helpers."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from ..exceptions import ScratchpadFileNotFoundError, ValidationError
from ..fs.unified_adapter import UnifiedSessionFSAdapter
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


def apply_remove_with_session(
    *,
    session_id: str | None,
    file_path: str,
    session_manager: SessionFileSystemManager | None = None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> dict[str, object]:
    """Remove a session-scoped file through the overlay filesystem."""
    if not session_id:
        raise ValueError("session_id is required")

    active_adapter = _build_adapter(session_manager, adapter)
    normalized_path = normalize_path(file_path)
    absolute_path = f"/{normalized_path.lstrip('/')}"
    manager = active_adapter._session_manager
    if manager is not None:
        manager.ensure_session(session_id)
    session_fs = manager.get_session_fs(session_id) if manager is not None else None
    if session_fs is None:
        raise ValueError(f"Session not found: {session_id}")
    if not session_fs.exists(absolute_path):
        raise ScratchpadFileNotFoundError(f"File not found: {normalized_path}")

    session_fs.rm(absolute_path)
    deleted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat() + "Z"
    return {
        "file_path": normalized_path,
        "name": normalized_path.split("/")[-1],
        "deleted_at": deleted_at,
        "deleted_by": "user",
        "persistent_before": False,
        "version": None,
        "uri": build_uri(normalized_path, session_id=session_id),
    }
def register_remove(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    """Register the remove tool."""

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
        session_id: Annotated[
            str,
            Field(description="Session ID for session-scoped remove operations"),
        ],
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
            if session_manager is None:
                raise ValidationError("session_manager is required")
            if expected_version is not None:
                logger.debug("expected_version is ignored for overlay-only remove")
            if force:
                logger.debug("force is ignored for overlay-only remove")

            await ctx.report_progress(25, 100, "Removing file")
            structured = apply_remove_with_session(
                session_id=session_id,
                file_path=file_path,
                session_manager=session_manager,
            )
            await ctx.report_progress(100, 100, "File removal completed")
            xml_content = build_file_operation_xml(structured, "remove")
            return create_tool_result_xml(
                xml_contents=xml_content, structured_data=structured
            )
        except Exception as exc:
            error_xml = build_error_xml(str(exc), "remove")
            return create_tool_result_xml(error_xml, {"error": str(exc)})
