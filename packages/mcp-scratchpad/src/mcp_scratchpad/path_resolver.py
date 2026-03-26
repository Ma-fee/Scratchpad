"""Centralized path resolution for all file tools.

Handles:
- URI parsing (scratchpad://)
- Relative path resolution
- Absolute path validation
- Security checks (path traversal protection)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import normalize_path

if TYPE_CHECKING:
    from .storage import FileSystemStore


class PathResolutionError(Exception):
    """Raised when path resolution fails."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


# Supported URI schemes
URI_SCHEMES = {
    "scratchpad": "Local scratchpad storage (primary scheme)",
}

# Default scheme when none specified
DEFAULT_SCHEME = "scratchpad"


def parse_uri(uri: str) -> tuple[str, str]:
    """Parse a URI string into (scheme, path) tuple.

    Args:
        uri: URI string like "scratchpad:///path/to/file" or "/path/to/file"

    Returns:
        Tuple of (scheme, path) where scheme defaults to "scratchpad"

    Raises:
        PathResolutionError: If URI format is invalid or scheme unsupported
    """
    if not uri or not uri.strip():
        raise PathResolutionError("Empty path provided")

    # Check if it looks like a URI (has :// or ://)
    uri_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://(.*)", uri)
    if uri_match:
        scheme = uri_match.group(1).lower()
        path = uri_match.group(2)

        if scheme not in URI_SCHEMES:
            supported = ", ".join(URI_SCHEMES.keys())
            raise PathResolutionError(
                f"Unsupported URI scheme: {scheme}. Supported schemes: {supported}", uri
            )

        # Handle scratchpad://///path or scratchpad:///path
        # Multiple slashes after scheme should collapse to single leading /
        path = "/" + path.lstrip("/")

        return scheme, path

    # Not a URI - treat as plain path (defaults to scratchpad scheme)
    return DEFAULT_SCHEME, uri


def resolve_file_path(
    path_input: str,
    store: FileSystemStore,
    allow_absolute: bool = True,
) -> Path:
    """Resolve any path input (URI, relative, absolute) to a filesystem Path.

    This is the central resolver used by ALL file tools. It handles:
    - scratchpad:// URIs
    - Relative paths (resolved against session directory)
    - Absolute paths (starting with /)

    Args:
        path_input: Path string (can be URI, relative, or absolute)
        store: FileSystemStore instance for session context
        allow_absolute: Whether to allow absolute paths (default: True)

    Returns:
        Resolved Path object pointing to actual filesystem location

    Raises:
        PathResolutionError: If path cannot be resolved or is invalid
    """
    # Parse URI if present
    scheme, path = parse_uri(path_input)

    # Currently only scratchpad scheme is supported
    if scheme != "scratchpad":
        raise PathResolutionError(f"Scheme '{scheme}' not yet implemented", path_input)

    # Basic validation: path must be non-empty and reasonable length
    if not path or len(path) > 256:
        raise PathResolutionError(
            "Path is empty or too long (max 256 chars)", path_input
        )

    # Convert backslashes to forward slashes for consistency
    path = path.replace("\\", "/")

    # Check for path traversal attempt pattern (contains .. in input)
    # We allow .. components but the final resolved path MUST be within bounds
    if ".." in path.split("/"):
        # Contains .. component - we'll resolve and check bounds after
        pass  # Let Path.resolve() handle the normalization

    # Determine base directory
    base_dir = store._session_dir()
    resolved_base = base_dir.resolve()

    # Handle absolute vs relative paths
    if path.startswith("/"):
        if not allow_absolute:
            raise PathResolutionError(
                "Absolute paths not allowed for this operation", path_input
            )
        # Absolute path: base_dir + path (without leading /)
        target_path = base_dir / path.lstrip("/")
    else:
        # Relative path: base_dir + path
        target_path = base_dir / path

    # Resolve to eliminate . and .. components
    try:
        resolved = target_path.resolve()
    except (OSError, ValueError) as e:
        raise PathResolutionError(f"Failed to resolve path: {e}", path_input) from e

    # Final security check: resolved path must be within base_dir
    try:
        resolved.relative_to(resolved_base)
    except ValueError:
        raise PathResolutionError(
            f"Path '{path_input}' resolves outside of allowed directory", path_input
        )

    return resolved


def resolve_file_path_for_read(
    path_input: str,
    store: FileSystemStore,
) -> Path:
    """Convenience wrapper for read operations.

    Allows absolute paths and returns resolved Path.
    """
    return resolve_file_path(path_input, store, allow_absolute=True)


def resolve_file_path_for_write(
    path_input: str,
    store: FileSystemStore,
) -> Path:
    """Convenience wrapper for write operations.

    Allows absolute paths. Creates parent directories if needed.
    """
    resolved = resolve_file_path(path_input, store, allow_absolute=True)
    return resolved


def get_relative_path(
    full_path: Path,
    store: FileSystemStore,
) -> str:
    """Get the relative path from a full filesystem path.

    Args:
        full_path: Absolute filesystem path
        store: FileSystemStore for session context

    Returns:
        Relative path string (for use in URIs or relative references)
    """
    try:
        rel = full_path.relative_to(store._session_dir())
        return str(rel).replace("\\", "/")
    except ValueError:
        # Path is outside session dir, return as-is with leading /
        return str(full_path).replace("\\", "/")


def build_uri(relative_path: str) -> str:
    """Build a scratchpad:// URI from a relative path.

    Args:
        relative_path: Relative path within scratchpad

    Returns:
        URI string like "scratchpad:///path/to/file"
    """
    # Ensure path doesn't have leading / (will be added in URI format)
    clean_path = relative_path.lstrip("/")
    return f"scratchpad:///{clean_path}"


def get_path_description() -> str:
    """Get standardized parameter description for file_path fields.

    Returns description text to use in Field(description=...)."""
    return (
        "Path to the file. Supports: "
        "(1) Relative path (e.g., 'reports/file.txt') - resolved relative to session directory; "
        "(2) Absolute path from session root (e.g., '/reports/file.txt'); "
        "(3) URI format (e.g., 'scratchpad:///reports/file.txt'). "
        "Use URI format for maximum clarity."
    )
