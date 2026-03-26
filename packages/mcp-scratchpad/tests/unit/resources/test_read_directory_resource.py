"""
Unit tests for read_directory_resource function.

This module tests the read_directory_resource function with various scenarios
including pagination, error handling, and edge cases.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.read_handler import (
    read_directory_resource,
    set_session_manager,
    DirectoryListingResult,
)

# Valid UUID for testing
TEST_SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def mock_fs():
    """Create a mock filesystem for testing."""
    fs = MagicMock()
    return fs


@pytest.fixture
def mock_session_manager(mock_fs):
    """Create a mock session manager for testing."""
    manager = MagicMock()
    manager.get_session_fs.return_value = mock_fs
    return manager


@pytest.fixture
def real_session_manager():
    """Create a real session manager for integration testing."""
    config = OverlayConfig(mounts=[])
    manager = SessionFileSystemManager(config)
    session_id = manager.create_session()
    fs = manager.get_session_fs(session_id)
    return manager, session_id, fs


class TestReadDirectoryResource:
    """Tests for read_directory_resource function."""

    def test_read_directory_success(self, mock_session_manager, mock_fs):
        """Test successful directory reading."""
        mock_fs.exists.return_value = True

        # Mock isdir - should return True for workspace itself, then for subdirs
        def mock_isdir(path):
            if path == "/workspace":
                return True
            return "subdir" in path

        mock_fs.isdir.side_effect = mock_isdir
        mock_fs.ls.return_value = [
            "/workspace/file1.txt",
            "/workspace/file2.txt",
            "/workspace/subdir",
        ]

        def mock_info(path):
            if "subdir" in path:
                return {"size": 0, "type": "directory", "mtime": 1609459200}
            return {"size": 100, "type": "file", "mtime": 1609459200}

        mock_fs.info.side_effect = mock_info

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is True
        assert result.session_id == TEST_SESSION_ID
        assert result.path == "/workspace"
        assert len(result.entries) == 3

    def test_read_directory_pagination(self, mock_session_manager, mock_fs):
        """Test directory reading with pagination."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.side_effect = lambda p: p == "/workspace"

        # Create 150 entries for pagination testing - with full paths
        all_entries = [f"/workspace/file{i:03d}.txt" for i in range(150)]
        mock_fs.ls.return_value = all_entries
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        # Test first page
        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager, limit=50, offset=0)

        assert result.success is True
        assert len(result.entries) == 50
        assert result.total_count == 150
        assert result.has_more is True
        assert result.offset == 0
        assert result.limit == 50

    def test_read_directory_pagination_second_page(self, mock_session_manager, mock_fs):
        """Test directory reading with pagination - second page."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.side_effect = lambda p: p == "/workspace"

        all_entries = [f"/workspace/file{i:03d}.txt" for i in range(150)]
        mock_fs.ls.return_value = all_entries
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        # Test second page
        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager, limit=50, offset=50)

        assert result.success is True
        assert len(result.entries) == 50
        assert result.offset == 50
        assert result.has_more is True

    def test_read_directory_pagination_last_page(self, mock_session_manager, mock_fs):
        """Test directory reading with pagination - last page."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.side_effect = lambda p: p == "/workspace"

        all_entries = [f"/workspace/file{i:03d}.txt" for i in range(150)]
        mock_fs.ls.return_value = all_entries
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        # Test last page
        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(
            uri, mock_session_manager, limit=50, offset=100
        )

        assert result.success is True
        assert len(result.entries) == 50
        assert result.offset == 100
        assert result.has_more is False  # No more pages

    def test_read_directory_empty(self, mock_session_manager, mock_fs):
        """Test reading an empty directory."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = True
        mock_fs.ls.return_value = []

        uri = f"scratchpad://{TEST_SESSION_ID}/emptydir"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is True
        assert len(result.entries) == 0
        assert result.total_count == 0
        assert result.has_more is False

    def test_read_directory_not_found(self, mock_session_manager, mock_fs):
        """Test reading a non-existent directory."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/nonexistent"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_read_directory_not_a_directory(self, mock_session_manager, mock_fs):
        """Test reading a file as if it were a directory."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False  # It's a file, not a directory

        uri = f"scratchpad://{TEST_SESSION_ID}/file.txt"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "not a directory" in result.error.lower()

    def test_read_directory_session_not_found(self, mock_session_manager):
        """Test reading directory with invalid session."""
        mock_session_manager.get_session_fs.return_value = None

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "Session not found" in result.error

    def test_read_directory_invalid_uri(self):
        """Test reading directory with invalid URI."""
        result = read_directory_resource("invalid://uri")

        assert result.success is False
        assert result.error is not None

    def test_read_directory_empty_uri(self):
        """Test reading directory with empty URI."""
        result = read_directory_resource("")

        assert result.success is False
        assert result.error is not None

    def test_read_directory_no_session_manager(self):
        """Test reading directory without session manager."""
        set_session_manager(None)

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri)

        assert result.success is False
        assert "Session manager" in result.error

    def test_read_directory_list_error(self, mock_session_manager, mock_fs):
        """Test handling error during directory listing."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = True
        mock_fs.ls.side_effect = OSError("Permission denied")

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "Failed to list directory" in result.error

    def test_read_directory_entry_with_error(self, mock_session_manager, mock_fs):
        """Test directory reading when some entries cause errors."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.side_effect = lambda p: p == "/workspace"
        mock_fs.ls.return_value = [
            "/workspace/file1.txt",
            "/workspace/badfile",
            "/workspace/file2.txt",
        ]

        def mock_info(path):
            if "badfile" in path:
                raise OSError("Cannot access")
            return {"size": 100, "type": "file", "mtime": 1609459200}

        mock_fs.info.side_effect = mock_info

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager)

        # Should succeed with only the valid entries
        assert result.success is True
        assert len(result.entries) == 2  # Skipped the bad entry

    def test_read_directory_to_dict(self, mock_session_manager, mock_fs):
        """Test converting directory result to dictionary."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.side_effect = lambda p: p == "/workspace"
        mock_fs.ls.return_value = ["/workspace/file.txt"]
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager)
        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["uri"] == uri
        assert result_dict["session_id"] == TEST_SESSION_ID
        assert "entries" in result_dict
        assert result_dict["total_count"] == 1
        assert result_dict["has_more"] is False


class TestReadDirectoryResourceIntegration:
    """Integration tests for read_directory_resource with real filesystem."""

    def test_read_real_directory(self, real_session_manager):
        """Test reading a real directory."""
        manager, session_id, fs = real_session_manager

        # Create test files
        fs.write_text("/workspace/file1.txt", "content1")
        fs.write_text("/workspace/file2.txt", "content2")
        fs.mkdir("/workspace/subdir")

        uri = f"scratchpad://{session_id}/workspace"
        set_session_manager(manager)
        result = read_directory_resource(uri)

        assert result.success is True
        assert result.session_id == session_id
        assert len(result.entries) == 3

        # Check entry names
        names = {e.name for e in result.entries}
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    def test_read_real_directory_pagination(self, real_session_manager):
        """Test pagination with real directory."""
        manager, session_id, fs = real_session_manager

        # Create 25 test files
        for i in range(25):
            fs.write_text(f"/workspace/file{i:02d}.txt", f"content{i}")

        uri = f"scratchpad://{session_id}/workspace"
        set_session_manager(manager)

        # Get first page
        result1 = read_directory_resource(uri, limit=10, offset=0)
        assert result1.success is True
        assert len(result1.entries) == 10
        assert result1.has_more is True

        # Get second page
        result2 = read_directory_resource(uri, limit=10, offset=10)
        assert result2.success is True
        assert len(result2.entries) == 10
        assert result2.has_more is True

        # Get third page - may include more than 5 due to directories created
        result3 = read_directory_resource(uri, limit=10, offset=20)
        assert result3.success is True
        assert len(result3.entries) >= 5  # At least the remaining files
        assert result3.has_more is False

    def test_read_real_directory_empty(self, real_session_manager):
        """Test reading an empty real directory."""
        manager, session_id, fs = real_session_manager

        fs.mkdir("/emptydir")

        uri = f"scratchpad://{session_id}/emptydir"
        set_session_manager(manager)
        result = read_directory_resource(uri)

        assert result.success is True
        assert len(result.entries) == 0
        assert result.total_count == 0
