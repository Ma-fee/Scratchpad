"""
Unit tests for MountConfig and OverlayConfig models.

This module tests all validation rules for mount configurations,
including name format, source URI scheme, mount point path validation,
and overlay-level constraints like duplicate names and multiple RW mounts.
"""

import pytest
from pydantic import ValidationError

from mcp_scratchpad.config.models import (
    ConfigValidationError,
    MountConfig,
    OverlayConfig,
)


class TestMountConfig:
    """Tests for MountConfig model."""

    def test_valid_mount_config(self) -> None:
        """Create a valid mount configuration."""
        mount = MountConfig(
            name="templates",
            source="file:///tmp/templates",
            mount_point="/templates",
            mode="ro",
        )

        assert mount.name == "templates"
        assert mount.source == "file:///tmp/templates"
        assert mount.mount_point == "/templates"
        assert mount.mode == "ro"
        assert mount.priority == 0
        assert mount.options == {}

    def test_valid_mount_with_rw_mode(self) -> None:
        """Create a valid RW mount configuration."""
        mount = MountConfig(
            name="workspace",
            source="memory://",
            mount_point="/workspace",
            mode="rw",
        )

        assert mount.mode == "rw"

    def test_valid_mount_with_options(self) -> None:
        """Create a mount with custom options."""
        mount = MountConfig(
            name="s3_bucket",
            source="s3://my-bucket/data",
            mount_point="/data",
            mode="ro",
            priority=10,
            options={"region": "us-west-2", "acl": "public-read"},
        )

        assert mount.priority == 10
        assert mount.options == {"region": "us-west-2", "acl": "public-read"}

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        mount = MountConfig(
            name="test",
            source="file:///tmp",
            mount_point="/test",
        )

        assert mount.mode == "ro"  # default
        assert mount.priority == 0  # default
        assert mount.options == {}  # default

    # Name validation tests

    @pytest.mark.parametrize(
        "name",
        [
            "validname",
            "ValidName",
            "valid_name",
            "valid-name",
            "validName123",
            "A",
            "a_123_b",
        ],
    )
    def test_valid_names(self, name: str) -> None:
        """Test various valid mount names."""
        mount = MountConfig(
            name=name,
            source="file:///tmp",
            mount_point="/test",
        )
        assert mount.name == name

    @pytest.mark.parametrize(
        "name,error_pattern",
        [
            ("123invalid", "must start with a letter"),
            ("_underscore", "must start with a letter"),
            ("-dash", "must start with a letter"),
            ("name with space", "must start with a letter"),
            ("name.with.dots", "must start with a letter"),
            ("name/with/slashes", "must start with a letter"),
            ("name\\with\\backslashes", "must start with a letter"),
            ("name:with:colons", "must start with a letter"),
        ],
    )
    def test_invalid_names(self, name: str, error_pattern: str) -> None:
        """Test various invalid mount names raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name=name,
                source="file:///tmp",
                mount_point="/test",
            )
        assert error_pattern in str(exc_info.value)

    # Source URI validation tests

    @pytest.mark.parametrize(
        "source",
        [
            "file:///tmp/test",
            "file://localhost/tmp/test",
            "file:///C:/Windows/System32",  # Windows path
            "s3://my-bucket/data",
            "s3://bucket-name/path/to/file",
            "memory://",
            "memory://local-storage",
        ],
    )
    def test_valid_sources(self, source: str) -> None:
        """Test various valid source URIs."""
        mount = MountConfig(
            name="test",
            source=source,
            mount_point="/test",
        )
        assert mount.source == source

    def test_invalid_source_no_scheme(self) -> None:
        """Test source URI without scheme raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="/tmp/test",
                mount_point="/test",
            )
        assert "must have a scheme" in str(exc_info.value)

    def test_invalid_source_scheme(self) -> None:
        """Test source URI with invalid scheme raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="http://example.com",
                mount_point="/test",
            )
        assert "has invalid scheme" in str(exc_info.value)
        assert "file, memory, s3" in str(exc_info.value)

    @pytest.mark.parametrize(
        "invalid_scheme",
        ["http", "https", "ftp", "ssh", "git"],
    )
    def test_invalid_source_schemes(self, invalid_scheme: str) -> None:
        """Test various invalid schemes raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source=f"{invalid_scheme}://example.com",
                mount_point="/test",
            )
        assert "has invalid scheme" in str(exc_info.value)

    # Mount point validation tests

    @pytest.mark.parametrize(
        "mount_point,expected",
        [
            ("/", "/"),
            ("/test", "/test"),
            ("/path/to/mount", "/path/to/mount"),
            ("/a/b/c/d", "/a/b/c/d"),
            ("/path/./to/mount", "/path/to/mount"),  # dot segments removed
        ],
    )
    def test_valid_mount_points(self, mount_point: str, expected: str) -> None:
        """Test various valid mount points."""
        mount = MountConfig(
            name="test",
            source="file:///tmp",
            mount_point=mount_point,
        )
        assert mount.mount_point == expected

    def test_mount_point_relative_path_rejected(self) -> None:
        """Test relative mount point raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="file:///tmp",
                mount_point="relative/path",
            )
        assert "must be an absolute path" in str(exc_info.value)

    def test_mount_point_path_traversal_detected(self) -> None:
        """Test mount point with .. sequence raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="file:///tmp",
                mount_point="/etc/../etc/passwd",
            )
        assert "path traversal" in str(exc_info.value)

    def test_mount_point_deep_traversal_detected(self) -> None:
        """Test deep path traversal raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="file:///tmp",
                mount_point="/a/b/../../..",
            )
        assert "path traversal" in str(exc_info.value)

    def test_mount_point_with_dotdot_not_starting_with_slash(self) -> None:
        """Test mount point starting with .. raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="file:///tmp",
                mount_point="../escape",
            )
        assert "must be an absolute path" in str(exc_info.value)

    # Mode validation tests

    def test_invalid_mode(self) -> None:
        """Test invalid mode value raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="file:///tmp",
                mount_point="/test",
                mode="invalid",  # type: ignore[arg-type]
            )
        # Pydantic Literal validation error
        assert "literal_error" in str(exc_info.value) or "ro" in str(exc_info.value)

    def test_repr(self) -> None:
        """Test string representation of MountConfig."""
        mount = MountConfig(
            name="test_mount",
            source="file:///tmp/test",
            mount_point="/mnt",
            mode="rw",
        )
        repr_str = repr(mount)

        assert "MountConfig" in repr_str
        assert "test_mount" in repr_str
        assert "file:///tmp/test" in repr_str
        assert "/mnt" in repr_str
        assert "rw" in repr_str


class TestOverlayConfig:
    """Tests for OverlayConfig model."""

    def test_empty_config(self) -> None:
        """Test empty overlay configuration is valid."""
        config = OverlayConfig()

        assert config.mounts == []

    def test_empty_config_explicit(self) -> None:
        """Test explicit empty mounts list is valid."""
        config = OverlayConfig(mounts=[])

        assert config.mounts == []

    def test_single_mount(self) -> None:
        """Test overlay with single mount."""
        mount = MountConfig(
            name="base",
            source="file:///base",
            mount_point="/",
        )
        config = OverlayConfig(mounts=[mount])

        assert len(config.mounts) == 1
        assert config.mounts[0].name == "base"

    def test_multiple_ro_mounts(self) -> None:
        """Test overlay with multiple RO mounts."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="base",
                    source="file:///base",
                    mount_point="/",
                ),
                MountConfig(
                    name="templates",
                    source="file:///templates",
                    mount_point="/templates",
                ),
                MountConfig(
                    name="config",
                    source="s3://bucket/config",
                    mount_point="/config",
                ),
            ]
        )

        assert len(config.mounts) == 3

    def test_mixed_ro_rw_mounts(self) -> None:
        """Test overlay with mix of RO and one RW mount."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="base",
                    source="file:///base",
                    mount_point="/",
                    mode="ro",
                ),
                MountConfig(
                    name="workspace",
                    source="memory://",
                    mount_point="/workspace",
                    mode="rw",
                ),
            ]
        )

        assert len(config.mounts) == 2
        rw_mount = config.get_rw_mount()
        assert rw_mount is not None
        assert rw_mount.name == "workspace"

    def test_duplicate_mount_names_rejected(self) -> None:
        """Test duplicate mount names raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            OverlayConfig(
                mounts=[
                    MountConfig(
                        name="same_name",
                        source="file:///a",
                        mount_point="/a",
                    ),
                    MountConfig(
                        name="same_name",
                        source="file:///b",
                        mount_point="/b",
                    ),
                ]
            )
        assert "Duplicate mount names" in str(exc_info.value)
        assert "same_name" in str(exc_info.value)

    def test_multiple_duplicates_detected(self) -> None:
        """Test multiple duplicate names are all reported."""
        with pytest.raises(ValidationError) as exc_info:
            OverlayConfig(
                mounts=[
                    MountConfig(name="dup1", source="file:///a", mount_point="/a"),
                    MountConfig(name="dup1", source="file:///b", mount_point="/b"),
                    MountConfig(name="dup2", source="file:///c", mount_point="/c"),
                    MountConfig(name="dup2", source="file:///d", mount_point="/d"),
                ]
            )
        assert "dup1" in str(exc_info.value)
        assert "dup2" in str(exc_info.value)

    def test_multiple_rw_mounts_rejected(self) -> None:
        """Test multiple RW mounts raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            OverlayConfig(
                mounts=[
                    MountConfig(
                        name="rw1",
                        source="file:///a",
                        mount_point="/a",
                        mode="rw",
                    ),
                    MountConfig(
                        name="rw2",
                        source="file:///b",
                        mount_point="/b",
                        mode="rw",
                    ),
                ]
            )
        assert "Multiple read-write mounts" in str(exc_info.value)
        assert "rw1" in str(exc_info.value)
        assert "rw2" in str(exc_info.value)

    def test_get_mount_by_name_found(self) -> None:
        """Test getting a mount by name when it exists."""
        mount1 = MountConfig(name="base", source="file:///base", mount_point="/")
        mount2 = MountConfig(
            name="overlay", source="memory://", mount_point="/workspace"
        )

        config = OverlayConfig(mounts=[mount1, mount2])

        found = config.get_mount_by_name("overlay")
        assert found is not None
        assert found.name == "overlay"
        assert found.source == "memory://"

    def test_get_mount_by_name_not_found(self) -> None:
        """Test getting a mount by name when it doesn't exist."""
        mount = MountConfig(name="base", source="file:///base", mount_point="/")
        config = OverlayConfig(mounts=[mount])

        found = config.get_mount_by_name("nonexistent")
        assert found is None

    def test_get_rw_mount_when_none(self) -> None:
        """Test getting RW mount when there is none."""
        config = OverlayConfig(
            mounts=[
                MountConfig(name="ro1", source="file:///a", mount_point="/a"),
                MountConfig(name="ro2", source="file:///b", mount_point="/b"),
            ]
        )

        rw_mount = config.get_rw_mount()
        assert rw_mount is None

    def test_get_sorted_mounts(self) -> None:
        """Test getting mounts sorted by priority."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="low", source="file:///low", mount_point="/low", priority=0
                ),
                MountConfig(
                    name="high",
                    source="file:///high",
                    mount_point="/high",
                    priority=100,
                ),
                MountConfig(
                    name="medium",
                    source="file:///med",
                    mount_point="/med",
                    priority=50,
                ),
            ]
        )

        sorted_mounts = config.get_sorted_mounts()
        assert [m.name for m in sorted_mounts] == ["high", "medium", "low"]
        assert [m.priority for m in sorted_mounts] == [100, 50, 0]

    def test_get_sorted_mounts_same_priority(self) -> None:
        """Test sorting with equal priorities maintains stable order."""
        mount1 = MountConfig(
            name="first", source="file:///1", mount_point="/1", priority=10
        )
        mount2 = MountConfig(
            name="second", source="file:///2", mount_point="/2", priority=10
        )

        config = OverlayConfig(mounts=[mount1, mount2])

        sorted_mounts = config.get_sorted_mounts()
        # Should maintain original order for equal priorities
        assert [m.name for m in sorted_mounts] == ["first", "second"]


class TestMountPointConflictDetection:
    """Tests for mount point overlap detection in OverlayConfig."""

    @pytest.mark.unit
    def test_non_overlapping_mounts_pass(self):
        """Test that non-overlapping mount points are accepted."""
        mounts = [
            MountConfig(
                name="templates",
                source="file:///tmp/templates",
                mount_point="/templates",
                priority=10,
            ),
            MountConfig(
                name="data",
                source="file:///tmp/data",
                mount_point="/data",
                priority=20,
            ),
        ]
        config = OverlayConfig(mounts=mounts)
        assert len(config.mounts) == 2
        assert config.get_mount_by_name("templates") is not None
        assert config.get_mount_by_name("data") is not None

    @pytest.mark.unit
    def test_overlapping_mount_points_detected(self):
        """Test that overlapping mount points (parent-child) are rejected."""
        mounts = [
            MountConfig(
                name="templates",
                source="file:///tmp",
                mount_point="/templates",
                priority=10,
            ),
            MountConfig(
                name="subdir",
                source="file:///tmp",
                mount_point="/templates/subdir",
                priority=20,
            ),
        ]
        with pytest.raises(ValidationError, match="Mount point conflict detected"):
            OverlayConfig(mounts=mounts)

    @pytest.mark.unit
    def test_prefix_conflict_detected(self):
        """Test that exact prefix conflicts are detected."""
        mounts = [
            MountConfig(
                name="a",
                source="file:///tmp",
                mount_point="/a",
                priority=10,
            ),
            MountConfig(
                name="ab",
                source="file:///tmp",
                mount_point="/ab",
                priority=20,
            ),
        ]
        # /a is NOT a prefix of /ab so this should pass
        config = OverlayConfig(mounts=mounts)
        assert len(config.mounts) == 2

    @pytest.mark.unit
    def test_same_parent_different_subdirs_pass(self):
        """Test that siblings under same parent are allowed."""
        mounts = [
            MountConfig(
                name="a",
                source="file:///tmp",
                mount_point="/workspace/a",
                priority=10,
            ),
            MountConfig(
                name="b",
                source="file:///tmp",
                mount_point="/workspace/b",
                priority=20,
            ),
        ]
        # /workspace/a and /workspace/b don't conflict
        config = OverlayConfig(mounts=mounts)
        assert len(config.mounts) == 2

    @pytest.mark.unit
    def test_deep_nesting_conflict(self):
        """Test deep nesting conflict detection."""
        mounts = [
            MountConfig(
                name="root",
                source="file:///tmp",
                mount_point="/app",
                priority=10,
            ),
            MountConfig(
                name="deep",
                source="file:///tmp",
                mount_point="/app/components/ui/buttons",
                priority=20,
            ),
        ]
        with pytest.raises(ValidationError, match="is a prefix of"):
            OverlayConfig(mounts=mounts)


class TestPriorityUniquenessValidation:
    """Tests for priority uniqueness validation in OverlayConfig."""

    @pytest.mark.unit
    def test_unique_priorities_accepted(self):
        """Test that unique priorities are accepted."""
        mounts = [
            MountConfig(
                name="a",
                source="file:///tmp",
                mount_point="/a",
                priority=10,
            ),
            MountConfig(
                name="b",
                source="file:///tmp",
                mount_point="/b",
                priority=20,
            ),
            MountConfig(
                name="c",
                source="file:///tmp",
                mount_point="/c",
                priority=30,
            ),
        ]
        config = OverlayConfig(mounts=mounts)
        assert len(config.mounts) == 3

    @pytest.mark.unit
    def test_duplicate_priorities_rejected(self):
        """Test that duplicate priorities are rejected."""
        mounts = [
            MountConfig(
                name="a",
                source="file:///tmp",
                mount_point="/a",
                priority=10,
            ),
            MountConfig(
                name="b",
                source="file:///tmp",
                mount_point="/b",
                priority=10,
            ),
        ]
        with pytest.raises(ValidationError, match="Duplicate priorities found"):
            OverlayConfig(mounts=mounts)

    @pytest.mark.unit
    def test_priority_error_shows_mount_info(self):
        """Test that priority error message includes mount names."""
        mounts = [
            MountConfig(
                name="first",
                source="file:///tmp",
                mount_point="/a",
                priority=5,
            ),
            MountConfig(
                name="second",
                source="file:///tmp",
                mount_point="/b",
                priority=5,
            ),
        ]
        with pytest.raises(ValidationError) as exc_info:
            OverlayConfig(mounts=mounts)

        error_msg = str(exc_info.value)
        assert "first" in error_msg
        assert "second" in error_msg

    @pytest.mark.unit
    def test_multiple_duplicate_priority_groups(self):
        """Test that multiple duplicate priority groups are all reported."""
        mounts = [
            MountConfig(
                name="a1",
                source="file:///tmp",
                mount_point="/a1",
                priority=10,
            ),
            MountConfig(
                name="a2",
                source="file:///tmp",
                mount_point="/a2",
                priority=10,
            ),
            MountConfig(
                name="b1",
                source="file:///tmp",
                mount_point="/b1",
                priority=20,
            ),
            MountConfig(
                name="b2",
                source="file:///tmp",
                mount_point="/b2",
                priority=20,
            ),
        ]
        with pytest.raises(ValidationError, match="Duplicate priorities found"):
            OverlayConfig(mounts=mounts)


class TestConfigValidationError:
    """Tests for ConfigValidationError exception."""

    @pytest.mark.unit
    def test_inheritance(self):
        """Test that ConfigValidationError inherits from ValueError."""
        err = ConfigValidationError("test error")
        assert isinstance(err, ValueError)
        assert str(err) == "test error"

    @pytest.mark.unit
    def test_can_be_caught_as_value_error(self):
        """Test that ConfigValidationError can be caught as ValueError."""
        with pytest.raises(ValueError):
            raise ConfigValidationError("test")
