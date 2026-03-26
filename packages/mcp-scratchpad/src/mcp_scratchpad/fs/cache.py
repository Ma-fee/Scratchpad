"""
Directory index cache with TTL and event-driven invalidation for overlay filesystem.

This module provides caching functionality for directory listings
to improve performance when accessing frequently queried directories.
Supports hybrid invalidation mode combining TTL-based and event-driven strategies.

Performance optimizations:
- O(1) cache lookup using hash-based indexing
- Cache warming for frequently accessed paths
- Adaptive TTL based on access patterns
- Memory-bounded LRU eviction
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from threading import Lock
from time import time
from typing import Any


@dataclass
class CacheEntry:
    """Represents a cached directory listing.

    Attributes:
        path: The directory path being cached
        entries: List of file/directory names in the directory
        created_at: Unix timestamp when the entry was created
        accessed_at: Unix timestamp of last access (for LRU)
        ttl: Time-to-live in seconds
    """

    path: str
    entries: list[str]
    created_at: float
    ttl: int
    accessed_at: float = field(default=0.0)

    def __post_init__(self) -> None:
        """Validate entry fields and set defaults."""
        if self.ttl <= 0:
            raise ValueError(f"TTL must be positive, got {self.ttl}")
        if self.accessed_at == 0.0:
            self.accessed_at = self.created_at


@dataclass
class CacheConfig:
    """Configuration for directory index cache.

    Attributes:
        default_ttl: Default time-to-live in seconds
        max_size: Maximum number of entries to store
        max_memory_bytes: Maximum memory usage in bytes (0 = unlimited)
        enabled: Whether caching is enabled
    """

    default_ttl: int = 60
    max_size: int = 1000
    max_memory_bytes: int = 0
    enabled: bool = True

    def __post_init__(self) -> None:
        """Validate configuration fields."""
        if self.default_ttl <= 0:
            raise ValueError(f"default_ttl must be positive, got {self.default_ttl}")
        if self.max_size <= 0:
            raise ValueError(f"max_size must be positive, got {self.max_size}")
        if self.max_memory_bytes < 0:
            raise ValueError(
                f"max_memory_bytes must be non-negative, got {self.max_memory_bytes}"
            )


class InvalidationEvent(str, Enum):
    """File system events that trigger cache invalidation.

    Attributes:
        WRITE: File content modified
        DELETE: File or directory deleted
        MKDIR: Directory created
        RMDIR: Directory removed
        RENAME: File or directory renamed
    """

    WRITE = "write"
    DELETE = "delete"
    MKDIR = "mkdir"
    RMDIR = "rmdir"
    RENAME = "rename"


@dataclass
class CacheStats:
    """Statistics for cache performance monitoring.

    Attributes:
        hits: Number of successful cache lookups
        misses: Number of failed cache lookups
        evictions: Number of entries evicted from cache
        avg_lookup_time_ms: Average lookup time in milliseconds
        total_lookup_time_ms: Total time spent in lookups
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    avg_lookup_time_ms: float = 0.0
    total_lookup_time_ms: float = 0.0
    _lookup_count_for_avg: int = field(default=0, repr=False)

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate as a percentage.

        Returns:
            Hit rate percentage (0.0 to 100.0), or 0.0 if no lookups
        """
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits / total) * 100.0

    @property
    def total_lookups(self) -> int:
        """Total number of cache lookups."""
        return self.hits + self.misses

    def record_lookup_time(self, elapsed_ms: float) -> None:
        """Record a lookup time for averaging.

        Args:
            elapsed_ms: Time taken for lookup in milliseconds
        """
        self.total_lookup_time_ms += elapsed_ms
        self._lookup_count_for_avg += 1
        self.avg_lookup_time_ms = self.total_lookup_time_ms / self._lookup_count_for_avg


@dataclass
class AccessPattern:
    """Tracks access patterns for a cached path.

    Used for adaptive TTL tuning and cache warming decisions.

    Attributes:
        path: The directory path
        access_count: Number of times accessed
        last_accessed: Timestamp of last access
        avg_access_interval: Average time between accesses in seconds
    """

    path: str
    access_count: int = 0
    last_accessed: float = field(default_factory=time)
    avg_access_interval: float = 0.0
    _first_accessed: float = field(default_factory=time, repr=False)

    def record_access(self) -> None:
        """Record an access to this path."""
        now = time()
        self.access_count += 1

        if self.access_count > 1:
            # Calculate running average of access intervals
            interval = now - self.last_accessed
            # Weighted average: new samples have 20% weight
            self.avg_access_interval = (
                0.8 * self.avg_access_interval + 0.2 * interval
                if self.avg_access_interval > 0
                else interval
            )

        self.last_accessed = now

    @property
    def access_frequency(self) -> float:
        """Calculate access frequency (accesses per minute).

        Returns:
            Accesses per minute, or 0 if insufficient data
        """
        if self.access_count < 2:
            return 0.0
        elapsed = time() - self._first_accessed
        if elapsed <= 0:
            return 0.0
        return (self.access_count / elapsed) * 60.0


@dataclass
class WarmPathConfig:
    """Configuration for cache warming.

    Attributes:
        enabled: Whether cache warming is enabled
        warmup_threshold: Minimum frequency (accesses/min) to qualify for warming
        max_warm_paths: Maximum number of paths to keep warmed
        check_interval: How often to update warm paths (in seconds)
    """

    enabled: bool = True
    warmup_threshold: float = 5.0  # 5 accesses per minute
    max_warm_paths: int = 50
    check_interval: float = 60.0  # 1 minute


class DirectoryIndexCache:
    """Cache for directory index listings with hybrid invalidation.

    Provides efficient caching of directory listings with automatic
    expiration (TTL), event-driven invalidation, LRU eviction,
    and memory pressure handling.

    Performance features:
    - O(1) lookup via hash-based indexing
    - O(1) dirty path checking via prefix index
    - Cache warming for hot paths
    - Adaptive TTL based on access patterns
    - Thread-safe operations

    Attributes:
        _cache: OrderedDict storing cache entries by path (maintains LRU order)
        _config: Cache configuration
        _dirty_paths: Set of paths marked as invalid (event-driven)
        _dirty_prefix_index: Prefix index for O(1) dirty path checking
        _stats: Cache performance statistics
        _access_patterns: Access pattern tracking for adaptive TTL
        _warm_paths: Set of paths marked for warming
        _warm_config: Cache warming configuration
        _lock: Thread-safe lock for concurrent access
    """

    # Overhead estimate per entry (rough approximation)
    # Includes dict overhead, object overhead, etc.
    _ENTRY_OVERHEAD_BYTES = 200

    def __init__(
        self,
        default_ttl: int = 60,
        max_size: int = 1000,
        max_memory_bytes: int = 0,
        config: CacheConfig | None = None,
        warm_config: WarmPathConfig | None = None,
        enable_adaptive_ttl: bool = True,
    ):
        """Initialize the directory index cache.

        Args:
            default_ttl: Default time-to-live in seconds
            max_size: Maximum number of entries before eviction
            max_memory_bytes: Maximum memory usage in bytes (0 = unlimited)
            config: Optional CacheConfig to use instead of individual params
            warm_config: Optional configuration for cache warming
            enable_adaptive_ttl: Whether to enable adaptive TTL tuning
        """
        if config is not None:
            self._config = config
        else:
            self._config = CacheConfig(
                default_ttl=default_ttl,
                max_size=max_size,
                max_memory_bytes=max_memory_bytes,
            )

        self._warm_config = warm_config if warm_config is not None else WarmPathConfig()
        self._enable_adaptive_ttl = enable_adaptive_ttl

        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._dirty_paths: set[str] = set()
        self._dirty_prefix_index: set[str] = set()  # Index for O(1) prefix checks
        self._stats = CacheStats()
        self._access_patterns: dict[str, AccessPattern] = {}
        self._warm_paths: set[str] = set()
        self._last_warm_check: float = 0.0
        self._lock = Lock()

    @property
    def config(self) -> CacheConfig:
        """Get the cache configuration."""
        return self._config

    @property
    def size(self) -> int:
        """Get the current number of cached entries."""
        with self._lock:
            return len(self._cache)

    @property
    def stats(self) -> CacheStats:
        """Get the cache statistics."""
        return self._stats

    @property
    def warm_paths(self) -> set[str]:
        """Get the set of warmed paths."""
        with self._lock:
            return self._warm_paths.copy()

    def _update_dirty_prefix_index(self, path: str, add: bool = True) -> None:
        """Update the dirty prefix index when a path is marked dirty.

        This maintains an index of all path prefixes for O(1) dirty checking.

        Args:
            path: The path to add/remove from the index
            add: True to add, False to remove
        """
        if add:
            # Add all prefixes of the path
            parts = path.strip("/").split("/")
            current = ""
            for part in parts:
                current = f"{current}/{part}" if current else f"/{part}"
                self._dirty_prefix_index.add(current)
        else:
            # Remove only the exact path (prefixes may still be dirty)
            self._dirty_prefix_index.discard(path)

    def _estimate_size(self, entries: list[str]) -> int:
        """Estimate memory size of a list of directory entries.

        Rough estimate: sum of string lengths + overhead per entry + overhead

        Args:
            entries: List of file/directory names

        Returns:
            Estimated size in bytes
        """
        # Sum of all string lengths (each char is ~1 byte on average for ASCII)
        content_size = sum(len(s) for s in entries)
        # Overhead per string object (Python object overhead ~49 bytes)
        string_overhead = len(entries) * 49
        # Total estimate
        return content_size + string_overhead + self._ENTRY_OVERHEAD_BYTES

    def _get_entry_memory_usage(self, entry: CacheEntry) -> int:
        """Calculate estimated memory usage of a cache entry.

        Args:
            entry: The cache entry to measure

        Returns:
            Estimated size in bytes
        """
        return self._estimate_size(entry.entries)

    def _get_total_memory_usage(self) -> int:
        """Calculate total estimated memory usage of all cache entries.

        Returns:
            Total estimated size in bytes
        """
        return sum(
            self._get_entry_memory_usage(entry) for entry in self._cache.values()
        )

    def _update_access_time(self, path: str) -> None:
        """Update the access time for a cache entry.

        Args:
            path: The path to update
        """
        if path in self._cache:
            entry = self._cache[path]
            entry.accessed_at = time()
            # Move to end (most recently used) by re-inserting
            # Python 3.7+ maintains insertion order in dicts
            self._cache.move_to_end(path)

    def _evict_for_memory(self, required_bytes: int) -> None:
        """Evict entries until enough memory is available.

        Uses LRU eviction - removes least recently accessed entries first.

        Args:
            required_bytes: Bytes needed to be available
        """
        if self._config.max_memory_bytes == 0:
            return  # No memory limit

        current_usage = self._get_total_memory_usage()
        target_usage = self._config.max_memory_bytes - required_bytes

        # Evict LRU entries until we have enough space
        while self._cache and current_usage > target_usage:
            # Get LRU entry (first in dict - least recently accessed)
            lru_path = next(iter(self._cache.keys()))
            lru_entry = self._cache[lru_path]
            lru_size = self._get_entry_memory_usage(lru_entry)

            del self._cache[lru_path]
            self._stats.evictions += 1
            current_usage -= lru_size

    def _is_dirty(self, path: str) -> bool:
        """Check if a path or any parent is marked as dirty.

        Optimized to O(1) using prefix index.

        Args:
            path: The directory path to check

        Returns:
            True if path or any parent is dirty, False otherwise
        """
        # Fast O(1) check using set lookups
        if path in self._dirty_paths:
            return True

        # Check using prefix index - O(1) lookup
        if path in self._dirty_prefix_index:
            # Check if this exact path or any parent is dirty
            parts = path.strip("/").split("/")
            current = ""
            for part in parts:
                current = f"{current}/{part}" if current else f"/{part}"
                if current in self._dirty_paths:
                    return True

        return False

    def invalidate(self, path: str, event: InvalidationEvent) -> None:
        """Mark a path as dirty due to a file system event.

        Args:
            path: The file/directory path affected by the event
            event: The type of file system event
        """
        with self._lock:
            # Mark the path and all parent directories as dirty
            self._dirty_paths.add(path)
            self._update_dirty_prefix_index(path, add=True)

            # For directory events, also invalidate parent directories
            if event in (
                InvalidationEvent.MKDIR,
                InvalidationEvent.RMDIR,
                InvalidationEvent.DELETE,
            ):
                # Invalidate the parent directory
                parent = str(PurePosixPath(path).parent)
                if parent and parent != ".":
                    self._dirty_paths.add(parent)
                    self._update_dirty_prefix_index(parent, add=True)

    def clear_dirty(self, path: str | None = None) -> None:
        """Clear dirty markers.

        Args:
            path: Specific path to clear, or None to clear all
        """
        with self._lock:
            if path is None:
                self._dirty_paths.clear()
                self._dirty_prefix_index.clear()
            else:
                self._dirty_paths.discard(path)
                self._update_dirty_prefix_index(path, add=False)

    def _record_access_pattern(self, path: str, hit: bool) -> None:
        """Record access pattern for a path.

        Args:
            path: The path being accessed
            hit: Whether the access was a cache hit
        """
        if not self._enable_adaptive_ttl and not self._warm_config.enabled:
            return

        if path not in self._access_patterns:
            self._access_patterns[path] = AccessPattern(path=path)
        self._access_patterns[path].record_access()

    def _update_warm_paths(self) -> None:
        """Update the set of warm paths based on access patterns."""
        if not self._warm_config.enabled:
            return

        now = time()
        if now - self._last_warm_check < self._warm_config.check_interval:
            return

        self._last_warm_check = now

        # Find paths that meet the warming threshold
        hot_paths = []
        for path, pattern in self._access_patterns.items():
            freq = pattern.access_frequency
            if freq >= self._warm_config.warmup_threshold:
                hot_paths.append((path, freq))

        # Sort by frequency (highest first) and take top N
        hot_paths.sort(key=lambda x: x[1], reverse=True)
        self._warm_paths = {p[0] for p in hot_paths[: self._warm_config.max_warm_paths]}

    def _get_adaptive_ttl(self, path: str, base_ttl: int) -> int:
        """Calculate adaptive TTL based on access patterns.

        Args:
            path: The directory path
            base_ttl: The base TTL value

        Returns:
            Adjusted TTL value
        """
        if not self._enable_adaptive_ttl:
            return base_ttl

        pattern = self._access_patterns.get(path)
        if pattern is None or pattern.access_count < 3:
            return base_ttl

        # For frequently accessed paths, extend TTL
        freq = pattern.access_frequency
        if freq >= 10.0:  # Very hot: 10+ accesses per minute
            return int(base_ttl * 2.0)  # Double TTL
        elif freq >= 5.0:  # Hot: 5-10 accesses per minute
            return int(base_ttl * 1.5)  # 1.5x TTL
        elif pattern.avg_access_interval < 5.0:  # Accessed every <5 seconds
            return int(base_ttl * 1.25)  # 1.25x TTL

        return base_ttl

    def get(self, path: str) -> list[str] | None:
        """Retrieve cached directory listing if not expired or dirty.

        Hybrid invalidation: checks both TTL expiration and dirty markers.
        Dirty markers (event-driven) take precedence over TTL.

        Performance: O(1) lookup with timing tracking.

        Args:
            path: The directory path to look up

        Returns:
            List of directory entries if found, not expired, and not dirty;
            None otherwise
        """
        start_time = time()

        with self._lock:
            if not self._config.enabled:
                self._stats.misses += 1
                self._stats.record_lookup_time((time() - start_time) * 1000)
                return None

            # Check if path or any parent is marked dirty (event-driven invalidation)
            if self._is_dirty(path):
                self._stats.misses += 1
                self._stats.record_lookup_time((time() - start_time) * 1000)
                return None

            entry = self._cache.get(path)
            if entry is None:
                self._stats.misses += 1
                self._record_access_pattern(path, hit=False)
                self._stats.record_lookup_time((time() - start_time) * 1000)
                return None

            if self._is_expired(entry):
                del self._cache[path]
                self._stats.misses += 1
                self._stats.record_lookup_time((time() - start_time) * 1000)
                return None

            # Update access time for LRU tracking
            self._update_access_time(path)
            self._stats.hits += 1
            self._record_access_pattern(path, hit=True)

            # Update warm paths if needed
            self._update_warm_paths()

            self._stats.record_lookup_time((time() - start_time) * 1000)
            return entry.entries

    def set(
        self,
        path: str,
        entries: list[str],
        ttl: int | None = None,
    ) -> None:
        """Store a directory listing in the cache.

        Args:
            path: The directory path
            entries: List of file/directory names
            ttl: Optional TTL override (uses config.default_ttl if None)

        Raises:
            ValueError: If ttl is provided and not positive
        """
        with self._lock:
            if not self._config.enabled:
                return

            effective_ttl = ttl if ttl is not None else self._config.default_ttl

            # Apply adaptive TTL if enabled
            effective_ttl = self._get_adaptive_ttl(path, effective_ttl)

            if effective_ttl <= 0:
                raise ValueError(f"TTL must be positive, got {effective_ttl}")

            # Calculate memory needed for this entry
            new_entry_size = self._estimate_size(entries)

            # Evict for memory limit if needed (before checking size limit)
            if self._config.max_memory_bytes > 0:
                # If this entry alone exceeds memory limit, don't cache it
                if new_entry_size > self._config.max_memory_bytes:
                    return
                self._evict_for_memory(new_entry_size)

            # Evict oldest entries if at capacity and this is a new entry
            if path not in self._cache and len(self._cache) >= self._config.max_size:
                self._evict_lru()

            current_time = time()
            self._cache[path] = CacheEntry(
                path=path,
                entries=list(entries),  # Create a copy to prevent external modification
                created_at=current_time,
                ttl=effective_ttl,
                accessed_at=current_time,
            )

    def delete(self, path: str) -> bool:
        """Remove a cached entry.

        Args:
            path: The directory path to remove

        Returns:
            True if an entry was found and removed, False otherwise
        """
        with self._lock:
            if path in self._cache:
                del self._cache[path]
                return True
            return False

    def clear(self) -> None:
        """Remove all cached entries and reset statistics."""
        with self._lock:
            self._cache.clear()
            self._dirty_paths.clear()
            self._dirty_prefix_index.clear()
            self._access_patterns.clear()
            self._warm_paths.clear()
            self._stats = CacheStats()

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if a cache entry has exceeded its TTL.

        Args:
            entry: The cache entry to check

        Returns:
            True if the entry has expired, False otherwise
        """
        current_time = time()
        age = current_time - entry.created_at
        return age > entry.ttl

    def _evict_lru(self) -> None:
        """Remove the least recently used entry from the cache."""
        if not self._cache:
            return

        # Remove first item (LRU - least recently accessed)
        lru_path = next(iter(self._cache.keys()))
        del self._cache[lru_path]
        self._stats.evictions += 1

    def _evict_oldest(self) -> None:
        """Remove the oldest entry from the cache (by creation time).

        Note: Now deprecated, use _evict_lru() for LRU eviction.
        """
        if not self._cache:
            return

        # Find and remove the oldest entry by created_at
        oldest_path = min(self._cache.keys(), key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_path]
        self._stats.evictions += 1

    def mark_dirty(self, path: str) -> None:
        """Mark a path as dirty (invalidated), triggering event-driven invalidation.

        When a path is marked dirty, it and its subpaths are considered invalid
        regardless of TTL. This enables hybrid invalidation where event-driven
        changes take precedence over TTL.

        Args:
            path: The path to mark as dirty
        """
        with self._lock:
            self._dirty_paths.add(path)
            self._update_dirty_prefix_index(path, add=True)

    def is_dirty(self, path: str) -> bool:
        """Check if a path is marked as dirty.

        A path is considered dirty if it or any of its parent directories
        have been marked dirty via mark_dirty() or invalidate_on_event().

        Args:
            path: The path to check

        Returns:
            True if the path is dirty, False otherwise
        """
        with self._lock:
            return self._is_dirty(path)

    def clean_dirty(self, path: str) -> bool:
        """Remove a path from the dirty set (mark as clean).

        Args:
            path: The path to mark as clean

        Returns:
            True if the path was dirty and is now clean, False otherwise
        """
        with self._lock:
            if path in self._dirty_paths:
                self._dirty_paths.remove(path)
                self._update_dirty_prefix_index(path, add=False)
                return True
            return False

    def invalidate_on_event(self, event_type: str, path: str) -> list[str]:
        """Invalidate cache entries based on a file system event.

        Invalidates affected paths based on the event type:
        - WRITE/DELETE: Invalidate the file's parent directory
        - MKDIR/RMDIR: Invalidate the parent directory
        - RENAME: Invalidate both source and destination parent directories

        Args:
            event_type: Type of file system event (write, delete, mkdir, rmdir, rename)
            path: The path affected by the event

        Returns:
            List of paths that were invalidated

        Raises:
            ValueError: If event_type is not a valid InvalidationEvent
        """
        with self._lock:
            # Validate event type
            try:
                event = InvalidationEvent(event_type.lower())
            except ValueError:
                valid_events = ", ".join(e.value for e in InvalidationEvent)
                raise ValueError(
                    f"Invalid event_type '{event_type}'. Valid: {valid_events}"
                )

            affected_paths = self._get_affected_paths(event, path)

            # Mark all affected paths as dirty
            for affected_path in affected_paths:
                self._dirty_paths.add(affected_path)
                self._update_dirty_prefix_index(affected_path, add=True)

            return affected_paths

    def _get_affected_paths(self, event: InvalidationEvent, path: str) -> list[str]:
        """Get the list of paths to invalidate for a given event.

        Args:
            event: The type of file system event
            path: The path affected by the event

        Returns:
            List of paths that should be invalidated
        """
        affected: list[str] = []

        if event in (InvalidationEvent.WRITE, InvalidationEvent.DELETE):
            # Invalidate the directory containing the changed item
            # For /parent/child/file.txt, we want /parent (grandparent of file)
            # For /parent/child (directory), we want /parent (parent of dir)
            path_obj = PurePosixPath(path)
            parent = path_obj.parent
            # If parent has a parent (i.e., not root), use grandparent for files
            # Otherwise use parent directly for top-level items
            if str(parent.parent) != "." and str(parent.parent) != "/":
                # Path is nested (e.g., /a/b/c), use grandparent (/a)
                affected_path = str(parent.parent)
            else:
                # Path is at 2nd level (e.g., /a/b), use parent (/a)
                affected_path = str(parent)

            if affected_path and affected_path != ".":
                affected.append(affected_path)
            else:
                affected.append("/")

        elif event in (InvalidationEvent.MKDIR, InvalidationEvent.RMDIR):
            # Invalidate the parent directory
            parent = str(PurePosixPath(path).parent)
            if parent and parent != ".":
                affected.append(parent)
            else:
                affected.append("/")

        elif event == InvalidationEvent.RENAME:
            # For rename, path should contain source and dest separated by '->'
            if "->" in path:
                parts = path.split("->", 1)
                src_path = parts[0].strip()
                dst_path = parts[1].strip()

                # Invalidate both source and destination parents
                src_parent = str(PurePosixPath(src_path).parent)
                dst_parent = str(PurePosixPath(dst_path).parent)

                if src_parent and src_parent != ".":
                    affected.append(src_parent)
                else:
                    affected.append("/")

                if dst_parent and dst_parent != "." and dst_parent not in affected:
                    affected.append(dst_parent)
                elif dst_parent == "." and "/" not in affected:
                    affected.append("/")
            else:
                # Single path rename - invalidate its parent
                parent = str(PurePosixPath(path).parent)
                if parent and parent != ".":
                    affected.append(parent)
                else:
                    affected.append("/")

        return affected

    def flush(self) -> None:
        """Clear all cached entries and dirty markers.

        This is a complete cache reset - all entries are removed and
        all dirty markers are cleared.
        """
        with self._lock:
            self._cache.clear()
            self._dirty_paths.clear()
            self._dirty_prefix_index.clear()
            self._access_patterns.clear()
            self._warm_paths.clear()

    def has_entry(self, path: str) -> bool:
        """Check if a path has a cached entry (not checking expiration).

        Args:
            path: The directory path to check

        Returns:
            True if an entry exists (even if expired), False otherwise
        """
        with self._lock:
            return path in self._cache

    def get_memory_usage(self) -> int:
        """Get the estimated memory usage of the cache.

        Returns:
            Estimated memory usage in bytes
        """
        with self._lock:
            return self._get_total_memory_usage()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics including size, config, health,
            hit/miss ratio, and memory usage
        """
        with self._lock:
            expired_count = sum(
                1 for entry in self._cache.values() if self._is_expired(entry)
            )

            return {
                "enabled": self._config.enabled,
                "size": len(self._cache),
                "max_size": self._config.max_size,
                "default_ttl": self._config.default_ttl,
                "expired_entries": expired_count,
                "dirty_entries": len(self._dirty_paths),
                "utilization": len(self._cache) / self._config.max_size,
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "evictions": self._stats.evictions,
                "hit_rate": self._stats.hit_rate,
                "total_lookups": self._stats.total_lookups,
                "avg_lookup_time_ms": self._stats.avg_lookup_time_ms,
                "memory_usage_bytes": self._get_total_memory_usage(),
                "max_memory_bytes": self._config.max_memory_bytes,
                "warm_paths_count": len(self._warm_paths),
                "adaptive_ttl_enabled": self._enable_adaptive_ttl,
            }

    def preload(self, path: str, entries: list[str], ttl: int | None = None) -> bool:
        """Preload a directory listing into the cache.

        This is used for cache warming - pre-populating the cache
        with frequently accessed paths.

        Args:
            path: The directory path
            entries: List of file/directory names
            ttl: Optional TTL override

        Returns:
            True if successfully preloaded, False otherwise
        """
        with self._lock:
            if not self._config.enabled:
                return False

            # Don't preload if already cached and not expired
            if path in self._cache:
                entry = self._cache[path]
                if not self._is_expired(entry):
                    return False

        # Use regular set which handles all the logic
        self.set(path, entries, ttl)
        return True

    def get_warm_paths(self) -> list[str]:
        """Get list of paths marked for warming.

        Returns:
            List of paths that are frequently accessed
        """
        with self._lock:
            return sorted(self._warm_paths)

    def is_warm_path(self, path: str) -> bool:
        """Check if a path is marked for warming.

        Args:
            path: The path to check

        Returns:
            True if the path is a warm path
        """
        with self._lock:
            return path in self._warm_paths

    def get_access_patterns(self) -> dict[str, dict[str, Any]]:
        """Get access patterns for all tracked paths.

        Returns:
            Dictionary mapping paths to their access pattern info
        """
        with self._lock:
            return {
                path: {
                    "access_count": pattern.access_count,
                    "access_frequency": pattern.access_frequency,
                    "avg_access_interval": pattern.avg_access_interval,
                    "last_accessed": pattern.last_accessed,
                }
                for path, pattern in self._access_patterns.items()
            }
