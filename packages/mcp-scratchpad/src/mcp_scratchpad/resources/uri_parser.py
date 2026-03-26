"""URI parser for scratchpad:// scheme.

This module provides utilities for parsing and validating scratchpad:// URIs
used by the MCP Scratchpad filesystem.

URI Format:
    scratchpad://{session_id}/{path}

Examples:
    - scratchpad://550e8400-e29b-41d4-a716-446655440000/file.txt
    - scratchpad://550e8400-e29b-41d4-a716-446655440000/dir/subdir/file.txt
    - scratchpad://550e8400-e29b-41d4-a716-446655440000/
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, unquote
import uuid
import re


@dataclass(frozen=True)
class ScratchpadURI:
    """Parsed scratchpad:// URI result.

    Attributes:
        session_id: The session UUID
        path: Normalized filesystem path (relative to session root)
        is_valid: Whether the URI is valid
        error: Error message if URI is invalid, None otherwise
        original_uri: The original URI string
    """

    session_id: Optional[str]
    path: str
    is_valid: bool
    error: Optional[str]
    original_uri: str


class URIParseError(Exception):
    """Exception raised for URI parsing errors."""

    pass


def _is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID.

    Accepts both standard UUID format with dashes and without.

    Args:
        value: The string to validate

    Returns:
        True if valid UUID, False otherwise
    """
    if not value:
        return False

    # Check for standard UUID format with dashes: 8-4-4-4-12 pattern
    if "-" in value:
        # Must match exact pattern: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        uuid_pattern = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        if not re.match(uuid_pattern, value):
            return False
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False
    else:
        # No dashes - check length and hex characters
        if len(value) != 32:
            return False
        if not all(c in "0123456789abcdefABCDEF" for c in value):
            return False
        # Try to parse the undashed format
        try:
            formatted = (
                f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"
            )
            uuid.UUID(formatted)
            return True
        except ValueError:
            return False


def _normalize_path(path: str) -> str:
    """Normalize a filesystem path.

    Performs the following normalizations:
    - Remove leading slashes (path is relative to session root)
    - Resolve . and .. segments
    - Remove trailing slashes
    - Handle empty path (returns empty string for root)
    - Prevent path traversal beyond root

    Args:
        path: The raw path from the URI

    Returns:
        Normalized path string

    Raises:
        URIParseError: If path traversal is detected beyond root
    """
    if not path:
        return ""

    # URL decode the path
    path = unquote(path)

    # Remove leading slashes to make path relative
    path = path.lstrip("/")

    # Split into components and process
    components = path.split("/")
    result = []

    for component in components:
        # Skip empty components and single dot
        if not component or component == ".":
            continue
        elif component == "..":
            # Try to go up one level
            if result:
                result.pop()
            else:
                # Path traversal beyond root detected
                raise URIParseError(
                    f"Path traversal detected: '{path}' attempts to access parent of root"
                )
        else:
            result.append(component)

    return "/".join(result)


def parse_scratchpad_uri(uri: str) -> ScratchpadURI:
    """Parse a scratchpad:// URI.

    Parses URIs in the format:
        scratchpad://{session_id}/{path}

    Validates:
    - Scheme must be 'scratchpad'
    - session_id must be a valid UUID
    - path must not contain traversal beyond root

    Args:
        uri: The URI string to parse

    Returns:
        ScratchpadURI object with parsed components and validation status

    Examples:
        >>> result = parse_scratchpad_uri(
        ...     "scratchpad://550e8400-e29b-41d4-a716-446655440000/file.txt"
        ... )
        >>> result.session_id
        '550e8400-e29b-41d4-a716-446655440000'
        >>> result.path
        'file.txt'
        >>> result.is_valid
        True

        >>> result = parse_scratchpad_uri("invalid://test")
        >>> result.is_valid
        False
        >>> result.error
        "Invalid scheme: expected 'scratchpad', got 'invalid'"
    """
    if not uri:
        return ScratchpadURI(
            session_id=None,
            path="",
            is_valid=False,
            error="URI cannot be empty",
            original_uri=uri,
        )

    try:
        # Parse the URI
        parsed = urlparse(uri)

        # Validate scheme
        if parsed.scheme != "scratchpad":
            return ScratchpadURI(
                session_id=None,
                path="",
                is_valid=False,
                error=f"Invalid scheme: expected 'scratchpad', got '{parsed.scheme}'",
                original_uri=uri,
            )

        # Extract session_id from netloc
        session_id = parsed.netloc

        # Validate session_id is a UUID
        if not session_id:
            return ScratchpadURI(
                session_id=None,
                path="",
                is_valid=False,
                error="Missing session_id in URI",
                original_uri=uri,
            )

        if not _is_valid_uuid(session_id):
            return ScratchpadURI(
                session_id=session_id,
                path="",
                is_valid=False,
                error=f"Invalid session_id format: '{session_id}' is not a valid UUID",
                original_uri=uri,
            )

        # Extract and normalize path
        # urlparse puts the path after netloc in the 'path' field
        raw_path = parsed.path

        try:
            normalized_path = _normalize_path(raw_path)
        except URIParseError as e:
            return ScratchpadURI(
                session_id=session_id,
                path=raw_path,
                is_valid=False,
                error=str(e),
                original_uri=uri,
            )

        return ScratchpadURI(
            session_id=session_id,
            path=normalized_path,
            is_valid=True,
            error=None,
            original_uri=uri,
        )

    except Exception as e:
        return ScratchpadURI(
            session_id=None,
            path="",
            is_valid=False,
            error=f"Unexpected error parsing URI: {str(e)}",
            original_uri=uri,
        )


def is_valid_scratchpad_uri(uri: str) -> bool:
    """Quick check if a URI is valid without full parsing.

    Args:
        uri: The URI string to check

    Returns:
        True if valid, False otherwise

    Examples:
        >>> is_valid_scratchpad_uri(
        ...     "scratchpad://550e8400-e29b-41d4-a716-446655440000/file.txt"
        ... )
        True
        >>> is_valid_scratchpad_uri("invalid://test")
        False
    """
    result = parse_scratchpad_uri(uri)
    return result.is_valid


def build_scratchpad_uri(session_id: str, path: str = "") -> str:
    """Build a scratchpad:// URI from components.

    Args:
        session_id: The session UUID
        path: Optional path (will be normalized)

    Returns:
        Formatted URI string

    Raises:
        ValueError: If session_id is not a valid UUID

    Examples:
        >>> build_scratchpad_uri("550e8400-e29b-41d4-a716-446655440000", "file.txt")
        'scratchpad://550e8400-e29b-41d4-a716-446655440000/file.txt'
        >>> build_scratchpad_uri("550e8400-e29b-41d4-a716-446655440000")
        'scratchpad://550e8400-e29b-41d4-a716-446655440000/'
    """
    if not _is_valid_uuid(session_id):
        raise ValueError(f"Invalid session_id: '{session_id}' is not a valid UUID")

    # Normalize the path
    if path:
        normalized = _normalize_path(path)
        if normalized:
            return f"scratchpad://{session_id}/{normalized}"

    return f"scratchpad://{session_id}/"
