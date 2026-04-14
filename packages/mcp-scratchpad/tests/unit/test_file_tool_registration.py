from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.tools.file_tools import register_file_tools


@pytest.mark.unit
def test_register_file_tools_registers_all_public_tools() -> None:
    """File tool registration should expose all expected tool names."""
    mcp = MagicMock()
    mcp.tool = MagicMock(return_value=lambda f: f)
    session_manager = SessionFileSystemManager(OverlayConfig())

    register_file_tools(mcp, session_manager=session_manager)

    tool_names = {
        call.kwargs["name"] for call in mcp.tool.call_args_list if "name" in call.kwargs
    }

    assert {
        "read",
        "edit",
        "multiedit",
        "patch",
        "list",
        "write",
        "remove",
        "publish_memory",
    } <= tool_names
