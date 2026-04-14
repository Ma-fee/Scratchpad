"""Aggregate registration for file-oriented FastMCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

from .apply_diff import register_apply_diff
from .edit import register_edit
from .list import register_list
from .publish_memory import register_publish_memory
from .read import register_read
from .remove import register_remove
from .write import register_write

if TYPE_CHECKING:
    from ..fs import SessionFileSystemManager


def register_file_tools(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    """Register all file operation tools to FastMCP server."""
    register_read(mcp, session_manager=session_manager)
    register_edit(mcp, session_manager=session_manager)
    register_apply_diff(mcp, session_manager=session_manager)
    register_list(mcp, session_manager=session_manager)
    register_write(mcp, session_manager=session_manager)
    register_remove(mcp, session_manager=session_manager)
    register_publish_memory(mcp, session_manager=session_manager)
