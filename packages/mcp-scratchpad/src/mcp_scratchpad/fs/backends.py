"""
Filesystem backend implementations.

This module provides factory functions for creating fsspec filesystem instances
with support for path prefixing using DirFileSystem.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.local import LocalFileSystem
from fsspec.implementations.memory import MemoryFileSystem

if TYPE_CHECKING:
    from typing import Any

    from fsspec import AbstractFileSystem

    from mcp_scratchpad.config.models import MountConfig, OverlayConfig

logger = logging.getLogger(__name__)


def create_local_filesystem(
    path_prefix: str | None = None,
    **options: Any,
) -> AbstractFileSystem:
    """Create a local filesystem with optional path prefix.

    This function creates a LocalFileSystem instance, optionally wrapped
    with DirFileSystem to restrict access to a specific path prefix.
    This is useful for mounting subdirectories as filesystem roots.

    Args:
        path_prefix: Optional base path to restrict filesystem access to.
            If provided, all paths will be relative to this prefix.
            If None, returns a standard LocalFileSystem with full access.
        **options: Additional options passed to LocalFileSystem constructor.
            Common options include:
            - use_listings_cache: Whether to cache directory listings
            - listings_expiry_time: How long to cache listings (seconds)
            - max_paths: Maximum number of paths to cache

    Returns:
        An fsspec filesystem instance. If path_prefix is provided, returns
        a DirFileSystem wrapping LocalFileSystem. Otherwise returns
        LocalFileSystem directly.

    Example:
        >>> # Create filesystem with full local access
        >>> fs = create_local_filesystem()
        >>> fs.write_text("/tmp/test.txt", "hello")

        >>> # Create filesystem restricted to a specific directory
        >>> fs = create_local_filesystem(path_prefix="/tmp/myapp")
        >>> # This writes to /tmp/myapp/data/file.txt
        >>> fs.write_text("/data/file.txt", "content")

        >>> # Pass options to the underlying filesystem
        >>> fs = create_local_filesystem(
        ...     path_prefix="/tmp/myapp",
        ...     use_listings_cache=True,
        ...     listings_expiry_time=60
        ... )

    Note:
        When path_prefix is used, DirFileSystem provides a chroot-like
        behavior where the prefix becomes the filesystem root. This
        is useful for sandboxing and multi-tenant applications.

    Raises:
        FileNotFoundError: If path_prefix is provided and the directory
            does not exist (depending on fsspec version).
        PermissionError: If path_prefix is provided and the directory
            cannot be accessed.
    """
    # Create the base LocalFileSystem with any provided options
    local_fs = LocalFileSystem(**options)

    # If no prefix specified, return local filesystem directly
    if path_prefix is None:
        return local_fs

    # Wrap with DirFileSystem to add path prefix restriction
    return DirFileSystem(path=path_prefix, fs=local_fs)


class S3NotInstalledError(ImportError):
    """Raised when s3fs is required but not installed."""

    def __init__(self) -> None:
        super().__init__(
            "s3fs is required for S3 support. "
            "Install with: uv pip install s3fs or pip install s3fs"
        )


def create_s3_filesystem(
    bucket: str,
    **options: Any,
) -> AbstractFileSystem:
    """Create an S3 filesystem with optional path prefix.

    This function creates an S3FileSystem instance, optionally wrapped
    with DirFileSystem to restrict access to a specific bucket/prefix.

    Args:
        bucket: S3 bucket name. Can include a path prefix (e.g., "mybucket/data").
        **options: Additional options passed to S3FileSystem constructor.
            Common options include:
            - key: AWS access key ID
            - secret: AWS secret access key
            - token: AWS session token (for temporary credentials)
            - client_kwargs: Dict of arguments passed to boto3 client
                - endpoint_url: Custom endpoint URL (for MinIO, testing)
                - region_name: AWS region
            - use_listings_cache: Whether to cache directory listings
            - listings_expiry_time: How long to cache listings (seconds)

    Returns:
        An fsspec filesystem instance wrapping S3FileSystem.
        The bucket becomes the root of the filesystem.

    Example:
        >>> # Create S3 filesystem with credentials
        >>> fs = create_s3_filesystem(
        ...     bucket="my-bucket",
        ...     key="AKIAIOSFODNN7EXAMPLE",
        ...     secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        ... )
        >>> fs.write_text("/data/file.txt", "content")

        >>> # Create S3 filesystem with custom endpoint (MinIO)
        >>> fs = create_s3_filesystem(
        ...     bucket="my-bucket",
        ...     client_kwargs={
        ...         "endpoint_url": "http://localhost:9000"
        ...     }
        ... )

        >>> # Create S3 filesystem with bucket prefix
        >>> fs = create_s3_filesystem(
        ...     bucket="my-bucket/data/subdir"
        ... )
        >>> # This writes to s3://my-bucket/data/subdir/file.txt
        >>> fs.write_text("/file.txt", "content")

    Note:
        Credentials can be provided in multiple ways (in order of priority):
        1. Directly via key/secret/token parameters
        2. Via client_kwargs (e.g., endpoint_url)
        3. From environment variables (AWS_ACCESS_KEY_ID, etc.)
        4. From AWS credentials file (~/.aws/credentials)
        5. From IAM role (when running on AWS)

        When using moto for testing, ensure endpoint_url is set
        in client_kwargs to connect to the mock server.

    Raises:
        S3NotInstalledError: If s3fs package is not installed.
        ValueError: If bucket name is empty or invalid.
        PermissionError: If credentials are invalid or bucket not accessible.
    """
    try:
        from s3fs import S3FileSystem
    except ImportError as e:
        logger.error("s3fs not installed, cannot create S3 filesystem")
        raise S3NotInstalledError() from e

    if not bucket:
        raise ValueError("Bucket name cannot be empty")

    # Extract bucket name and prefix from bucket string
    # Bucket can be "mybucket" or "mybucket/prefix/path"
    bucket_parts = bucket.split("/", 1)
    bucket_name = bucket_parts[0]
    prefix = bucket_parts[1] if len(bucket_parts) > 1 else ""

    logger.debug(
        f"Creating S3 filesystem for bucket: {bucket_name}, prefix: {prefix!r}"
    )

    # Build S3FileSystem options
    s3_options: dict[str, Any] = {}

    # Handle credential options
    if "key" in options:
        s3_options["key"] = options.pop("key")
    if "secret" in options:
        s3_options["secret"] = options.pop("secret")
    if "token" in options:
        s3_options["token"] = options.pop("token")

    # Handle client_kwargs
    client_kwargs = options.pop("client_kwargs", {}) or {}
    if client_kwargs:
        s3_options["client_kwargs"] = client_kwargs

    # Handle other s3fs options
    for key in ["use_listings_cache", "listings_expiry_time", "default_cache_type"]:
        if key in options:
            s3_options[key] = options.pop(key)

    # Warn about unused options
    if options:
        logger.warning(f"Unused options for S3 filesystem: {list(options.keys())}")

    # Create the S3FileSystem
    s3_fs = S3FileSystem(**s3_options)

    # If prefix is specified, wrap with DirFileSystem
    if prefix:
        full_path = f"{bucket_name}/{prefix}"
        return DirFileSystem(path=full_path, fs=s3_fs)

    # Otherwise, wrap with DirFileSystem using bucket as root
    return DirFileSystem(path=bucket_name, fs=s3_fs)


def create_memory_filesystem(
    **options: Any,
) -> AbstractFileSystem:
    """Create an in-memory filesystem.

    This function creates a MemoryFileSystem instance for temporary
    in-memory storage. Data is lost when the filesystem is garbage collected.

    Args:
        **options: Additional options passed to MemoryFileSystem constructor.

    Returns:
        An fsspec MemoryFileSystem instance.

    Example:
        >>> fs = create_memory_filesystem()
        >>> fs.write_text("/test.txt", "hello")
        >>> content = fs.read_text("/test.txt")
    """
    return MemoryFileSystem(**options)


def create_filesystem(config: MountConfig) -> AbstractFileSystem:
    """Create a filesystem instance from a MountConfig.

    This factory function parses the source URI from the MountConfig
    and dispatches to the appropriate backend creator based on the URI scheme.
    All backend-specific options from config.options are passed through.

    Args:
        config: MountConfig containing source URI, mode, and options.

    Returns:
        An fsspec AbstractFileSystem instance configured per the mount.

    Raises:
        ValueError: If the URI scheme is not supported.
        ImportError: If required backend package (e.g., s3fs) is not installed.

    Example:
        >>> from mcp_scratchpad.config.models import MountConfig
        >>> mount = MountConfig(
        ...     name="data",
        ...     source="file:///tmp/data",
        ...     mount_point="/data",
        ...     mode="ro"
        ... )
        >>> fs = create_filesystem(mount)
    """
    parsed = urlparse(config.source)
    scheme = parsed.scheme
    options = dict(config.options)

    if scheme == "file":
        # file://path -> use local filesystem with path as prefix
        path = parsed.path
        return create_local_filesystem(path_prefix=path, **options)
    elif scheme == "s3":
        # s3://bucket/path -> use S3 filesystem
        # Build bucket string: bucket + optional path prefix
        bucket = parsed.netloc
        path = parsed.path.lstrip("/")
        bucket_str = f"{bucket}/{path}" if path else bucket
        return create_s3_filesystem(bucket=bucket_str, **options)
    elif scheme == "memory":
        # memory:// -> use in-memory filesystem
        return create_memory_filesystem(**options)
    else:
        raise ValueError(
            f"Unsupported URI scheme '{scheme}' in source '{config.source}'. "
            f"Valid schemes: file, s3, memory"
        )


def create_filesystems_from_config(
    overlay_config: OverlayConfig,
) -> tuple[list[AbstractFileSystem], AbstractFileSystem]:
    """Create filesystems from an OverlayConfig.

    This function processes all mounts in the OverlayConfig and returns
    separate lists for read-only (lower) and read-write (upper) filesystems.
    Lower filesystems are sorted by priority (highest first) for overlay
    resolution order.

    Args:
        overlay_config: OverlayConfig containing multiple mount configurations.

    Returns:
        A tuple of (lower_filesystems, upper_filesystem) where:
        - lower_filesystems: List of read-only filesystems sorted by priority
        - upper_filesystem: The single read-write filesystem (or first RO mount)

    Raises:
        ValueError: If no mounts are configured.

    Example:
        >>> from mcp_scratchpad.config.models import OverlayConfig, MountConfig
        >>> config = OverlayConfig(mounts=[
        ...     MountConfig(name="base", source="file:///base", mount_point="/", mode="ro"),
        ...     MountConfig(name="work", source="memory://", mount_point="/work", mode="rw"),
        ... ])
        >>> lowers, upper = create_filesystems_from_config(config)
    """
    if not overlay_config.mounts:
        raise ValueError("No mounts configured in OverlayConfig")

    # Separate RW and RO mounts
    rw_mounts: list[MountConfig] = []
    ro_mounts: list[MountConfig] = []

    for mount in overlay_config.mounts:
        if mount.mode == "rw":
            rw_mounts.append(mount)
        else:
            ro_mounts.append(mount)

    # Sort RO mounts by priority (highest first)
    ro_mounts.sort(key=lambda m: m.priority, reverse=True)

    # Create filesystems for RO mounts (lowers)
    lower_filesystems: list[AbstractFileSystem] = []
    for mount in ro_mounts:
        try:
            fs = create_filesystem(mount)
            lower_filesystems.append(fs)
            logger.debug(
                f"Created filesystem for mount '{mount.name}' (RO, priority={mount.priority})"
            )
        except Exception as e:
            logger.error(f"Failed to create filesystem for mount '{mount.name}': {e}")
            raise

    # Create filesystem for RW mount (upper)
    if rw_mounts:
        upper_mount = rw_mounts[0]  # Should only be one due to validation
        try:
            upper_filesystem = create_filesystem(upper_mount)
            logger.debug(f"Created filesystem for mount '{upper_mount.name}' (RW)")
        except Exception as e:
            logger.error(
                f"Failed to create filesystem for mount '{upper_mount.name}': {e}"
            )
            raise
    else:
        # If no RW mount, use the first RO mount as upper (read-only overlay)
        upper_mount = ro_mounts[0]
        upper_filesystem = create_filesystem(upper_mount)
        logger.debug(f"No RW mount found, using '{upper_mount.name}' as upper")

    return lower_filesystems, upper_filesystem
