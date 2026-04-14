"""
Configuration models for overlay filesystem mounts.

This module defines Pydantic models for mount configurations, including
validation for mount names, source URIs, mount points, and mode settings.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

# Valid URI schemes for mount sources
VALID_SCHEMES = {"file", "s3", "memory"}

# Pattern for valid mount names: start with letter, alphanumeric/underscore/hyphen
VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


class ConfigValidationError(ValueError):
    """Exception raised when configuration validation fails.

    This exception is raised when mount point conflicts are detected
    or other configuration validation errors occur that require user
    intervention to resolve.

    Example:
        >>> raise ConfigValidationError("Mount point '/a' overlaps with '/a/b'")
    """

    pass


class MountConfig(BaseModel):
    """Configuration for a single mount point in the overlay filesystem.

    Attributes:
        name: Unique identifier for the mount (must start with letter,
            contain only alphanumeric, underscore, hyphen).
        source: URI with scheme (file://, s3://, memory://).
        mount_point: Path where the mount is accessible (no path traversal).
        mode: Access mode - "ro" (read-only) or "rw" (read-write).
        priority: Mount priority (higher = higher priority), default 0.
        options: Backend-specific options dictionary, default empty.

    Example:
        >>> mount = MountConfig(
        ...     name="templates",
        ...     source="file:///var/templates",
        ...     mount_point="/templates",
        ...     mode="ro",
        ...     priority=10,
        ... )
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Mount name - must start with letter, "
            + "contain only alphanumeric, underscore, hyphen"
        ),
    )
    source: str = Field(
        ...,
        description="Source URI with scheme (file://, s3://, memory://)",
    )
    mount_point: str = Field(
        ...,
        min_length=1,
        description="Mount point path (no path traversal with ..)",
    )
    mode: Literal["ro", "rw"] = Field(
        default="ro",
        description="Access mode: 'ro' (read-only) or 'rw' (read-write)",
    )
    priority: int = Field(
        default=0,
        description="Mount priority (higher = higher priority)",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Backend-specific options",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        """Validate mount name format.

        Names must:
        - Start with a letter (a-z, A-Z)
        - Contain only alphanumeric characters, underscores, or hyphens
        """
        if not VALID_NAME_PATTERN.match(v):
            raise ValueError(
                f"Mount name '{v}' must start with a letter and contain only "
                + "alphanumeric characters, underscores, or hyphens"
            )
        return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        """Validate source URI scheme.

        Only the following schemes are allowed:
        - file:// (local filesystem)
        - s3:// (Amazon S3)
        - memory:// (in-memory storage)
        """
        parsed = urlparse(v)
        if not parsed.scheme:
            raise ValueError(f"Source URI '{v}' must have a scheme")
        if parsed.scheme not in VALID_SCHEMES:
            raise ValueError(
                f"Source URI '{v}' has invalid scheme '{parsed.scheme}'. "
                + f"Valid schemes: {', '.join(sorted(VALID_SCHEMES))}"
            )
        return v

    @field_validator("mount_point")
    @classmethod
    def _validate_mount_point(cls, v: str) -> str:
        """Validate mount point path.

        Rejects:
        - Directory traversal sequences (..)
        - Empty paths
        - Non-absolute paths (must start with /)
        """
        if not v.startswith("/"):
            raise ValueError(
                f"Mount point '{v}' must be an absolute path (start with /)"
            )

        # Check for path traversal attempts
        parts: list[str] = [p for p in v.split("/") if p]
        depth = 0
        for part in parts:
            if part == "..":
                depth -= 1
            elif part != ".":
                depth += 1
            if depth < 0:
                raise ValueError(
                    f"Mount point '{v}' contains path traversal sequence (..)"
                )

        # Normalize the path for consistency
        normalized = "/" + "/".join(p for p in parts if p and p != ".")
        if not normalized or normalized == "/":
            normalized = "/"

        return normalized

    def __repr__(self) -> str:
        return (
            f"MountConfig(name='{self.name}', source='{self.source}', "
            f"mount_point='{self.mount_point}', mode='{self.mode}')"
        )


def _check_duplicate_names(mounts: list[MountConfig]) -> None:
    """Check for duplicate mount names.

    Args:
        mounts: List of mount configurations

    Raises:
        ConfigValidationError: If duplicate names are found
    """
    names: list[str] = [m.name for m in mounts]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    if duplicates:
        dupes = ", ".join(sorted(duplicates))
        raise ConfigValidationError(f"Duplicate mount names found: {dupes}")


def _check_multiple_rw_mounts(mounts: list[MountConfig]) -> None:
    """Check for multiple read-write mounts.

    Args:
        mounts: List of mount configurations

    Raises:
        ConfigValidationError: If multiple RW mounts are found
    """
    rw_mounts = [m for m in mounts if m.mode == "rw"]
    if len(rw_mounts) > 1:
        rw_names = ", ".join(m.name for m in rw_mounts)
        raise ConfigValidationError(
            f"Multiple read-write mounts not allowed. RW mounts: {rw_names}"
        )


def _check_overlapping_mount_points(mounts: list[MountConfig]) -> None:
    """Check for overlapping mount points (prefix conflicts).

    Args:
        mounts: List of mount configurations

    Raises:
        ConfigValidationError: If overlapping mount points are found
    """
    # Sort by path length to efficiently check for prefix relationships
    sorted_mounts = sorted(mounts, key=lambda m: len(m.mount_point))
    for i, mount_a in enumerate(sorted_mounts):
        for mount_b in sorted_mounts[i + 1 :]:
            # Check if mount_a is a prefix of mount_b
            if mount_b.mount_point.startswith(mount_a.mount_point + "/"):
                raise ConfigValidationError(
                    "Mount point conflict detected: "
                    + f"'{mount_a.mount_point}' (mount: '{mount_a.name}') is a prefix of "
                    + f"'{mount_b.mount_point}' (mount: '{mount_b.name}'). "
                    + "Overlapping mount points are not allowed."
                )


def _check_duplicate_priorities(mounts: list[MountConfig]) -> None:
    """Check for duplicate priorities.

    Args:
        mounts: List of mount configurations

    Raises:
        ConfigValidationError: If duplicate priorities are found
    """
    priorities = [m.priority for m in mounts]
    priority_counts: dict[int, int] = {}
    for p in priorities:
        priority_counts[p] = priority_counts.get(p, 0) + 1

    duplicate_priorities = {p for p, count in priority_counts.items() if count > 1}
    if duplicate_priorities:
        dup_mounts = [
            (m.name, m.priority) for m in mounts if m.priority in duplicate_priorities
        ]
        raise ConfigValidationError(
            f"Duplicate priorities found: {sorted(dup_mounts)}. "
            + "Each mount must have a unique priority for deterministic "
            + "conflict resolution."
        )


class OverlayRolloutConfig(BaseModel):
    """Rollout flags that control new overlay capabilities."""

    unified_overlay_fs: bool = Field(
        default=False,
        description="Enable the new unified overlay filesystem stack",
    )
    canonical_uri_only: bool = Field(
        default=False,
        description="Require downstream tools to use canonical scratchpad URIs",
    )
    event_driven_subscriptions: bool = Field(
        default=False,
        description="Use event-driven subscriptions instead of polling",
    )
    dual_write_legacy_store: bool = Field(
        default=False,
        description="Dual-write files to the legacy store during migration",
    )


class SharedMemoryNamespaceConfig(BaseModel):
    """Shared memory backend configuration for a single namespace."""

    backend: Literal["file", "s3"]
    root: str = Field(..., min_length=1)


class SharedMemoryPublishConfig(BaseModel):
    """Configuration for publish_memory namespace routing."""

    namespaces: dict[str, SharedMemoryNamespaceConfig] = Field(default_factory=dict)


class SharedMemoryConfig(BaseModel):
    """Top-level shared memory configuration."""

    publish: SharedMemoryPublishConfig = Field(
        default_factory=SharedMemoryPublishConfig
    )


class OverlayConfig(BaseModel):
    """Root configuration model for overlay filesystem with multiple mounts.

    This model represents the complete overlay filesystem configuration,
    containing a list of mount configurations.

    Attributes:
        mounts: List of MountConfig objects defining the overlay layers.

    Validation:
        - Mount names must be unique across all mounts
        - Only one mount can be configured in read-write (rw) mode

    Example:
        >>> config = OverlayConfig(
        ...     mounts=[
        ...         MountConfig(name="base", source="file:///base", mount_point="/"),
        ...         MountConfig(
        ...             name="overlay",
        ...             source="memory://",
        ...             mount_point="/workspace",
        ...             mode="rw",
        ...         ),
        ...     ]
        ... )
    """

    mounts: list[MountConfig] = Field(
        default_factory=list,
        description="List of mount configurations",
    )

    rollout: OverlayRolloutConfig = Field(
        default_factory=OverlayRolloutConfig,
        description="Rollout flags for overlay filesystem features",
    )

    memory: SharedMemoryConfig = Field(
        default_factory=SharedMemoryConfig,
        description="Shared memory publishing configuration",
    )

    @model_validator(mode="after")
    def _validate_mounts(self) -> OverlayConfig:
        """Validate the mounts list.

        Checks:
        - Duplicate mount names are not allowed
        - Only one RW mount is allowed
        - Mount points must not overlap
        - Priorities must be unique
        """
        mounts = self.mounts

        if not mounts:
            return self

        _check_duplicate_names(mounts)
        _check_multiple_rw_mounts(mounts)
        _check_overlapping_mount_points(mounts)
        _check_duplicate_priorities(mounts)

        return self

    def get_mount_by_name(self, name: str) -> MountConfig | None:
        """Get a mount configuration by its name.

        Args:
            name: The mount name to look up.

        Returns:
            MountConfig if found, None otherwise.
        """
        for mount in self.mounts:
            if mount.name == name:
                return mount
        return None

    def get_rw_mount(self) -> MountConfig | None:
        """Get the read-write mount if one exists.

        Returns:
            The RW MountConfig if found, None otherwise.
        """
        for mount in self.mounts:
            if mount.mode == "rw":
                return mount
        return None

    def get_sorted_mounts(self) -> list[MountConfig]:
        """Get mounts sorted by priority (highest first).

        Returns:
            List of mounts sorted by descending priority.
        """
        return sorted(self.mounts, key=lambda m: m.priority, reverse=True)
