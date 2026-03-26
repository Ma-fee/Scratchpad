"""
Custom exceptions for MCP Scratchpad
"""

from typing import Any


class ScratchpadError(Exception):
    """Base exception for all scratchpad errors"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}


class ValidationError(ScratchpadError):
    """Raised when input validation fails"""

    pass


class ScratchpadFileNotFoundError(ScratchpadError):
    """Raised when a requested file is not found"""

    pass


class FileTooLargeError(ScratchpadError):
    """Raised when file size exceeds limits"""

    pass


class PermissionDeniedError(ScratchpadError):
    """Raised when operation is not permitted"""

    pass


class StorageError(ScratchpadError):
    """Raised when storage operation fails"""

    pass


class ConfigurationError(ScratchpadError):
    """Raised when configuration is invalid"""

    pass


class PathTraversalError(ScratchpadError):
    """Raised when a path traversal attack is detected"""

    def __init__(
        self,
        message: str,
        path: str,
        base_path: str | None = None,
    ):
        super().__init__(message)
        self.path = path
        self.base_path = base_path


class SymlinkEscapeError(ScratchpadError):
    """Raised when a symlink points outside allowed bounds"""

    def __init__(
        self,
        message: str,
        link_path: str,
        target: str,
    ):
        super().__init__(message)
        self.link_path = link_path
        self.target = target


class SessionIsolationError(ScratchpadError):
    """Raised when session isolation is violated"""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
        attempted_path: str | None = None,
        workspace: str | None = None,
    ):
        super().__init__(message)
        self.session_id = session_id
        self.attempted_path = attempted_path
        self.workspace = workspace


class InvalidSessionError(ScratchpadError):
    """Raised when session ID is invalid or expired"""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
    ):
        super().__init__(message)
        self.session_id = session_id


class FileSizeLimitError(ScratchpadError):
    """Raised when file size exceeds the configured limit"""

    def __init__(
        self,
        message: str,
        file_path: str | None = None,
        file_size: int | None = None,
        size_limit: int | None = None,
    ):
        super().__init__(message)
        self.file_path = file_path
        self.file_size = file_size
        self.size_limit = size_limit


class ResourceLimitError(ScratchpadError):
    """Raised when resource limits are exceeded (directory count, total size, etc.)"""

    def __init__(
        self,
        message: str,
        resource_type: str | None = None,
        current_value: int | None = None,
        limit_value: int | None = None,
        path: str | None = None,
    ):
        super().__init__(message)
        self.resource_type = resource_type
        self.current_value = current_value
        self.limit_value = limit_value
        self.path = path
