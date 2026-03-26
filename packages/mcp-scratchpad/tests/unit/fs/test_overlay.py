"""
Unit tests for OverlayFileSystem.

Tests the basic skeleton and instantiation of OverlayFileSystem.
Full operation tests will be in separate test files.
"""

import io
from typing import Any

import pytest
from fsspec import AbstractFileSystem
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.fs.overlay import OverlayFileSystem, _normalize_path


class MockBytesIO:
    """Mock file object that writes to MockFileSystem on close."""

    def __init__(
        self,
        store: dict[str, bytes],
        path: str,
        mode: str,
        initial_content: bytes = b"",
    ):
        self._store = store
        self._path = path
        self._mode = mode
        self._buffer = io.BytesIO(initial_content)
        self._closed = False

        # For append mode, seek to end
        if "a" in mode:
            self._buffer.seek(0, 2)  # Seek to end

    def read(self, size: int = -1) -> bytes:
        """Read data from buffer."""
        return self._buffer.read(size)

    def write(self, data: bytes | str) -> int:
        """Write data to buffer."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return self._buffer.write(data)

    def readall(self) -> bytes:
        """Read all remaining data."""
        return self._buffer.read()

    def close(self) -> None:
        """Close and save data to store."""
        if not self._closed:
            self._store[self._path] = self._buffer.getvalue()
            self._closed = True

    def readable(self) -> bool:
        """Check if file is readable."""
        return "r" in self._mode or "+" in self._mode

    def writable(self) -> bool:
        """Check if file is writable."""
        return (
            "w" in self._mode
            or "a" in self._mode
            or "x" in self._mode
            or "+" in self._mode
        )

    def seekable(self) -> bool:
        """Check if file is seekable."""
        return True

    def seek(self, pos: int, whence: int = 0) -> int:
        """Seek to position."""
        return self._buffer.seek(pos, whence)

    def tell(self) -> int:
        """Return current position."""
        return self._buffer.tell()

    @property
    def closed(self) -> bool:
        """Check if file is closed."""
        return self._closed

    def flush(self) -> None:
        """Flush the buffer (no-op for memory buffer)."""
        pass

    def __enter__(self) -> "MockBytesIO":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class MockFileSystem(AbstractFileSystem):
    """Mock filesystem for testing with isolated storage.

    Unlike MemoryFileSystem which shares storage across instances,
    MockFileSystem has instance-specific storage for proper isolation testing.
    """

    protocol = "mock"
    cachable = False

    def __init__(self, **kwargs):
        """Initialize with empty instance-specific storage."""
        super().__init__(**kwargs)
        self._store: dict[str, bytes] = {}
        self._dirs: set[str] = {"/"}

    def write_text(self, path: str, content: str) -> None:
        """Write text to path."""
        self._store[path] = content.encode("utf-8")
        # Ensure parent directories exist
        parts = path.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i]) or "/"
            self._dirs.add(parent)

    def mkdir(self, path: str) -> None:
        """Create directory."""
        self._dirs.add(path)

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        """Create directory and all its parents."""
        if path in self._dirs and exist_ok:
            return
        # Create all parent directories
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            parent = "/".join(parts[:i]) or "/"
            self._dirs.add(parent)

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        return path in self._store or path in self._dirs

    def isfile(self, path: str) -> bool:
        """Check if path is a file."""
        return path in self._store

    def isdir(self, path: str) -> bool:
        """Check if path is a directory."""
        return path in self._dirs

    def pipe(self, path: str, data: bytes) -> None:
        """Write bytes to path."""
        self._store[path] = data
        # Ensure parent directories exist
        parts = path.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i]) or "/"
            self._dirs.add(parent)

    def cat_file(self, path: str) -> bytes:
        """Read bytes from path."""
        if path not in self._store:
            raise FileNotFoundError(f"Path not found: {path}")
        return self._store[path]

    def rm_file(self, path: str) -> None:
        """Remove a file."""
        if path in self._store:
            del self._store[path]

    def rm(self, path: str, **kwargs) -> None:
        """Remove a file (fsspec compatibility)."""
        if path in self._store:
            del self._store[path]

    def rmdir(self, path: str, **kwargs) -> None:
        """Remove a directory."""
        if path in self._dirs:
            self._dirs.remove(path)

    def ls(self, path: str, **kwargs) -> list[str]:
        """List directory contents.

        Returns list of paths that are direct children of the given path.
        """
        normalized = path if path.endswith("/") else path + "/"
        results = []

        # Find all files and directories that are direct children
        all_paths = set(self._store.keys()) | self._dirs

        for p in all_paths:
            # Check if p is a direct child of path
            if p == path or p == "/":
                continue
            if p.startswith(normalized):
                # Get the relative part
                relative = p[len(normalized) :]
                # Only include direct children (no nested slashes)
                if "/" not in relative:
                    results.append(p)

        return sorted(results)

    def _open(self, path: str, mode: str = "rb", **kwargs) -> MockBytesIO:
        """Open a file for reading or writing."""
        # Ensure parent directories exist for write/append modes
        if "w" in mode or "a" in mode or "x" in mode:
            parts = path.split("/")
            for i in range(1, len(parts)):
                parent = "/".join(parts[:i]) or "/"
                self._dirs.add(parent)

        if "r" in mode and "+" not in mode:
            # Pure read mode
            if path not in self._store:
                raise FileNotFoundError(f"Path not found: {path}")
            return MockBytesIO(self._store, path, mode, self._store[path])
        elif "w" in mode:
            # Write mode - truncates existing or creates new
            return MockBytesIO(self._store, path, mode)
        elif "a" in mode:
            # Append mode - start with existing content if present
            initial = self._store.get(path, b"")
            return MockBytesIO(self._store, path, mode, initial)
        elif "x" in mode:
            # Exclusive create mode
            if path in self._store:
                raise FileExistsError(f"File exists: {path}")
            return MockBytesIO(self._store, path, mode)
        elif "+" in mode:
            # Read+write mode
            initial = self._store.get(path, b"")
            return MockBytesIO(self._store, path, mode, initial)
        else:
            # Default to read
            if path not in self._store:
                raise FileNotFoundError(f"Path not found: {path}")
            return MockBytesIO(self._store, path, mode, self._store[path])


class TestOverlayFileSystemReadOps:
    """Test OverlayFileSystem read operations: ls, exists, isfile, isdir."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        # Clear all MemoryFileSystem storage after tests
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    @pytest.fixture
    def upper_fs(self):
        """Create an upper MemoryFileSystem with test files."""
        fs = MemoryFileSystem()
        fs.pipe("/upper_file.txt", b"upper content")
        fs.mkdir("/shared_dir")
        fs.pipe("/shared_dir/shared.txt", b"shared in upper")
        return fs

    @pytest.fixture
    def lower_fs(self):
        """Create a lower MemoryFileSystem with test files."""
        fs = MemoryFileSystem()
        fs.pipe("/lower_file.txt", b"lower content")
        fs.mkdir("/lower_dir")
        fs.pipe("/shared_dir/lower_exclusive.txt", b"lower exclusive")
        return fs

    @pytest.fixture
    def overlay(self, upper_fs, lower_fs):
        """Create an OverlayFileSystem with upper and one lower layer."""
        return OverlayFileSystem(upper_fs, [lower_fs])

    @pytest.fixture
    def multi_layer_overlay(self):
        """Create an OverlayFileSystem with multiple lower layers."""
        upper = MemoryFileSystem()
        upper.pipe("/upper.txt", b"upper")

        lower1 = MemoryFileSystem()
        lower1.pipe("/lower1.txt", b"lower1")
        lower1.pipe("/shared.txt", b"shared1")

        lower2 = MemoryFileSystem()
        lower2.pipe("/lower2.txt", b"lower2")
        lower2.pipe("/shared.txt", b"shared2")

        return OverlayFileSystem(upper, [lower1, lower2])

    # ============== ls() tests ==============

    def test_ls_merges_multiple_layers(self, overlay):
        """ls() should merge directory listings from all layers."""
        result = overlay.ls("/")
        assert "upper_file.txt" in result
        assert "lower_file.txt" in result

    def test_ls_removes_duplicates_upper_visible(self, overlay):
        """ls() should show upper layer entry when duplicates exist."""
        # Create a file with same name in both layers
        overlay.upper.pipe("/lower_file.txt", b"upper overrides")
        result = overlay.ls("/")
        assert result.count("lower_file.txt") == 1

    def test_ls_returns_sorted_list(self, overlay):
        """ls() should return sorted list of entries."""
        result = overlay.ls("/")
        assert result == sorted(result)

    def test_ls_empty_directory(self):
        """ls() should handle empty directories."""
        upper = MemoryFileSystem()
        upper.mkdir("/empty_dir")
        lower = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        result = overlay.ls("/empty_dir")
        assert result == []

    def test_ls_nonexistent_directory(self):
        """ls() should return empty list for non-existent directory."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        result = overlay.ls("/nonexistent")
        assert result == []

    def test_ls_multi_layer_merge(self, multi_layer_overlay):
        """ls() should merge listings from multiple lower layers."""
        result = multi_layer_overlay.ls("/")
        assert "upper.txt" in result
        assert "lower1.txt" in result
        assert "lower2.txt" in result
        assert "shared.txt" in result

    def test_ls_shows_only_unique_entries(self, multi_layer_overlay):
        """ls() should show duplicate once with upper layer winning."""
        # shared.txt exists in lower1 and lower2, lower1 should win
        result = multi_layer_overlay.ls("/")
        assert result.count("shared.txt") == 1

    # ============== exists() tests ==============

    def test_exists_returns_true_if_in_upper(self, overlay):
        """exists() should return True for path in upper layer."""
        assert overlay.exists("/upper_file.txt") is True

    def test_exists_returns_true_if_in_lower(self, overlay):
        """exists() should return True for path in lower layer."""
        assert overlay.exists("/lower_file.txt") is True

    def test_exists_returns_false_if_not_in_any_layer(self, overlay):
        """exists() should return False for path not in any layer."""
        assert overlay.exists("/nonexistent.txt") is False

    def test_exists_works_with_directories(self, overlay):
        """exists() should return True for directories."""
        assert overlay.exists("/shared_dir") is True
        assert overlay.exists("/lower_dir") is True

    # ============== isfile() tests ==============

    def test_isfile_returns_true_for_file_in_upper(self, overlay):
        """isfile() should return True for file in upper layer."""
        assert overlay.isfile("/upper_file.txt") is True

    def test_isfile_returns_true_for_file_in_lower(self, overlay):
        """isfile() should return True for file in lower layer."""
        assert overlay.isfile("/lower_file.txt") is True

    def test_isfile_returns_false_for_directory(self, overlay):
        """isfile() should return False for directories."""
        assert overlay.isfile("/shared_dir") is False

    def test_isfile_returns_false_for_nonexistent(self, overlay):
        """isfile() should return False for non-existent paths."""
        assert overlay.isfile("/nonexistent.txt") is False

    # ============== isdir() tests ==============

    def test_isdir_returns_true_for_dir_in_upper(self, overlay):
        """isdir() should return True for directory in upper layer."""
        assert overlay.isdir("/shared_dir") is True

    def test_isdir_returns_true_for_dir_in_lower(self, overlay):
        """isdir() should return True for directory in lower layer."""
        assert overlay.isdir("/lower_dir") is True

    def test_isdir_returns_false_for_file(self, overlay):
        """isdir() should return False for files."""
        assert overlay.isdir("/upper_file.txt") is False

    def test_isdir_returns_false_for_nonexistent(self, overlay):
        """isdir() should return False for non-existent paths."""
        assert overlay.isdir("/nonexistent") is False


class TestOverlayFileSystemInfo:
    """Test OverlayFileSystem info() method."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage before and after each test."""
        # Clear before test (shared storage persists between tests)
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()
        yield
        # Clear after test
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    @pytest.fixture
    def upper_fs(self):
        """Create an upper MemoryFileSystem with test files."""
        fs = MemoryFileSystem()
        fs.pipe("/test.txt", b"upper content")
        fs.mkdir("/upperdir")
        return fs

    @pytest.fixture
    def lower_fs(self):
        """Create a lower MemoryFileSystem with test files."""
        fs = MemoryFileSystem()
        fs.pipe("/lower.txt", b"lower content")
        fs.mkdir("/lowerdir")
        return fs

    @pytest.fixture
    def overlay(self, upper_fs, lower_fs):
        """Create an OverlayFileSystem with upper and one lower layer."""
        return OverlayFileSystem(upper_fs, [lower_fs])

    @pytest.fixture
    def multi_layer_overlay(self, upper_fs):
        """Create an OverlayFileSystem with multiple lower layers."""
        lower1 = MemoryFileSystem()
        lower1.pipe("/layer1.txt", b"layer1 content")
        lower2 = MemoryFileSystem()
        lower2.pipe("/layer2.txt", b"layer2 content")
        return OverlayFileSystem(upper_fs, [lower1, lower2])

    def test_info_returns_dict(self, overlay):
        """info() should return a dictionary."""
        info = overlay.info("/test.txt")
        assert isinstance(info, dict)

    def test_info_has_layer_field(self, overlay):
        """info() result should have _layer field."""
        info = overlay.info("/test.txt")
        assert "_layer" in info

    def test_info_layer_upper_file(self, overlay):
        """_layer should be 0 for upper layer files."""
        info = overlay.info("/test.txt")
        assert info["_layer"] == 0

    def test_info_layer_from_upper_directory(self, overlay):
        """_layer should be 0 for upper layer directories."""
        info = overlay.info("/upperdir")
        assert info["_layer"] == 0

    def test_info_layer_value_is_int(self, overlay):
        """_layer should be an integer."""
        info = overlay.info("/test.txt")
        assert isinstance(info["_layer"], int)

    def test_info_nonexistent_path_raises_error(self, overlay):
        """info() should raise FileNotFoundError for non-existent paths."""
        with pytest.raises(FileNotFoundError):
            overlay.info("/nonexistent.txt")

    def test_info_has_standard_fields(self, overlay):
        """info() should include standard fsspec info fields."""
        info = overlay.info("/test.txt")
        # Standard fsspec info fields
        assert "name" in info
        assert "size" in info
        assert "type" in info

    def test_info_preserves_underlying_metadata(self, overlay):
        """info() should preserve all metadata from underlying filesystem."""
        info = overlay.info("/test.txt")
        # Should have original fields plus _layer
        assert "name" in info
        assert "size" in info
        assert info["size"] == len(b"upper content")
        assert "_layer" in info

    def test_info_upper_takes_precedence(self, upper_fs, lower_fs):
        """info() should return upper layer info when file exists in both."""
        # Create same file in both layers
        lower_fs.pipe("/test.txt", b"lower content")
        overlay = OverlayFileSystem(upper_fs, [lower_fs])

        info = overlay.info("/test.txt")
        # Should come from upper layer
        assert info["_layer"] == 0
        assert info["size"] == len(b"upper content")


class TestOverlayFileSystemSkeleton:
    """Test OverlayFileSystem skeleton and basic attributes."""

    def test_class_extends_abstract_filesystem(self):
        """OverlayFileSystem should extend AbstractFileSystem."""
        assert issubclass(OverlayFileSystem, AbstractFileSystem)

    def test_protocol_attribute(self):
        """OverlayFileSystem should have protocol = 'overlay'."""
        assert OverlayFileSystem.protocol == "overlay"

    def test_cachable_attribute(self):
        """OverlayFileSystem should have cachable = False."""
        assert OverlayFileSystem.cachable is False


class TestOverlayFileSystemInstantiation:
    """Test OverlayFileSystem instantiation with upper and lowers."""

    def test_instantiation_with_memory_filesystems(self):
        """Can instantiate with MemoryFileSystem as upper and lowers."""
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        assert overlay is not None
        assert isinstance(overlay, OverlayFileSystem)

    def test_upper_attribute_set(self):
        """Upper filesystem should be stored as instance attribute."""
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        assert overlay.upper is upper
        assert isinstance(overlay.upper, AbstractFileSystem)

    def test_lowers_attribute_set(self):
        """Lower filesystems should be stored as instance attribute."""
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem(), MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        assert overlay.lowers is lowers
        assert len(overlay.lowers) == 2
        for fs in overlay.lowers:
            assert isinstance(fs, AbstractFileSystem)

    def test_instantiation_with_empty_lowers(self):
        """Can instantiate with empty lowers list."""
        upper = MemoryFileSystem()
        lowers: list[MemoryFileSystem] = []
        overlay = OverlayFileSystem(upper, lowers)

        assert overlay.upper is upper
        assert overlay.lowers == []

    def test_protocol_access_on_instance(self):
        """Can access protocol attribute on instance."""
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        assert overlay.protocol == "overlay"

    def test_cachable_access_on_instance(self):
        """Can access cachable attribute on instance."""
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        assert overlay.cachable is False

    def test_instance_is_abstract_filesystem(self):
        """Instance should be instance of AbstractFileSystem."""
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        assert isinstance(overlay, AbstractFileSystem)


class TestPathNormalization:
    """Tests for path normalization utility."""

    def test_normalize_path_adds_leading_slash(self) -> None:
        """Test that path without leading slash gets one added."""
        assert _normalize_path("test.txt") == "/test.txt"

    def test_normalize_path_preserves_leading_slash(self) -> None:
        """Test that path with leading slash is unchanged."""
        assert _normalize_path("/test.txt") == "/test.txt"

    def test_normalize_path_removes_trailing_slash(self) -> None:
        """Test that trailing slash is removed."""
        assert _normalize_path("/test/") == "/test"

    def test_normalize_path_preserves_root(self) -> None:
        """Test that root path '/' is preserved."""
        assert _normalize_path("/") == "/"

    def test_normalize_path_handles_deep_paths(self) -> None:
        """Test normalization of deep paths."""
        assert _normalize_path("a/b/c.txt") == "/a/b/c.txt"
        assert _normalize_path("/a/b/c.txt") == "/a/b/c.txt"
        assert _normalize_path("/a/b/c/") == "/a/b/c"


class TestOverlayResolve:
    """Tests for OverlayFileSystem._resolve() method."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        # Clear all MemoryFileSystem storage after tests
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_resolve_file_in_upper_layer(self) -> None:
        """Test file exists in upper layer resolves to upper."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "upper content")

        overlay = OverlayFileSystem(upper, [])

        result = overlay._resolve("/test.txt")

        assert result is not None
        fs, path, idx = result
        assert fs is upper
        assert path == "/test.txt"
        assert idx == 0

    def test_resolve_file_in_lower_layer_only(self) -> None:
        """Test file exists in lower layer only resolves to lower."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        result = overlay._resolve("/test.txt")

        assert result is not None
        fs, path, idx = result
        assert fs is lower
        assert path == "/test.txt"
        assert idx == 1

    def test_resolve_prefers_upper_over_lower(self) -> None:
        """Test file exists in multiple layers resolves to upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()

        upper.write_text("/test.txt", "upper content")
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        result = overlay._resolve("/test.txt")

        assert result is not None
        fs, path, idx = result
        assert fs is upper
        assert idx == 0

    def test_resolve_nonexistent_file_returns_none(self) -> None:
        """Test non-existent file returns None."""
        upper = MockFileSystem()
        lower = MockFileSystem()

        overlay = OverlayFileSystem(upper, [lower])

        result = overlay._resolve("/nonexistent.txt")

        assert result is None

    def test_resolve_deep_path(self) -> None:
        """Test resolution of deep paths works correctly."""
        upper = MockFileSystem()
        upper.mkdir("/a")
        upper.mkdir("/a/b")
        upper.write_text("/a/b/c.txt", "deep content")

        overlay = OverlayFileSystem(upper, [])

        result = overlay._resolve("/a/b/c.txt")

        assert result is not None
        fs, path, idx = result
        assert fs is upper
        assert path == "/a/b/c.txt"
        assert idx == 0

    def test_resolve_path_without_leading_slash(self) -> None:
        """Test path normalization without leading slash."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "content")

        overlay = OverlayFileSystem(upper, [])

        result = overlay._resolve("test.txt")

        assert result is not None
        fs, path, idx = result
        assert path == "/test.txt"

    def test_resolve_multiple_lower_layers_priority(self) -> None:
        """Test resolution checks lower layers in priority order."""
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()
        lower3 = MockFileSystem()
        upper = MockFileSystem()

        # File exists only in lower2 (second lower layer)
        lower2.write_text("/test.txt", "layer2 content")

        overlay = OverlayFileSystem(upper, [lower1, lower2, lower3])

        result = overlay._resolve("/test.txt")

        assert result is not None
        fs, path, idx = result
        assert fs is lower2
        assert idx == 2  # layer_index: 0=upper, 1=lower1, 2=lower2

    def test_resolve_first_lower_with_file_wins(self) -> None:
        """Test first lower layer with file wins for shared files."""
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()

        # File exists in both lower layers
        lower1.write_text("/shared.txt", "lower1")
        lower2.write_text("/shared.txt", "lower2")

        overlay = OverlayFileSystem(MockFileSystem(), [lower1, lower2])

        result = overlay._resolve("/shared.txt")

        assert result is not None
        fs, path, idx = result
        # Should resolve to first lower (lower1), not second (lower2)
        assert fs is lower1
        assert idx == 1

    def test_resolve_directory_in_upper(self) -> None:
        """Test directory resolution in upper layer."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")
        upper.write_text("/testdir/file.txt", "content")

        overlay = OverlayFileSystem(upper, [])

        result = overlay._resolve("/testdir")

        assert result is not None
        fs, path, idx = result
        assert fs is upper
        assert path == "/testdir"
        assert idx == 0

    def test_resolve_directory_prefers_upper(self) -> None:
        """Test directory resolution prefers upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()

        upper.mkdir("/testdir")
        lower.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [lower])

        result = overlay._resolve("/testdir")

        assert result is not None
        fs, path, idx = result
        assert fs is upper
        assert idx == 0


class TestOverlayGetLayerFs:
    """Tests for OverlayFileSystem._get_layer_fs() helper."""

    def test_get_layer_fs_returns_upper_for_index_zero(self) -> None:
        """Test layer index 0 returns upper filesystem."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        result = overlay._get_layer_fs(0)

        assert result is upper

    def test_get_layer_fs_returns_first_lower(self) -> None:
        """Test layer index 1 returns first lower."""
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()
        overlay = OverlayFileSystem(MockFileSystem(), [lower1, lower2])

        result = overlay._get_layer_fs(1)

        assert result is lower1

    def test_get_layer_fs_returns_second_lower(self) -> None:
        """Test layer index 2 returns second lower."""
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()
        overlay = OverlayFileSystem(MockFileSystem(), [lower1, lower2])

        result = overlay._get_layer_fs(2)

        assert result is lower2

    def test_get_layer_fs_raises_for_out_of_range(self) -> None:
        """Test out of range index raises IndexError."""
        overlay = OverlayFileSystem(MockFileSystem(), [])

        with pytest.raises(IndexError, match="Layer index 1 out of range"):
            overlay._get_layer_fs(1)

    def test_get_layer_fs_raises_for_negative_index(self) -> None:
        """Test negative index raises IndexError."""
        overlay = OverlayFileSystem(MockFileSystem(), [])

        with pytest.raises(IndexError, match="Layer index -1 out of range"):
            overlay._get_layer_fs(-1)


class TestOverlayExistsInLayer:
    """Tests for OverlayFileSystem._exists_in_layer() helper."""

    def test_exists_in_layer_returns_true_for_file(self) -> None:
        """Test exists check for existing file."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "content")

        overlay = OverlayFileSystem(upper, [])

        assert overlay._exists_in_layer(upper, "/test.txt") is True

    def test_exists_in_layer_returns_true_for_directory(self) -> None:
        """Test exists check for existing directory."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [])

        assert overlay._exists_in_layer(upper, "/testdir") is True

    def test_exists_in_layer_returns_false_for_nonexistent(self) -> None:
        """Test exists check for non-existent path."""
        upper = MockFileSystem()

        overlay = OverlayFileSystem(upper, [])

        assert overlay._exists_in_layer(upper, "/nonexistent") is False


class TestOverlayNeedsCopyUp:
    """Tests for OverlayFileSystem._needs_copy_up() method."""

    def test_needs_copy_up_returns_true_for_lower_only_file(self) -> None:
        """Test _needs_copy_up returns True when file exists in lower only."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        assert overlay._needs_copy_up("/test.txt") is True

    def test_needs_copy_up_returns_false_for_upper_file(self) -> None:
        """Test _needs_copy_up returns False when file exists in upper."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "upper content")
        lower = MockFileSystem()

        overlay = OverlayFileSystem(upper, [lower])

        assert overlay._needs_copy_up("/test.txt") is False

    def test_needs_copy_up_returns_false_for_nonexistent(self) -> None:
        """Test _needs_copy_up returns False when file doesn't exist."""
        upper = MockFileSystem()
        lower = MockFileSystem()

        overlay = OverlayFileSystem(upper, [lower])

        assert overlay._needs_copy_up("/nonexistent.txt") is False

    def test_needs_copy_up_prefers_upper_over_lower(self) -> None:
        """Test file exists in both layers returns False (upper takes precedence)."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "upper content")
        lower = MockFileSystem()
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        assert overlay._needs_copy_up("/test.txt") is False

    def test_needs_copy_up_multiple_lower_layers(self) -> None:
        """Test _needs_copy_up with multiple lower layers."""
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()
        lower2.write_text("/only_in_lower2.txt", "content")

        overlay = OverlayFileSystem(MockFileSystem(), [lower1, lower2])

        assert overlay._needs_copy_up("/only_in_lower2.txt") is True


class TestOverlayEnsureParentDirs:
    """Tests for OverlayFileSystem._ensure_parent_dirs() method."""

    def test_ensure_parent_dirs_creates_single_parent(self) -> None:
        """Test parent directory creation for simple path."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._ensure_parent_dirs("/subdir/file.txt")

        assert upper.isdir("/subdir") is True

    def test_ensure_parent_dirs_creates_nested_parents(self) -> None:
        """Test recursive parent directory creation."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._ensure_parent_dirs("/a/b/c/file.txt")

        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        assert upper.isdir("/a/b/c") is True

    def test_ensure_parent_dirs_no_parents_for_root(self) -> None:
        """Test root path doesn't create any directories."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._ensure_parent_dirs("/")

        # Only root exists (created by default)
        assert upper.isdir("/") is True
        assert len(upper._dirs) == 1

    def test_ensure_parent_dirs_no_parents_for_single_component(self) -> None:
        """Test single component path doesn't create extra directories."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._ensure_parent_dirs("/file.txt")

        assert "/" in upper._dirs

    def test_ensure_parent_dirs_idempotent(self) -> None:
        """Test calling twice is safe (idempotent)."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._ensure_parent_dirs("/a/b/c/file.txt")
        overlay._ensure_parent_dirs("/a/b/c/file.txt")

        assert upper.isdir("/a/b/c") is True


class TestOverlayCopyUp:
    """Tests for OverlayFileSystem._copy_up() COW method."""

    def test_copy_up_copies_file_from_lower_to_upper(self) -> None:
        """Test basic copy_up from lower to upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])
        overlay._copy_up("/test.txt")

        # Verify file exists in upper layer
        assert upper.isfile("/test.txt") is True
        # Verify content is correct
        assert upper._store["/test.txt"] == b"lower content"

    def test_copy_up_creates_parent_directories(self) -> None:
        """Test parent directories are created in upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/a/b")
        lower.write_text("/a/b/c.txt", "deep content")

        overlay = OverlayFileSystem(upper, [lower])
        overlay._copy_up("/a/b/c.txt")

        # Verify directories exist in upper layer
        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        # Verify file exists
        assert upper.isfile("/a/b/c.txt") is True

    def test_copy_up_lower_layer_unchanged(self) -> None:
        """Test lower layer is not modified after copy_up."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/test.txt", "original")
        original_store = lower._store.copy()
        original_dirs = lower._dirs.copy()

        overlay = OverlayFileSystem(upper, [lower])
        overlay._copy_up("/test.txt")

        # Verify lower layer unchanged
        assert lower._store == original_store
        assert lower._dirs == original_dirs
        assert lower._store["/test.txt"] == b"original"

    def test_copy_up_preserves_binary_content(self) -> None:
        """Test binary content is preserved exactly."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        binary_data = bytes([0x00, 0x01, 0xFF, 0xFE, 0xAB, 0xCD])
        lower.pipe("/binary.bin", binary_data)

        overlay = OverlayFileSystem(upper, [lower])
        overlay._copy_up("/binary.bin")

        # Verify exact binary content
        assert upper._store["/binary.bin"] == binary_data

    def test_copy_up_raises_for_nonexistent_file(self) -> None:
        """Test copy_up raises FileNotFoundError for non-existent file."""
        upper = MockFileSystem()
        lower = MockFileSystem()

        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(FileNotFoundError, match="Path not found"):
            overlay._copy_up("/nonexistent.txt")

    def test_copy_up_nothing_for_upper_only_file(self) -> None:
        """Test copy_up does nothing when file already in upper layer."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "upper content")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        # Should not raise
        overlay._copy_up("/test.txt")

        # Content should remain unchanged
        assert upper._store["/test.txt"] == b"upper content"

    def test_copy_up_raises_for_directory(self) -> None:
        """Test copy_up raises IsADirectoryError for directories."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            overlay._copy_up("/testdir")

    def test_copy_up_path_normalization(self) -> None:
        """Test copy_up handles path without leading slash."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/test.txt", "content")

        overlay = OverlayFileSystem(upper, [lower])
        overlay._copy_up("test.txt")  # Without leading slash

        # Should create normalized path
        assert upper.isfile("/test.txt") is True


class TestOverlayCopyUpQAScenarios:
    """QA scenario tests for Copy-on-Write operations."""

    def test_cow_copies_file_to_upper_layer(self) -> None:
        """
        QA Scenario: COW copies file to upper layer

        Steps:
            1. lower = MockFileSystem()
            2. lower.write_text("/test.txt", "content")
            3. overlay = OverlayFileSystem(upper, [lower])
            4. overlay._copy_up("/test.txt")
            5. assert upper.exists("/test.txt")
            6. assert lower.read_text("/test.txt") == "content" (unchanged)

        Expected: File copied to upper, lower unchanged
        """
        # Step 1 & 2: Create lower with file
        lower = MockFileSystem()
        lower.write_text("/test.txt", "content")

        # Step 3: Create overlay with empty upper
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Step 4: Copy up
        overlay._copy_up("/test.txt")

        # Step 5: Verify file in upper
        assert upper.exists("/test.txt") is True, (
            "File should exist in upper after copy_up"
        )

        # Step 6: Verify lower unchanged
        assert lower._store["/test.txt"] == b"content", (
            "Lower layer should be unchanged"
        )

    def test_cow_preserves_binary_content(self) -> None:
        """
        QA Scenario: COW preserves binary content exactly

        Steps:
            1. Create binary file in lower (with non-text bytes)
            2. Copy up to upper
            3. Verify bytes are identical bit-for-bit

        Expected: Binary content preserved exactly
        """
        lower = MockFileSystem()
        upper = MockFileSystem()
        binary_content = bytes(range(256))  # All byte values 0-255
        lower.pipe("/all_bytes.bin", binary_content)

        overlay = OverlayFileSystem(upper, [lower])
        overlay._copy_up("/all_bytes.bin")

        assert upper._store["/all_bytes.bin"] == binary_content

    def test_cow_creates_parent_directories_recursively(self) -> None:
        """
        QA Scenario: COW creates all parent directories

        Steps:
            1. lower = MockFileSystem()
            2. Create nested file in lower
            3. overlay._copy_up("/deep/path/to/file.txt")
            4. Verify all parent directories exist in upper

        Expected: All parent directories created in upper
        """
        lower = MockFileSystem()
        lower.mkdir("/deep")
        lower.mkdir("/deep/path")
        lower.mkdir("/deep/path/to")
        lower.write_text("/deep/path/to/file.txt", "deep text")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay._copy_up("/deep/path/to/file.txt")

        assert upper.isdir("/deep") is True
        assert upper.isdir("/deep/path") is True
        assert upper.isdir("/deep/path/to") is True
        assert upper.isfile("/deep/path/to/file.txt") is True


class TestOverlayResolveQAScenarios:
    """QA scenario tests for multi-layer path resolution."""

    def test_multi_layer_resolution_scenario(self) -> None:
        """
        QA Scenario: Multi-layer resolution

        Steps:
            1. upper = MockFileSystem()
            2. lower = MockFileSystem()
            3. lower.write_text("/test.txt", "lower")
            4. upper.write_text("/test.txt", "upper")
            5. overlay = OverlayFileSystem(upper, [lower])
            6. fs, path, idx = overlay._resolve("/test.txt")

        Expected: idx == 0 (upper layer)
        """
        # Step 1 & 2: Create filesystems
        upper = MockFileSystem()
        lower = MockFileSystem()

        # Step 3 & 4: Write same file to both
        lower.write_text("/test.txt", "lower")
        upper.write_text("/test.txt", "upper")

        # Step 5: Create overlay
        overlay = OverlayFileSystem(upper, [lower])

        # Step 6: Resolve path
        result = overlay._resolve("/test.txt")

        # Expected: Should resolve to upper layer
        assert result is not None
        fs, path, idx = result
        assert idx == 0, "File should resolve to upper layer (index 0)"
        assert fs is upper

    def test_resolve_through_multiple_layers_scenario(self) -> None:
        """
        QA Scenario: Resolution through multiple lower layers

        Steps:
            1. upper = MockFileSystem()
            2. lower1 = MockFileSystem()
            3. lower2 = MockFileSystem()
            4. lower2.write_text("/only_in_lower2.txt", "content")
            5. overlay = OverlayFileSystem(upper, [lower1, lower2])
            6. result = overlay._resolve("/only_in_lower2.txt")

        Expected: result.idx == 2 (second lower layer)
        """
        upper = MockFileSystem()
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()

        # File only exists in second lower layer
        lower2.write_text("/only_in_lower2.txt", "content")

        overlay = OverlayFileSystem(upper, [lower1, lower2])
        result = overlay._resolve("/only_in_lower2.txt")

        assert result is not None
        fs, path, idx = result
        assert idx == 2, "Should resolve to second lower layer"
        assert fs is lower2

    def test_resolve_not_found_scenario(self) -> None:
        """
        QA Scenario: Resolution returns None for not found

        Steps:
            1. overlay = OverlayFileSystem(MockFileSystem(), [MockFileSystem()])
            2. result = overlay._resolve("/does_not_exist.txt")

        Expected: result is None
        """
        overlay = OverlayFileSystem(MockFileSystem(), [MockFileSystem()])
        result = overlay._resolve("/does_not_exist.txt")

        assert result is None, "Non-existent file should return None"

    def test_resolve_deep_path_scenario(self) -> None:
        """
        QA Scenario: Deep path resolution

        Steps:
            1. upper = MockFileSystem()
            2. upper.mkdir("/a")
            3. upper.mkdir("/a/b")
            4. upper.write_text("/a/b/c/d.txt", "deep")
            5. overlay = OverlayFileSystem(upper, [])
            6. result = overlay._resolve("/a/b/c/d.txt")

        Expected: result.path == "/a/b/c/d.txt", result.idx == 0
        """
        upper = MockFileSystem()
        upper.mkdir("/a")
        upper.mkdir("/a/b")
        upper.mkdir("/a/b/c")
        upper.write_text("/a/b/c/d.txt", "deep")

        overlay = OverlayFileSystem(upper, [])
        result = overlay._resolve("/a/b/c/d.txt")

        assert result is not None
        fs, path, idx = result
        assert path == "/a/b/c/d.txt"
        assert idx == 0

    def test_path_normalization_resolution_scenario(self) -> None:
        """
        QA Scenario: Path normalization in resolution

        Steps:
            1. upper = MockFileSystem()
            2. upper.write_text("/test.txt", "content")
            3. overlay = OverlayFileSystem(upper, [])
            4. result1 = overlay._resolve("test.txt")
            5. result2 = overlay._resolve("/test.txt")

        Expected: Both resolve to same path "/test.txt"
        """
        upper = MockFileSystem()
        upper.write_text("/test.txt", "content")

        overlay = OverlayFileSystem(upper, [])

        result1 = overlay._resolve("test.txt")
        result2 = overlay._resolve("/test.txt")

        assert result1 is not None
        assert result2 is not None

        fs1, path1, idx1 = result1
        fs2, path2, idx2 = result2

        assert path1 == "/test.txt"
        assert path2 == "/test.txt"
        assert fs1 is fs2
        assert idx1 == idx2

    def test_three_layer_priority_resolution(self) -> None:
        """
        QA Scenario: Three layer priority test

        Steps:
            1. upper = MockFileSystem()
            2. lower1 = MockFileSystem()
            3. lower2 = MockFileSystem()
            4. lower2.write_text("/priority.txt", "lower2")
            5. lower1.write_text("/priority.txt", "lower1")
            6. overlay = OverlayFileSystem(upper, [lower1, lower2])
            7. result = overlay._resolve("/priority.txt")

        Expected: result.idx == 1 (found in lower1 first)
        """
        upper = MockFileSystem()
        lower1 = MockFileSystem()
        lower2 = MockFileSystem()

        # Same file in both lower layers
        lower2.write_text("/priority.txt", "lower2")
        lower1.write_text("/priority.txt", "lower1")

        overlay = OverlayFileSystem(upper, [lower1, lower2])
        result = overlay._resolve("/priority.txt")

        assert result is not None
        fs, path, idx = result
        assert idx == 1, "Should find in first lower layer (lower1), not lower2"
        assert fs is lower1


class TestOverlayMkdir:
    """Tests for OverlayFileSystem.mkdir() method."""

    def test_mkdir_creates_directory_in_upper(self) -> None:
        """mkdir() should create directory in upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.mkdir("/newdir")

        assert upper.isdir("/newdir") is True

    def test_mkdir_raises_if_parent_missing(self) -> None:
        """mkdir() should raise if parent doesn't exist (create_parents=False)."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(FileNotFoundError, match="Parent directory does not exist"):
            overlay.mkdir("/parent/child", create_parents=False)

    def test_mkdir_with_create_parents_creates_parents(self) -> None:
        """mkdir() with create_parents=True should create all parents."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.mkdir("/a/b/c", create_parents=True)

        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        assert upper.isdir("/a/b/c") is True

    def test_mkdir_raises_if_directory_exists_in_upper(self) -> None:
        """mkdir() should raise FileExistsError if directory exists in upper."""
        upper = MockFileSystem()
        upper.mkdir("/existing")
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(FileExistsError, match="Directory already exists"):
            overlay.mkdir("/existing")

    def test_mkdir_allows_directory_in_lower(self) -> None:
        """mkdir() should allow creating same directory if only in lower."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/existing_in_lower")
        overlay = OverlayFileSystem(upper, [lower])

        # Should succeed - creating in upper layer
        overlay.mkdir("/existing_in_lower")

        # Now should exist in upper
        assert upper.isdir("/existing_in_lower") is True

    def test_mkdir_path_normalization(self) -> None:
        """mkdir() should normalize paths."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay.mkdir("newdir")  # Without leading slash

        assert upper.isdir("/newdir") is True


class TestOverlayMakedirs:
    """Tests for OverlayFileSystem.makedirs() method."""

    def test_makedirs_creates_nested_directories(self) -> None:
        """makedirs() should create directory and all parents."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.makedirs("/a/b/c/d")

        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        assert upper.isdir("/a/b/c") is True
        assert upper.isdir("/a/b/c/d") is True

    def test_makedirs_with_exist_ok_does_not_raise(self) -> None:
        """makedirs() with exist_ok=True should not raise if exists."""
        upper = MockFileSystem()
        upper.mkdir("/existing")
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Should not raise
        overlay.makedirs("/existing", exist_ok=True)

        assert upper.isdir("/existing") is True

    def test_makedirs_raises_if_exists_and_exist_ok_false(self) -> None:
        """makedirs() should raise if exists and exist_ok=False."""
        upper = MockFileSystem()
        upper.mkdir("/existing")
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(FileExistsError, match="Directory already exists"):
            overlay.makedirs("/existing", exist_ok=False)

    def test_makedirs_only_creates_in_upper_not_lower(self) -> None:
        """makedirs() should only create directories in upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.makedirs("/newdir/subdir")

        # Upper should have directories
        assert upper.isdir("/newdir") is True
        assert upper.isdir("/newdir/subdir") is True

        # Lower should not have directories
        assert lower.isdir("/newdir") is False
        assert lower.isdir("/newdir/subdir") is False

    def test_makedirs_path_normalization(self) -> None:
        """makedirs() should normalize paths."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay.makedirs("a/b/c")  # Without leading slash

        assert upper.isdir("/a/b/c") is True


class TestOverlayMkdirQA:
    """QA scenario tests for directory creation."""

    def test_directory_creation_in_upper_layer(self) -> None:
        """
        QA Scenario: Directory creation in upper layer

        Steps:
            1. overlay = OverlayFileSystem(upper, [lower])
            2. overlay.mkdir("/newdir")
            3. assert upper.isdir("/newdir")
            4. overlay.makedirs("/a/b/c")
            5. assert upper.isdir("/a/b/c")

        Expected: Directories created in upper only
        """
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Step 2: Create single directory
        overlay.mkdir("/newdir")

        # Step 3: Verify in upper
        assert upper.isdir("/newdir") is True, "Directory should exist in upper"

        # Step 4: Create nested directories
        overlay.makedirs("/a/b/c")

        # Step 5: Verify all nested directories in upper
        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        assert upper.isdir("/a/b/c") is True

        # Verify lower is never modified
        assert not lower._dirs.difference({"/"}), "Lower should only have root"

    def test_mkdir_creates_only_in_upper_not_lower(self) -> None:
        """
        QA Scenario: mkdir only creates in upper layer

        Steps:
            1. lower = MockFileSystem(); lower.mkdir("/lowerdir")
            2. upper = MockFileSystem()
            3. overlay = OverlayFileSystem(upper, [lower])
            4. overlay.mkdir("/newdir")
            5. assert upper.isdir("/newdir")
            6. assert not lower.isdir("/newdir")

        Expected: Directory only in upper, lower unchanged
        """
        lower = MockFileSystem()
        lower.mkdir("/lowerdir")
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.mkdir("/newdir")

        assert upper.isdir("/newdir") is True
        assert lower.isdir("/newdir") is False
        assert "/lowerdir" in lower._dirs  # Original lower unchanged

    def test_makedirs_with_exist_ok_scenario(self) -> None:
        """
        QA Scenario: makedirs with exist_ok

        Steps:
            1. upper = MockFileSystem(); upper.mkdir("/existing")
            2. overlay = OverlayFileSystem(upper, [])
            3. overlay.makedirs("/existing", exist_ok=True)  # Should not raise
            4. with pytest.raises: overlay.makedirs("/existing", exist_ok=False)

        Expected: exist_ok=True passes, exist_ok=False raises
        """
        upper = MockFileSystem()
        upper.mkdir("/existing")
        overlay = OverlayFileSystem(upper, [])

        # Should not raise
        overlay.makedirs("/existing", exist_ok=True)

        # Should raise
        with pytest.raises(FileExistsError):
            overlay.makedirs("/existing", exist_ok=False)


class TestIsWriteMode:
    """Tests for OverlayFileSystem._is_write_mode() helper."""

    def test_is_write_mode_detects_write(self) -> None:
        """Test 'w' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("w") is True

    def test_is_write_mode_detects_write_binary(self) -> None:
        """Test 'wb' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("wb") is True

    def test_is_write_mode_detects_append(self) -> None:
        """Test 'a' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("a") is True

    def test_is_write_mode_detects_append_binary(self) -> None:
        """Test 'ab' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("ab") is True

    def test_is_write_mode_detects_exclusive(self) -> None:
        """Test 'x' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("x") is True

    def test_is_write_mode_detects_read_write_plus(self) -> None:
        """Test 'r+' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("r+") is True

    def test_is_write_mode_detects_write_plus(self) -> None:
        """Test 'w+' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("w+") is True

    def test_is_write_mode_detects_append_plus(self) -> None:
        """Test 'a+' mode is detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("a+") is True

    def test_is_write_mode_read_is_not_write(self) -> None:
        """Test 'r' mode is NOT detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("r") is False

    def test_is_write_mode_read_binary_is_not_write(self) -> None:
        """Test 'rb' mode is NOT detected as write."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._is_write_mode("rb") is False


class TestOverlayOpenRead:
    """Tests for OverlayFileSystem.open() in read modes."""

    def test_open_read_reads_from_upper_layer(self) -> None:
        """Test read mode reads from upper layer if file exists there."""
        upper = MockFileSystem()
        upper.write_text("/test.txt", "upper content")
        lower = MockFileSystem()
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/test.txt", "r") as f:
            content = f.read()

        assert content == "upper content"

    def test_open_read_reads_from_lower_layer(self) -> None:
        """Test read mode reads from lower layer if file only there."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/test.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/test.txt", "r") as f:
            content = f.read()

        assert content == "lower content"

    def test_open_read_binary_mode(self) -> None:
        """Test binary read mode works."""
        upper = MockFileSystem()
        upper.pipe("/binary.bin", b"\x00\x01\x02\x03")

        overlay = OverlayFileSystem(upper, [])

        with overlay.open("/binary.bin", "rb") as f:
            content = f.read()

        assert content == b"\x00\x01\x02\x03"

    def test_open_read_raises_for_nonexistent(self) -> None:
        """Test read mode raises FileNotFoundError for non-existent file."""
        overlay = OverlayFileSystem(MockFileSystem(), [MockFileSystem()])

        with pytest.raises(FileNotFoundError):
            overlay.open("/nonexistent.txt", "r")

    def test_open_read_raises_for_directory(self) -> None:
        """Test read mode raises IsADirectoryError for directories."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(IsADirectoryError):
            overlay.open("/testdir", "r")


class TestOverlayOpenWrite:
    """Tests for OverlayFileSystem.open() in write modes."""

    def test_open_write_creates_new_file_in_upper(self) -> None:
        """Test write mode creates new file in upper layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()

        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/new_file.txt", "w") as f:
            f.write("new content")

        # File should be in upper layer
        assert upper.isfile("/new_file.txt") is True
        assert upper._store["/new_file.txt"] == b"new content"

    def test_open_write_triggers_cow_for_lower_file(self) -> None:
        """Test write mode triggers COW when file exists in lower layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/existing.txt", "original content")

        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/existing.txt", "w") as f:
            f.write("modified content")

        # File should be copied to upper and modified
        assert upper.isfile("/existing.txt") is True
        assert upper._store["/existing.txt"] == b"modified content"
        # Lower should be unchanged
        assert lower._store["/existing.txt"] == b"original content"

    def test_open_write_preserves_lower_when_file_in_upper(self) -> None:
        """Test write mode doesn't affect lower when file already in upper."""
        upper = MockFileSystem()
        upper.write_text("/existing.txt", "upper content")
        lower = MockFileSystem()
        lower.write_text("/existing.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])
        original_lower = lower._store.copy()

        with overlay.open("/existing.txt", "w") as f:
            f.write("modified")

        # Lower should be unchanged
        assert lower._store == original_lower

    def test_open_write_creates_parent_directories(self) -> None:
        """Test write mode creates parent directories in upper layer."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        with overlay.open("/a/b/c/deep.txt", "w") as f:
            f.write("deep content")

        # Parent directories should exist
        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        assert upper.isdir("/a/b/c") is True
        assert upper.isfile("/a/b/c/deep.txt") is True


class TestOverlayOpenAppend:
    """Tests for OverlayFileSystem.open() in append modes."""

    def test_open_append_creates_new_file(self) -> None:
        """Test append mode creates new file if doesn't exist."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        with overlay.open("/new_file.txt", "a") as f:
            f.write("appended")

        assert upper.isfile("/new_file.txt") is True
        assert upper._store["/new_file.txt"] == b"appended"

    def test_open_append_triggers_cow_for_lower_file(self) -> None:
        """Test append mode triggers COW when file exists in lower layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/existing.txt", "original")

        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/existing.txt", "a") as f:
            f.write(" - appended")

        # File should be copied to upper with appended content
        assert upper.isfile("/existing.txt") is True
        assert upper._store["/existing.txt"] == b"original - appended"
        # Lower should be unchanged
        assert lower._store["/existing.txt"] == b"original"


class TestOverlayOpenUpdateModes:
    """Tests for OverlayFileSystem.open() in read+write update modes."""

    def test_open_read_plus_triggers_cow(self) -> None:
        """Test r+ mode triggers COW for lower layer file."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/existing.txt", "original content")

        overlay = OverlayFileSystem(upper, [lower])

        # r+ triggers COW
        with overlay.open("/existing.txt", "r+") as f:
            f.write("modified")

        # File should be in upper layer
        assert upper.isfile("/existing.txt") is True
        assert upper._store["/existing.txt"].startswith(b"modified")

    def test_open_write_plus_creates_new_file(self) -> None:
        """Test w+ mode creates new file."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        with overlay.open("/new_file.txt", "w+") as f:
            f.write("new content")

        assert upper.isfile("/new_file.txt") is True
        assert upper._store["/new_file.txt"] == b"new content"


class TestOverlayOpenQAScenarios:
    """QA scenario tests for open() operations."""

    def test_write_mode_triggers_cow_scenario(self) -> None:
        """
        QA Scenario: Write mode triggers COW

        Steps:
            1. lower.write_text("/file.txt", "original")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. with overlay.open("/file.txt", "w") as f:
                 f.write("modified")
            4. assert upper.read_text("/file.txt") == "modified"
            5. assert lower.read_text("/file.txt") == "original"

        Expected: COW triggered, upper modified, lower unchanged
        """
        # Step 1: Create file in lower layer
        lower = MockFileSystem()
        lower.write_text("/file.txt", "original")

        # Step 2: Create overlay with empty upper
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Step 3: Open in write mode and modify
        with overlay.open("/file.txt", "w") as f:
            f.write("modified")

        # Step 4: Verify upper has modified content
        assert upper._store["/file.txt"] == b"modified", (
            "Upper should have modified content"
        )

        # Step 5: Verify lower unchanged
        assert lower._store["/file.txt"] == b"original", "Lower should be unchanged"

    def test_open_write_creates_new_file_in_upper(self) -> None:
        """
        QA Scenario: open("w") creates new file in upper

        Steps:
            1. overlay = OverlayFileSystem(upper, [lower])
            2. with overlay.open("/new_file.txt", "w") as f:
                 f.write("new content")
            3. assert upper.exists("/new_file.txt")
            4. assert lower.exists("/new_file.txt") is False

        Expected: New file only in upper layer
        """
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/new_file.txt", "w") as f:
            f.write("new content")

        assert upper.isfile("/new_file.txt") is True
        assert lower.exists("/new_file.txt") is False

    def test_open_append_preserves_existing_content(self) -> None:
        """
        QA Scenario: open("a") appends to existing file

        Steps:
            1. upper.write_text("/file.txt", "existing")
            2. overlay = OverlayFileSystem(upper, [])
            3. with overlay.open("/file.txt", "a") as f:
                 f.write(" - appended")
            4. assert upper.read_text("/file.txt") == "existing - appended"

        Expected: Content appended, original preserved
        """
        upper = MockFileSystem()
        upper.write_text("/file.txt", "existing")
        overlay = OverlayFileSystem(upper, [])

        with overlay.open("/file.txt", "a") as f:
            f.write(" - appended")

        assert upper._store["/file.txt"] == b"existing - appended"

    def test_open_read_mode_from_resolved_layer(self) -> None:
        """
        QA Scenario: open("r") reads from resolved layer

        Steps:
            1. upper.write_text("/upper_only.txt", "upper content")
            2. lower.write_text("/lower_only.txt", "lower content")
            3. overlay = OverlayFileSystem(upper, [lower])
            4. upper_content = overlay.open("/upper_only.txt", "r").read()
            5. lower_content = overlay.open("/lower_only.txt", "r").read()

        Expected: Read from correct layer in each case
        """
        upper = MockFileSystem()
        upper.write_text("/upper_only.txt", "upper content")
        lower = MockFileSystem()
        lower.write_text("/lower_only.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/upper_only.txt", "r") as f:
            upper_content = f.read()

        with overlay.open("/lower_only.txt", "r") as f:
            lower_content = f.read()

        assert upper_content == "upper content"
        assert lower_content == "lower content"

    def test_binary_modes_preserve_content(self) -> None:
        """
        QA Scenario: Binary modes preserve content exactly

        Steps:
            1. Create binary file in lower
            2. overlay.open("/binary.bin", "rb") to read
            3. overlay.open("/binary.bin", "wb") to write new
            4. Verify bytes identical

        Expected: Binary content preserved bit-for-bit
        """
        lower = MockFileSystem()
        binary_data = bytes(range(256))
        lower.pipe("/binary.bin", binary_data)

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Read from lower via overlay
        with overlay.open("/binary.bin", "rb") as f:
            read_content = f.read()

        assert read_content == binary_data

        # Write new binary to upper
        new_binary = bytes(reversed(range(256)))
        with overlay.open("/new_binary.bin", "wb") as f:
            f.write(new_binary)

        assert upper._store["/new_binary.bin"] == new_binary

    def test_writes_only_go_to_upper_layer(self) -> None:
        """
        QA Scenario: Writes only go to upper layer

        Steps:
            1. lower.write_text("/shared.txt", "lower original")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. with overlay.open("/shared.txt", "w") as f:
                 f.write("upper modified")
            4. Verify upper has new content
            5. Verify lower unchanged

        Expected: Write only affects upper layer
        """
        lower = MockFileSystem()
        lower.write_text("/shared.txt", "lower original")
        original_lower = lower._store.copy()

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with overlay.open("/shared.txt", "w") as f:
            f.write("upper modified")

        # Verify upper has the write
        assert upper._store["/shared.txt"] == b"upper modified"
        # Verify lower unchanged
        assert lower._store == original_lower


class TestOverlayWhiteout:
    """Tests for OverlayFileSystem whiteout functionality."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    # ============== _get_whiteout_path tests ==============

    def test_get_whiteout_path_root_file(self) -> None:
        """Test whiteout path for file in root directory."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._get_whiteout_path("/file.txt") == "/.wh.file.txt"

    def test_get_whiteout_path_nested_file(self) -> None:
        """Test whiteout path for file in nested directory."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._get_whiteout_path("/dir/file.txt") == "/dir/.wh.file.txt"

    def test_get_whiteout_path_deeply_nested(self) -> None:
        """Test whiteout path for deeply nested file."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._get_whiteout_path("/a/b/c/file.txt") == "/a/b/c/.wh.file.txt"

    def test_get_whiteout_path_without_leading_slash(self) -> None:
        """Test whiteout path normalization for path without leading slash."""
        overlay = OverlayFileSystem(MockFileSystem(), [])
        assert overlay._get_whiteout_path("file.txt") == "/.wh.file.txt"

    # ============== _has_whiteout tests ==============

    def test_has_whiteout_returns_true_when_marker_exists(self) -> None:
        """Test _has_whiteout returns True when whiteout marker exists."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        # Create whiteout marker manually
        upper.pipe("/.wh.file.txt", b"")

        assert overlay._has_whiteout("/file.txt") is True

    def test_has_whiteout_returns_false_when_no_marker(self) -> None:
        """Test _has_whiteout returns False when no whiteout marker."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        assert overlay._has_whiteout("/file.txt") is False

    def test_has_whiteout_nested_path(self) -> None:
        """Test _has_whiteout works for nested paths."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        upper.mkdir("/dir")
        upper.pipe("/dir/.wh.file.txt", b"")

        assert overlay._has_whiteout("/dir/file.txt") is True

    # ============== _create_whiteout tests ==============

    def test_create_whiteout_creates_marker_file(self) -> None:
        """Test _create_whiteout creates empty marker file."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._create_whiteout("/file.txt")

        assert upper.isfile("/.wh.file.txt") is True
        assert upper._store["/.wh.file.txt"] == b""

    def test_create_whiteout_creates_parent_dirs(self) -> None:
        """Test _create_whiteout creates parent directories."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        overlay._create_whiteout("/a/b/c/file.txt")

        assert upper.isdir("/a") is True
        assert upper.isdir("/a/b") is True
        assert upper.isdir("/a/b/c") is True
        assert upper.isfile("/a/b/c/.wh.file.txt") is True

    # ============== rm() tests ==============

    def test_rm_deletes_upper_layer_file(self) -> None:
        """Test rm deletes file in upper layer directly."""
        upper = MockFileSystem()
        upper.write_text("/file.txt", "upper content")
        overlay = OverlayFileSystem(upper, [])

        overlay.rm("/file.txt")

        assert upper.exists("/file.txt") is False
        assert overlay.exists("/file.txt") is False

    def test_rm_creates_whiteout_for_lower_layer_file(self) -> None:
        """Test rm creates whiteout marker for lower layer file."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        overlay.rm("/file.txt")

        # Whiteout marker created in upper
        assert upper.isfile("/.wh.file.txt") is True
        # Lower layer unchanged
        assert lower.isfile("/file.txt") is True
        assert lower._store["/file.txt"] == b"lower content"

    def test_rm_raises_error_for_nonexistent_file(self) -> None:
        """Test rm raises FileNotFoundError for non-existent file."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(FileNotFoundError, match="Path not found"):
            overlay.rm("/nonexistent.txt")

    def test_rm_raises_error_for_directory(self) -> None:
        """Test rm raises IsADirectoryError for directories."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")
        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            overlay.rm("/testdir")

    def test_rm_idempotent_for_already_whited_out(self) -> None:
        """Test rm is idempotent for already whited-out file."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        # First rm
        overlay.rm("/file.txt")
        # Second rm should not raise
        overlay.rm("/file.txt")

        # Still only one whiteout marker
        assert overlay.exists("/file.txt") is False

    # ============== exists() whiteout tests ==============

    def test_exists_returns_false_for_whited_out_lower_file(self) -> None:
        """Test exists returns False for whited-out lower layer file."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        # File exists before whiteout
        assert overlay.exists("/file.txt") is True

        # Create whiteout
        overlay._create_whiteout("/file.txt")

        # File now appears non-existent
        assert overlay.exists("/file.txt") is False

    def test_exists_returns_true_for_upper_file(self) -> None:
        """Test exists returns True for upper layer file."""
        upper = MockFileSystem()
        upper.write_text("/file.txt", "upper content")
        overlay = OverlayFileSystem(upper, [])

        assert overlay.exists("/file.txt") is True

    def test_exists_returns_false_for_whited_out_upper_file(self) -> None:
        """Test exists returns False when upper file has whiteout."""
        upper = MockFileSystem()
        upper.write_text("/file.txt", "upper content")
        overlay = OverlayFileSystem(upper, [])

        # Create whiteout (unusual case, but should work)
        overlay._create_whiteout("/file.txt")

        # File should appear non-existent
        assert overlay.exists("/file.txt") is False

    # ============== ls() whiteout tests ==============

    def test_ls_filters_whiteout_markers(self) -> None:
        """Test ls hides .wh.* marker files from listing."""
        upper = MockFileSystem()
        upper.write_text("/visible.txt", "visible")
        upper.pipe("/.wh.hidden.txt", b"")

        overlay = OverlayFileSystem(upper, [])
        result = overlay.ls("/")

        # Visible file should be listed
        assert "visible.txt" in result
        # Whiteout marker should be hidden
        assert ".wh.hidden.txt" not in result

    def test_ls_filters_whited_out_files(self) -> None:
        """Test ls hides files that have whiteout markers."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/deleted.txt", "lower content")
        lower.write_text("/visible.txt", "visible")

        overlay = OverlayFileSystem(upper, [lower])

        # Before whiteout, both files visible
        result_before = overlay.ls("/")
        assert "deleted.txt" in result_before
        assert "visible.txt" in result_before

        # Create whiteout
        overlay._create_whiteout("/deleted.txt")

        # After whiteout, deleted.txt hidden
        result_after = overlay.ls("/")
        assert "deleted.txt" not in result_after
        assert "visible.txt" in result_after

    def test_ls_handles_nested_whited_out_files(self) -> None:
        """Test ls correctly filters whited-out files in subdirectories."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/subdir")
        lower.write_text("/subdir/file1.txt", "content1")
        lower.write_text("/subdir/file2.txt", "content2")

        overlay = OverlayFileSystem(upper, [lower])

        # Whiteout one file in subdir
        overlay._create_whiteout("/subdir/file1.txt")

        result = overlay.ls("/subdir")

        assert "file1.txt" not in result
        assert "file2.txt" in result

    # ============== _resolve() whiteout tests ==============

    def test_resolve_returns_none_for_whited_out_file(self) -> None:
        """Test _resolve returns None when file has whiteout marker."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        # Before whiteout
        assert overlay._resolve("/file.txt") is not None

        # Create whiteout
        overlay._create_whiteout("/file.txt")

        # After whiteout, resolve returns None
        assert overlay._resolve("/file.txt") is None

    def test_resolve_without_whiteout_finds_whited_out_file(self) -> None:
        """Test _resolve_without_whiteout finds file despite whiteout."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])
        overlay._create_whiteout("/file.txt")

        # _resolve returns None
        assert overlay._resolve("/file.txt") is None
        # _resolve_without_whiteout finds the file
        result = overlay._resolve_without_whiteout("/file.txt")
        assert result is not None
        assert result[2] == 1  # layer_index 1 = lower layer


class TestOverlayRecreateAfterDelete:
    """Tests for the "recreate after delete" edge case.

    This edge case occurs when:
    1. File exists in lower layer
    2. File is deleted (whiteout created)
    3. File is recreated in upper layer

    The whiteout marker must be removed so the new file is visible.
    """

    # ============== _remove_whiteout tests ==============

    def test_remove_whiteout_removes_existing_marker(self) -> None:
        """Test _remove_whiteout removes existing whiteout marker."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        # Create whiteout marker
        overlay._create_whiteout("/file.txt")
        assert upper.isfile("/.wh.file.txt") is True

        # Remove whiteout marker
        result = overlay._remove_whiteout("/file.txt")

        assert result is True
        assert upper.isfile("/.wh.file.txt") is False

    def test_remove_whiteout_returns_false_when_no_marker(self) -> None:
        """Test _remove_whiteout returns False when no marker exists."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        result = overlay._remove_whiteout("/file.txt")

        assert result is False

    def test_remove_whiteout_nested_path(self) -> None:
        """Test _remove_whiteout works for nested paths."""
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [])

        # Create nested directory and whiteout
        upper.mkdir("/dir")
        overlay._create_whiteout("/dir/file.txt")
        assert upper.isfile("/dir/.wh.file.txt") is True

        # Remove whiteout
        result = overlay._remove_whiteout("/dir/file.txt")

        assert result is True
        assert upper.isfile("/dir/.wh.file.txt") is False

    # ============== Recreate after delete tests ==============

    def test_recreate_after_delete_from_lower_layer(self) -> None:
        """Test recreating a file after deleting it from lower layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/shared.txt", "original lower content")

        overlay = OverlayFileSystem(upper, [lower])

        # Step 1: Verify file exists
        assert overlay.exists("/shared.txt") is True
        assert overlay.isfile("/shared.txt") is True

        # Step 2: Delete the file (creates whiteout)
        overlay.rm("/shared.txt")

        # Step 3: Verify file appears deleted
        assert overlay.exists("/shared.txt") is False
        assert upper.isfile("/.wh.shared.txt") is True

        # Step 4: Recreate the file
        with overlay.open("/shared.txt", "w") as f:
            f.write("recreated content")

        # Step 5: Verify recreated file is visible
        assert overlay.exists("/shared.txt") is True
        assert overlay.isfile("/shared.txt") is True

        # Step 6: Verify whiteout marker is removed
        assert upper.isfile("/.wh.shared.txt") is False

        # Step 7: Verify content is correct
        with overlay.open("/shared.txt", "r") as f:
            content = f.read()
        assert content == "recreated content"

    def test_recreate_multiple_cycles(self) -> None:
        """Test delete-recreate cycle.

        Note: After the first cycle, the file is in the upper layer,
        so subsequent rm() calls would delete it directly. This test focuses
        on the first (critical) cycle where whiteout is created and removed.
        """
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/cycle.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        # First cycle: file in lower, whiteout created
        overlay.rm("/cycle.txt")
        assert overlay.exists("/cycle.txt") is False
        assert upper.isfile("/.wh.cycle.txt") is True

        # Recreate file - this should remove whiteout
        with overlay.open("/cycle.txt", "w") as f:
            f.write("cycle 1")

        assert overlay.exists("/cycle.txt") is True
        assert upper.isfile("/.wh.cycle.txt") is False

        with overlay.open("/cycle.txt", "r") as f:
            assert f.read() == "cycle 1"

        # File should be directly in upper now
        assert upper.isfile("/cycle.txt") is True

    def test_recreate_preserves_lower_layer(self) -> None:
        """Test that recreating doesn't modify the lower layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/original.txt", "lower original")
        original_lower = lower._store.copy()

        overlay = OverlayFileSystem(upper, [lower])

        # Delete and recreate
        overlay.rm("/original.txt")
        with overlay.open("/original.txt", "w") as f:
            f.write("new content")

        # Verify lower unchanged
        assert lower._store == original_lower
        assert lower._store["/original.txt"] == b"lower original"

    def test_recreate_after_delete_lists_correctly(self) -> None:
        """Test ls() shows recreated file after delete."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")

        overlay = OverlayFileSystem(upper, [lower])

        # Initially visible
        assert "file.txt" in overlay.ls("/")

        # Delete
        overlay.rm("/file.txt")
        assert "file.txt" not in overlay.ls("/")

        # Recreate
        with overlay.open("/file.txt", "w") as f:
            f.write("new content")

        # Should be visible again
        assert "file.txt" in overlay.ls("/")

    def test_recreate_with_append_mode(self) -> None:
        """Test recreating a file using append mode."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/append.txt", "original from lower")

        overlay = OverlayFileSystem(upper, [lower])

        # Delete
        overlay.rm("/append.txt")
        assert overlay.exists("/append.txt") is False

        # Recreate using append mode
        with overlay.open("/append.txt", "a") as f:
            f.write(" appended content")

        # Should be visible and have appended content (lower was COW'd then appended)
        assert overlay.exists("/append.txt") is True
        with overlay.open("/append.txt", "r") as f:
            content = f.read()
        assert content == "original from lower appended content"

    def test_recreate_with_write_plus_mode(self) -> None:
        """Test recreating a file using w+ mode."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/write_plus.txt", "original")

        overlay = OverlayFileSystem(upper, [lower])

        # Delete
        overlay.rm("/write_plus.txt")

        # Recreate using w+ mode
        with overlay.open("/write_plus.txt", "w+") as f:
            f.write("w+ content")
            f.seek(0)
            content = f.read()
        assert content == "w+ content"

        # Verify whiteout removed
        assert overlay.exists("/write_plus.txt") is True


class TestOverlayWhiteoutQAScenarios:
    """QA scenario tests for whiteout functionality."""

    def test_whiteout_hides_lower_layer_file(self) -> None:
        """
        QA Scenario: Whiteout hides lower layer file

        Steps:
            1. lower.write_text("/file.txt", "content")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. overlay.rm("/file.txt")
            4. assert not overlay.exists("/file.txt")
            5. assert lower.exists("/file.txt")  # lower unchanged
            6. assert ".wh.file.txt" in upper.ls("/")

        Expected: File appears deleted, lower unchanged, marker created
        """
        # Step 1: Create lower with file
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")

        # Step 2: Create overlay with empty upper
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Step 3: Remove file via overlay
        overlay.rm("/file.txt")

        # Step 4: Verify file appears deleted
        assert overlay.exists("/file.txt") is False, (
            "File should not exist in overlay view"
        )

        # Step 5: Verify lower layer unchanged
        assert lower.exists("/file.txt") is True, "Lower layer should be unchanged"
        assert lower._store["/file.txt"] == b"content", (
            "Lower layer content should be preserved"
        )

        # Step 6: Verify whiteout marker created
        assert upper.isfile("/.wh.file.txt") is True, (
            "Whiteout marker should exist in upper layer"
        )

    def test_rm_deletes_upper_layer_file_no_whiteout(self) -> None:
        """
        QA Scenario: rm() deletes upper layer file directly

        Steps:
            1. upper.write_text("/file.txt", "upper content")
            2. overlay = OverlayFileSystem(upper, [])
            3. overlay.rm("/file.txt")
            4. assert not overlay.exists("/file.txt")
            5. assert not upper.exists("/file.txt")

        Expected: File deleted from upper, no whiteout marker created
        """
        # Step 1: Create upper with file
        upper = MockFileSystem()
        upper.write_text("/file.txt", "upper content")

        # Step 2: Create overlay
        overlay = OverlayFileSystem(upper, [])

        # Step 3: Remove file
        overlay.rm("/file.txt")

        # Step 4 & 5: Verify file deleted, no whiteout
        assert overlay.exists("/file.txt") is False
        assert upper.exists("/file.txt") is False
        assert ".wh.file.txt" not in upper.ls("/")

    def test_ls_filters_completely(self) -> None:
        """
        QA Scenario: ls() completely filters whited-out files

        Steps:
            1. lower.write_text("/file1.txt", "1")
            2. lower.write_text("/file2.txt", "2")
            3. overlay = OverlayFileSystem(upper, [lower])
            4. result_before = overlay.ls("/")
            5. overlay.rm("/file1.txt")
            6. result_after = overlay.ls("/")

        Expected: file1.txt not in result_after, file2.txt still present
        """
        lower = MockFileSystem()
        lower.write_text("/file1.txt", "1")
        lower.write_text("/file2.txt", "2")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Before deletion
        result_before = overlay.ls("/")
        assert "file1.txt" in result_before
        assert "file2.txt" in result_before

        # Delete file1
        overlay.rm("/file1.txt")

        # After deletion
        result_after = overlay.ls("/")
        assert "file1.txt" not in result_after, (
            "Whited-out file should not appear in listing"
        )
        assert "file2.txt" in result_after, "Non-deleted file should still appear"

    def test_exists_returns_false_with_whiteout(self) -> None:
        """
        QA Scenario: exists() returns False for whited-out file

        Steps:
            1. lower.write_text("/file.txt", "content")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. assert overlay.exists("/file.txt")  # Before whiteout
            4. overlay._create_whiteout("/file.txt")
            5. assert not overlay.exists("/file.txt")  # After whiteout

        Expected: exists() returns False after whiteout creation
        """
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Before whiteout
        assert overlay.exists("/file.txt") is True

        # Create whiteout marker
        overlay._create_whiteout("/file.txt")

        # After whiteout
        assert overlay.exists("/file.txt") is False, (
            "exists() should return False after whiteout creation"
        )

        # Lower still has the file
        assert lower.exists("/file.txt") is True


class TestOverlayRename:
    """Tests for OverlayFileSystem.rename() method with COW semantics."""

    # ============== Basic rename tests ==============

    def test_rename_upper_to_upper_same_dir(self) -> None:
        """Test renaming file within upper layer (same directory)."""
        upper = MockFileSystem()
        upper.write_text("/old.txt", "upper content")
        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/old.txt", "/new.txt")

        # Source should not exist
        assert upper.exists("/old.txt") is False
        # Destination should exist with same content
        assert upper.isfile("/new.txt") is True
        assert upper._store["/new.txt"] == b"upper content"

    def test_rename_lower_to_upper_triggers_cow(self) -> None:
        """Test renaming file from lower layer triggers COW first."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/lower.txt", "lower content")

        overlay = OverlayFileSystem(upper, [lower])

        overlay.rename("/lower.txt", "/renamed.txt")

        # Source should appear deleted in overlay (whiteout created)
        assert overlay.exists("/lower.txt") is False
        # Destination should exist in upper with copied content
        assert upper.isfile("/renamed.txt") is True
        assert upper._store["/renamed.txt"] == b"lower content"
        # Original lower should be unchanged
        assert lower._store["/lower.txt"] == b"lower content"
        # Whiteout should be created for source in lower layer case
        assert upper.isfile("/.wh.lower.txt") is True

    def test_rename_across_directories(self) -> None:
        """Test rename across different directories creates parent dirs."""
        upper = MockFileSystem()
        upper.mkdir("/src")
        upper.write_text("/src/file.txt", "moved content")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/src/file.txt", "/dst/file.txt")

        # Source directory
        assert upper.exists("/src/file.txt") is False
        # Destination directory created
        assert upper.isdir("/dst") is True
        assert upper.isfile("/dst/file.txt") is True
        assert upper._store["/dst/file.txt"] == b"moved content"

    def test_rename_overwrite_upper_layer_target(self) -> None:
        """Test rename overwrites existing file in upper layer."""
        upper = MockFileSystem()
        upper.write_text("/source.txt", "source content")
        upper.write_text("/target.txt", "original target")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/source.txt", "/target.txt")

        # Source is gone
        assert upper.exists("/source.txt") is False
        # Target has source's content
        assert upper._store["/target.txt"] == b"source content"

    def test_rename_overwrite_lower_layer_target(self) -> None:
        """Test rename overwrites existing file in lower layer."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        upper.write_text("/source.txt", "source content")
        lower.write_text("/target.txt", "lower target")

        overlay = OverlayFileSystem(upper, [lower])

        overlay.rename("/source.txt", "/target.txt")

        # Source is gone
        assert upper.exists("/source.txt") is False
        # Target is now in upper with source's content
        assert upper.isfile("/target.txt") is True
        assert upper._store["/target.txt"] == b"source content"
        # Original lower target unchanged
        assert lower._store["/target.txt"] == b"lower target"

    def test_rename_raises_for_nonexistent_source(self) -> None:
        """Test rename raises FileNotFoundError for non-existent source."""
        overlay = OverlayFileSystem(MockFileSystem(), [MockFileSystem()])

        with pytest.raises(FileNotFoundError, match="Path not found"):
            overlay.rename("/nonexistent.txt", "/new.txt")

    def test_rename_raises_for_directory(self) -> None:
        """Test rename raises IsADirectoryError for directories."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            overlay.rename("/testdir", "/newdir")

    def test_rename_preserves_binary_content(self) -> None:
        """Test rename preserves binary content exactly."""
        upper = MockFileSystem()
        binary_data = bytes(range(256))
        upper.pipe("/binary.bin", binary_data)

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/binary.bin", "/moved.bin")

        assert upper._store["/moved.bin"] == binary_data

    def test_rename_deeply_nested_path(self) -> None:
        """Test rename works with deeply nested paths."""
        upper = MockFileSystem()
        upper.mkdir("/a")
        upper.mkdir("/a/b")
        upper.write_text("/a/b/file.txt", "deep content")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/a/b/file.txt", "/x/y/z/file.txt")

        # Original path deleted
        assert upper.exists("/a/b/file.txt") is False
        # All parent directories created
        assert upper.isdir("/x") is True
        assert upper.isdir("/x/y") is True
        assert upper.isdir("/x/y/z") is True
        # File at new location
        assert upper.isfile("/x/y/z/file.txt") is True
        assert upper._store["/x/y/z/file.txt"] == b"deep content"

    def test_rename_without_leading_slash(self) -> None:
        """Test rename handles paths without leading slash."""
        upper = MockFileSystem()
        upper.write_text("/file.txt", "content")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        # Rename without leading slash
        overlay.rename("file.txt", "newfile.txt")

        # Should work with normalized paths
        assert upper.exists("/file.txt") is False
        assert upper.isfile("/newfile.txt") is True


class TestOverlayRenameQAScenarios:
    """QA scenario tests for rename() with COW semantics."""

    def test_rename_upper_to_upper_scenario(self) -> None:
        """
        QA Scenario: Rename file within upper layer

        Steps:
            1. upper.write_text("/old.txt", "content")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. overlay.rename("/old.txt", "/new.txt")
            4. assert not upper.exists("/old.txt")
            5. assert upper._store["/new.txt"] == b"content"

        Expected: File renamed within upper, content preserved
        """
        upper = MockFileSystem()
        upper.write_text("/old.txt", "content")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/old.txt", "/new.txt")

        assert upper.exists("/old.txt") is False, "Source should be deleted"
        assert upper.isfile("/new.txt") is True, "Destination should exist"
        assert upper._store["/new.txt"] == b"content", "Content preserved"

    def test_rename_lower_triggers_cow_scenario(self) -> None:
        """
        QA Scenario: Rename lower layer file triggers COW

        Steps:
            1. lower.write_text("/lower.txt", "original")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. overlay.rename("/lower.txt", "/renamed.txt")
            4. assert upper.isfile("/renamed.txt")
            5. assert upper._store["/renamed.txt"] == b"original"
            6. assert lower._store["/lower.txt"] == b"original" (unchanged)
            7. assert overlay.exists("/lower.txt") is False (whited out)

        Expected: COW triggered, lower unchanged, source whited out
        """
        lower = MockFileSystem()
        lower.write_text("/lower.txt", "original")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.rename("/lower.txt", "/renamed.txt")

        # Destination in upper with copied content
        assert upper.isfile("/renamed.txt") is True
        assert upper._store["/renamed.txt"] == b"original"

        # Lower unchanged
        assert lower._store["/lower.txt"] == b"original"

        # Source appears deleted with whiteout
        assert overlay.exists("/lower.txt") is False
        assert upper.isfile("/.wh.lower.txt") is True

    def test_rename_overwrite_scenario(self) -> None:
        """
        QA Scenario: Rename overwrites existing file

        Steps:
            1. upper.write_text("/source.txt", "new")
            2. upper.write_text("/target.txt", "old")
            3. overlay.rename("/source.txt", "/target.txt")
            4. assert not upper.exists("/source.txt")
            5. assert upper._store["/target.txt"] == b"new"

        Expected: Source moved to target, overwriting target content
        """
        upper = MockFileSystem()
        upper.write_text("/source.txt", "new")
        upper.write_text("/target.txt", "old")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/source.txt", "/target.txt")

        assert upper.exists("/source.txt") is False
        assert upper._store["/target.txt"] == b"new"

    def test_rename_across_directories_scenario(self) -> None:
        """
        QA Scenario: Rename across directories creates parent dirs

        Steps:
            1. upper.mkdir("/a")
            2. upper.write_text("/a/file.txt", "move me")
            3. overlay.rename("/a/file.txt", "/b/c/file.txt")
            4. assert not upper.exists("/a/file.txt")
            5. assert upper.isdir("/b")
            6. assert upper.isdir("/b/c")
            7. assert upper.isfile("/b/c/file.txt")

        Expected: File moved, parent directories auto-created
        """
        upper = MockFileSystem()
        upper.mkdir("/a")
        upper.write_text("/a/file.txt", "move me")

        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay.rename("/a/file.txt", "/b/c/file.txt")

        assert upper.exists("/a/file.txt") is False
        assert upper.isdir("/b") is True
        assert upper.isdir("/b/c") is True
        assert upper.isfile("/b/c/file.txt") is True
        assert upper._store["/b/c/file.txt"] == b"move me"

    def test_rename_lower_to_different_dir_triggers_cow(self) -> None:
        """
        QA Scenario: Rename lower file to different directory

        Steps:
            1. lower.write_text("/source.txt", "content")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. overlay.rename("/source.txt", "/dst/renamed.txt")
            4. assert upper.isdir("/dst")
            5. assert upper.isfile("/dst/renamed.txt")
            6. assert overlay.exists("/source.txt") is False
            7. assert lower._store["/source.txt"] == b"content" (unchanged)

        Expected: COW + move, parents created, source whited out
        """
        lower = MockFileSystem()
        lower.write_text("/source.txt", "content")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay.rename("/source.txt", "/dst/renamed.txt")

        # Destination directory and file created
        assert upper.isdir("/dst") is True
        assert upper.isfile("/dst/renamed.txt") is True
        assert upper._store["/dst/renamed.txt"] == b"content"

        # Source appears deleted
        assert overlay.exists("/source.txt") is False

        # Lower unchanged
        assert lower._store["/source.txt"] == b"content"


class TestOverlayDirectoryWhiteout:
    """Tests for directory whiteout functionality (Task 28)."""

    def test_rmdir_deletes_upper_layer_directory(self) -> None:
        """Test rmdir deletes directory in upper layer directly."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")
        upper.write_text("/testdir/file.txt", "content")
        overlay = OverlayFileSystem(upper, [])

        # First delete the file
        overlay.rm("/testdir/file.txt")
        # Then delete the directory
        overlay.rmdir("/testdir")

        assert upper.exists("/testdir") is False
        assert overlay.exists("/testdir") is False

    def test_rmdir_creates_whiteout_for_lower_layer_directory(self) -> None:
        """Test rmdir creates whiteout marker for lower layer directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")
        lower.write_text("/testdir/file.txt", "content")

        overlay = OverlayFileSystem(upper, [lower])

        # Delete the file first
        overlay.rm("/testdir/file.txt")
        # Then delete the directory
        overlay.rmdir("/testdir")

        # Whiteout marker created in upper
        assert upper.isfile("/.wh.testdir") is True
        # Lower layer unchanged
        assert lower.isdir("/testdir") is True
        # Directory appears deleted in overlay
        assert overlay.exists("/testdir") is False
        assert overlay.isdir("/testdir") is False

    def test_rmdir_raises_error_for_nonexistent_directory(self) -> None:
        """Test rmdir raises FileNotFoundError for non-existent directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        with pytest.raises(FileNotFoundError, match="Path not found"):
            overlay.rmdir("/nonexistent")

    def test_rmdir_raises_error_for_file(self) -> None:
        """Test rmdir raises NotADirectoryError for files."""
        upper = MockFileSystem()
        upper.write_text("/file.txt", "content")
        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(NotADirectoryError, match="Path is a file"):
            overlay.rmdir("/file.txt")

    def test_rmdir_raises_error_for_nonempty_directory(self) -> None:
        """Test rmdir raises OSError for non-empty directory."""
        upper = MockFileSystem()
        upper.mkdir("/testdir")
        upper.write_text("/testdir/file.txt", "content")
        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(OSError, match="Directory not empty"):
            overlay.rmdir("/testdir")

    def test_rmdir_idempotent_for_already_whited_out(self) -> None:
        """Test rmdir is idempotent for already whited-out directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")
        lower.write_text("/testdir/file.txt", "content")

        overlay = OverlayFileSystem(upper, [lower])

        # First delete the file
        overlay.rm("/testdir/file.txt")
        # Delete the directory
        overlay.rmdir("/testdir")
        # Second rmdir should not raise
        overlay.rmdir("/testdir")

        # Still only one whiteout marker
        assert overlay.exists("/testdir") is False

    def test_isdir_returns_false_for_whited_out_directory(self) -> None:
        """Test isdir returns False for whited-out directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [lower])

        # Directory exists before whiteout
        assert overlay.isdir("/testdir") is True

        # Create whiteout
        overlay._create_whiteout("/testdir")

        # Directory now appears non-existent
        assert overlay.isdir("/testdir") is False

    def test_ls_returns_empty_for_whited_out_directory(self) -> None:
        """Test ls returns empty list for whited-out directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/parent")
        lower.mkdir("/parent/testdir")
        lower.write_text("/parent/testdir/file.txt", "content")
        lower.write_text("/parent/other.txt", "other")

        overlay = OverlayFileSystem(upper, [lower])

        # Before whiteout
        assert "testdir" in overlay.ls("/parent")
        assert "file.txt" in overlay.ls("/parent/testdir")

        # Create whiteout for testdir
        overlay._create_whiteout("/parent/testdir")

        # testdir should not appear in listing
        assert "testdir" not in overlay.ls("/parent")
        # ls on whited-out dir should return empty
        assert overlay.ls("/parent/testdir") == []

    def test_exists_returns_false_for_whited_out_directory(self) -> None:
        """Test exists returns False for whited-out directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [lower])

        # Directory exists before whiteout
        assert overlay.exists("/testdir") is True

        # Create whiteout
        overlay._create_whiteout("/testdir")

        # Directory now appears non-existent
        assert overlay.exists("/testdir") is False
        assert lower.exists("/testdir") is True  # Lower unchanged

    def test_mkdir_removes_directory_whiteout(self) -> None:
        """Test mkdir removes whiteout marker when recreating directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [lower])

        # Delete directory (creates whiteout)
        overlay.rmdir("/testdir")
        assert overlay.exists("/testdir") is False
        assert upper.isfile("/.wh.testdir") is True

        # Recreate directory
        overlay.mkdir("/testdir")
        assert overlay.exists("/testdir") is True
        assert overlay.isdir("/testdir") is True
        assert upper.isfile("/.wh.testdir") is False  # Whiteout removed

    def test_makedirs_removes_directory_whiteout(self) -> None:
        """Test makedirs removes whiteout marker when recreating directory."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [lower])

        # Delete directory (creates whiteout)
        overlay.rmdir("/testdir")
        assert overlay.exists("/testdir") is False

        # Recreate with makedirs
        overlay.makedirs("/testdir")
        assert overlay.exists("/testdir") is True
        assert overlay.isdir("/testdir") is True

    def test_nested_directory_whiteout_hides_all_contents(self) -> None:
        """Test directory whiteout hides all nested contents."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/parent/child/grandchild")
        lower.write_text("/parent/child/file1.txt", "content1")
        lower.write_text("/parent/child/grandchild/file2.txt", "content2")
        lower.write_text("/parent/other.txt", "other")

        overlay = OverlayFileSystem(upper, [lower])

        # Before whiteout
        assert "child" in overlay.ls("/parent")
        assert "file1.txt" in overlay.ls("/parent/child")
        assert "grandchild" in overlay.ls("/parent/child")

        # Whiteout parent/child
        overlay.rm("/parent/child/grandchild/file2.txt")
        overlay.rmdir("/parent/child/grandchild")
        overlay.rm("/parent/child/file1.txt")
        overlay.rmdir("/parent/child")

        # All contents hidden
        assert "child" not in overlay.ls("/parent")
        assert overlay.exists("/parent/child") is False
        assert overlay.exists("/parent/child/file1.txt") is False
        assert overlay.exists("/parent/child/grandchild") is False

        # Parent's other file still visible
        assert "other.txt" in overlay.ls("/parent")


class TestOverlayDirectoryWhiteoutQAScenarios:
    """QA scenario tests for directory whiteout functionality."""

    def test_delete_and_recreate_directory_cycle(self) -> None:
        """
        QA Scenario: Delete and recreate directory cycle

        Steps:
            1. lower.mkdir("/testdir")
            2. lower.write_text("/testdir/file.txt", "original")
            3. overlay.rmdir("/testdir/file.txt")
            4. overlay.rmdir("/testdir")  # Creates .wh.testdir
            5. assert not overlay.exists("/testdir")
            6. overlay.mkdir("/testdir")  # Removes .wh.testdir
            7. overlay.write_text("/testdir/new.txt", "new")
            8. assert overlay.ls("/testdir") == ["new.txt"]

        Expected: Can recreate directory after deletion, lower content hidden
        """
        lower = MockFileSystem()
        lower.mkdir("/testdir")
        lower.write_text("/testdir/file.txt", "original")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Delete the file and directory
        overlay.rm("/testdir/file.txt")
        overlay.rmdir("/testdir")

        # Directory appears deleted
        assert overlay.exists("/testdir") is False
        assert upper.isfile("/.wh.testdir") is True

        # Recreate directory
        overlay.mkdir("/testdir")

        # Can add new content
        with overlay.open("/testdir/new.txt", "w") as f:
            f.write("new")

        # Only new content visible (lower layer hidden by new upper layer)
        entries = overlay.ls("/testdir")
        assert "new.txt" in entries
        assert "file.txt" not in entries  # Lower layer file hidden

    def test_directory_whiteout_blocks_lower_layer_access(self) -> None:
        """
        QA Scenario: Directory whiteout blocks all lower layer access

        Steps:
            1. lower.mkdir("/blocked/subdir")
            2. lower.write_text("/blocked/file.txt", "content")
            3. lower.write_text("/blocked/subdir/nested.txt", "nested")
            4. overlay.rmdir("/blocked/subdir/nested.txt")
            5. overlay.rmdir("/blocked/subdir")
            6. overlay.rmdir("/blocked/file.txt")
            7. overlay.rmdir("/blocked")
            8. Verify none of the paths are accessible

        Expected: All paths under whited-out directory are hidden
        """
        lower = MockFileSystem()
        lower.mkdir("/blocked/subdir")
        lower.write_text("/blocked/file.txt", "content")
        lower.write_text("/blocked/subdir/nested.txt", "nested")
        lower.write_text("/other.txt", "other")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Delete everything under /blocked (must be empty to rmdir)
        overlay.rm("/blocked/subdir/nested.txt")
        overlay.rmdir("/blocked/subdir")
        overlay.rm("/blocked/file.txt")
        overlay.rmdir("/blocked")

        # All paths under /blocked should be hidden
        assert overlay.exists("/blocked") is False
        assert overlay.exists("/blocked/file.txt") is False
        assert overlay.exists("/blocked/subdir") is False
        assert overlay.exists("/blocked/subdir/nested.txt") is False

        # Other paths still accessible
        assert overlay.exists("/other.txt") is True

    def test_can_create_file_where_directory_was_deleted(self) -> None:
        """
        QA Scenario: Can create file with same name as deleted directory

        Steps:
            1. lower.mkdir("/path")
            2. overlay.rmdir("/path")
            3. overlay.write_text("/path", "file content")
            4. assert overlay.isfile("/path")
            5. assert not overlay.isdir("/path")

        Expected: Can repurpose path from directory to file
        """
        lower = MockFileSystem()
        lower.mkdir("/path")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Delete directory
        overlay.rmdir("/path")
        assert overlay.exists("/path") is False

        # Create file with same name
        with overlay.open("/path", "w") as f:
            f.write("file content")

        assert overlay.isfile("/path") is True
        assert overlay.isdir("/path") is False

    def test_can_recreate_directory_tree_after_deletion(self) -> None:
        """
        QA Scenario: Can recreate directory tree after deletion

        Steps:
            1. lower.mkdir("/a/b")
            2. lower.write_text("/a/b/file.txt", "original")
            3. overlay.rmdir("/a/b/file.txt")
            4. overlay.rmdir("/a/b")
            5. overlay.rmdir("/a")
            6. overlay.makedirs("/a/b/c")
            7. overlay.write_text("/a/b/c/new.txt", "new")
            8. Verify structure exists

        Expected: Full directory tree can be recreated
        """
        lower = MockFileSystem()
        lower.mkdir("/a/b")
        lower.write_text("/a/b/file.txt", "original")

        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Delete the tree (bottom up)
        overlay.rm("/a/b/file.txt")
        overlay.rmdir("/a/b")
        overlay.rmdir("/a")

        assert overlay.exists("/a") is False

        # Recreate with deeper structure
        overlay.makedirs("/a/b/c")
        with overlay.open("/a/b/c/new.txt", "w") as f:
            f.write("new")

        assert overlay.isdir("/a")
        assert overlay.isdir("/a/b")
        assert overlay.isdir("/a/b/c")
        assert overlay.isfile("/a/b/c/new.txt")


class TestStaleWhiteoutDetection:
    """Tests for stale whiteout detection and cleanup functionality."""

    def test_get_all_whiteouts_empty_filesystem(self) -> None:
        """Test _get_all_whiteouts returns empty list for empty filesystem."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        whiteouts = overlay._get_all_whiteouts("/")
        assert whiteouts == []

    def test_get_all_whiteouts_single_whiteout(self) -> None:
        """Test _get_all_whiteouts finds a single whiteout."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        # Create a whiteout
        overlay._create_whiteout("/file.txt")

        whiteouts = overlay._get_all_whiteouts("/")
        assert len(whiteouts) == 1
        assert whiteouts[0].path == "/file.txt"
        assert whiteouts[0].whiteout_path == "/.wh.file.txt"

    def test_get_all_whiteouts_multiple_whiteouts(self) -> None:
        """Test _get_all_whiteouts finds multiple whiteouts."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file1.txt", "content1")
        lower.write_text("/file2.txt", "content2")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/file1.txt")
        overlay._create_whiteout("/file2.txt")

        whiteouts = overlay._get_all_whiteouts("/")
        assert len(whiteouts) == 2
        paths = {w.path for w in whiteouts}
        assert paths == {"/file1.txt", "/file2.txt"}

    def test_get_all_whiteouts_nested_directories(self) -> None:
        """Test _get_all_whiteouts finds whiteouts in nested directories."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/a/b")
        lower.write_text("/a/b/file.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/a/b/file.txt")

        whiteouts = overlay._get_all_whiteouts("/")
        assert len(whiteouts) == 1
        assert whiteouts[0].path == "/a/b/file.txt"
        assert whiteouts[0].whiteout_path == "/a/b/.wh.file.txt"

    def test_is_stale_whiteout_true_when_nothing_hidden(self) -> None:
        """Test _is_stale_whiteout returns True when whiteout hides nothing."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        # Create whiteout without any file in lower layer
        overlay._create_whiteout("/file.txt")

        assert overlay._is_stale_whiteout("/file.txt") is True

    def test_is_stale_whiteout_false_when_file_hidden(self) -> None:
        """Test _is_stale_whiteout returns False when whiteout hides valid file."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/file.txt")

        assert overlay._is_stale_whiteout("/file.txt") is False

    def test_is_stale_whiteout_false_when_no_whiteout(self) -> None:
        """Test _is_stale_whiteout returns False when no whiteout exists."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        assert overlay._is_stale_whiteout("/file.txt") is False

    def test_is_stale_whiteout_true_when_directory_hidden(self) -> None:
        """Test _is_stale_whiteout works for directories too."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.mkdir("/dir")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/dir")

        assert overlay._is_stale_whiteout("/dir") is False

    def test_find_stale_whiteouts_returns_stale_only(self) -> None:
        """Test find_stale_whiteouts only returns stale whiteouts."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/valid.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        # Create a stale whiteout (nothing hidden)
        overlay._create_whiteout("/stale.txt")
        # Create a valid whiteout (hides a file)
        overlay._create_whiteout("/valid.txt")

        stale = overlay.find_stale_whiteouts("/")
        assert len(stale) == 1
        assert stale[0].path == "/stale.txt"

    def test_find_stale_whiteouts_empty_when_all_valid(self) -> None:
        """Test find_stale_whiteouts returns empty list when all whiteouts valid."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file1.txt", "content1")
        lower.write_text("/file2.txt", "content2")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/file1.txt")
        overlay._create_whiteout("/file2.txt")

        stale = overlay.find_stale_whiteouts("/")
        assert stale == []

    def test_find_stale_whiteouts_finds_all_stale(self) -> None:
        """Test find_stale_whiteouts finds all stale whiteouts."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/stale1.txt")
        overlay._create_whiteout("/stale2.txt")

        stale = overlay.find_stale_whiteouts("/")
        assert len(stale) == 2
        paths = {s.path for s in stale}
        assert paths == {"/stale1.txt", "/stale2.txt"}

    def test_cleanup_stale_whiteouts_removes_markers(self) -> None:
        """Test cleanup_stale_whiteouts removes stale whiteout markers."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/stale.txt")

        removed = overlay.cleanup_stale_whiteouts("/")

        assert len(removed) == 1
        assert "/.wh.stale.txt" in removed
        assert not upper.exists("/.wh.stale.txt")

    def test_cleanup_stale_whiteouts_preserves_valid(self) -> None:
        """Test cleanup_stale_whiteouts preserves valid whiteouts."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/valid.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/valid.txt")

        removed = overlay.cleanup_stale_whiteouts("/")

        assert removed == []
        assert upper.exists("/.wh.valid.txt")

    def test_cleanup_stale_whiteouts_mixed_scenario(self) -> None:
        """Test cleanup_stale_whiteouts handles mix of stale and valid."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/valid.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/stale.txt")
        overlay._create_whiteout("/valid.txt")

        removed = overlay.cleanup_stale_whiteouts("/")

        assert len(removed) == 1
        assert "/.wh.stale.txt" in removed
        assert not upper.exists("/.wh.stale.txt")
        assert upper.exists("/.wh.valid.txt")

    def test_get_whiteout_stats_empty(self) -> None:
        """Test get_whiteout_stats returns zeros for empty filesystem."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        stats = overlay.get_whiteout_stats("/")

        assert stats["total"] == 0
        assert stats["stale"] == 0
        assert stats["valid"] == 0
        assert stats["by_layer"] == {}

    def test_get_whiteout_stats_with_whiteouts(self) -> None:
        """Test get_whiteout_stats counts correctly."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/valid.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/stale.txt")
        overlay._create_whiteout("/valid.txt")

        stats = overlay.get_whiteout_stats("/")

        assert stats["total"] == 2
        assert stats["stale"] == 1
        assert stats["valid"] == 1

    def test_whiteout_becomes_stale_after_lower_layer_change(self) -> None:
        """Test whiteout becomes stale when hidden file is removed from lower."""
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        # Create whiteout for file in lower
        overlay._create_whiteout("/file.txt")
        assert overlay._is_stale_whiteout("/file.txt") is False

        # Remove file from lower layer (simulating external change)
        del lower._store["/file.txt"]

        # Whiteout is now stale
        assert overlay._is_stale_whiteout("/file.txt") is True


class TestStaleWhiteoutQA:
    """QA scenario tests for stale whiteout functionality."""

    def test_stale_whiteout_detection_scenario(self) -> None:
        """
        QA Scenario: Detect stale whiteouts

        Steps:
            1. lower.write_text("/file.txt", "content")
            2. overlay = OverlayFileSystem(upper, [lower])
            3. overlay._create_whiteout("/file.txt")  # Valid whiteout
            4. overlay._create_whiteout("/orphan.txt")  # Stale whiteout
            5. stale = overlay.find_stale_whiteouts()

        Expected: stale contains only orphan.txt whiteout
        """
        lower = MockFileSystem()
        lower.write_text("/file.txt", "content")
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/file.txt")
        overlay._create_whiteout("/orphan.txt")

        stale = overlay.find_stale_whiteouts("/")

        assert len(stale) == 1
        assert stale[0].path == "/orphan.txt"

    def test_stale_whiteout_cleanup_scenario(self) -> None:
        """
        QA Scenario: Cleanup stale whiteouts

        Steps:
            1. Create whiteouts without corresponding lower files
            2. Call cleanup_stale_whiteouts()
            3. Verify stale whiteouts are removed
            4. Verify filesystem is clean

        Expected: Only stale whiteouts removed, clean filesystem state
        """
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        overlay._create_whiteout("/stale1.txt")
        overlay._create_whiteout("/stale2.txt")

        removed = overlay.cleanup_stale_whiteouts("/")

        assert len(removed) == 2
        assert overlay.find_stale_whiteouts("/") == []
        assert overlay.get_whiteout_stats("/")["total"] == 0

    def test_whiteout_stats_accuracy_scenario(self) -> None:
        """
        QA Scenario: Verify whiteout statistics accuracy

        Steps:
            1. Create mix of valid and stale whiteouts
            2. Get statistics
            3. Verify counts match expectations

        Expected: Stats correctly report total, stale, valid counts
        """
        upper = MockFileSystem()
        lower = MockFileSystem()
        lower.write_text("/valid1.txt", "content")
        lower.write_text("/valid2.txt", "content")
        overlay = OverlayFileSystem(upper, [lower])

        overlay._create_whiteout("/valid1.txt")
        overlay._create_whiteout("/valid2.txt")
        overlay._create_whiteout("/stale.txt")

        stats = overlay.get_whiteout_stats("/")

        assert stats["total"] == 3
        assert stats["valid"] == 2
        assert stats["stale"] == 1

    def test_nested_stale_whiteout_cleanup(self) -> None:
        """
        QA Scenario: Cleanup stale whiteouts in nested directories

        Steps:
            1. Create nested directory structure with stale whiteouts
            2. Run cleanup
            3. Verify all stale whiteouts removed recursively

        Expected: All stale whiteouts removed at all directory levels
        """
        upper = MockFileSystem()
        overlay = OverlayFileSystem(upper, [MockFileSystem()])

        upper.mkdir("/a")
        upper.mkdir("/a/b")
        upper.mkdir("/a/b/c")

        overlay._create_whiteout("/a/file.txt")
        overlay._create_whiteout("/a/b/file.txt")
        overlay._create_whiteout("/a/b/c/file.txt")

        removed = overlay.cleanup_stale_whiteouts("/")

        assert len(removed) == 3
        assert overlay.find_stale_whiteouts("/") == []
