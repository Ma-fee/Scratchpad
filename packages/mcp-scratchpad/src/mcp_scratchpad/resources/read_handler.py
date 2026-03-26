"""
Resource read handler for scratchpad:// URIs.

This module provides functionality to read files from the scratchpad filesystem,
detect MIME types, and return appropriate content representations based on file type.

Resource Read Flow:
    1. Parse URI → (session_id, path)
    2. Validate session exists
    3. Get filesystem for session
    4. Check file exists and is readable
    5. Detect MIME type
    6. Read content (text or binary)
    7. Return: {content, mime_type, size, last_modified}

Example:
    >>> from mcp_scratchpad.resources.read_handler import read_resource
    >>> result = read_resource("scratchpad://abc-123/workspace/file.txt")
    >>> result.content
    'Hello, World!'
    >>> result.mime_type
    'text/plain'
"""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, Union

try:
    from fsspec import AbstractFileSystem
except ImportError:
    # Fallback for type checking when fsspec is not installed
    from typing import Any as AbstractFileSystem

from ..exceptions import (
    ConfigurationError,
    ScratchpadError,
    ScratchpadFileNotFoundError,
)
from ..fs.session_manager import SessionFileSystemManager
from .uri_parser import ScratchpadURI, URIParseError, parse_scratchpad_uri


class ResourceContentType(Enum):
    """Content type classification for resources.

    This enum categorizes resources by their content type to determine
    how they should be processed and returned.

    Attributes:
        TEXT: Text content that can be decoded as UTF-8
        BINARY: Raw binary content (bytes)
        IMAGE: Image files with special handling
        JSON: JSON files that can be parsed
        XML: XML files with structured content
    """

    TEXT = "text"
    BINARY = "binary"
    IMAGE = "image"
    JSON = "json"
    XML = "xml"


@dataclass(frozen=True)
class ResourceContent:
    """Content representation for a resource.

        This dataclass holds the decoded content of a resource file,
    along with metadata about how it was processed.

        Attributes:
            data: The content data (str for text, bytes for binary)
            encoding: The encoding used (e.g., 'utf-8', 'base64')
            is_binary: Whether the content is binary
            size_bytes: Size of the content in bytes

        Example:
            >>> content = ResourceContent(
            ...     data="Hello, World!",
            ...     encoding="utf-8",
            ...     is_binary=False,
            ...     size_bytes=13
            ... )
    """

    data: Union[str, bytes]
    encoding: str
    is_binary: bool
    size_bytes: int

    def to_string(self) -> str:
        """Convert content to string representation.

        For text content, returns the data directly.
        For binary content, returns base64-encoded string.

        Returns:
            String representation of the content.

        Raises:
            ValueError: If binary content cannot be decoded.
        """
        if isinstance(self.data, str):
            return self.data
        elif isinstance(self.data, bytes):
            if self.is_binary:
                return base64.b64encode(self.data).decode("ascii")
            else:
                return self.data.decode(self.encoding or "utf-8")
        else:
            raise ValueError(f"Unknown data type: {type(self.data)}")


@dataclass(frozen=True)
class ResourceMetadata:
    """Metadata for a scratchpad resource.

    Attributes:
        size: File size in bytes
        modified: Last modification timestamp (ISO format)
        created: Creation timestamp (ISO format)
        mime_type: MIME type of the resource
        content_type: Content type classification
        extension: File extension
        is_directory: Whether this is a directory

    Example:
        >>> meta = ResourceMetadata(
        ...     size=1024,
        ...     modified="2024-01-15T10:30:00",
        ...     mime_type="text/plain"
        ... )
    """

    size: int
    mime_type: str
    modified: Optional[str] = None
    created: Optional[str] = None
    content_type: str = "text"
    extension: Optional[str] = None
    is_directory: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "size": self.size,
            "mime_type": self.mime_type,
            "modified": self.modified,
            "created": self.created,
            "content_type": self.content_type,
            "extension": self.extension,
            "is_directory": self.is_directory,
        }


@dataclass(frozen=True)
class ResourceReadResult:
    """Result of reading a scratchpad resource.

    This dataclass contains all information returned when reading a resource,
    including the content, metadata, and URI information.

    Attributes:
        uri: The original scratchpad:// URI
        session_id: The session identifier
        path: The file path within the session
        content: The file content (ResourceContent)
        metadata: Resource metadata (ResourceMetadata)
        success: Whether the read operation succeeded
        error: Error message if the operation failed
        subscription_info: Optional subscription information for the resource
        capability_metadata: Optional client capability metadata

    Example:
        >>> result = ResourceReadResult(
        ...     uri="scratchpad://abc-123/file.txt",
        ...     session_id="abc-123",
        ...     path="file.txt",
        ...     content=ResourceContent(...),
        ...     metadata=ResourceMetadata(...),
        ...     success=True
        ... )
    """

    uri: str
    session_id: str
    path: str
    content: ResourceContent
    metadata: ResourceMetadata
    success: bool
    error: Optional[str] = None
    subscription_info: dict[str, Any] = field(default_factory=dict)
    capability_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        result: dict[str, Any] = {
            "uri": self.uri,
            "session_id": self.session_id,
            "path": self.path,
            "content": {
                "data": self.content.to_string()
                if not isinstance(self.content.data, bytes)
                else base64.b64encode(self.content.data).decode("ascii"),
                "encoding": self.content.encoding,
                "is_binary": self.content.is_binary,
                "size_bytes": self.content.size_bytes,
            },
            "metadata": self.metadata.to_dict(),
            "subscription_info": self.subscription_info,
            "success": self.success,
            "error": self.error,
        }
        if self.capability_metadata:
            result["capability_metadata"] = self.capability_metadata
        return result


@dataclass(frozen=True)
class DirectoryEntry:
    """Entry in a directory listing.

    This dataclass represents a single file or directory entry
    within a directory listing.

    Attributes:
        name: The entry name (filename or directory name)
        type: The entry type ('file' or 'directory')
        size: File size in bytes (0 for directories)
        mimetype: MIME type of the entry (None for directories)
        modified_time: Last modification timestamp (ISO format)

    Example:
        >>> entry = DirectoryEntry(
        ...     name="test.txt",
        ...     type="file",
        ...     size=1024,
        ...     mimetype="text/plain",
        ...     modified_time="2024-01-15T10:30:00"
        ... )
    """

    name: str
    type: str  # 'file' or 'directory'
    size: int = 0
    mimetype: Optional[str] = None
    modified_time: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert entry to dictionary representation."""
        return {
            "name": self.name,
            "type": self.type,
            "size": self.size,
            "mimetype": self.mimetype,
            "modified_time": self.modified_time,
        }


@dataclass(frozen=True)
class DirectoryListingResult:
    """Result of reading a directory resource.

    This dataclass contains all information returned when listing
    a directory, including entries and pagination info.

    Attributes:
        uri: The original scratchpad:// URI
        session_id: The session identifier
        path: The directory path within the session
        entries: List of directory entries
        total_count: Total number of entries in the directory
        has_more: Whether there are more entries beyond this page
        offset: Current offset (skip count)
        limit: Current limit (page size)
        success: Whether the operation succeeded
        error: Error message if the operation failed

    Example:
        >>> result = DirectoryListingResult(
        ...     uri="scratchpad://abc-123/workspace",
        ...     session_id="abc-123",
        ...     path="/workspace",
        ...     entries=[DirectoryEntry(...)],
        ...     total_count=10,
        ...     has_more=False,
        ...     offset=0,
        ...     limit=100,
        ...     success=True
        ... )
    """

    uri: str
    session_id: str
    path: str
    entries: list[DirectoryEntry] = field(default_factory=list)
    total_count: int = 0
    has_more: bool = False
    offset: int = 0
    limit: int = 100
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "uri": self.uri,
            "session_id": self.session_id,
            "path": self.path,
            "entries": [entry.to_dict() for entry in self.entries],
            "total_count": self.total_count,
            "has_more": self.has_more,
            "offset": self.offset,
            "limit": self.limit,
            "success": self.success,
            "error": self.error,
        }


class ResourceReadError(Exception):
    """Exception raised when resource read operation fails.

    Attributes:
        message: Error message
        uri: The URI that caused the error
        code: Error code for programmatic handling
    """

    def __init__(
        self, message: str, uri: Optional[str] = None, code: str = "RESOURCE_ERROR"
    ):
        super().__init__(message)
        self.message = message
        self.uri = uri
        self.code = code


class SessionManagerProvider(Protocol):
    """Protocol for providing SessionFileSystemManager instances.

    This protocol allows dependency injection for testing and flexibility
    in how the session manager is obtained.
    """

    def get_manager(self) -> SessionFileSystemManager:
        """Get the session filesystem manager."""
        ...


# Large file threshold (1MB)
# Files larger than this will be returned as preview mode
LARGE_FILE_THRESHOLD = 1024 * 1024

# Default preview size for large files (1000 bytes/chars)
DEFAULT_PREVIEW_SIZE = 1000

# MIME type mapping for common extensions
# Maps file extensions to their MIME types (overrides mimetypes defaults)
MIME_TYPE_OVERRIDES: dict[str, str] = {
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".tsx": "text/typescript-jsx",
    ".jsx": "text/jsx",
    ".md": "text/markdown",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/toml",
    ".rst": "text/x-rst",
    ".lock": "text/plain",
    ".dockerfile": "text/x-dockerfile",
    ".dockerignore": "text/plain",
    ".gitignore": "text/plain",
    ".env": "text/plain",
    ".gitattributes": "text/plain",
    ".editorconfig": "text/plain",
}

# Binary MIME types that should not be decoded as text
BINARY_MIME_TYPES: set[str] = {
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-dosexec",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
}

# Image MIME types that get special handling
IMAGE_MIME_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/tiff",
    "image/x-icon",
}

# Text MIME types that are safe to decode as UTF-8
TEXT_MIME_TYPES: set[str] = {
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "text/markdown",
    "text/x-python",
    "text/x-python-script",
    "text/typescript",
    "text/jsx",
    "text/typescript-jsx",
    "text/xml",
    "text/yaml",
    "text/toml",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-httpd-php",
    "application/x-sh",
    "application/x-ruby",
}


def detect_mime_type(path: str, content: Optional[bytes] = None) -> str:
    """Detect MIME type from file path and optional content.

    Uses file extension first, then optionally examines content for
    type detection. Falls back to application/octet-stream for
    unrecognized types.

    Args:
        path: The file path (used for extension-based detection)
        content: Optional file content for content-based detection

    Returns:
        The detected MIME type string

    Example:
        >>> detect_mime_type("/workspace/file.txt")
        'text/plain'
        >>> detect_mime_type("/workspace/script.py")
        'text/x-python'
        >>> detect_mime_type("/workspace/image.png")
        'image/png'
    """
    # First check overrides for known extensions
    ext = Path(path).suffix.lower()
    if ext in MIME_TYPE_OVERRIDES:
        return MIME_TYPE_OVERRIDES[ext]

    # Use mimetypes library for standard detection
    mime_type, _ = mimetypes.guess_type(path, strict=False)

    if mime_type:
        return mime_type

    # If content is provided, try content-based detection
    if content:
        # Check for common binary signatures
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        elif content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        elif content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
            return "image/gif"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        elif content.startswith(b"%PDF-"):
            return "application/pdf"
        elif content.startswith(b"PK\x03\x04"):
            return "application/zip"
        elif content.startswith(b"\x1f\x8b"):
            return "application/gzip"
        elif content.startswith(b"ustar\x00") or content.startswith(b"ustar  "):
            return "application/x-tar"

        # Try to detect if it's text by checking for null bytes
        # and valid UTF-8 sequences
        try:
            if b"\x00" in content[:1024]:
                return "application/octet-stream"
            content[:1024].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return "application/octet-stream"

    # Default fallback
    return "application/octet-stream"


def classify_content_type(mime_type: str, path: str) -> ResourceContentType:
    """Classify content type from MIME type and path.

    Determines the ResourceContentType classification based on the
    MIME type and file extension.

    Args:
        mime_type: The detected MIME type
        path: The file path (for extension hints)

    Returns:
        The ResourceContentType classification

    Example:
        >>> classify_content_type("text/plain", "/test.txt")
        <ResourceContentType.TEXT: 'text'>
        >>> classify_content_type("image/png", "/test.png")
        <ResourceContentType.IMAGE: 'image'>
    """
    # Check for image types
    if mime_type in IMAGE_MIME_TYPES or mime_type.startswith("image/"):
        return ResourceContentType.IMAGE

    # Check for JSON
    if mime_type == "application/json" or path.endswith(".json"):
        return ResourceContentType.JSON

    # Check for XML
    if mime_type in ("application/xml", "text/xml") or path.endswith(".xml"):
        return ResourceContentType.XML

    # Check for text types
    if (
        mime_type in TEXT_MIME_TYPES
        or mime_type.startswith("text/")
        or mime_type in ("application/javascript", "application/json")
    ):
        return ResourceContentType.TEXT

    # Default to binary
    return ResourceContentType.BINARY


def is_binary_content(mime_type: str) -> bool:
    """Check if content should be treated as binary based on MIME type.

    Args:
        mime_type: The MIME type to check

    Returns:
        True if the content should be treated as binary

    Example:
        >>> is_binary_content("image/png")
        True
        >>> is_binary_content("text/plain")
        False
    """
    if mime_type in BINARY_MIME_TYPES:
        return True
    if mime_type.startswith("image/"):
        return True
    if mime_type.startswith("audio/"):
        return True
    if mime_type.startswith("video/"):
        return True
    if mime_type.startswith("application/"):
        # Some application types are text-safe
        if mime_type in TEXT_MIME_TYPES:
            return False
        return True
    return False


def read_file_content(
    fs: AbstractFileSystem,
    path: str,
    mime_type: str,
    max_size_bytes: Optional[int] = None,
) -> ResourceContent:
    """Read file content from filesystem with appropriate handling.

        Reads a file and returns its content wrapped in ResourceContent,
    with appropriate encoding based on the MIME type.

        Args:
            fs: The filesystem to read from
            path: The file path
            mime_type: The detected MIME type
            max_size_bytes: Optional maximum file size to read

        Returns:
            ResourceContent containing the file data

        Raises:
            ResourceReadError: If the file cannot be read
            FileTooLargeError: If file exceeds max_size_bytes

        Example:
            >>> content = read_file_content(fs, "/workspace/test.txt", "text/plain")
            >>> content.encoding
            'utf-8'
            >>> content.is_binary
            False
    """
    # Get file info for size check
    try:
        info = fs.info(path)
        file_size = info.get("size", 0)
    except Exception as e:
        raise ResourceReadError(
            f"Failed to get file info for '{path}': {e}", code="FILE_INFO_ERROR"
        ) from e

    # Check size limit
    if max_size_bytes and file_size > max_size_bytes:
        from ..exceptions import FileTooLargeError

        raise FileTooLargeError(
            f"File too large: {file_size} bytes exceeds limit of {max_size_bytes} bytes"
        )

    # Determine if binary
    binary_mode = is_binary_content(mime_type)

    try:
        if binary_mode:
            # Read as binary
            with fs.open(path, "rb") as f:
                data = f.read()
            return ResourceContent(
                data=data,
                encoding="base64",
                is_binary=True,
                size_bytes=len(data),
            )
        else:
            # Read as text (UTF-8)
            with fs.open(path, "r", encoding="utf-8") as f:
                data = f.read()
            return ResourceContent(
                data=data,
                encoding="utf-8",
                is_binary=False,
                size_bytes=len(data.encode("utf-8")),
            )
    except UnicodeDecodeError as e:
        # Failed to decode as UTF-8, fall back to binary
        try:
            with fs.open(path, "rb") as f:
                data = f.read()
            return ResourceContent(
                data=data,
                encoding="base64",
                is_binary=True,
                size_bytes=len(data),
            )
        except Exception as e2:
            raise ResourceReadError(
                f"Failed to read file '{path}': {e2}", code="READ_ERROR"
            ) from e2
    except Exception as e:
        raise ResourceReadError(
            f"Failed to read file '{path}': {e}", code="READ_ERROR"
        ) from e


def get_resource_metadata(
    fs: AbstractFileSystem,
    path: str,
    mime_type: str,
) -> ResourceMetadata:
    """Extract metadata from a file.

    Gathers file metadata including size, timestamps, and type information.

    Args:
        fs: The filesystem containing the file
        path: The file path
        mime_type: The detected MIME type

    Returns:
        ResourceMetadata containing file metadata

    Example:
        >>> meta = get_resource_metadata(fs, "/workspace/test.txt", "text/plain")
        >>> meta.size
        1024
        >>> meta.mime_type
        'text/plain'
    """
    # Get file info
    try:
        info = fs.info(path)
    except Exception:
        # Return minimal metadata if info fails
        ext = Path(path).suffix.lower() or None
        content_type = classify_content_type(mime_type, path).value
        return ResourceMetadata(
            size=0,
            mime_type=mime_type,
            extension=ext,
            content_type=content_type,
        )

    # Extract timestamps
    mtime = info.get("mtime")
    created = info.get("created")

    mtime_str = None
    created_str = None

    if mtime:
        try:
            if isinstance(mtime, (int, float)):
                mtime_str = datetime.fromtimestamp(mtime).isoformat()
            else:
                mtime_str = str(mtime)
        except Exception:
            pass

    if created:
        try:
            if isinstance(created, (int, float)):
                created_str = datetime.fromtimestamp(created).isoformat()
            else:
                created_str = str(created)
        except Exception:
            pass

    # Determine content type
    ext = Path(path).suffix.lower() or None
    content_type = classify_content_type(mime_type, path).value
    is_dir = info.get("type") == "directory" or fs.isdir(path)

    return ResourceMetadata(
        size=info.get("size", 0),
        mime_type=mime_type,
        modified=mtime_str,
        created=created_str,
        content_type=content_type,
        extension=ext,
        is_directory=is_dir,
    )


# Global session manager instance (can be overridden for testing)
_session_manager: Optional[SessionFileSystemManager] = None


def set_session_manager(manager: SessionFileSystemManager) -> None:
    """Set the global session manager instance.

    This function is primarily used for testing and dependency injection.

    Args:
        manager: The SessionFileSystemManager to use
    """
    global _session_manager
    _session_manager = manager


def get_session_manager() -> Optional[SessionFileSystemManager]:
    """Get the global session manager instance.

    Returns:
        The configured SessionFileSystemManager or None if not set
    """
    return _session_manager


def read_resource(
    uri: str,
    session_manager: Optional[SessionFileSystemManager] = None,
    max_size_bytes: Optional[int] = None,
    client_caps: Optional[set[Any]] = None,
) -> ResourceReadResult:
    """Read a resource from a scratchpad:// URI.

    This is the main entry point for reading scratchpad resources. It handles:
    - URI parsing
    - Session validation
    - File reading with appropriate encoding
    - MIME type detection
    - Metadata extraction
    - Error handling
    - Client capability negotiation

    Args:
        uri: The scratchpad:// URI to read
        session_manager: Optional session manager (uses global if not provided)
        max_size_bytes: Optional maximum file size limit
        client_caps: Optional set of client capabilities for format negotiation

    Returns:
        ResourceReadResult containing content, metadata, and capability info

    Raises:
        ResourceReadError: If the resource cannot be read
        SessionError: If the session is invalid or expired

    Example:
        >>> result = read_resource("scratchpad://abc-123/workspace/test.txt")
        >>> result.success
        True
        >>> result.content.data
        'Hello, World!'
        >>> result.metadata.mime_type
        'text/plain'

        >>> # With client capabilities
        >>> from mcp_scratchpad.resources.capabilities import ClientCapability
        >>> caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        >>> result = read_resource("scratchpad://abc-123/test.png", client_caps=caps)
        >>> result.capability_metadata["supported_formats"]
        ['text', 'image', 'binary']

        >>> # Error case
        >>> result = read_resource("scratchpad://invalid/file.txt")
        >>> result.success
        False
        >>> result.error
        "Session not found: invalid"
    """
    # Parse the URI
    try:
        parsed = parse_scratchpad_uri(uri)
        if not parsed.is_valid:
            error_msg = parsed.error or "Invalid URI"
            return ResourceReadResult(
                uri=uri,
                session_id=parsed.session_id or "",
                path=parsed.path,
                content=ResourceContent(
                    data="", encoding="utf-8", is_binary=False, size_bytes=0
                ),
                metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
                success=False,
                error=error_msg,
            )
    except URIParseError as e:
        return ResourceReadResult(
            uri=uri,
            session_id="",
            path="",
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=str(e),
        )
    except Exception as e:
        return ResourceReadResult(
            uri=uri,
            session_id="",
            path="",
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=f"Failed to parse URI: {e}",
        )

    # Ensure session_id is valid (should be non-None after is_valid check)
    if parsed.session_id is None:
        return ResourceReadResult(
            uri=uri,
            session_id="",
            path="",
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error="Invalid session_id in URI",
        )

    session_id: str = parsed.session_id
    path = "/" + parsed.path  # Ensure absolute path

    # Get session manager
    sm = session_manager or _session_manager
    if sm is None:
        # Try to import from main module (lazy import to avoid circular deps)
        try:
            from ..server import create_server

            # This is a fallback - in practice, the session manager should be provided
            return ResourceReadResult(
                uri=uri,
                session_id=session_id,
                path=path,
                content=ResourceContent(
                    data="", encoding="utf-8", is_binary=False, size_bytes=0
                ),
                metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
                success=False,
                error="Session manager not available. Please provide a session_manager.",
            )
        except ImportError:
            return ResourceReadResult(
                uri=uri,
                session_id=session_id,
                path=path,
                content=ResourceContent(
                    data="", encoding="utf-8", is_binary=False, size_bytes=0
                ),
                metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
                success=False,
                error="Session manager not available. Please provide a session_manager.",
            )

    # Get session filesystem
    fs = sm.get_session_fs(session_id)
    if fs is None:
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=f"Session not found: {session_id}",
        )

    # Check if path exists and is a file
    if not fs.exists(path):
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=f"File not found: {path}",
        )

    if fs.isdir(path):
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(
                size=0, mime_type="application/octet-stream", is_directory=True
            ),
            success=False,
            error=f"Path is a directory, not a file: {path}",
        )

    # Detect MIME type (read a small sample for content detection)
    try:
        with fs.open(path, "rb") as f:
            sample = f.read(1024)
        mime_type = detect_mime_type(path, sample)
    except Exception as e:
        # Fall back to extension-based detection
        mime_type = detect_mime_type(path)

    # Handle binary files (PDFs and other binary formats) with special processing
    if mime_type == "application/pdf" or (
        mime_type in BINARY_MIME_TYPES and not mime_type.startswith("image/")
    ):
        from .binary_handler import process_pdf_resource, process_binary_resource

        # Get file size for binary processing
        try:
            file_info = fs.info(path)
            file_size = file_info.get("size", 0)
        except Exception:
            file_size = 0

        if mime_type == "application/pdf":
            # Process PDF with metadata and optional text extraction
            binary_result = process_pdf_resource(
                uri=uri,
                fs=fs,
                session_id=session_id,
                path=path,
                file_size=file_size,
                extract_text=True,
                max_pages=2,
            )

            # Convert BinaryResource to ResourceReadResult
            if binary_result.success:
                # Create a ResourceContent with the binary data or metadata
                binary_dict = binary_result.to_dict()
                content_data = binary_dict.get("content", "")

                # For large files, content might be empty - use JSON representation
                if binary_result.is_large_file or not content_data:
                    import json

                    content_data = json.dumps(binary_dict)

                content = ResourceContent(
                    data=content_data,
                    encoding="base64" if not binary_result.is_large_file else "utf-8",
                    is_binary=not binary_result.is_large_file,
                    size_bytes=binary_result.size_bytes,
                )

                metadata = get_resource_metadata(fs, path, mime_type)

                # Get subscription info
                subscription_info = _get_subscription_info_for_uri(uri)

                # Get capability metadata
                capability_metadata: dict[str, Any] = {}
                if client_caps is not None:
                    from .capabilities import get_capability_info_for_resource

                    capability_metadata = get_capability_info_for_resource(
                        uri, mime_type, client_caps
                    )

                return ResourceReadResult(
                    uri=uri,
                    session_id=session_id,
                    path=path,
                    content=content,
                    metadata=metadata,
                    success=True,
                    subscription_info=subscription_info,
                    capability_metadata=capability_metadata,
                )
            else:
                return ResourceReadResult(
                    uri=uri,
                    session_id=session_id,
                    path=path,
                    content=ResourceContent(
                        data="", encoding="utf-8", is_binary=False, size_bytes=0
                    ),
                    metadata=ResourceMetadata(size=0, mime_type=mime_type),
                    success=False,
                    error=binary_result.error or "Failed to process PDF",
                )
        else:
            # Process other binary files
            binary_result = process_binary_resource(
                uri=uri,
                fs=fs,
                session_id=session_id,
                path=path,
                mime_type=mime_type,
            )

            # Convert BinaryResource to ResourceReadResult
            if binary_result.success:
                binary_dict = binary_result.to_dict()
                content_data = binary_dict.get("content", "")

                # For large files, use JSON representation
                if binary_result.is_large_file or not content_data:
                    import json

                    content_data = json.dumps(binary_dict)

                content = ResourceContent(
                    data=content_data,
                    encoding="base64" if not binary_result.is_large_file else "utf-8",
                    is_binary=not binary_result.is_large_file,
                    size_bytes=binary_result.size_bytes,
                )

                metadata = get_resource_metadata(fs, path, mime_type)
                subscription_info = _get_subscription_info_for_uri(uri)

                capability_metadata = {}
                if client_caps is not None:
                    from .capabilities import get_capability_info_for_resource

                    capability_metadata = get_capability_info_for_resource(
                        uri, mime_type, client_caps
                    )

                return ResourceReadResult(
                    uri=uri,
                    session_id=session_id,
                    path=path,
                    content=content,
                    metadata=metadata,
                    success=True,
                    subscription_info=subscription_info,
                    capability_metadata=capability_metadata,
                )
            else:
                return ResourceReadResult(
                    uri=uri,
                    session_id=session_id,
                    path=path,
                    content=ResourceContent(
                        data="", encoding="utf-8", is_binary=False, size_bytes=0
                    ),
                    metadata=ResourceMetadata(size=0, mime_type=mime_type),
                    success=False,
                    error=binary_result.error or "Failed to process binary file",
                )

    # Handle image files with special processing
    if mime_type.startswith("image/"):
        from .image_handler import process_image_resource

        # Get file info for image processing
        try:
            file_info = fs.info(path)
            file_size = file_info.get("size", 0)
        except Exception:
            file_size = 0

        # Determine thumbnail sizes from client capabilities
        thumbnail_sizes = ["small"]  # Default thumbnail size
        if client_caps is not None:
            # Check if client requested specific thumbnail sizes
            for cap in client_caps:
                if hasattr(cap, "value"):
                    cap_value = cap.value
                    if "thumbnail_medium" in str(cap_value).lower():
                        thumbnail_sizes.append("medium")
                    if "thumbnail_large" in str(cap_value).lower():
                        thumbnail_sizes.append("large")

        # Process image with metadata and thumbnails
        image_result = process_image_resource(
            uri=uri,
            fs=fs,
            session_id=session_id,
            path=path,
            mime_type=mime_type,
            thumbnail_sizes=thumbnail_sizes,
        )

        # Convert ImageResource to ResourceReadResult format
        if image_result.success:
            image_dict = image_result.to_dict()
            content_data = image_dict.get("content", "")

            # For large files, use JSON representation with metadata and thumbnails
            if image_result.is_large_file or not content_data:
                import json

                content_data = json.dumps(image_dict)

            content = ResourceContent(
                data=content_data,
                encoding="base64" if not image_result.is_large_file else "utf-8",
                is_binary=True,
                size_bytes=image_result.size_bytes,
            )

            # Create metadata with image-specific fields
            metadata = ResourceMetadata(
                size=image_result.size_bytes,
                mime_type=mime_type,
                content_type="image",
                extension=Path(path).suffix.lower() or None,
            )

            # Get subscription info
            subscription_info = _get_subscription_info_for_uri(uri)

            # Add image metadata to capability_metadata
            capability_metadata: dict[str, Any] = {
                "image_format": image_result.image_format,
                "dimensions": {
                    "width": image_result.width,
                    "height": image_result.height,
                },
                "thumbnails": list(image_result.thumbnail_content.keys()),
                "is_large_file": image_result.is_large_file,
            }

            return ResourceReadResult(
                uri=uri,
                session_id=session_id,
                path=path,
                content=content,
                metadata=metadata,
                success=True,
                subscription_info=subscription_info,
                capability_metadata=capability_metadata,
            )
        else:
            return ResourceReadResult(
                uri=uri,
                session_id=session_id,
                path=path,
                content=ResourceContent(
                    data="", encoding="utf-8", is_binary=False, size_bytes=0
                ),
                metadata=ResourceMetadata(size=0, mime_type=mime_type),
                success=False,
                error=image_result.error or "Failed to process image",
            )

    # Read content for non-binary files
    try:
        content = read_file_content(fs, path, mime_type, max_size_bytes)
    except ResourceReadError:
        raise
    except Exception as e:
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type=mime_type),
            success=False,
            error=f"Failed to read file: {e}",
        )

    # Get metadata
    metadata = get_resource_metadata(fs, path, mime_type)

    # Get subscription info for this resource
    subscription_info = _get_subscription_info_for_uri(uri)

    # Get capability metadata if client_caps provided
    capability_metadata: dict[str, Any] = {}
    if client_caps is not None:
        from .capabilities import get_capability_info_for_resource

        capability_metadata = get_capability_info_for_resource(
            uri, mime_type, client_caps
        )

    return ResourceReadResult(
        uri=uri,
        session_id=session_id,
        path=path,
        content=content,
        metadata=metadata,
        success=True,
        subscription_info=subscription_info,
        capability_metadata=capability_metadata,
    )


def _get_subscription_info_for_uri(uri: str) -> dict[str, Any]:
    """Get subscription information for a URI.

    This is a helper function to lazily import subscription functions
    and avoid circular imports.

    Args:
        uri: The resource URI

    Returns:
        Dictionary with subscription info
    """
    try:
        from .subscription import get_resource_subscription_info

        return get_resource_subscription_info(uri)
    except ImportError:
        # Subscription module not available
        return {
            "is_subscribed": False,
            "subscription_count": 0,
            "subscription_ids": [],
            "last_modified": None,
        }


def read_resource_text(
    uri: str,
    session_manager: Optional[SessionFileSystemManager] = None,
    max_size_bytes: Optional[int] = None,
) -> str:
    """Read a resource and return content as text.

    Convenience function that reads a resource and returns just the text
    content. For binary files, returns base64-encoded string.

    Args:
        uri: The scratchpad:// URI to read
        session_manager: Optional session manager
        max_size_bytes: Optional maximum file size limit

    Returns:
        The file content as text (or base64 for binary)

    Raises:
        ResourceReadError: If the resource cannot be read

    Example:
        >>> text = read_resource_text("scratchpad://abc-123/test.txt")
        >>> print(text)
        Hello, World!
    """
    result = read_resource(uri, session_manager, max_size_bytes)
    if not result.success:
        raise ResourceReadError(result.error or "Unknown error", uri=uri)
    return result.content.to_string()


def read_resource_bytes(
    uri: str,
    session_manager: Optional[SessionFileSystemManager] = None,
    max_size_bytes: Optional[int] = None,
) -> bytes:
    """Read a resource and return content as bytes.

    Convenience function that reads a resource and returns raw bytes.

    Args:
        uri: The scratchpad:// URI to read
        session_manager: Optional session manager
        max_size_bytes: Optional maximum file size limit

    Returns:
        The file content as raw bytes

    Raises:
        ResourceReadError: If the resource cannot be read

    Example:
        >>> data = read_resource_bytes("scratchpad://abc-123/image.png")
        >>> len(data)
        1024
    """
    result = read_resource(uri, session_manager, max_size_bytes)
    if not result.success:
        raise ResourceReadError(result.error or "Unknown error", uri=uri)

    if isinstance(result.content.data, bytes):
        return result.content.data
    else:
        # Handle base64 encoded content (binary data stored as base64 string)
        if result.content.encoding == "base64":
            import base64

            return base64.b64decode(result.content.data)
        # Handle regular text content
        return result.content.data.encode(result.content.encoding or "utf-8")


def read_directory_resource(
    uri: str,
    session_manager: Optional[SessionFileSystemManager] = None,
    limit: int = 100,
    offset: int = 0,
) -> DirectoryListingResult:
    """Read a directory listing from a scratchpad:// URI.

    This function lists the contents of a directory, returning structured
    information about each entry including name, type, size, and metadata.
    It supports pagination for large directories.

    Args:
        uri: The scratchpad:// URI to read (must point to a directory)
        session_manager: Optional session manager (uses global if not provided)
        limit: Maximum number of entries to return (default 100)
        offset: Number of entries to skip (default 0)

    Returns:
        DirectoryListingResult containing entries and pagination info

    Raises:
        ResourceReadError: If the directory cannot be read

    Example:
        >>> result = read_directory_resource("scratchpad://abc-123/workspace/")
        >>> result.success
        True
        >>> len(result.entries)
        5
        >>> result.entries[0].name
        'file.txt'
        >>> result.entries[0].type
        'file'

        >>> # Pagination example
        >>> result = read_directory_resource(
        ...     "scratchpad://abc-123/workspace/",
        ...     limit=10,
        ...     offset=20
        ... )
        >>> result.offset
        20
        >>> result.has_more
        True
    """
    # Parse the URI
    try:
        parsed = parse_scratchpad_uri(uri)
        if not parsed.is_valid:
            error_msg = parsed.error or "Invalid URI"
            return DirectoryListingResult(
                uri=uri,
                session_id=parsed.session_id or "",
                path=parsed.path,
                success=False,
                error=error_msg,
            )
    except URIParseError as e:
        return DirectoryListingResult(
            uri=uri,
            session_id="",
            path="",
            success=False,
            error=str(e),
        )
    except Exception as e:
        return DirectoryListingResult(
            uri=uri,
            session_id="",
            path="",
            success=False,
            error=f"Failed to parse URI: {e}",
        )

    # Ensure session_id is valid
    if parsed.session_id is None:
        return DirectoryListingResult(
            uri=uri,
            session_id="",
            path="",
            success=False,
            error="Invalid session_id in URI",
        )

    session_id: str = parsed.session_id
    path = "/" + parsed.path if parsed.path else "/"

    # Get session manager
    sm = session_manager or _session_manager
    if sm is None:
        return DirectoryListingResult(
            uri=uri,
            session_id=session_id,
            path=path,
            success=False,
            error="Session manager not available. Please provide a session_manager.",
        )

    # Get session filesystem
    fs = sm.get_session_fs(session_id)
    if fs is None:
        return DirectoryListingResult(
            uri=uri,
            session_id=session_id,
            path=path,
            success=False,
            error=f"Session not found: {session_id}",
        )

    # Check if path exists
    if not fs.exists(path):
        return DirectoryListingResult(
            uri=uri,
            session_id=session_id,
            path=path,
            success=False,
            error=f"Resource not found: {path}",
        )

    # Check if path is a directory
    if not fs.isdir(path):
        return DirectoryListingResult(
            uri=uri,
            session_id=session_id,
            path=path,
            success=False,
            error=f"Resource is not a directory: {path}",
        )

    # List directory contents
    try:
        all_entries = fs.ls(path, detail=False)
    except Exception as e:
        return DirectoryListingResult(
            uri=uri,
            session_id=session_id,
            path=path,
            success=False,
            error=f"Failed to list directory: {e}",
        )

    # Get total count before pagination
    total_count = len(all_entries)

    # Apply pagination
    paginated_entries = all_entries[offset : offset + limit]
    has_more = (offset + limit) < total_count

    # Build entry list with metadata
    entries: list[DirectoryEntry] = []
    for entry_path in paginated_entries:
        try:
            # Get entry name from path
            name = Path(entry_path).name

            # Get file info
            try:
                info = fs.info(entry_path)
            except Exception:
                # Skip entries we can't stat
                continue

            # Determine entry type
            entry_type = "directory" if fs.isdir(entry_path) else "file"

            # Get size (0 for directories)
            size = 0 if entry_type == "directory" else info.get("size", 0)

            # Get MIME type for files
            mimetype = None
            if entry_type == "file":
                mimetype = detect_mime_type(entry_path)

            # Get modification time
            mtime = info.get("mtime")
            modified_time: Optional[str] = None
            if mtime:
                try:
                    if isinstance(mtime, (int, float)):
                        modified_time = datetime.fromtimestamp(mtime).isoformat()
                    else:
                        modified_time = str(mtime)
                except Exception:
                    pass

            entries.append(
                DirectoryEntry(
                    name=name,
                    type=entry_type,
                    size=size,
                    mimetype=mimetype,
                    modified_time=modified_time,
                )
            )
        except Exception:
            # Skip entries that can't be processed
            continue

    return DirectoryListingResult(
        uri=uri,
        session_id=session_id,
        path=path,
        entries=entries,
        total_count=total_count,
        has_more=has_more,
        offset=offset,
        limit=limit,
        success=True,
    )


# ===============================================================================
# Large File Preview Support (Task 38)
# ===============================================================================


@dataclass(frozen=True)
class LargeFilePreview:
    """Preview information for large files.

    When a file exceeds LARGE_FILE_THRESHOLD, this structure provides
    a preview of the file content including start/end chunks and metadata.

    Attributes:
        total_size: Total file size in bytes
        mimetype: Detected MIME type of the file
        preview_start: First N bytes/chars of the file (base64 for binary)
        preview_end: Last N bytes/chars of the file (base64 for binary)
        preview_size: Number of bytes/chars in each preview chunk
        line_count: Number of lines (for text files, None for binary)
        is_binary: Whether the file is binary
        message: Human-readable message about the preview

    Example:
        >>> preview = LargeFilePreview(
        ...     total_size=10000000,
        ...     mimetype="text/plain",
        ...     preview_start="First 1000 chars...",
        ...     preview_end="...last 1000 chars",
        ...     line_count=50000,
        ...     is_binary=False,
        ...     message="File too large, showing preview"
        ... )
    """

    total_size: int
    mimetype: str
    preview_start: str
    preview_end: str
    preview_size: int
    is_binary: bool
    line_count: Optional[int] = None
    message: str = "File too large, showing preview"

    def to_dict(self) -> dict[str, Any]:
        """Convert preview to dictionary representation."""
        result: dict[str, Any] = {
            "type": "large_file_preview",
            "total_size": self.total_size,
            "mimetype": self.mimetype,
            "preview_start": self.preview_start,
            "preview_end": self.preview_end,
            "preview_size": self.preview_size,
            "is_binary": self.is_binary,
            "message": self.message,
        }
        if self.line_count is not None:
            result["line_count"] = self.line_count
        return result


@dataclass(frozen=True)
class FileMetadataResult:
    """Result of getting file metadata.

    This dataclass contains metadata-only information about a file,
    used when you only need file information without reading content.

    Attributes:
        uri: The original scratchpad:// URI
        session_id: The session identifier
        path: The file path within the session
        exists: Whether the file exists
        size: File size in bytes
        mimetype: MIME type of the resource
        modified: Last modification timestamp (ISO format)
        created: Creation timestamp (ISO format)
        is_binary: Whether the file is binary
        is_directory: Whether this is a directory
        line_count: Number of lines (for text files)
        success: Whether the metadata retrieval succeeded
        error: Error message if the operation failed

    Example:
        >>> result = FileMetadataResult(
        ...     uri="scratchpad://abc-123/file.txt",
        ...     session_id="abc-123",
        ...     path="file.txt",
        ...     exists=True,
        ...     size=1024,
        ...     mimetype="text/plain",
        ...     line_count=50,
        ...     success=True
        ... )
    """

    uri: str
    session_id: str
    path: str
    exists: bool
    size: int
    mimetype: str
    modified: Optional[str] = None
    created: Optional[str] = None
    is_binary: bool = False
    is_directory: bool = False
    line_count: Optional[int] = None
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        result: dict[str, Any] = {
            "uri": self.uri,
            "session_id": self.session_id,
            "path": self.path,
            "exists": self.exists,
            "size": self.size,
            "mimetype": self.mimetype,
            "modified": self.modified,
            "created": self.created,
            "is_binary": self.is_binary,
            "is_directory": self.is_directory,
            "success": self.success,
        }
        if self.line_count is not None:
            result["line_count"] = self.line_count
        if self.error is not None:
            result["error"] = self.error
        return result


def count_lines_in_text(
    fs: AbstractFileSystem, path: str, sample_size: int = 1024 * 1024
) -> int:
    """Count lines in a text file efficiently.

    For large files, samples the beginning to estimate line count.

    Args:
        fs: The filesystem containing the file
        path: The file path
        sample_size: Number of bytes to sample for line counting (default 1MB)

    Returns:
        Number of lines in the file, or -1 if counting failed
    """
    try:
        info = fs.info(path)
        file_size = info.get("size", 0)

        if file_size == 0:
            return 0

        # For very large files, sample beginning to estimate
        if file_size > sample_size:
            with fs.open(path, "r", encoding="utf-8", errors="replace") as f:
                first_chunk = f.read(sample_size)
                lines_in_first = first_chunk.count("\n")
                avg_line_length = sample_size / max(1, lines_in_first)
                estimated_lines = int(file_size / avg_line_length)
                return estimated_lines
        else:
            # For smaller files, count all lines
            with fs.open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)

    except Exception:
        return -1


def read_large_file_preview(
    fs: AbstractFileSystem,
    path: str,
    mime_type: str,
    preview_size: int = DEFAULT_PREVIEW_SIZE,
) -> LargeFilePreview:
    """Read preview of a large file (start and end chunks).

    This function efficiently reads preview chunks from large files
    without loading the entire file into memory.

    Args:
        fs: The filesystem containing the file
        path: The file path
        mime_type: The detected MIME type
        preview_size: Number of bytes/chars to read from start and end

    Returns:
        LargeFilePreview containing preview information

    Example:
        >>> preview = read_large_file_preview(fs, "/large.txt", "text/plain")
        >>> preview.total_size
        10000000
        >>> preview.preview_start
        'First 1000 chars of the file...'
    """
    try:
        info = fs.info(path)
        total_size = info.get("size", 0)
    except Exception:
        total_size = 0

    is_binary = is_binary_content(mime_type)

    # Read start chunk
    start_content = ""
    end_content = ""

    if is_binary:
        # For binary files, use byte chunks and base64 encode
        try:
            # Read start bytes
            with fs.open(path, "rb") as f:
                start_bytes = f.read(min(preview_size, total_size))
                start_content = base64.b64encode(start_bytes).decode("ascii")

            # Read end bytes
            if total_size > preview_size:
                # Use cat_file for byte range reading if available
                if hasattr(fs, "cat_file"):
                    import os

                    end_bytes = fs.cat_file(
                        path, start=max(0, total_size - preview_size)
                    )
                    end_content = base64.b64encode(end_bytes).decode("ascii")
                else:
                    # Fall back to reading from filesystem
                    with fs.open(path, "rb") as f:
                        # Try to seek
                        try:
                            f.seek(max(0, total_size - preview_size))
                            end_bytes = f.read(preview_size)
                            end_content = base64.b64encode(end_bytes).decode("ascii")
                        except (OSError, ValueError):
                            end_content = (
                                "<binary content - unable to read end preview>"
                            )
            else:
                end_content = start_content
        except Exception:
            start_content = "<binary content - unable to read preview>"
            end_content = "<binary content - unable to read preview>"
    else:
        # For text files, read as text
        try:
            # Read start of file
            with fs.open(path, "r", encoding="utf-8", errors="replace") as f:
                start_content = f.read(preview_size)

            # Read end of file
            if total_size > preview_size:
                with fs.open(path, "r", encoding="utf-8", errors="replace") as f:
                    # For text, we need to read and skip
                    chunk_size = min(preview_size, total_size)
                    # Read all content and take last N chars
                    # This is memory-intensive but necessary for text files
                    if total_size <= 10 * 1024 * 1024:  # Only for files < 10MB
                        full_content = f.read()
                        end_content = full_content[-preview_size:]
                    else:
                        # For very large files, just note we couldn't read end
                        end_content = f"<file too large ({total_size} bytes) - end preview not available>"
            else:
                end_content = start_content
        except Exception as e:
            start_content = f"<error reading preview: {e}>"
            end_content = f"<error reading preview: {e}>"

    # Count lines for text files
    line_count: Optional[int] = None
    if not is_binary:
        line_count = count_lines_in_text(fs, path)

    return LargeFilePreview(
        total_size=total_size,
        mimetype=mime_type,
        preview_start=start_content,
        preview_end=end_content,
        preview_size=preview_size,
        is_binary=is_binary,
        line_count=line_count,
        message=f"File too large ({total_size} bytes), showing preview of first and last {preview_size} bytes/chars",
    )


def get_file_metadata(
    uri: str,
    session_manager: Optional[SessionFileSystemManager] = None,
    include_line_count: bool = True,
) -> FileMetadataResult:
    """Get metadata for a file without reading its full content.

    This is useful when you only need file information (size, type, timestamps)
    without loading the entire file into memory.

    Args:
        uri: The scratchpad:// URI to get metadata for
        session_manager: Optional session manager (uses global if not provided)
        include_line_count: Whether to count lines for text files (default True)

    Returns:
        FileMetadataResult containing file metadata

    Example:
        >>> result = get_file_metadata("scratchpad://abc-123/workspace/file.txt")
        >>> result.success
        True
        >>> result.size
        1024
        >>> result.mimetype
        'text/plain'
        >>> result.line_count
        50
    """
    # Parse the URI
    try:
        parsed = parse_scratchpad_uri(uri)
        if not parsed.is_valid:
            error_msg = parsed.error or "Invalid URI"
            return FileMetadataResult(
                uri=uri,
                session_id=parsed.session_id or "",
                path=parsed.path,
                exists=False,
                size=0,
                mimetype="application/octet-stream",
                success=False,
                error=error_msg,
            )
    except URIParseError as e:
        return FileMetadataResult(
            uri=uri,
            session_id="",
            path="",
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=False,
            error=str(e),
        )
    except Exception as e:
        return FileMetadataResult(
            uri=uri,
            session_id="",
            path="",
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=False,
            error=f"Failed to parse URI: {e}",
        )

    # Ensure session_id is valid
    if parsed.session_id is None:
        return FileMetadataResult(
            uri=uri,
            session_id="",
            path="",
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=False,
            error="Invalid session_id in URI",
        )

    session_id: str = parsed.session_id
    path = "/" + parsed.path  # Ensure absolute path

    # Get session manager
    sm = session_manager or _session_manager
    if sm is None:
        return FileMetadataResult(
            uri=uri,
            session_id=session_id,
            path=path,
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=False,
            error="Session manager not available",
        )

    # Get session filesystem
    fs = sm.get_session_fs(session_id)
    if fs is None:
        return FileMetadataResult(
            uri=uri,
            session_id=session_id,
            path=path,
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=False,
            error=f"Session not found: {session_id}",
        )

    # Check if path exists
    if not fs.exists(path):
        return FileMetadataResult(
            uri=uri,
            session_id=session_id,
            path=path,
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=True,  # Success - file just doesn't exist
        )

    # Check if it's a directory
    is_directory = fs.isdir(path)

    # Detect MIME type
    try:
        if is_directory:
            mime_type = "application/octet-stream"
        else:
            with fs.open(path, "rb") as f:
                sample = f.read(1024)
            mime_type = detect_mime_type(path, sample)
    except Exception:
        mime_type = detect_mime_type(path)

    is_binary = is_binary_content(mime_type)

    # Get file info
    size = 0
    modified = None
    created = None
    line_count: Optional[int] = None

    try:
        info = fs.info(path)
        size = info.get("size", 0)

        mtime = info.get("mtime")
        if mtime:
            try:
                import datetime

                if isinstance(mtime, (int, float)):
                    modified = datetime.fromtimestamp(mtime).isoformat()
                else:
                    modified = str(mtime)
            except Exception:
                pass

        ctime = info.get("created")
        if ctime:
            try:
                if isinstance(ctime, (int, float)):
                    created = datetime.fromtimestamp(ctime).isoformat()
                else:
                    created = str(ctime)
            except Exception:
                pass

        # Count lines for text files if requested
        if include_line_count and not is_directory and not is_binary:
            line_count = count_lines_in_text(fs, path)
    except Exception:
        pass

    return FileMetadataResult(
        uri=uri,
        session_id=session_id,
        path=path,
        exists=True,
        size=size,
        mimetype=mime_type,
        modified=modified,
        created=created,
        is_binary=is_binary,
        is_directory=is_directory,
        line_count=line_count,
        success=True,
    )


def read_file_chunk(
    uri: str,
    offset: int = 0,
    limit: int = 1024,
    session_manager: Optional[SessionFileSystemManager] = None,
) -> ResourceReadResult:
    """Read a specific chunk of a file from a scratchpad:// URI.

    This function allows reading a specific portion of a file using
    byte/char offset and limit parameters.

    Args:
        uri: The scratchpad:// URI to read
        offset: Byte/char offset to start reading from (default 0)
        limit: Maximum number of bytes/chars to read (default 1024)
        session_manager: Optional session manager (uses global if not provided)

    Returns:
        ResourceReadResult containing the requested chunk

    Raises:
        ResourceReadError: If the resource cannot be read

    Example:
        >>> result = read_file_chunk("scratchpad://abc-123/large.log", offset=0, limit=1024)
        >>> result.content.data
        'First 1KB of the file...'
        >>> result = read_file_chunk("scratchpad://abc-123/large.log", offset=1024, limit=1024)
        >>> result.content.data
        'Second 1KB of the file...'
    """
    # Parse the URI
    try:
        parsed = parse_scratchpad_uri(uri)
        if not parsed.is_valid:
            error_msg = parsed.error or "Invalid URI"
            return ResourceReadResult(
                uri=uri,
                session_id=parsed.session_id or "",
                path=parsed.path,
                content=ResourceContent(
                    data="", encoding="utf-8", is_binary=False, size_bytes=0
                ),
                metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
                success=False,
                error=error_msg,
            )
    except URIParseError as e:
        return ResourceReadResult(
            uri=uri,
            session_id="",
            path="",
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=str(e),
        )

    # Ensure session_id is valid
    if parsed.session_id is None:
        return ResourceReadResult(
            uri=uri,
            session_id="",
            path="",
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error="Invalid session_id in URI",
        )

    session_id: str = parsed.session_id
    path = "/" + parsed.path  # Ensure absolute path

    # Get session manager
    sm = session_manager or _session_manager
    if sm is None:
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error="Session manager not available",
        )

    # Get session filesystem
    fs = sm.get_session_fs(session_id)
    if fs is None:
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=f"Session not found: {session_id}",
        )

    # Check if path exists and is a file
    if not fs.exists(path):
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type="application/octet-stream"),
            success=False,
            error=f"File not found: {path}",
        )

    if fs.isdir(path):
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(
                size=0, mime_type="application/octet-stream", is_directory=True
            ),
            success=False,
            error=f"Path is a directory, not a file: {path}",
        )

    # Detect MIME type
    try:
        with fs.open(path, "rb") as f:
            sample = f.read(1024)
        mime_type = detect_mime_type(path, sample)
    except Exception:
        mime_type = detect_mime_type(path)

    is_binary = is_binary_content(mime_type)

    # Read the chunk
    try:
        if is_binary:
            # Binary mode with seek
            with fs.open(path, "rb") as f:
                if hasattr(f, "seek"):
                    f.seek(offset)
                data = f.read(limit)
            content = ResourceContent(
                data=data,
                encoding="base64",
                is_binary=True,
                size_bytes=len(data),
            )
        else:
            # Text mode
            with fs.open(path, "r", encoding="utf-8", errors="replace") as f:
                # For text, we need to read and skip characters
                if hasattr(f, "seek") and offset > 0:
                    # Try to seek if supported
                    try:
                        f.seek(offset)
                        data = f.read(limit)
                    except (OSError, TypeError):
                        # Fall back to reading character by character
                        f.read(offset)  # Skip characters
                        data = f.read(limit)
                else:
                    if offset > 0:
                        f.read(offset)  # Skip characters
                    data = f.read(limit)

            content = ResourceContent(
                data=data,
                encoding="utf-8",
                is_binary=False,
                size_bytes=len(data.encode("utf-8")),
            )
    except Exception as e:
        return ResourceReadResult(
            uri=uri,
            session_id=session_id,
            path=path,
            content=ResourceContent(
                data="", encoding="utf-8", is_binary=False, size_bytes=0
            ),
            metadata=ResourceMetadata(size=0, mime_type=mime_type),
            success=False,
            error=f"Failed to read file chunk: {e}",
        )

    # Get metadata
    metadata = get_resource_metadata(fs, path, mime_type)

    return ResourceReadResult(
        uri=uri,
        session_id=session_id,
        path=path,
        content=content,
        metadata=metadata,
        success=True,
        subscription_info=_get_subscription_info_for_uri(uri),
    )
