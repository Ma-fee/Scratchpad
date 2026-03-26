"""FastMCP resource handlers for scratchpad filesystem access.

This module provides MCP resource handlers that expose scratchpad files via
the scratchpad:// URI scheme. Resources are dynamically resolved based on
session ID and file path, integrating with the SessionFileSystemManager.

Example URIs:
    - scratchpad://{session_id}/workspace/file.txt
    - scratchpad://{session_id}/config.json
    - scratchpad://{session_id}/data/

Usage:
    from fastmcp import FastMCP
    from mcp_scratchpad.resources import register_scratchpad_resources

    mcp = FastMCP("My Server")
    manager = SessionFileSystemManager(config)
    register_scratchpad_resources(mcp, manager)
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from ..fs.session_manager import SessionFileSystemManager

logger = logging.getLogger(__name__)


def _guess_mime_type(path: str, content: bytes | None = None) -> str:
    """Guess MIME type from file path and optional content.

    Args:
        path: File path to guess MIME type from.
        content: Optional file content for content-based detection.

    Returns:
        MIME type string (defaults to text/plain if unknown).
    """
    # Content-based detection takes precedence for known signatures
    if content:
        # Check for common binary signatures
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith(b"%PDF-"):
            return "application/pdf"
        if content.startswith(b"\x1f\x8b"):
            return "application/gzip"
        if content.startswith(b"PK\x03\x04"):
            return "application/zip"

    # Try path-based detection
    mime_type, _ = mimetypes.guess_type(path)

    if mime_type:
        return mime_type

    # Default to text/plain for unknown types
    return "text/plain"


def _is_binary_content(mime_type: str) -> bool:
    """Check if MIME type represents binary content.

    Args:
        mime_type: MIME type to check.

    Returns:
        True if content is binary, False otherwise.
    """
    binary_prefixes = (
        "image/",
        "audio/",
        "video/",
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-",
    )
    return mime_type.startswith(binary_prefixes)


@dataclass
class ResourceError:
    """Error response for resource operations.

    Attributes:
        code: Error code (e.g., "NOT_FOUND", "ACCESS_DENIED").
        message: Human-readable error message.
        details: Optional additional error details.
    """

    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary format."""
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


class ResourceNotFoundError(Exception):
    """Exception raised when a requested resource is not found."""

    def __init__(self, session_id: str, path: str) -> None:
        self.session_id = session_id
        self.path = path
        super().__init__(f"Resource not found: scratchpad://{session_id}/{path}")


class SessionNotFoundError(Exception):
    """Exception raised when a session is not found or expired."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session not found or expired: {session_id}")


def _normalize_path(path: str) -> str:
    """Normalize resource path for filesystem access.

    Args:
        path: Resource path from URI.

    Returns:
        Normalized path starting with /.
    """
    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path

    # Remove trailing slash except for root
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    return path


def _read_file_content(
    manager: SessionFileSystemManager,
    session_id: str,
    path: str,
) -> tuple[bytes, str]:
    """Read file content from session filesystem.

    Args:
        manager: SessionFileSystemManager instance.
        session_id: Session ID.
        path: File path (normalized, starting with /).

    Returns:
        Tuple of (content_bytes, mime_type).

    Raises:
        SessionNotFoundError: If session doesn't exist or is expired.
        ResourceNotFoundError: If file doesn't exist.
        IsADirectoryError: If path is a directory.
    """
    fs = manager.get_session_fs(session_id)
    if fs is None:
        raise SessionNotFoundError(session_id)

    # Check if path exists
    if not fs.exists(path):
        raise ResourceNotFoundError(session_id, path)

    # Check if it's a file (not a directory)
    try:
        info = fs.info(path)
        if info.get("type") == "directory":
            raise IsADirectoryError(f"Path is a directory: {path}")
    except (OSError, ValueError) as e:
        logger.warning(f"Could not get file info for {path}: {e}")
        # Continue anyway, will fail on read if not a file

    # Read file content
    try:
        # Try binary read first
        with fs.open(path, "rb") as f:
            content = f.read()
    except IsADirectoryError:
        # Re-raise IsADirectoryError for proper handling
        raise
    except (OSError, IOError) as e:
        raise ResourceNotFoundError(session_id, path) from e

    # Determine MIME type
    mime_type = _guess_mime_type(path, content)

    return content, mime_type


def _list_directory(
    manager: SessionFileSystemManager,
    session_id: str,
    path: str,
) -> list[dict[str, Any]]:
    """List directory contents.

    Args:
        manager: SessionFileSystemManager instance.
        session_id: Session ID.
        path: Directory path (normalized, starting with /).

    Returns:
        List of file/directory entries with metadata.

    Raises:
        SessionNotFoundError: If session doesn't exist or is expired.
        ResourceNotFoundError: If directory doesn't exist.
        NotADirectoryError: If path is not a directory.
    """
    fs = manager.get_session_fs(session_id)
    if fs is None:
        raise SessionNotFoundError(session_id)

    # Check if path exists
    if not fs.exists(path):
        raise ResourceNotFoundError(session_id, path)

    # Check if it's a directory
    if not fs.isdir(path):
        raise NotADirectoryError(f"Path is not a directory: {path}")

    # List directory contents
    try:
        entries = fs.ls(path, detail=True)
    except (OSError, ValueError) as e:
        raise ResourceNotFoundError(session_id, path) from e

    # Format entries
    formatted = []
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("name", "").split("/")[-1] or entry.get("name", "")
            entry_type = "directory" if entry.get("type") == "directory" else "file"
            size = entry.get("size", 0)
        else:
            # entry is just a path string
            name = str(entry).split("/")[-1] or str(entry)
            entry_type = "directory" if fs.isdir(str(entry)) else "file"
            size = 0

        formatted.append(
            {
                "name": name,
                "type": entry_type,
                "size": size,
            }
        )

    return formatted


def register_scratchpad_resources(
    mcp: FastMCP,
    manager: SessionFileSystemManager,
) -> None:
    """Register scratchpad resource handlers with FastMCP server.

    This function registers resource handlers that expose scratchpad files
    via the scratchpad:// URI scheme. Resources are dynamically resolved
    based on session ID and file path.

    Args:
        mcp: FastMCP server instance.
        manager: SessionFileSystemManager for filesystem access.

    Example:
        >>> from fastmcp import FastMCP
        >>> from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
        >>> from mcp_scratchpad.config.models import OverlayConfig
        >>> from mcp_scratchpad.resources import register_scratchpad_resources
        >>>
        >>> mcp = FastMCP("My Server")
        >>> manager = SessionFileSystemManager(OverlayConfig(mounts=[]))
        >>> register_scratchpad_resources(mcp, manager)

    Resource URIs:
        - scratchpad://{session_id}/{file_path} - Any file in a session

    The {file_path} pattern with match pattern allows slashes in the path component,
    enabling access to nested files like scratchpad://abc-123/workspace/file.txt.
    """
    logger.info("Registering scratchpad resource handlers")

    @mcp.resource(
        "scratchpad://{session_id}/{file_path}",
        mime_type="application/octet-stream",
    )
    def read_scratchpad_resource(session_id: str, file_path: str) -> bytes | str:
        """Read a file from the scratchpad session filesystem.

        This resource handler reads files from a session's overlay filesystem.
        It supports both text and binary files, with automatic MIME type
        detection based on file extension and content.

        Args:
            session_id: Unique session identifier (UUID4 format).
            file_path: File path within the session (e.g., "workspace/file.txt").

        Returns:
            File content as bytes for binary files, or string for text files.

        Raises:
            ValueError: If session_id is empty or invalid.
            FileNotFoundError: If the file doesn't exist.
            IsADirectoryError: If the path is a directory.
        """
        logger.debug(f"Resource request: scratchpad://{session_id}/{file_path}")

        # Validate session_id
        if not session_id or not session_id.strip():
            raise ValueError("Session ID cannot be empty")

        # Normalize path
        normalized_path = _normalize_path(file_path)

        try:
            content, mime_type = _read_file_content(
                manager, session_id, normalized_path
            )

            # Return string for text content, bytes for binary
            if _is_binary_content(mime_type):
                logger.debug(f"Returning binary content ({mime_type})")
                return content
            else:
                # Try to decode as text
                try:
                    text_content = content.decode("utf-8")
                    logger.debug(f"Returning text content ({mime_type})")
                    return text_content
                except UnicodeDecodeError:
                    # Fallback to bytes if can't decode as text
                    logger.debug(f"Failed to decode as UTF-8, returning bytes")
                    return content

        except SessionNotFoundError as e:
            logger.warning(f"Session not found: {session_id}")
            raise FileNotFoundError(str(e)) from e
        except ResourceNotFoundError as e:
            logger.warning(f"Resource not found: {file_path} in session {session_id}")
            raise FileNotFoundError(str(e)) from e
        except IsADirectoryError as e:
            logger.warning(f"Path is a directory: {file_path}")
            raise IsADirectoryError(str(e)) from e

    logger.info("Scratchpad resource handlers registered successfully")


def register_directory_resources(
    mcp: FastMCP,
    manager: SessionFileSystemManager,
) -> None:
    """Register directory listing resource handlers.

    This is an optional extension that provides directory listing as JSON.
    Can be registered separately if needed.

    Args:
        mcp: FastMCP server instance.
        manager: SessionFileSystemManager for filesystem access.
    """
    import json

    @mcp.resource(
        "scratchpad://{session_id}/",
        mime_type="application/json",
    )
    def list_session_root(session_id: str) -> str:
        """List root directory contents of a session.

        Args:
            session_id: Unique session identifier.

        Returns:
            JSON string containing directory listing.
        """
        logger.debug(f"Directory listing request: scratchpad://{session_id}/")

        if not session_id or not session_id.strip():
            raise ValueError("Session ID cannot be empty")

        try:
            entries = _list_directory(manager, session_id, "/")
            return json.dumps(
                {
                    "path": "/",
                    "session_id": session_id,
                    "entries": entries,
                }
            )
        except SessionNotFoundError as e:
            raise FileNotFoundError(str(e)) from e
        except ResourceNotFoundError as e:
            raise FileNotFoundError(str(e)) from e

    @mcp.resource(
        "scratchpad://{session_id}/{dir_path}/",
        mime_type="application/json",
    )
    def list_session_directory(session_id: str, dir_path: str) -> str:
        """List directory contents within a session.

        Args:
            session_id: Unique session identifier.
            dir_path: Directory path.

        Returns:
            JSON string containing directory listing.
        """
        logger.debug(
            f"Directory listing request: scratchpad://{session_id}/{dir_path}/"
        )

        if not session_id or not session_id.strip():
            raise ValueError("Session ID cannot be empty")

        normalized_path = _normalize_path(dir_path)

        try:
            entries = _list_directory(manager, session_id, normalized_path)
            return json.dumps(
                {
                    "path": normalized_path,
                    "session_id": session_id,
                    "entries": entries,
                }
            )
        except SessionNotFoundError as e:
            raise FileNotFoundError(str(e)) from e
        except ResourceNotFoundError as e:
            raise FileNotFoundError(str(e)) from e
