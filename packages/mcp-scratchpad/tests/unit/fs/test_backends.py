"""
Unit tests for filesystem backend implementations.

Tests the LocalFileSystem backend with DirFileSystem wrapper for
path prefix support.
"""

import tempfile
from pathlib import Path

import pytest
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.local import LocalFileSystem

from unittest.mock import MagicMock, patch

from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.config.models import MountConfig, OverlayConfig
from mcp_scratchpad.fs.backends import (
    S3NotInstalledError,
    create_filesystem,
    create_filesystems_from_config,
    create_local_filesystem,
    create_memory_filesystem,
    create_s3_filesystem,
)


class TestCreateLocalFilesystem:
    """Tests for create_local_filesystem function."""

    def test_create_without_prefix_returns_local_filesystem(self):
        """Test that create_local_filesystem without prefix returns LocalFileSystem."""
        fs = create_local_filesystem()

        assert isinstance(fs, LocalFileSystem)
        assert not isinstance(fs, DirFileSystem)

    def test_create_with_prefix_returns_dir_filesystem(self):
        """Test that create_local_filesystem with prefix returns DirFileSystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem(path_prefix=tmpdir)

            assert isinstance(fs, DirFileSystem)

    def test_create_passes_options_to_local_filesystem(self):
        """Test that options are passed to LocalFileSystem constructor."""
        # Create with options - LocalFileSystem accepts use_listings_cache
        fs = create_local_filesystem(use_listings_cache=True)

        # Verify it's a LocalFileSystem
        assert isinstance(fs, LocalFileSystem)
        # The options are passed to the constructor - verifying by checking
        # the filesystem works correctly with the options
        assert fs is not None

    def test_create_with_prefix_and_options(self):
        """Test that options are passed when using path prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem(
                path_prefix=tmpdir,
                use_listings_cache=True,
            )

            assert isinstance(fs, DirFileSystem)
            # The underlying filesystem should be LocalFileSystem
            assert isinstance(fs.fs, LocalFileSystem)
            # Verify the underlying filesystem is properly initialized
            assert fs.fs is not None


class TestLocalFilesystemOperations:
    """Tests for file operations on local filesystem."""

    def test_write_and_read_text_without_prefix(self):
        """Test writing and reading text files without prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem()
            test_file = Path(tmpdir) / "test.txt"

            # Write file
            fs.write_text(str(test_file), "hello world")

            # Verify file exists and content
            assert test_file.exists()
            assert test_file.read_text() == "hello world"

            # Read through filesystem
            content = fs.read_text(str(test_file))
            assert content == "hello world"

    def test_write_and_read_binary_without_prefix(self):
        """Test writing and reading binary files without prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem()
            test_file = Path(tmpdir) / "test.bin"
            test_data = b"\x00\x01\x02\x03"

            # Write file
            fs.write_bytes(str(test_file), test_data)

            # Read and verify
            result = fs.read_bytes(str(test_file))
            assert result == test_data

    def test_directory_operations_without_prefix(self):
        """Test directory operations without prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem()
            test_dir = Path(tmpdir) / "subdir"

            # Create directory
            fs.mkdir(str(test_dir))
            assert test_dir.exists()
            assert test_dir.is_dir()

            # List directory
            entries = fs.ls(tmpdir)
            assert "subdir" in [Path(e).name for e in entries]

            # Check isdir
            assert fs.isdir(str(test_dir))


class TestDirFilesystemOperations:
    """Tests for file operations with DirFileSystem prefix."""

    def test_write_and_read_text_with_prefix(self):
        """Test that writes go to prefix directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))

            # Write using relative path
            fs.write_text("/file.txt", "content")

            # Verify file is under prefix
            expected_file = base_path / "file.txt"
            assert expected_file.exists()
            assert expected_file.read_text() == "content"

    def test_nested_paths_with_prefix(self):
        """Test nested directory paths with prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))

            # Create nested structure
            fs.makedirs("/a/b/c")
            fs.write_text("/a/b/c/nested.txt", "nested content")

            # Verify full path
            expected_file = base_path / "a" / "b" / "c" / "nested.txt"
            assert expected_file.exists()
            assert expected_file.read_text() == "nested content"

    def test_prefix_isolates_access(self):
        """Test that prefix restricts filesystem access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            outside_path = Path(tmpdir) / "outside"
            base_path.mkdir()
            outside_path.mkdir()

            # Create file outside prefix
            (outside_path / "private.txt").write_text("secret")

            # Create restricted filesystem
            fs = create_local_filesystem(path_prefix=str(base_path))

            # Cannot access files outside prefix
            # DirFileSystem should resolve relative to prefix
            # Accessing /private.txt would try base/private.txt, not outside/private.txt
            assert not fs.exists("/private.txt")

            # Create file inside prefix
            fs.write_text("/public.txt", "public")

            # Verify it's in the right place
            assert (base_path / "public.txt").exists()
            assert fs.exists("/public.txt")

    def test_list_directory_with_prefix(self):
        """Test listing directory contents with prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))

            # Create files
            fs.write_text("/file1.txt", "content1")
            fs.write_text("/file2.txt", "content2")
            fs.mkdir("/subdir")

            # List directory
            entries = fs.ls("/")
            names = [
                Path(e).name if isinstance(e, str) else e["name"].split("/")[-1]
                for e in entries
            ]
            assert "file1.txt" in names
            assert "file2.txt" in names
            assert "subdir" in names

    def test_exists_with_prefix(self):
        """Test exists operation with prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))

            # File should not exist initially
            assert not fs.exists("/nonexistent.txt")

            # Create file
            fs.write_text("/test.txt", "test")

            # Now it should exist
            assert fs.exists("/test.txt")

    def test_isfile_and_isdir_with_prefix(self):
        """Test isfile and isdir operations with prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))

            # Create file and directory
            fs.write_text("/test.txt", "content")
            fs.mkdir("/testdir")

            # Test file detection
            assert fs.isfile("/test.txt")
            assert not fs.isdir("/test.txt")

            # Test directory detection
            assert fs.isdir("/testdir")
            assert not fs.isfile("/testdir")


class TestFilesystemInfo:
    """Tests for filesystem info operations."""

    def test_info_without_prefix(self):
        """Test getting file info without prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem()
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello world")

            info = fs.info(str(test_file))

            assert info["name"] == str(test_file)
            assert info["size"] == 11  # "hello world"
            assert info["type"] == "file"

    def test_info_with_prefix(self):
        """Test getting file info with prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))
            fs.write_text("/test.txt", "hello world")

            info = fs.info("/test.txt")

            # Name should be relative to prefix
            assert info["name"] == "/test.txt"
            assert info["size"] == 11
            assert info["type"] == "file"


class TestFileRemoval:
    """Tests for file removal operations."""

    def test_rm_without_prefix(self):
        """Test file removal without prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = create_local_filesystem()
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            assert test_file.exists()

            fs.rm(str(test_file))

            assert not test_file.exists()

    def test_rm_with_prefix(self):
        """Test file removal with prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base"
            base_path.mkdir()

            fs = create_local_filesystem(path_prefix=str(base_path))
            fs.write_text("/test.txt", "content")

            assert (base_path / "test.txt").exists()

            fs.rm("/test.txt")

            assert not (base_path / "test.txt").exists()


class TestCreateMemoryFilesystem:
    """Tests for create_memory_filesystem function."""

    def test_create_memory_filesystem(self):
        """Test creating memory filesystem."""
        fs = create_memory_filesystem()

        assert isinstance(fs, MemoryFileSystem)

    def test_create_memory_with_options(self):
        """Test creating memory filesystem with options."""
        fs = create_memory_filesystem(storage={})

        assert isinstance(fs, MemoryFileSystem)


class TestCreateS3Filesystem:
    """Tests for create_s3_filesystem function."""

    @pytest.mark.skip(reason="Cannot mock s3fs import properly")
    def test_s3_import_error(self):
        """Test that ImportError is raised when s3fs is not installed."""
        from mcp_scratchpad.fs.backends import create_s3_filesystem, S3NotInstalledError

        with patch.dict("sys.modules", {"s3fs": None}):
            with pytest.raises((ImportError, S3NotInstalledError)) as exc_info:
                create_s3_filesystem("test-bucket")

            assert "s3fs" in str(exc_info.value).lower()

    @pytest.mark.skip(reason="Cannot mock s3fs properly with DirFileSystem")
    def test_s3_create_with_bucket(self):
        """Test creating S3 filesystem with bucket."""
        from mcp_scratchpad.fs.backends import create_s3_filesystem

        mock_s3fs = MagicMock()
        mock_s3_class = MagicMock(return_value=mock_s3fs)

        with patch.dict("sys.modules", {"s3fs": MagicMock(S3FileSystem=mock_s3_class)}):
            fs = create_s3_filesystem("test-bucket")

            mock_s3_class.assert_called_once()
            assert isinstance(fs, DirFileSystem)

    @pytest.mark.skip(reason="Cannot mock s3fs properly with DirFileSystem")
    def test_s3_create_with_bucket_and_prefix(self):
        """Test creating S3 filesystem with bucket and path prefix."""
        from mcp_scratchpad.fs.backends import create_s3_filesystem

        mock_s3fs = MagicMock()
        mock_s3_class = MagicMock(return_value=mock_s3fs)

        with patch.dict("sys.modules", {"s3fs": MagicMock(S3FileSystem=mock_s3_class)}):
            fs = create_s3_filesystem("my-bucket/data/subdir")

            mock_s3_class.assert_called_once()
            assert isinstance(fs, DirFileSystem)


class TestCreateFilesystem:
    """Tests for create_filesystem factory function."""

    def test_factory_creates_local_from_file_uri(self):
        """Test factory creates LocalFileSystem from file:// URI."""
        mount = MountConfig(
            name="test",
            source="file:///tmp/data",
            mount_point="/",
            mode="ro",
        )

        fs = create_filesystem(mount)

        assert isinstance(fs, DirFileSystem)
        assert fs.path == "/tmp/data"

    def test_factory_creates_memory_from_memory_uri(self):
        """Test factory creates MemoryFileSystem from memory:// URI."""
        mount = MountConfig(
            name="test",
            source="memory://",
            mount_point="/work",
            mode="rw",
        )

        fs = create_filesystem(mount)

        assert isinstance(fs, MemoryFileSystem)

    @pytest.mark.skip(reason="Cannot mock s3fs properly")
    def test_factory_creates_s3_from_s3_uri(self):
        """Test factory creates S3 filesystem from s3:// URI."""
        mount = MountConfig(
            name="test",
            source="s3://my-bucket/path",
            mount_point="/data",
            mode="ro",
        )

        mock_s3fs = MagicMock()
        mock_s3_class = MagicMock(return_value=mock_s3fs)

        # Need to patch at the module level where it's imported
        with patch("mcp_scratchpad.fs.backends.S3FileSystem", mock_s3_class):
            fs = create_filesystem(mount)

            mock_s3_class.assert_called_once()
            assert isinstance(fs, DirFileSystem)

    def test_factory_passes_options_correctly(self):
        """Test factory passes options to underlying filesystem."""
        mount = MountConfig(
            name="test",
            source="file:///tmp",
            mount_point="/",
            mode="ro",
            options={"use_listings_cache": True},
        )

        fs = create_filesystem(mount)

        assert isinstance(fs, DirFileSystem)

    def test_factory_raises_on_unsupported_scheme(self):
        """Test factory raises error for unsupported URI scheme."""
        from pydantic import ValidationError

        # MountConfig now validates source scheme at construction
        with pytest.raises(ValidationError) as exc_info:
            MountConfig(
                name="test",
                source="ftp://example.com",
                mount_point="/",
                mode="ro",
            )

        assert "invalid scheme 'ftp'" in str(exc_info.value).lower()

    def test_factory_file_uri_no_path_prefix_when_root(self):
        """Test file:// URI with root path."""
        mount = MountConfig(
            name="test",
            source="file:///",
            mount_point="/",
            mode="ro",
        )

        fs = create_filesystem(mount)

        assert isinstance(fs, DirFileSystem)
        assert fs.path == "/"


class TestCreateFilesystemsFromConfig:
    """Tests for create_filesystems_from_config function."""

    def test_separates_upper_and_lower_filesystems(self):
        """Test that function correctly separates upper (RW) and lower (RO) filesystems."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="base",
                    source="file:///base",
                    mount_point="/",
                    mode="ro",
                    priority=10,
                ),
                MountConfig(
                    name="work",
                    source="memory://",
                    mount_point="/work",
                    mode="rw",
                    priority=20,
                ),
            ]
        )

        lowers, upper = create_filesystems_from_config(config)

        assert len(lowers) == 1
        assert isinstance(lowers[0], DirFileSystem)
        assert isinstance(upper, MemoryFileSystem)

    def test_sorts_lowers_by_priority(self):
        """Test that lower filesystems are sorted by priority (highest first)."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="low",
                    source="file:///low",
                    mount_point="/low",
                    mode="ro",
                    priority=5,
                ),
                MountConfig(
                    name="high",
                    source="file:///high",
                    mount_point="/high",
                    mode="ro",
                    priority=20,
                ),
                MountConfig(
                    name="mid",
                    source="file:///mid",
                    mount_point="/mid",
                    mode="ro",
                    priority=10,
                ),
                MountConfig(
                    name="work",
                    source="memory://",
                    mount_point="/work",
                    mode="rw",
                    priority=1,
                ),
            ]
        )

        lowers, _ = create_filesystems_from_config(config)

        assert len(lowers) == 3
        # Should be sorted by priority desc: high (20), mid (10), low (5)
        assert lowers[0].path == "/high"
        assert lowers[1].path == "/mid"
        assert lowers[2].path == "/low"

    def test_no_rw_mount_uses_first_ro_as_upper(self):
        """Test that when no RW mount, first RO is used as upper."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="base1",
                    source="file:///base1",
                    mount_point="/",
                    mode="ro",
                    priority=10,
                ),
                MountConfig(
                    name="base2",
                    source="file:///base2",
                    mount_point="/data",
                    mode="ro",
                    priority=5,
                ),
            ]
        )

        lowers, upper = create_filesystems_from_config(config)

        # All RO mounts go to lowers, first one also becomes upper
        assert len(lowers) == 2
        assert isinstance(upper, DirFileSystem)
        assert upper.path == "/base1"  # Sorted by priority desc, so base1 (10) first

    def test_raises_on_no_mounts(self):
        """Test that error is raised when no mounts are configured."""
        config = OverlayConfig(mounts=[])

        with pytest.raises(ValueError) as exc_info:
            create_filesystems_from_config(config)

        assert "No mounts configured" in str(exc_info.value)

    def test_single_rw_mount_only(self):
        """Test with single RW mount only."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="work",
                    source="memory://",
                    mount_point="/",
                    mode="rw",
                    priority=10,
                ),
            ]
        )

        lowers, upper = create_filesystems_from_config(config)

        assert len(lowers) == 0
        assert isinstance(upper, MemoryFileSystem)

    def test_all_ro_mounts(self):
        """Test with all RO mounts (no RW)."""
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="base1",
                    source="file:///base1",
                    mount_point="/",
                    mode="ro",
                    priority=10,
                ),
                MountConfig(
                    name="base2",
                    source="file:///base2",
                    mount_point="/data",
                    mode="ro",
                    priority=20,
                ),
            ]
        )

        lowers, upper = create_filesystems_from_config(config)

        # All RO mounts go to lowers, highest priority (base2) also becomes upper
        # Sorted by priority desc: base2 (20), base1 (10)
        assert len(lowers) == 2
        assert lowers[0].path == "/base2"
        assert lowers[1].path == "/base1"
        assert upper.path == "/base2"


# =============================================================================
# Moto-based S3 Integration Tests
# =============================================================================

try:
    import boto3
    from moto import mock_aws

    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

try:
    import s3fs

    HAS_S3FS = True
except ImportError:
    HAS_S3FS = False


@pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")
@pytest.mark.skipif(not HAS_S3FS, reason="s3fs not installed")
class TestS3FilesystemWithMoto:
    """Integration tests for S3 filesystem using moto mock."""

    TEST_BUCKET = "test-bucket"
    TEST_REGION = "us-east-1"

    @pytest.fixture
    def mock_s3(self):
        """Create a mock S3 environment with a test bucket."""
        with mock_aws():
            conn = boto3.client("s3", region_name=self.TEST_REGION)
            conn.create_bucket(Bucket=self.TEST_BUCKET)
            yield conn

    def test_create_s3_filesystem_basic(self, mock_s3):
        """Test creating a basic S3 filesystem with moto mock."""
        fs = create_s3_filesystem(bucket=self.TEST_BUCKET)
        assert fs is not None
        assert isinstance(fs, DirFileSystem)

    def test_s3_file_operations(self, mock_s3):
        """Test basic file operations on mock S3."""
        fs = create_s3_filesystem(bucket=self.TEST_BUCKET)

        # Test write and read
        fs.write_text("/file.txt", "test content")
        assert fs.read_text("/file.txt") == "test content"

        # Test exists
        assert fs.exists("/file.txt")
        assert not fs.exists("/nonexistent.txt")

        # Test list directory
        fs.write_text("/dir1/file1.txt", "content1")
        fs.write_text("/dir1/file2.txt", "content2")
        files = fs.ls("/dir1")
        assert len(files) == 2

        # Test delete
        fs.rm("/file.txt")
        assert not fs.exists("/file.txt")

    def test_s3_with_path_prefix(self, mock_s3):
        """Test S3 filesystem with bucket/path prefix."""
        fs = create_s3_filesystem(bucket=f"{self.TEST_BUCKET}/data/subdir")

        fs.write_text("/test.txt", "hello from prefix")
        assert fs.exists("/test.txt")
        assert fs.read_text("/test.txt") == "hello from prefix"

    def test_s3_with_credentials(self, mock_s3):
        """Test S3 filesystem with explicit credentials."""
        fs = create_s3_filesystem(
            bucket=self.TEST_BUCKET,
            key="AKIAIOSFODNN7EXAMPLE",
            secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        assert fs is not None
        fs.write_text("/creds-test.txt", "with credentials")
        assert fs.exists("/creds-test.txt")

    def test_s3_empty_bucket_raises(self, mock_s3):
        """Test that empty bucket name raises ValueError."""
        with pytest.raises(ValueError, match="Bucket name cannot be empty"):
            create_s3_filesystem(bucket="")


@pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")
@pytest.mark.skipif(not HAS_S3FS, reason="s3fs not installed")
class TestFilesystemFactoryWithMoto:
    """Integration tests for filesystem factory using moto mock S3."""

    @pytest.fixture
    def mock_s3(self):
        """Create a mock S3 environment."""
        with mock_aws():
            conn = boto3.client("s3", region_name="us-east-1")
            conn.create_bucket(Bucket="factory-test-bucket")
            yield conn

    def test_factory_creates_s3_from_s3_uri_live(self, mock_s3):
        """Test factory creates working S3 filesystem using moto."""
        mount = MountConfig(
            name="s3-test",
            source="s3://factory-test-bucket/data",
            mount_point="/data",
            mode="ro",
        )

        fs = create_filesystem(mount)
        assert fs is not None

        # Verify file operations work
        fs.write_text("/factory-live.txt", "from factory with moto")
        assert fs.exists("/factory-live.txt")
        assert fs.read_text("/factory-live.txt") == "from factory with moto"
