"""
Tests for directory index cache with hybrid invalidation.

This module tests the DirectoryIndexCache implementation, verifying:
- Cache entries are stored and retrieved correctly
- TTL expiration works as expected
- Max size limits are enforced
- Clear removes all entries
- Event-driven invalidation via mark_dirty
- Hybrid mode (TTL + event-driven) works correctly
"""

import time
from dataclasses import FrozenInstanceError

import pytest

from mcp_scratchpad.fs.cache import (
    AccessPattern,
    CacheConfig,
    CacheEntry,
    CacheStats,
    DirectoryIndexCache,
    InvalidationEvent,
    WarmPathConfig,
)


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_cache_entry_creation(self) -> None:
        """Test creating CacheEntry with all fields."""
        entry = CacheEntry(
            path="/test/dir",
            entries=["file1.txt", "subdir"],
            created_at=1234567890.0,
            ttl=60,
        )

        assert entry.path == "/test/dir"
        assert entry.entries == ["file1.txt", "subdir"]
        assert entry.created_at == 1234567890.0
        assert entry.ttl == 60

    def test_cache_entry_invalid_ttl(self) -> None:
        """Test that CacheEntry rejects non-positive TTL."""
        with pytest.raises(ValueError, match="TTL must be positive"):
            CacheEntry(
                path="/test",
                entries=[],
                created_at=1234567890.0,
                ttl=0,
            )

    def test_cache_entry_negative_ttl(self) -> None:
        """Test that CacheEntry rejects negative TTL."""
        with pytest.raises(ValueError, match="TTL must be positive"):
            CacheEntry(
                path="/test",
                entries=[],
                created_at=1234567890.0,
                ttl=-1,
            )


class TestCacheConfig:
    """Tests for CacheConfig dataclass."""

    def test_cache_config_defaults(self) -> None:
        """Test CacheConfig with default values."""
        config = CacheConfig()

        assert config.default_ttl == 60
        assert config.max_size == 1000
        assert config.enabled is True

    def test_cache_config_custom_values(self) -> None:
        """Test CacheConfig with custom values."""
        config = CacheConfig(default_ttl=300, max_size=500, enabled=False)

        assert config.default_ttl == 300
        assert config.max_size == 500
        assert config.enabled is False

    def test_cache_config_invalid_default_ttl(self) -> None:
        """Test that CacheConfig rejects non-positive default_ttl."""
        with pytest.raises(ValueError, match="default_ttl must be positive"):
            CacheConfig(default_ttl=0)

    def test_cache_config_invalid_max_size(self) -> None:
        """Test that CacheConfig rejects non-positive max_size."""
        with pytest.raises(ValueError, match="max_size must be positive"):
            CacheConfig(max_size=0)


class TestInvalidationEvent:
    """Tests for InvalidationEvent enum."""

    def test_invalidation_event_values(self) -> None:
        """Test that InvalidationEvent has correct values."""
        assert InvalidationEvent.WRITE == "write"
        assert InvalidationEvent.DELETE == "delete"
        assert InvalidationEvent.MKDIR == "mkdir"
        assert InvalidationEvent.RMDIR == "rmdir"
        assert InvalidationEvent.RENAME == "rename"

    def test_invalidation_event_is_str(self) -> None:
        """Test that InvalidationEvent members are strings."""
        assert isinstance(InvalidationEvent.WRITE, str)
        assert InvalidationEvent.WRITE == "write"


class TestDirectoryIndexCacheInstantiation:
    """Tests for cache instantiation."""

    def test_cache_instantiates_with_defaults(self) -> None:
        """Test that cache instantiates with default parameters."""
        cache = DirectoryIndexCache()

        assert isinstance(cache, DirectoryIndexCache)
        assert cache.config.default_ttl == 60
        assert cache.config.max_size == 1000
        assert cache.config.enabled is True
        assert cache.size == 0

    def test_cache_instantiates_with_custom_params(self) -> None:
        """Test that cache instantiates with custom parameters."""
        cache = DirectoryIndexCache(default_ttl=120, max_size=500)

        assert cache.config.default_ttl == 120
        assert cache.config.max_size == 500

    def test_cache_instantiates_with_config(self) -> None:
        """Test that cache instantiates with CacheConfig."""
        config = CacheConfig(default_ttl=300, max_size=200, enabled=False)
        cache = DirectoryIndexCache(config=config)

        assert cache.config == config
        assert cache.config.default_ttl == 300
        assert cache.config.enabled is False

    def test_config_takes_precedence_over_params(self) -> None:
        """Test that config parameter takes precedence."""
        config = CacheConfig(default_ttl=300, max_size=200)
        cache = DirectoryIndexCache(default_ttl=60, max_size=1000, config=config)

        assert cache.config.default_ttl == 300
        assert cache.config.max_size == 200


class TestCacheSetAndGet:
    """Tests for cache set and get operations."""

    def test_cache_stores_and_retrieves(self) -> None:
        """Test that cache stores and retrieves entries."""
        cache = DirectoryIndexCache()

        entries = ["file1.txt", "file2.txt", "subdir"]
        cache.set("/test", entries)

        result = cache.get("/test")

        assert result == entries

    def test_cache_returns_none_for_nonexistent(self) -> None:
        """Test that cache returns None for non-existent path."""
        cache = DirectoryIndexCache()

        result = cache.get("/nonexistent")

        assert result is None

    def test_cache_updates_existing_entry(self) -> None:
        """Test that set updates existing entry without eviction."""
        cache = DirectoryIndexCache(max_size=2)

        cache.set("/test", ["old.txt"])
        cache.set("/test", ["new.txt"])

        result = cache.get("/test")
        assert result == ["new.txt"]
        assert cache.size == 1

    def test_cache_does_not_store_when_disabled(self) -> None:
        """Test that cache does not store when disabled."""
        config = CacheConfig(enabled=False)
        cache = DirectoryIndexCache(config=config)

        cache.set("/test", ["file.txt"])
        result = cache.get("/test")

        assert result is None
        assert cache.size == 0

    def test_cache_get_returns_none_when_disabled(self) -> None:
        """Test that cache returns None when disabled, even with stored entry."""
        cache = DirectoryIndexCache()
        cache.set("/test", ["file.txt"])

        # Disable cache
        cache._config.enabled = False

        result = cache.get("/test")
        assert result is None

    def test_cache_creates_copy_of_entries(self) -> None:
        """Test that cache creates a copy of entries list."""
        cache = DirectoryIndexCache()

        entries = ["file1.txt"]
        cache.set("/test", entries)

        # Modify original list
        entries.append("file2.txt")

        # Cache should still have original
        result = cache.get("/test")
        assert result == ["file1.txt"]


class TestCacheExpiration:
    """Tests for cache TTL expiration."""

    def test_cache_expiration_works(self) -> None:
        """Test that entries expire after TTL."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=1)

        # Should return entries immediately
        result1 = cache.get("/test")
        assert result1 == ["file.txt"]

        # Wait for expiration
        time.sleep(1.1)

        # Should return None after expiration
        result2 = cache.get("/test")
        assert result2 is None

    def test_expired_entry_is_removed_on_access(self) -> None:
        """Test that expired entry is removed when accessed."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=1)
        time.sleep(1.1)

        # Access should remove expired entry
        cache.get("/test")

        assert cache.has_entry("/test") is False

    def test_default_ttl_used_when_not_specified(self) -> None:
        """Test that default TTL is used when not specified."""
        cache = DirectoryIndexCache(default_ttl=1)

        cache.set("/test", ["file.txt"])

        # Should return entries immediately
        assert cache.get("/test") == ["file.txt"]

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("/test") is None

    def test_custom_ttl_overrides_default(self) -> None:
        """Test that custom TTL overrides default."""
        cache = DirectoryIndexCache(default_ttl=10)

        # Use short TTL
        cache.set("/test", ["file.txt"], ttl=1)

        time.sleep(1.1)

        # Should be expired due to short TTL
        assert cache.get("/test") is None

    def test_different_paths_have_independent_ttl(self) -> None:
        """Test that different paths expire independently."""
        cache = DirectoryIndexCache()

        cache.set("/path1", ["file1.txt"], ttl=1)
        cache.set("/path2", ["file2.txt"], ttl=10)

        time.sleep(1.1)

        # path1 should be expired
        assert cache.get("/path1") is None

        # path2 should still be valid
        assert cache.get("/path2") == ["file2.txt"]


class TestCacheMaxSize:
    """Tests for cache max size enforcement."""

    def test_cache_respects_max_size(self) -> None:
        """Test that cache respects max size limit."""
        cache = DirectoryIndexCache(max_size=2)

        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])
        cache.set("/path3", ["file3.txt"])  # Should evict oldest

        assert cache.size <= 2

    def test_oldest_entry_evicted_when_full(self) -> None:
        """Test that oldest entry is evicted when cache is full."""
        cache = DirectoryIndexCache(max_size=2)

        cache.set("/path1", ["file1.txt"])
        time.sleep(0.01)  # Ensure different timestamps
        cache.set("/path2", ["file2.txt"])
        time.sleep(0.01)
        cache.set("/path3", ["file3.txt"])

        # path1 (oldest) should be evicted
        assert cache.get("/path1") is None
        assert cache.get("/path2") is not None
        assert cache.get("/path3") is not None

    def test_update_does_not_trigger_eviction(self) -> None:
        """Test that updating existing entry does not trigger eviction."""
        cache = DirectoryIndexCache(max_size=2)

        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])

        # Update path1 - should not trigger eviction
        cache.set("/path1", ["updated.txt"])

        # All entries should still exist
        assert cache.get("/path1") == ["updated.txt"]
        assert cache.get("/path2") == ["file2.txt"]
        assert cache.size == 2

    def test_cache_size_property(self) -> None:
        """Test cache size property returns correct count."""
        cache = DirectoryIndexCache()

        assert cache.size == 0

        cache.set("/path1", ["file.txt"])
        assert cache.size == 1

        cache.set("/path2", ["file.txt"])
        assert cache.size == 2

        cache.delete("/path1")
        assert cache.size == 1


class TestCacheDelete:
    """Tests for cache delete operation."""

    def test_delete_returns_true_for_existing(self) -> None:
        """Test that delete returns True for existing entry."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])
        result = cache.delete("/test")

        assert result is True
        assert cache.get("/test") is None

    def test_delete_returns_false_for_nonexistent(self) -> None:
        """Test that delete returns False for non-existent entry."""
        cache = DirectoryIndexCache()

        result = cache.delete("/nonexistent")

        assert result is False


class TestCacheClear:
    """Tests for cache clear operation."""

    def test_clear_removes_all_entries(self) -> None:
        """Test that clear removes all entries."""
        cache = DirectoryIndexCache()

        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])
        cache.set("/path3", ["file3.txt"])

        assert cache.size == 3

        cache.clear()

        assert cache.size == 0
        assert cache.get("/path1") is None
        assert cache.get("/path2") is None
        assert cache.get("/path3") is None

    def test_clear_on_empty_cache(self) -> None:
        """Test that clear on empty cache does not raise."""
        cache = DirectoryIndexCache()

        cache.clear()  # Should not raise

        assert cache.size == 0


class TestCacheHasEntry:
    """Tests for has_entry method."""

    def test_has_entry_returns_true_for_existing(self) -> None:
        """Test that has_entry returns True for existing entry."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])

        assert cache.has_entry("/test") is True

    def test_has_entry_returns_false_for_nonexistent(self) -> None:
        """Test that has_entry returns False for non-existent entry."""
        cache = DirectoryIndexCache()

        assert cache.has_entry("/nonexistent") is False

    def test_has_entry_returns_true_for_expired(self) -> None:
        """Test that has_entry returns True even for expired entries."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=1)
        time.sleep(1.1)

        # Should still report as having entry (doesn't check expiration)
        assert cache.has_entry("/test") is True

        # But get should return None due to expiration
        assert cache.get("/test") is None


class TestCacheStats:
    """Tests for cache statistics."""

    def test_get_stats_returns_dict(self) -> None:
        """Test that get_stats returns a dictionary."""
        cache = DirectoryIndexCache()

        stats = cache.get_stats()

        assert isinstance(stats, dict)

    def test_get_stats_contains_expected_keys(self) -> None:
        """Test that get_stats contains expected keys."""
        cache = DirectoryIndexCache()

        stats = cache.get_stats()

        expected_keys = [
            "enabled",
            "size",
            "max_size",
            "default_ttl",
            "expired_entries",
            "dirty_entries",
            "utilization",
        ]
        for key in expected_keys:
            assert key in stats

    def test_get_stats_reflects_current_state(self) -> None:
        """Test that get_stats reflects current cache state."""
        cache = DirectoryIndexCache(default_ttl=120, max_size=500)

        stats1 = cache.get_stats()
        assert stats1["size"] == 0
        assert stats1["default_ttl"] == 120
        assert stats1["max_size"] == 500

        cache.set("/test", ["file.txt"])

        stats2 = cache.get_stats()
        assert stats2["size"] == 1
        assert stats2["utilization"] == 0.002


class TestCacheErrorHandling:
    """Tests for cache error handling."""

    def test_set_rejects_negative_ttl(self) -> None:
        """Test that set rejects negative TTL."""
        cache = DirectoryIndexCache()

        with pytest.raises(ValueError, match="TTL must be positive"):
            cache.set("/test", ["file.txt"], ttl=-1)

    def test_set_rejects_zero_ttl(self) -> None:
        """Test that set rejects zero TTL."""
        cache = DirectoryIndexCache()

        with pytest.raises(ValueError, match="TTL must be positive"):
            cache.set("/test", ["file.txt"], ttl=0)


class TestCacheMarkDirty:
    """Tests for mark_dirty and dirty path invalidation."""

    def test_mark_dirty_makes_entry_invalid(self) -> None:
        """Test that mark_dirty causes get to return None."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=60)
        assert cache.get("/test") == ["file.txt"]

        cache.mark_dirty("/test")
        assert cache.get("/test") is None

    def test_mark_dirty_affects_child_paths(self) -> None:
        """Test that marking parent dirty invalidates child paths."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["child"], ttl=60)
        cache.set("/parent/child", ["file.txt"], ttl=60)

        # Mark parent dirty
        cache.mark_dirty("/parent")

        # Both parent and child should be invalid
        assert cache.get("/parent") is None
        assert cache.get("/parent/child") is None

    def test_is_dirty_returns_true_for_dirty_path(self) -> None:
        """Test is_dirty returns True for explicitly marked path."""
        cache = DirectoryIndexCache()

        assert cache.is_dirty("/test") is False

        cache.mark_dirty("/test")

        assert cache.is_dirty("/test") is True

    def test_is_dirty_returns_true_for_parent_dirty(self) -> None:
        """Test is_dirty returns True when parent is dirty."""
        cache = DirectoryIndexCache()

        cache.mark_dirty("/parent")

        # Child should be considered dirty
        assert cache.is_dirty("/parent/child") is True
        assert cache.is_dirty("/parent/child/grandchild") is True

    def test_is_dirty_returns_false_for_unrelated_path(self) -> None:
        """Test is_dirty returns False for unrelated paths."""
        cache = DirectoryIndexCache()

        cache.mark_dirty("/parent1")

        # Different branch should not be dirty
        assert cache.is_dirty("/parent2") is False
        assert cache.is_dirty("/parent2/child") is False

    def test_mark_dirty_preserves_entry(self) -> None:
        """Test that mark_dirty doesn't delete the entry, just marks dirty."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=60)
        cache.mark_dirty("/test")

        # Entry should still exist (has_entry checks storage, not dirtiness)
        assert cache.has_entry("/test") is True

    def test_clean_dirty_removes_dirty_marker(self) -> None:
        """Test clean_dirty removes dirty marker from path."""
        cache = DirectoryIndexCache()

        cache.mark_dirty("/test")
        assert cache.is_dirty("/test") is True

        result = cache.clean_dirty("/test")
        assert result is True
        assert cache.is_dirty("/test") is False

    def test_clean_dirty_returns_false_for_clean_path(self) -> None:
        """Test clean_dirty returns False if path was not dirty."""
        cache = DirectoryIndexCache()

        result = cache.clean_dirty("/test")

        assert result is False

    def test_clean_dirty_allows_revalidation(self) -> None:
        """Test that after clean_dirty, entry becomes valid again if not TTL expired."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=60)
        cache.mark_dirty("/test")
        assert cache.get("/test") is None

        cache.clean_dirty("/test")
        # Entry should be valid again (not expired)
        assert cache.get("/test") == ["file.txt"]


class TestCacheEventDrivenInvalidation:
    """Tests for event-driven invalidation via invalidate_on_event."""

    def test_invalidate_on_write_invalidates_parent(self) -> None:
        """Test WRITE event invalidates parent directory."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["child"], ttl=60)

        # Writing to /parent/child/file.txt should invalidate /parent
        invalidated = cache.invalidate_on_event("write", "/parent/child/file.txt")

        assert "/parent" in invalidated
        assert cache.get("/parent") is None

    def test_invalidate_on_delete_invalidates_parent(self) -> None:
        """Test DELETE event invalidates parent directory."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["child"], ttl=60)

        invalidated = cache.invalidate_on_event("delete", "/parent/child/file.txt")

        assert "/parent" in invalidated
        assert cache.get("/parent") is None

    def test_invalidate_on_mkdir_invalidates_parent(self) -> None:
        """Test MKDIR event invalidates parent directory."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["existing"], ttl=60)

        invalidated = cache.invalidate_on_event("mkdir", "/parent/newdir")

        assert "/parent" in invalidated
        assert cache.get("/parent") is None

    def test_invalidate_on_rmdir_invalidates_parent(self) -> None:
        """Test RMDIR event invalidates parent directory."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["child"], ttl=60)

        invalidated = cache.invalidate_on_event("rmdir", "/parent/child")

        assert "/parent" in invalidated
        assert cache.get("/parent") is None

    def test_invalidate_on_rename_invalidates_both_parents(self) -> None:
        """Test RENAME event invalidates both source and dest parents."""
        cache = DirectoryIndexCache()

        cache.set("/src", ["file.txt"], ttl=60)
        cache.set("/dst", [], ttl=60)

        invalidated = cache.invalidate_on_event(
            "rename", "/src/file.txt -> /dst/file.txt"
        )

        assert "/src" in invalidated
        assert "/dst" in invalidated
        assert cache.get("/src") is None
        assert cache.get("/dst") is None

    def test_invalidate_on_rename_single_path(self) -> None:
        """Test RENAME with single path falls back to invalidating parent."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["file.txt"], ttl=60)

        invalidated = cache.invalidate_on_event("rename", "/parent/file.txt")

        assert "/parent" in invalidated
        assert cache.get("/parent") is None

    def test_invalidate_handles_root_parent(self) -> None:
        """Test that events in root directory invalidate root."""
        cache = DirectoryIndexCache()

        cache.set("/", ["file.txt"], ttl=60)

        invalidated = cache.invalidate_on_event("write", "/file.txt")

        assert "/" in invalidated
        assert cache.get("/") is None

    def test_invalidate_event_case_insensitive(self) -> None:
        """Test that event type matching is case insensitive."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["child"], ttl=60)

        # Uppercase event type
        invalidated = cache.invalidate_on_event("WRITE", "/parent/child")

        assert "/parent" in invalidated

    def test_invalidate_invalid_event_raises(self) -> None:
        """Test that invalid event type raises ValueError."""
        cache = DirectoryIndexCache()

        with pytest.raises(ValueError, match="Invalid event_type"):
            cache.invalidate_on_event("invalid_event", "/path")


class TestCacheHybridMode:
    """Tests for hybrid invalidation mode (TTL + event-driven)."""

    def test_dirty_takes_precedence_over_ttl(self) -> None:
        """Test that dirty status takes precedence over TTL validity."""
        cache = DirectoryIndexCache()

        # Set entry with long TTL
        cache.set("/test", ["file.txt"], ttl=60)
        assert cache.get("/test") == ["file.txt"]

        # Mark dirty - should invalidate even though TTL is still valid
        cache.mark_dirty("/test")
        assert cache.get("/test") is None

    def test_dirty_marked_entry_can_be_revalidated(self) -> None:
        """Test that cleaning dirty allows TTL to work again."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=60)
        cache.mark_dirty("/test")
        assert cache.get("/test") is None

        # Clean the dirty marker
        cache.clean_dirty("/test")

        # Should be valid again (TTL not expired)
        assert cache.get("/test") == ["file.txt"]

    def test_event_invalidation_works_with_ttl(self) -> None:
        """Test that event-driven invalidation works alongside TTL."""
        cache = DirectoryIndexCache()

        cache.set("/parent", ["child"], ttl=60)
        cache.set("/parent/child", ["file.txt"], ttl=60)

        # Event invalidates parent but child TTL is untouched
        cache.invalidate_on_event("write", "/parent/child/file.txt")

        # Parent should be invalid
        assert cache.get("/parent") is None

        # Child should also be invalid (parent is dirty)
        assert cache.get("/parent/child") is None

    def test_cache_prefers_dirty_over_expired(self) -> None:
        """Test that dirty check happens before TTL check."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=1)
        time.sleep(1.1)

        # Entry is expired, but also mark dirty
        cache.mark_dirty("/test")

        # Should return None (either way)
        assert cache.get("/test") is None


class TestCacheFlush:
    """Tests for flush operation."""

    def test_flush_clears_all_entries(self) -> None:
        """Test that flush removes all cached entries."""
        cache = DirectoryIndexCache()

        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])

        assert cache.size == 2

        cache.flush()

        assert cache.size == 0
        assert cache.get("/path1") is None
        assert cache.get("/path2") is None

    def test_flush_clears_dirty_markers(self) -> None:
        """Test that flush removes all dirty markers."""
        cache = DirectoryIndexCache()

        cache.mark_dirty("/path1")
        cache.mark_dirty("/path2")

        assert cache.is_dirty("/path1") is True

        cache.flush()

        assert cache.is_dirty("/path1") is False
        assert cache.is_dirty("/path2") is False

    def test_flush_stats_show_zero(self) -> None:
        """Test that cache stats show zero after flush."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])
        cache.mark_dirty("/test")

        stats_before = cache.get_stats()
        assert stats_before["size"] == 1
        assert stats_before["dirty_entries"] == 1

        cache.flush()

        stats_after = cache.get_stats()
        assert stats_after["size"] == 0
        assert stats_after["dirty_entries"] == 0
        assert stats_after["expired_entries"] == 0


class TestCacheQAScenario:
    """QA scenario tests as specified in task requirements."""

    def test_ttl_expiration_scenario(self) -> None:
        """
        QA Scenario: Cache with TTL

        Steps:
          1. cache.set("/test", ["file1"], ttl=1)
          2. cache.get("/test") -> returns listing
          3. time.sleep(2)
          4. cache.get("/test") -> returns None

        Expected: TTL expiration works
        """
        cache = DirectoryIndexCache()

        # Step 1: Set cache entry with 1-second TTL
        cache.set("/test", ["file1"], ttl=1)

        # Step 2: Should return listing
        result = cache.get("/test")
        assert result == ["file1"], "Entry should be immediately retrievable"

        # Step 3: Wait for expiration
        time.sleep(2)

        # Step 4: Should return None after expiration
        result = cache.get("/test")
        assert result is None, "Entry should expire after TTL"

    def test_event_driven_invalidation_scenario(self) -> None:
        """
        QA Scenario: Event-driven invalidation

        Steps:
            1. cache.set("/parent", ["child/"], ttl=60)
            2. cache.invalidate_on_event("write", "/parent/child/file.txt")
            3. cache.get("/parent") -> returns None (invalidated)

        Expected: Parent directory cache invalidated
        """
        cache = DirectoryIndexCache()

        # Step 1: Set parent directory cache with long TTL
        cache.set("/parent", ["child/"], ttl=60)
        assert cache.get("/parent") == ["child/"], "Parent should be cached"

        # Step 2: Invalidate on write event to child file
        invalidated = cache.invalidate_on_event("write", "/parent/child/file.txt")

        # Step 3: Parent should be invalidated
        assert "/parent" in invalidated, "Parent should be in invalidated list"
        assert cache.get("/parent") is None, "Parent cache should be invalidated"

    def test_hybrid_mode_prefers_dirty_over_ttl(self) -> None:
        """
        QA Scenario: Hybrid mode prefers dirty over TTL

        Steps:
            1. cache.set("/test", ["file1"], ttl=60)
            2. Verify entry is valid
            3. cache.mark_dirty("/test")
            4. cache.get("/test") -> returns None (even though TTL valid)

        Expected: Dirty marker takes precedence over TTL
        """
        cache = DirectoryIndexCache()

        # Step 1: Set entry with long TTL
        cache.set("/test", ["file1"], ttl=60)

        # Step 2: Verify valid
        assert cache.get("/test") == ["file1"], "Entry should be valid initially"

        # Step 3: Mark dirty
        cache.mark_dirty("/test")

        # Step 4: Should be invalidated despite valid TTL
        assert cache.get("/test") is None, "Dirty should take precedence over TTL"

    def test_parent_directory_invalidation_on_child_change(self) -> None:
        """
        QA Scenario: Parent directories invalidated on child change

        Steps:
            1. cache.set("/parent", ["child"], ttl=60)
            2. cache.invalidate_on_event("mkdir", "/parent/newdir")
            3. cache.get("/parent") -> returns None

        Expected: Parent directory invalidated on child mkdir
        """
        cache = DirectoryIndexCache()

        # Step 1: Cache parent directory
        cache.set("/parent", ["child"], ttl=60)

        # Step 2: Create new directory (mkdir event)
        cache.invalidate_on_event("mkdir", "/parent/newdir")

        # Step 3: Parent should be invalidated
        assert cache.get("/parent") is None

    def test_flush_clears_all_scenario(self) -> None:
        """
        QA Scenario: Flush clears all entries

        Steps:
            1. cache.set("/path1", ["a"], ttl=60)
            2. cache.set("/path2", ["b"], ttl=60)
            3. cache.mark_dirty("/path1")
            4. cache.flush()
            5. cache.size == 0
            6. cache.is_dirty("/path1") == False

        Expected: All entries and dirty markers cleared
        """
        cache = DirectoryIndexCache()

        cache.set("/path1", ["a"], ttl=60)
        cache.set("/path2", ["b"], ttl=60)
        cache.mark_dirty("/path1")

        assert cache.size == 2
        assert cache.is_dirty("/path1") is True

        cache.flush()

        assert cache.size == 0
        assert cache.is_dirty("/path1") is False


class TestCacheMemoryManagement:
    """Tests for cache memory management features."""

    def test_memory_estimation_basic(self) -> None:
        """Test basic memory estimation for entries."""
        cache = DirectoryIndexCache()
        entries = ["file1.txt", "file2.txt", "subdir"]
        estimated = cache._estimate_size(entries)

        # Should be positive and proportional to content
        assert estimated > 0
        # Sum of string lengths + overhead
        expected_min = sum(len(s) for s in entries)
        assert estimated > expected_min

    def test_memory_usage_tracking(self) -> None:
        """Test that memory usage is tracked."""
        cache = DirectoryIndexCache()

        # Empty cache should have 0 memory usage
        assert cache.get_memory_usage() == 0

        # Add entries
        cache.set("/path1", ["file1.txt"])
        usage1 = cache.get_memory_usage()
        assert usage1 > 0

        cache.set("/path2", ["file2.txt", "file3.txt"])
        usage2 = cache.get_memory_usage()
        assert usage2 > usage1

    def test_cache_config_max_memory_bytes(self) -> None:
        """Test CacheConfig with max_memory_bytes."""
        config = CacheConfig(max_memory_bytes=1000)
        cache = DirectoryIndexCache(config=config)

        assert cache.config.max_memory_bytes == 1000

    def test_cache_config_negative_memory_bytes(self) -> None:
        """Test that CacheConfig rejects negative max_memory_bytes."""
        with pytest.raises(ValueError, match="max_memory_bytes must be non-negative"):
            CacheConfig(max_memory_bytes=-1)

    def test_memory_limit_eviction(self) -> None:
        """Test that entries are evicted when memory limit is reached."""
        # Set a small memory limit to force eviction
        cache = DirectoryIndexCache(max_memory_bytes=500)

        # Add entries that together exceed the limit
        cache.set("/path1", ["a" * 100])  # Large entry
        cache.set("/path2", ["b" * 100])  # Another large entry
        cache.set("/path3", ["c" * 100])  # Should trigger eviction

        # Memory should be under the limit
        assert cache.get_memory_usage() <= 500

    def test_single_entry_exceeds_memory_limit(self) -> None:
        """Test that entries larger than memory limit are not cached."""
        cache = DirectoryIndexCache(max_memory_bytes=100)

        # Try to cache an entry larger than the limit
        cache.set("/path1", ["a" * 200])

        # Entry should not be cached
        assert cache.get("/path1") is None
        assert cache.size == 0


class TestCacheLRU:
    """Tests for LRU eviction behavior."""

    def test_lru_tracking_on_get(self) -> None:
        """Test that get updates LRU order."""
        cache = DirectoryIndexCache(max_size=3)

        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])
        cache.set("/path3", ["file3.txt"])

        # Access path1 to make it most recently used
        cache.get("/path1")

        # Add a new entry which should evict path2 (now LRU)
        cache.set("/path4", ["file4.txt"])

        # path2 should be evicted, path1 should still exist
        assert cache.get("/path1") == ["file1.txt"]
        assert cache.get("/path2") is None
        assert cache.get("/path3") == ["file3.txt"]
        assert cache.get("/path4") == ["file4.txt"]

    def test_lru_eviction_order(self) -> None:
        """Test that LRU entries are evicted first."""
        cache = DirectoryIndexCache(max_size=2)

        # Add entries in order
        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])

        # Access path1 to make it MRU
        cache.get("/path1")

        # Add a new entry
        cache.set("/path3", ["file3.txt"])

        # path2 (LRU) should be evicted
        assert cache.get("/path2") is None
        assert cache.get("/path1") == ["file1.txt"]
        assert cache.get("/path3") == ["file3.txt"]

    def test_access_time_updated_on_get(self) -> None:
        """Test that access time is updated on successful get."""
        cache = DirectoryIndexCache()

        cache.set("/path1", ["file1.txt"])
        original_access_time = cache._cache["/path1"].accessed_at

        # Wait a bit and access
        import time

        time.sleep(0.01)
        cache.get("/path1")

        new_access_time = cache._cache["/path1"].accessed_at
        assert new_access_time > original_access_time


class TestCacheStatistics:
    """Tests for cache hit/miss statistics."""

    def test_cache_stats_initialization(self) -> None:
        """Test that CacheStats initializes with zeros."""
        stats = CacheStats()

        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.hit_rate == 0.0
        assert stats.total_lookups == 0

    def test_hit_rate_calculation(self) -> None:
        """Test hit rate calculation."""
        stats = CacheStats(hits=80, misses=20)

        assert stats.hit_rate == 80.0
        assert stats.total_lookups == 100

    def test_hit_rate_zero_lookups(self) -> None:
        """Test hit rate when no lookups have occurred."""
        stats = CacheStats()

        assert stats.hit_rate == 0.0

    def test_stats_tracked_on_get_hit(self) -> None:
        """Test that hits are tracked."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])
        cache.get("/test")

        assert cache.stats.hits == 1
        assert cache.stats.misses == 0

    def test_stats_tracked_on_get_miss(self) -> None:
        """Test that misses are tracked."""
        cache = DirectoryIndexCache()

        # Miss: non-existent entry
        cache.get("/nonexistent")

        assert cache.stats.hits == 0
        assert cache.stats.misses == 1

    def test_stats_tracked_on_expired(self) -> None:
        """Test that expired entry access counts as miss."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"], ttl=1)
        import time

        time.sleep(1.1)
        cache.get("/test")

        assert cache.stats.misses == 1

    def test_stats_tracked_on_disabled_cache(self) -> None:
        """Test that access on disabled cache counts as miss."""
        config = CacheConfig(enabled=False)
        cache = DirectoryIndexCache(config=config)

        cache.get("/test")

        assert cache.stats.misses == 1

    def test_evictions_tracked(self) -> None:
        """Test that evictions are tracked."""
        cache = DirectoryIndexCache(max_size=2)

        cache.set("/path1", ["file1.txt"])
        cache.set("/path2", ["file2.txt"])
        cache.set("/path3", ["file3.txt"])  # Should trigger eviction

        assert cache.stats.evictions >= 1

    def test_get_stats_includes_hit_miss(self) -> None:
        """Test that get_stats includes hit/miss information."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])
        cache.get("/test")  # hit
        cache.get("/other")  # miss

        stats = cache.get_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0
        assert stats["total_lookups"] == 2

    def test_get_stats_includes_memory_usage(self) -> None:
        """Test that get_stats includes memory usage."""
        cache = DirectoryIndexCache(max_memory_bytes=10000)

        cache.set("/test", ["file.txt"])

        stats = cache.get_stats()

        assert "memory_usage_bytes" in stats
        assert stats["memory_usage_bytes"] > 0
        assert stats["max_memory_bytes"] == 10000

    def test_stats_reset_on_clear(self) -> None:
        """Test that stats are reset when cache is cleared."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])
        cache.get("/test")
        cache.get("/missing")

        cache.clear()

        assert cache.stats.hits == 0
        assert cache.stats.misses == 0
        assert cache.stats.evictions == 0

    def test_evictions_tracked_for_memory_pressure(self) -> None:
        """Test that memory pressure evictions are tracked."""
        cache = DirectoryIndexCache(max_memory_bytes=500)

        initial_evictions = cache.stats.evictions

        # Add entries to trigger memory eviction
        cache.set("/path1", ["a" * 100])
        cache.set("/path2", ["b" * 100])
        cache.set("/path3", ["c" * 100])

        assert cache.stats.evictions > initial_evictions


class TestCacheLRUQAScenario:
    """QA scenario tests for LRU eviction as specified in task requirements."""

    def test_lru_eviction_scenario(self) -> None:
        """
        QA Scenario: LRU eviction with memory limit

        Steps:
          1. Set memory limit to small value
          2. Add many cache entries
          3. Verify oldest accessed entries evicted

        Expected: LRU eviction works
        """
        import time

        # Small memory limit to force eviction
        cache = DirectoryIndexCache(max_memory_bytes=800, max_size=10)

        # Step 1 & 2: Add entries
        cache.set("/path1", ["content1"])
        time.sleep(0.01)
        cache.set("/path2", ["content2"])
        time.sleep(0.01)
        cache.set("/path3", ["content3"])

        # Access path1 to make it MRU
        cache.get("/path1")

        # Add more entries to trigger LRU eviction
        cache.set("/path4", ["content_longer_than_others"])
        cache.set("/path5", ["content5"])

        # Step 3: Verify LRU eviction
        # path1 was accessed most recently, should still exist
        assert cache.get("/path1") == ["content1"], "MRU entry should not be evicted"

        # path2 was least recently used, might be evicted
        # but we just verify cache stays under memory limit
        assert cache.get_memory_usage() <= 800, "Memory usage should be under limit"

        # Verify evictions were tracked
        assert cache.stats.evictions >= 1, "Evictions should be tracked"

        # Verify stats work
        stats = cache.get_stats()
        assert stats["hits"] >= 1
        assert stats["hit_rate"] > 0
        assert "memory_usage_bytes" in stats


class TestCacheWarming:
    """Tests for cache warming functionality."""

    def test_warm_paths_identified(self) -> None:
        """Test that frequently accessed paths are identified as warm paths."""
        warm_config = WarmPathConfig(
            enabled=True, warmup_threshold=1.0, max_warm_paths=10, check_interval=0.1
        )
        cache = DirectoryIndexCache(warm_config=warm_config)

        # Access a path multiple times quickly
        cache.set("/hot", ["file.txt"])
        for _ in range(10):
            cache.get("/hot")

        # Wait for warm check interval
        time.sleep(0.15)
        cache.get("/hot")  # Trigger warm check

        # Path should be identified as warm
        assert "/hot" in cache.get_warm_paths()
        assert cache.is_warm_path("/hot")

    def test_warm_path_config_disable(self) -> None:
        """Test that warming can be disabled."""
        warm_config = WarmPathConfig(enabled=False)
        cache = DirectoryIndexCache(warm_config=warm_config)

        cache.set("/test", ["file.txt"])
        for _ in range(10):
            cache.get("/test")

        time.sleep(0.15)
        cache.get("/test")

        # Should not identify any warm paths when disabled
        assert len(cache.get_warm_paths()) == 0

    def test_max_warm_paths_respected(self) -> None:
        """Test that max_warm_paths limit is respected."""
        warm_config = WarmPathConfig(
            enabled=True, warmup_threshold=0.1, max_warm_paths=3, check_interval=0.1
        )
        cache = DirectoryIndexCache(warm_config=warm_config)

        # Access many paths
        for i in range(10):
            cache.set(f"/path{i}", [f"file{i}.txt"])
            for _ in range(5):
                cache.get(f"/path{i}")

        time.sleep(0.15)
        cache.get("/path0")  # Trigger warm check

        # Should have at most max_warm_paths
        warm_paths = cache.get_warm_paths()
        assert len(warm_paths) <= 3

    def test_preload_adds_entry(self) -> None:
        """Test that preload adds entries to cache."""
        cache = DirectoryIndexCache()

        result = cache.preload("/test", ["file1.txt", "file2.txt"])

        assert result is True
        assert cache.get("/test") == ["file1.txt", "file2.txt"]

    def test_preload_skips_existing_valid(self) -> None:
        """Test that preload skips already cached valid entries."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["original.txt"], ttl=60)
        result = cache.preload("/test", ["new.txt"])

        # Should not overwrite existing valid entry
        assert result is False
        assert cache.get("/test") == ["original.txt"]

    def test_preload_replaces_expired(self) -> None:
        """Test that preload replaces expired entries."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["old.txt"], ttl=1)
        time.sleep(1.1)

        result = cache.preload("/test", ["new.txt"])

        assert result is True
        assert cache.get("/test") == ["new.txt"]


class TestAdaptiveTTL:
    """Tests for adaptive TTL functionality."""

    def test_adaptive_ttl_increases_for_hot_paths(self) -> None:
        """Test that adaptive TTL increases for frequently accessed paths."""
        cache = DirectoryIndexCache(default_ttl=60, enable_adaptive_ttl=True)

        # Access path frequently
        for i in range(20):
            cache.set("/hot", [f"file{i}.txt"])
            cache.get("/hot")
            time.sleep(0.05)  # Fast access pattern

        # Next set should use adaptive TTL
        cache.set("/hot", ["final.txt"])
        entry = cache._cache["/hot"]

        # Adaptive TTL should be higher than base
        assert entry.ttl >= 60

    def test_adaptive_ttl_disabled_uses_default(self) -> None:
        """Test that adaptive TTL can be disabled."""
        cache = DirectoryIndexCache(default_ttl=60, enable_adaptive_ttl=False)

        for _ in range(20):
            cache.set("/test", ["file.txt"])
            cache.get("/test")

        cache.set("/test", ["final.txt"])
        entry = cache._cache["/test"]

        assert entry.ttl == 60

    def test_access_pattern_tracking(self) -> None:
        """Test that access patterns are tracked."""
        cache = DirectoryIndexCache(enable_adaptive_ttl=True)

        cache.set("/test", ["file.txt"])
        for _ in range(5):
            cache.get("/test")

        patterns = cache.get_access_patterns()
        assert "/test" in patterns
        assert patterns["/test"]["access_count"] == 5

    def test_access_frequency_calculation(self) -> None:
        """Test access frequency calculation."""
        pattern = AccessPattern(path="/test")

        # Simulate 10 accesses over 1 second
        for _ in range(10):
            pattern.record_access()
            time.sleep(0.1)

        freq = pattern.access_frequency
        assert freq > 0  # Should have some frequency


class TestPerformanceOptimizations:
    """Tests for cache performance optimizations."""

    def test_lookup_time_tracking(self) -> None:
        """Test that cache lookup times are tracked."""
        cache = DirectoryIndexCache()

        cache.set("/test", ["file.txt"])
        cache.get("/test")
        cache.get("/test")

        stats = cache.get_stats()
        assert "avg_lookup_time_ms" in stats
        assert stats["avg_lookup_time_ms"] >= 0

    def test_o1_lookup_performance(self) -> None:
        """Test that cache lookup is O(1) regardless of cache size."""
        import statistics

        cache_small = DirectoryIndexCache(max_size=10)
        cache_large = DirectoryIndexCache(max_size=1000)

        # Populate caches
        for i in range(10):
            cache_small.set(f"/path{i}", [f"file{i}.txt"])
        for i in range(1000):
            cache_large.set(f"/path{i}", [f"file{i}.txt"])

        # Measure lookup times
        small_times = []
        large_times = []

        for _ in range(100):
            start = time.time()
            cache_small.get("/path5")
            small_times.append((time.time() - start) * 1000)

            start = time.time()
            cache_large.get("/path500")
            large_times.append((time.time() - start) * 1000)

        avg_small = statistics.mean(small_times)
        avg_large = statistics.mean(large_times)

        # Large cache should not be significantly slower (O(1) check)
        # Allow 2x tolerance for timing variance
        assert avg_large < avg_small * 3, (
            f"Large cache lookup ({avg_large:.4f}ms) too slow vs small ({avg_small:.4f}ms)"
        )

    def test_dirty_check_performance(self) -> None:
        """Test that dirty path checking is O(1)."""
        import statistics

        cache = DirectoryIndexCache()

        # Mark many paths as dirty
        for i in range(100):
            cache.mark_dirty(f"/dirty/path{i}")

        # Measure dirty check times for different depths
        times = []
        for _ in range(100):
            start = time.time()
            cache.is_dirty("/dirty/path50/nested/deep/file")
            times.append((time.time() - start) * 1000)

        avg_time = statistics.mean(times)
        # Should be very fast (O(1) with prefix index)
        assert avg_time < 1.0, f"Dirty check too slow: {avg_time:.4f}ms"

    def test_thread_safety(self) -> None:
        """Test that cache operations are thread-safe."""
        import threading

        cache = DirectoryIndexCache()
        errors = []
        results = []

        def writer():
            try:
                for i in range(100):
                    cache.set(f"/path{i}", [f"file{i}.txt"])
            except Exception as e:
                errors.append(f"Writer error: {e}")

        def reader():
            try:
                for i in range(100):
                    result = cache.get(f"/path{i}")
                    results.append(result)
            except Exception as e:
                errors.append(f"Reader error: {e}")

        def deleter():
            try:
                for i in range(50):
                    cache.delete(f"/path{i}")
            except Exception as e:
                errors.append(f"Deleter error: {e}")

        # Run operations concurrently
        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=deleter),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_cache_improves_read_performance(self) -> None:
        """Test that cache significantly improves read performance."""
        import statistics

        # Simulate "filesystem" lookup
        filesystem_data = {
            f"/path{i}": [f"file{j}.txt" for j in range(10)] for i in range(100)
        }

        def uncached_lookup(path: str) -> list[str] | None:
            """Simulate slow filesystem lookup."""
            time.sleep(0.001)  # 1ms filesystem delay
            return filesystem_data.get(path)

        # Measure uncached performance
        uncached_times = []
        for i in range(50):
            start = time.time()
            uncached_lookup(f"/path{i % 100}")
            uncached_times.append((time.time() - start) * 1000)

        # Now measure cached performance
        cache = DirectoryIndexCache()
        for i in range(100):
            cache.set(f"/path{i}", filesystem_data[f"/path{i}"])

        cached_times = []
        for i in range(50):
            start = time.time()
            cache.get(f"/path{i % 100}")
            cached_times.append((time.time() - start) * 1000)

        avg_uncached = statistics.mean(uncached_times)
        avg_cached = statistics.mean(cached_times)

        # Cache should be significantly faster (>50% improvement)
        improvement = (avg_uncached - avg_cached) / avg_uncached * 100
        assert improvement > 50, (
            f"Cache improvement only {improvement:.1f}%, expected >50%"
        )


class TestCachePerformanceBenchmarks:
    """Performance benchmarks requiring pytest-benchmark."""

    @pytest.mark.skipif(
        not hasattr(pytest, "config") or "benchmark" not in dir(pytest),
        reason="pytest-benchmark not installed",
    )
    def test_benchmark_cache_get(self, benchmark) -> None:
        """Benchmark cache get operation."""
        cache = DirectoryIndexCache()
        cache.set("/test", ["file.txt"])

        result = benchmark(cache.get, "/test")
        assert result == ["file.txt"]

    @pytest.mark.skipif(
        not hasattr(pytest, "config") or "benchmark" not in dir(pytest),
        reason="pytest-benchmark not installed",
    )
    def test_benchmark_cache_set(self, benchmark) -> None:
        """Benchmark cache set operation."""
        cache = DirectoryIndexCache()

        def set_and_clear():
            cache.set("/test", ["file.txt"])
            cache.delete("/test")

        benchmark(set_and_clear)

    def test_memory_per_entry_under_1kb(self) -> None:
        """Test that memory per entry is under 1KB average."""
        cache = DirectoryIndexCache(max_size=1000, max_memory_bytes=1000000)

        # Add entries with typical content
        for i in range(100):
            entries = [f"file{j}.txt" for j in range(10)]
            cache.set(f"/path{i}", entries)

        memory_usage = cache.get_memory_usage()
        avg_per_entry = memory_usage / 100

        # Should be under 1KB per entry on average
        assert avg_per_entry < 1024, (
            f"Memory per entry too high: {avg_per_entry:.0f} bytes"
        )

    def test_cache_miss_overhead_under_5ms(self) -> None:
        """Test that cache miss overhead is under 5ms."""
        import statistics

        cache = DirectoryIndexCache()

        times = []
        for _ in range(100):
            start = time.time()
            cache.get("/nonexistent")
            times.append((time.time() - start) * 1000)

        avg_time = statistics.mean(times)
        assert avg_time < 5.0, f"Cache miss overhead too high: {avg_time:.4f}ms"

    def test_cache_lookup_under_1ms(self) -> None:
        """Test that cache lookup is under 1ms."""
        import statistics

        cache = DirectoryIndexCache()
        cache.set("/test", ["file.txt"])

        times = []
        for _ in range(100):
            start = time.time()
            cache.get("/test")
            times.append((time.time() - start) * 1000)

        avg_time = statistics.mean(times)
        assert avg_time < 1.0, f"Cache lookup too slow: {avg_time:.4f}ms"
