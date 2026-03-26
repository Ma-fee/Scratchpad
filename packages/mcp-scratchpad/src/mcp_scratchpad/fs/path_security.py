"""Path security utilities for OverlayFileSystem.

This module provides comprehensive path traversal protection including:
- Path validation within session bounds
- Symlink resolution and validation
- Path traversal attack detection
- Safe path normalization
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..exceptions import PathTraversalError, SymlinkEscapeError

if TYPE_CHECKING:
    pass


# Path patterns that may indicate traversal attacks
TRAVERSE_PATTERNS = [
    re.compile(r"\.\.[\\/]"),  # ../ or ..\
    re.compile(r"[\\/]\.\."),  # /.. or \..
    re.compile(r"^\.\."),  # starts with ..
    re.compile(r"\.\.$"),  # ends with ..
    re.compile(r"%2e%2e", re.IGNORECASE),  # URL encoded ..
    re.compile(r"%252e%252e", re.IGNORECASE),  # Double URL encoded ..
]

# Null byte pattern
NULL_BYTE_PATTERN = re.compile(r"\x00")

# Unsafe path characters
UNSAFE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _contains_traversal_sequence(path: str) -> bool:
    """Check if path contains directory traversal sequences.

    Args:
        path: The path to check

    Returns:
        True if traversal sequence detected
    """
    # Check for .. sequences in various forms
    if ".." in path.split(os.sep):
        return True
    if ".." in path.split("/"):
        return True

    # Check URL encoded variants
    decoded = path.replace("%2f", "/").replace("%2F", "/")
    if ".." in decoded:
        return True

    # Check for other patterns
    for pattern in TRAVERSE_PATTERNS:
        if pattern.search(path):
            return True

    return False


def _normalize_and_resolve(path: str) -> str:
    """Normalize and resolve a path string.

    Args:
        path: The path to normalize

    Returns:
        Normalized path

    Raises:
        PathTraversalError: If path contains unsafe components
    """
    # Check for null bytes
    if NULL_BYTE_PATTERN.search(path):
        raise PathTraversalError("Path contains null bytes", path=path)

    # Check for traversal sequences before normalization
    if _contains_traversal_sequence(path):
        raise PathTraversalError(
            f"Path contains directory traversal sequence: {path}", path=path
        )

    # Normalize separators
    normalized = path.replace("\\", "/")

    # Remove leading slashes for relative path check
    normalized = normalized.lstrip("/")

    return normalized


def validate_path_within_bounds(
    path: str,
    base_path: str | Path,
    allow_absolute: bool = False,
    check_symlinks: bool = True,
) -> Path:
    """Validate that a path stays within the allowed base directory.

    This function provides comprehensive path traversal protection:
    1. Blocks paths containing .. sequences
    2. Blocks absolute paths that escape base directory
    3. Resolves and validates symlinks (if check_symlinks is True)
    4. Validates path components against unsafe patterns
    5. Prevents path concatenation attacks

    Args:
        path: The path to validate (relative or absolute)
        base_path: The base directory that the path must stay within
        allow_absolute: Whether to allow absolute paths (default False)
        check_symlinks: Whether to validate symlink targets (default True)

    Returns:
        Path object for the validated path relative to base

    Raises:
        PathTraversalError: If path escapes base directory bounds
        SymlinkEscapeError: If a symlink points outside bounds
        ValueError: If path is empty or contains invalid characters
    """
    if not path:
        raise ValueError("Path cannot be empty")

    base = Path(base_path).resolve()

    # Handle absolute paths
    if os.path.isabs(path) or path.startswith("/"):
        if not allow_absolute:
            raise PathTraversalError(
                f"Absolute paths not allowed: {path}",
                path=path,
                base_path=str(base),
            )
        # Convert to relative by removing leading separators
        path = path.lstrip("/").lstrip(os.sep)

    # Check for unsafe characters
    if UNSAFE_CHARS.search(path):
        raise PathTraversalError(
            f"Path contains unsafe characters: {path}",
            path=path,
            base_path=str(base),
        )

    # Normalize the path
    normalized = _normalize_and_resolve(path)

    # Re-check after normalization
    if _contains_traversal_sequence(normalized):
        raise PathTraversalError(
            f"Path contains directory traversal sequence: {path}",
            path=path,
            base_path=str(base),
        )

    # Build full path and resolve
    full_path = base / normalized

    try:
        resolved_path = full_path.resolve()
    except (OSError, ValueError) as e:
        raise PathTraversalError(
            f"Failed to resolve path: {path}",
            path=path,
            base_path=str(base),
        ) from e

    # Ensure resolved path is within base directory
    try:
        # Use relative_to which raises ValueError if not subpath
        resolved_path.relative_to(base)
    except ValueError:
        raise PathTraversalError(
            f"Path escapes base directory: {path} -> {resolved_path}",
            path=path,
            base_path=str(base),
        )

    # Check symlinks if requested
    if check_symlinks:
        _validate_symlink_chain(full_path, base)

    # Return path relative to base for further use
    return resolved_path


def _validate_symlink_chain(path: Path, base: Path) -> None:
    """Validate that all symlinks in the path chain stay within bounds.

    Args:
        path: The path to check for symlinks
        base: The base directory that must contain all symlink targets

    Raises:
        SymlinkEscapeError: If a symlink points outside bounds
    """
    # Walk up the path checking each component
    current = path
    checked: set[Path] = set()

    while current != current.parent:  # Stop at root
        if current in checked:
            break
        checked.add(current)

        if current.is_symlink():
            try:
                target = current.readlink()
            except (OSError, ValueError) as e:
                raise SymlinkEscapeError(
                    f"Cannot read symlink: {current}",
                    link_path=str(current),
                    target="",
                ) from e

            # Get absolute target path
            if target.is_absolute():
                abs_target = target.resolve()
            else:
                abs_target = (current.parent / target).resolve()

            # Validate target is within base
            try:
                abs_target.relative_to(base)
            except ValueError:
                raise SymlinkEscapeError(
                    f"Symlink points outside base directory: {current} -> {target}",
                    link_path=str(current),
                    target=str(target),
                )

        current = current.parent


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal.

    Args:
        filename: The filename to sanitize

    Returns:
        Sanitized filename safe for use

    Raises:
        PathTraversalError: If filename is unsafe
    """
    if not filename:
        raise PathTraversalError("Filename cannot be empty", path=filename)

    # Reject if contains path separators
    if "/" in filename or os.sep in filename or "\\\\" in filename:
        raise PathTraversalError(
            f"Filename contains path separator: {filename}",
            path=filename,
        )

    # Check for traversal
    if ".." in filename:
        raise PathTraversalError(
            f"Filename contains traversal: {filename}",
            path=filename,
        )

    # Check for unsafe characters
    if UNSAFE_CHARS.search(filename):
        raise PathTraversalError(
            f"Filename contains unsafe characters: {filename}",
            path=filename,
        )

    return filename


def join_paths_safely(base: str | Path, *paths: str) -> Path:
    """Safely join paths with traversal protection.

    Args:
        base: Base directory
        *paths: Path components to join

    Returns:
        Safe path within base directory

    Raises:
        PathTraversalError: If combined path escapes bounds
    """
    base_path = Path(base).resolve()

    # Join all path components
    result = base_path
    for path in paths:
        # Validate each component before joining
        if _contains_traversal_sequence(path):
            raise PathTraversalError(
                f"Path component contains traversal: {path}",
                path=path,
                base_path=str(base_path),
            )
        result = result / path

    # Resolve and validate
    resolved = result.resolve()
    try:
        resolved.relative_to(base_path)
    except ValueError:
        raise PathTraversalError(
            f"Path escapes base directory: {result}",
            path=str(result),
            base_path=str(base_path),
        )

    return resolved
