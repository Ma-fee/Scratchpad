"""
Exception handling for MCP Scratchpad
"""

from .custom import (
    ConfigurationError,
    FileSizeLimitError,
    FileTooLargeError,
    InvalidSessionError,
    PathTraversalError,
    PermissionDeniedError,
    ResourceLimitError,
    ScratchpadError,
    ScratchpadFileNotFoundError,
    SessionIsolationError,
    StorageError,
    SymlinkEscapeError,
    ValidationError,
)
from .handlers import (
    handle_tool_exception,
    handle_tool_exception_xml,
    safe_execute_tool,
)

__all__ = [
    "ScratchpadError",
    "ValidationError",
    "ScratchpadFileNotFoundError",
    "FileTooLargeError",
    "PermissionDeniedError",
    "StorageError",
    "ConfigurationError",
    "PathTraversalError",
    "SymlinkEscapeError",
    "SessionIsolationError",
    "InvalidSessionError",
    "FileSizeLimitError",
    "ResourceLimitError",
    "handle_tool_exception",
    "handle_tool_exception_xml",
    "safe_execute_tool",
]
