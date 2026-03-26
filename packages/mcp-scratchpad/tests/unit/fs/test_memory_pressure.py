"""
Unit tests for OverlayFileSystem memory pressure handling.

Tests the memory monitoring, automatic eviction, and graceful degradation
features of the overlay filesystem under various memory pressure scenarios.
"""

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.fs.overlay import (
    MemoryPressureConfig,
    MemoryPressureError,
    MemoryStats,
    OverlayFileSystem,
)


class TestMemoryPressureConfig:
    """Tests for MemoryPressureConfig dataclass."""

    def test_default_config_values(self) -> None:
        """Default config should have reasonable values."""
        config = MemoryPressureConfig()

        assert config.max_memory_bytes == 0  # Unlimited
        assert config.warning_threshold == 0.8
        assert config.critical_threshold == 0.9
        assert config.auto_evict is True
        assert config.evict_to_target == 0.7

    def test_custom_config_values(self) -> None:
        """Custom config should accept valid values."""
        config = MemoryPressureConfig(
            max_memory_bytes=100 * 1024 * 1024,  # 100MB
            warning_threshold=0.75,
            critical_threshold=0.85,
            auto_evict=False,
            evict_to_target=0.6,
        )

        assert config.max_memory_bytes == 100 * 1024 * 1024
        assert config.warning_threshold == 0.75
        assert config.critical_threshold == 0.85
        assert config.auto_evict is False
        assert config.evict_to_target == 0.6

    def test_config_validates_negative_memory(self) -> None:
        """Config should reject negative memory limit."""
        with pytest.raises(ValueError, match="max_memory_bytes must be non-negative"):
            MemoryPressureConfig(max_memory_bytes=-1)

    def test_config_validates_warning_threshold_range(self) -> None:
        """Config should reject warning threshold outside 0-1 range."""
        with pytest.raises(ValueError, match="warning_threshold must be between"):
            MemoryPressureConfig(warning_threshold=1.5)

        with pytest.raises(ValueError, match="warning_threshold must be between"):
            MemoryPressureConfig(warning_threshold=-0.1)

    def test_config_validates_critical_threshold_range(self) -> None:
        """Config should reject critical threshold outside 0-1 range."""
        with pytest.raises(ValueError, match="critical_threshold must be between"):
            MemoryPressureConfig(critical_threshold=1.5)

        with pytest.raises(ValueError, match="critical_threshold must be between"):
            MemoryPressureConfig(critical_threshold=-0.1)

    def test_config_validates_evict_to_target_range(self) -> None:
        """Config should reject evict_to_target outside 0-1 range."""
        with pytest.raises(ValueError, match="evict_to_target must be between"):
            MemoryPressureConfig(evict_to_target=1.5)

        with pytest.raises(ValueError, match="evict_to_target must be between"):
            MemoryPressureConfig(evict_to_target=-0.1)

    def test_config_validates_threshold_order(self) -> None:
        """Config should reject warning >= critical threshold."""
        with pytest.raises(ValueError, match="warning_threshold.*must be less than"):
            MemoryPressureConfig(warning_threshold=0.9, critical_threshold=0.8)

        with pytest.raises(ValueError, match="warning_threshold.*must be less than"):
            MemoryPressureConfig(warning_threshold=0.9, critical_threshold=0.9)


class TestMemoryStats:
    """Tests for MemoryStats dataclass."""

    def test_default_stats_values(self) -> None:
        """Default stats should have zero values."""
        stats = MemoryStats()

        assert stats.current_usage_bytes == 0
        assert stats.max_allowed_bytes == 0
        assert stats.usage_percentage == 0.0
        assert stats.is_under_pressure is False
        assert stats.files_count == 0
        assert stats.directories_count == 0
        assert stats.eviction_count == 0

    def test_available_bytes_unlimited(self) -> None:
        """available_bytes should be 0 when unlimited."""
        stats = MemoryStats(max_allowed_bytes=0, current_usage_bytes=100)
        assert stats.available_bytes == 0

    def test_available_bytes_with_limit(self) -> None:
        """available_bytes should calculate correctly with limit."""
        stats = MemoryStats(max_allowed_bytes=1000, current_usage_bytes=600)
        assert stats.available_bytes == 400

    def test_available_bytes_cannot_go_negative(self) -> None:
        """available_bytes should not go below 0."""
        stats = MemoryStats(max_allowed_bytes=500, current_usage_bytes=1000)
        assert stats.available_bytes == 0

    def test_to_dict_converts_correctly(self) -> None:
        """to_dict should convert stats to dictionary."""
        stats = MemoryStats(
            current_usage_bytes=1024 * 1024,  # 1MB
            max_allowed_bytes=10 * 1024 * 1024,  # 10MB
            usage_percentage=0.1,
            is_under_pressure=False,
            files_count=10,
            eviction_count=2,
        )

        d = stats.to_dict()

        assert d["current_usage_bytes"] == 1024 * 1024
        assert d["current_usage_mb"] == 1.0
        assert d["max_allowed_mb"] == 10.0
        assert d["usage_percentage"] == 10.0
        assert d["files_count"] == 10
        assert d["eviction_count"] == 2


class TestMemoryPressureError:
    """Tests for MemoryPressureError exception."""

    def test_error_stores_message(self) -> None:
        """Error should store message."""
        error = MemoryPressureError("Out of memory")
        assert str(error) == "Out of memory"

    def test_error_stores_usage_stats(self) -> None:
        """Error should store usage stats."""
        error = MemoryPressureError(
            "Out of memory",
            current_usage=1000,
            max_allowed=500,
        )
        assert error.current_usage == 1000
        assert error.max_allowed == 500


class TestOverlayMemoryEstimation:
    """Tests for memory estimation in OverlayFileSystem."""

    @pytest.fixture
    def unlimited_overlay(self) -> OverlayFileSystem:
        """Create an overlay with unlimited memory."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        return OverlayFileSystem(upper, [lower])

    @pytest.fixture
    def limited_overlay(self) -> OverlayFileSystem:
        """Create an overlay with 1MB memory limit."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        config = MemoryPressureConfig(max_memory_bytes=1024 * 1024)  # 1MB
        return OverlayFileSystem(upper, [lower], memory_config=config)

    def test_estimate_memory_empty(self, unlimited_overlay: OverlayFileSystem) -> None:
        """Memory estimate should be 0 for empty overlay."""
        usage = unlimited_overlay._estimate_memory_usage()
        assert usage == 0

    def test_estimate_memory_with_files(
        self, unlimited_overlay: OverlayFileSystem
    ) -> None:
        """Memory estimate should include file contents."""
        unlimited_overlay.upper.pipe("/test.txt", b"Hello, World!")
        usage = unlimited_overlay._estimate_memory_usage()
        assert usage >= 13  # At least "Hello, World!" length

    def test_estimate_memory_with_multiple_files(
        self, unlimited_overlay: OverlayFileSystem
    ) -> None:
        """Memory estimate should sum all file contents."""
        unlimited_overlay.upper.pipe("/file1.txt", b"AAAA")
        unlimited_overlay.upper.pipe("/file2.txt", b"BBBB")
        usage = unlimited_overlay._estimate_memory_usage()
        assert usage >= 8  # At least 4 + 4 bytes

    def test_get_memory_stats_empty(self, unlimited_overlay: OverlayFileSystem) -> None:
        """Stats for empty overlay should show zeros."""
        stats = unlimited_overlay.get_memory_stats()

        assert stats.current_usage_bytes == 0
        assert stats.usage_percentage == 0.0
        assert stats.is_under_pressure is False

    def test_get_memory_stats_with_files(
        self, unlimited_overlay: OverlayFileSystem
    ) -> None:
        """Stats should reflect actual file sizes."""
        content = b"X" * 1000
        unlimited_overlay.upper.pipe("/large.txt", content)

        stats = unlimited_overlay.get_memory_stats()

        assert stats.current_usage_bytes >= 1000
        # Files count might vary depending on MemoryFileSystem internal state
        assert stats.current_usage_bytes > 0


class TestOverlayMemoryPressure:
    """Tests for memory pressure detection and handling."""

    @pytest.fixture
    def low_limit_overlay(self) -> OverlayFileSystem:
        """Create an overlay with a very low memory limit (10KB)."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        config = MemoryPressureConfig(
            max_memory_bytes=10 * 1024,  # 10KB limit
            warning_threshold=0.5,
            critical_threshold=0.8,
            auto_evict=True,
            evict_to_target=0.3,
        )
        return OverlayFileSystem(upper, [lower], memory_config=config)

    def test_memory_pressure_detected_at_critical(
        self, low_limit_overlay: OverlayFileSystem
    ) -> None:
        """Memory pressure should be detected when exceeding critical threshold."""
        # Fill up to 90% (above critical threshold of 80%)
        content = b"X" * (9 * 1024)  # 9KB
        low_limit_overlay.upper.pipe("/file.txt", content)

        stats = low_limit_overlay.get_memory_stats()
        assert stats.is_under_pressure is True

    def test_memory_pressure_not_detected_below_critical(
        self, low_limit_overlay: OverlayFileSystem
    ) -> None:
        """Memory pressure should not be detected below critical threshold."""
        # Fill up to 50% (below critical threshold of 80%)
        content = b"X" * (5 * 1024)  # 5KB
        low_limit_overlay.upper.pipe("/file.txt", content)

        stats = low_limit_overlay.get_memory_stats()
        assert stats.is_under_pressure is False

    def test_auto_eviction_triggered_at_critical(
        self, low_limit_overlay: OverlayFileSystem
    ) -> None:
        """Auto-eviction should trigger when memory at critical level."""
        # Create files to reach critical threshold
        for i in range(5):
            low_limit_overlay.upper.pipe(f"/file{i}.txt", b"X" * 2048)  # 2KB each

        # Trigger a memory check (this should trigger eviction)
        is_critical, stats = low_limit_overlay._check_memory_pressure()

        # Should have performed eviction
        assert stats.eviction_count > 0 or is_critical is False

    def test_memory_limit_enforced_on_write(self) -> None:
        """Memory limit should be enforced when writing files."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        config = MemoryPressureConfig(max_memory_bytes=100)  # Very small limit
        overlay = OverlayFileSystem(upper, [lower], memory_config=config)

        # Pre-fill the upper layer
        upper.pipe("/existing.txt", b"X" * 100)

        # Try to COW a file that would exceed the limit
        lower.pipe("/lower_file.txt", b"Y" * 50)

        # This should either succeed by evicting or raise MemoryPressureError
        try:
            overlay._copy_up("/lower_file.txt")
            # If we get here, eviction must have freed space
            stats = overlay.get_memory_stats()
            assert stats.current_usage_bytes <= 100
        except MemoryPressureError:
            # This is also valid behavior - limit enforcement
            pass


class TestOverlayManualEviction:
    """Tests for manual memory eviction."""

    @pytest.fixture
    def overlay_with_files(self) -> OverlayFileSystem:
        """Create an overlay with several files."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Create files in reverse chronological order (oldest first)
        import time

        for i in range(5):
            upper.pipe(f"/file{i}.txt", f"Content {i}".encode())
            time.sleep(0.01)  # Small delay for ordering

        return overlay

    def test_evict_oldest_files_removes_files(
        self, overlay_with_files: OverlayFileSystem
    ) -> None:
        """evict_oldest_files should remove files."""
        # Should have 5 files initially
        initial_count = len(overlay_with_files.upper.ls("/"))

        evicted = overlay_with_files.evict_oldest_files(count=2)

        assert len(evicted) == 2

    def test_evict_oldest_files_updates_stats(
        self, overlay_with_files: OverlayFileSystem
    ) -> None:
        """Eviction should update eviction stats."""
        initial_stats = overlay_with_files.get_memory_stats()

        overlay_with_files.evict_oldest_files(count=1)

        updated_stats = overlay_with_files.get_memory_stats()
        assert updated_stats.eviction_count == initial_stats.eviction_count + 1
        assert updated_stats.last_eviction_at > 0

    def test_evict_oldest_files_ignores_whiteouts(
        self, overlay_with_files: OverlayFileSystem
    ) -> None:
        """Eviction should skip whiteout markers."""
        # Create a whiteout marker
        overlay_with_files.upper.pipe("/.wh.hidden.txt", b"")

        evicted = overlay_with_files.evict_oldest_files(count=10)

        # Whiteout should not be evicted
        for path in evicted:
            assert not path.startswith(".wh.")


class TestMemoryPressureConfigUpdate:
    """Tests for updating memory configuration."""

    def test_set_memory_config_updates_config(self) -> None:
        """set_memory_config should update the configuration."""
        overlay = OverlayFileSystem(MemoryFileSystem(), [])

        new_config = MemoryPressureConfig(max_memory_bytes=5000)
        overlay.set_memory_config(new_config)

        assert overlay.memory_config.max_memory_bytes == 5000

    def test_set_memory_config_resets_warning_flag(self) -> None:
        """set_memory_config should reset warning state."""
        overlay = OverlayFileSystem(MemoryFileSystem(), [])
        overlay._memory_warning_issued = True

        new_config = MemoryPressureConfig(max_memory_bytes=5000)
        overlay.set_memory_config(new_config)

        assert overlay._memory_warning_issued is False


class TestMemoryPressureIntegration:
    """Integration tests for memory pressure handling."""

    def test_full_memory_pressure_lifecycle(self) -> None:
        """Test complete memory pressure lifecycle."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()

        # Configure with tight memory constraints
        config = MemoryPressureConfig(
            max_memory_bytes=5 * 1024,  # 5KB
            warning_threshold=0.6,
            critical_threshold=0.8,
            auto_evict=True,
            evict_to_target=0.4,
        )

        overlay = OverlayFileSystem(upper, [lower], memory_config=config)

        # Phase 1: Empty state
        stats = overlay.get_memory_stats()
        assert stats.current_usage_bytes == 0
        assert stats.is_under_pressure is False

        # Phase 2: Add files
        upper.pipe("/file1.txt", b"X" * 1024)  # 1KB
        upper.pipe("/file2.txt", b"Y" * 1024)  # 1KB

        stats = overlay.get_memory_stats()
        assert stats.current_usage_bytes >= 2048
        assert stats.is_under_pressure is False  # 40% < 80% critical

        # Phase 3: Reach critical threshold
        upper.pipe("/file3.txt", b"Z" * 3072)  # 3KB (total ~5KB = 100%)

        stats = overlay.get_memory_stats()
        assert stats.is_under_pressure is True  # 100% > 80% critical

        # Phase 4: Trigger auto-eviction via memory check
        is_critical, stats = overlay._check_memory_pressure()

        # After eviction, usage should be reduced
        assert stats.current_usage_bytes < 5 * 1024 or is_critical is False

    def test_memory_stats_are_accurate(self) -> None:
        """Memory stats should accurately reflect filesystem state."""
        upper = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [])

        # Add files of known sizes
        sizes = [100, 200, 300, 400]
        for i, size in enumerate(sizes):
            upper.pipe(f"/file{i}.txt", b"X" * size)

        stats = overlay.get_memory_stats()

        # Total should be at least sum of file contents
        assert stats.current_usage_bytes >= sum(sizes)

        # Largest file should be 400 bytes
        assert stats.largest_file_bytes >= 400

        # Average should be around 250 bytes
        assert stats.average_file_bytes >= 250


class TestQuietMode:
    """Tests for unlimited/quiet memory mode."""

    def test_unlimited_mode_no_pressure_detection(self) -> None:
        """With unlimited memory, no pressure should be detected."""
        upper = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [])  # Default config = unlimited

        # Add lots of data
        for i in range(100):
            upper.pipe(f"/file{i}.txt", b"X" * 1024)

        stats = overlay.get_memory_stats()

        # Should never be under pressure with unlimited memory
        assert stats.is_under_pressure is False
        assert stats.max_allowed_bytes == 0
        assert stats.usage_percentage == 0.0

    def test_unlimited_mode_no_eviction(self) -> None:
        """With unlimited memory, no eviction should occur."""
        upper = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [])

        # Fill with data
        for i in range(10):
            upper.pipe(f"/file{i}.txt", b"X" * 1024)

        # Check memory pressure (should not evict)
        is_critical, stats = overlay._check_memory_pressure()

        assert is_critical is False
        assert stats.eviction_count == 0
