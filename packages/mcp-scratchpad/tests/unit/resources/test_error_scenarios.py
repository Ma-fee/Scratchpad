"""
Unit tests for error scenarios in resource handlers.

This module tests all error conditions:
- SessionNotFoundError
- ResourceNotFoundError
- NotADirectoryError
- IsADirectoryError
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.scratchpad_resources import (
    ResourceNotFoundError,
    SessionNotFoundError,
    _read_file_content,
    _list_directory,
    _normalize_path,
)
from mcp_scratchpad.resources.read_handler import (
    read_resource,
    read_directory_resource,
    set_session_manager,
    ResourceReadError,
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


class TestSessionNotFoundError:
    """Tests for SessionNotFoundError scenarios."""

    def test_session_not_found_error_creation(self):
        """Test SessionNotFoundError exception creation."""
        error = SessionNotFoundError("invalid-session-id")

        assert error.session_id == "invalid-session-id"
        assert "invalid-session-id" in str(error)

    def test_read_file_content_session_not_found(self, mock_session_manager):
        """Test _read_file_content with non-existent session."""
        mock_session_manager.get_session_fs.return_value = None

        with pytest.raises(SessionNotFoundError) as exc_info:
            _read_file_content(mock_session_manager, "invalid-session", "/file.txt")

        assert exc_info.value.session_id == "invalid-session"

    def test_list_directory_session_not_found(self, mock_session_manager):
        """Test _list_directory with non-existent session."""
        mock_session_manager.get_session_fs.return_value = None

        with pytest.raises(SessionNotFoundError) as exc_info:
            _list_directory(mock_session_manager, "invalid-session", "/")

        assert exc_info.value.session_id == "invalid-session"

    def test_read_resource_session_not_found(self, mock_session_manager):
        """Test read_resource with non-existent session."""
        mock_session_manager.get_session_fs.return_value = None

        uri = f"scratchpad://{TEST_SESSION_ID}/file.txt"
        result = read_resource(uri, mock_session_manager)

        assert result.success is False
        assert "Session not found" in result.error

    def test_read_directory_resource_session_not_found(self, mock_session_manager):
        """Test read_directory_resource with non-existent session."""
        mock_session_manager.get_session_fs.return_value = None

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "Session not found" in result.error


class TestResourceNotFoundError:
    """Tests for ResourceNotFoundError scenarios."""

    def test_resource_not_found_error_creation(self):
        """Test ResourceNotFoundError exception creation."""
        error = ResourceNotFoundError("session-123", "/missing/file.txt")

        assert error.session_id == "session-123"
        assert error.path == "/missing/file.txt"
        assert "session-123" in str(error)
        assert "/missing/file.txt" in str(error)

    def test_read_file_content_resource_not_found(self, mock_session_manager, mock_fs):
        """Test _read_file_content with non-existent file."""
        mock_fs.exists.return_value = False

        with pytest.raises(ResourceNotFoundError) as exc_info:
            _read_file_content(mock_session_manager, "session-123", "/missing.txt")

        assert exc_info.value.path == "/missing.txt"

    def test_list_directory_resource_not_found(self, mock_session_manager, mock_fs):
        """Test _list_directory with non-existent directory."""
        mock_fs.exists.return_value = False

        with pytest.raises(ResourceNotFoundError) as exc_info:
            _list_directory(mock_session_manager, "session-123", "/missing")

        assert "/missing" in str(exc_info.value)

    def test_read_resource_file_not_found(self, mock_session_manager, mock_fs):
        """Test read_resource with non-existent file."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/missing.txt"
        result = read_resource(uri, mock_session_manager)

        assert result.success is False
        assert "File not found" in result.error

    def test_read_directory_resource_not_found(self, mock_session_manager, mock_fs):
        """Test read_directory_resource with non-existent directory."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/missing"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "not found" in result.error.lower()


class TestIsADirectoryError:
    """Tests for IsADirectoryError scenarios."""

    def test_read_file_content_is_directory(self, mock_session_manager, mock_fs):
        """Test _read_file_content when path is a directory."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = True
        mock_fs.info.return_value = {"type": "directory"}
        mock_fs.open.side_effect = IsADirectoryError("Path is a directory")

        with pytest.raises(IsADirectoryError):
            _read_file_content(mock_session_manager, "session-123", "/workspace")

    def test_read_resource_path_is_directory(self, mock_session_manager, mock_fs):
        """Test read_resource when path is a directory."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = True

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_resource(uri, mock_session_manager)

        assert result.success is False
        assert "directory" in result.error.lower()
        assert result.metadata.is_directory is True


class TestNotADirectoryError:
    """Tests for NotADirectoryError scenarios."""

    def test_list_directory_not_a_directory(self, mock_session_manager, mock_fs):
        """Test _list_directory when path is a file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False

        with pytest.raises(NotADirectoryError):
            _list_directory(mock_session_manager, "session-123", "/file.txt")

    def test_read_directory_resource_not_a_directory(
        self, mock_session_manager, mock_fs
    ):
        """Test read_directory_resource when path is a file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/file.txt"
        result = read_directory_resource(uri, mock_session_manager)

        assert result.success is False
        assert "not a directory" in result.error.lower()


class TestResourceReadError:
    """Tests for ResourceReadError scenarios."""

    def test_resource_read_error_creation(self):
        """Test ResourceReadError exception creation."""
        error = ResourceReadError("Failed to read", uri="scratchpad://test/file.txt")

        assert error.message == "Failed to read"
        assert error.uri == "scratchpad://test/file.txt"
        assert error.code == "RESOURCE_ERROR"

    def test_resource_read_error_with_custom_code(self):
        """Test ResourceReadError with custom code."""
        error = ResourceReadError(
            "Permission denied",
            uri="scratchpad://test/file.txt",
            code="PERMISSION_DENIED",
        )

        assert error.code == "PERMISSION_DENIED"

    def test_resource_read_error_str_representation(self):
        """Test ResourceReadError string representation."""
        error = ResourceReadError("Something went wrong")

        assert str(error) == "Something went wrong"


class TestNormalizePathEdgeCases:
    """Tests for _normalize_path edge cases."""

    def test_normalize_path_empty(self):
        """Test normalizing empty path."""
        result = _normalize_path("")
        assert result == "/"

    def test_normalize_path_root(self):
        """Test normalizing root path."""
        result = _normalize_path("/")
        assert result == "/"

    def test_normalize_path_without_leading_slash(self):
        """Test normalizing path without leading slash."""
        result = _normalize_path("workspace/file.txt")
        assert result == "/workspace/file.txt"

    def test_normalize_path_with_trailing_slash(self):
        """Test normalizing path with trailing slash."""
        result = _normalize_path("/workspace/")
        assert result == "/workspace"

    def test_normalize_path_complex(self):
        """Test normalizing complex path."""
        result = _normalize_path("workspace/nested/deep/file.txt")
        assert result == "/workspace/nested/deep/file.txt"


class TestInvalidURIErrorScenarios:
    """Tests for invalid URI error scenarios."""

    def test_read_resource_invalid_scheme(self):
        """Test read_resource with invalid URI scheme."""
        result = read_resource("http://example.com/file.txt")

        assert result.success is False
        assert "Invalid scheme" in result.error or "scheme" in result.error.lower()

    def test_read_resource_empty_uri(self):
        """Test read_resource with empty URI."""
        result = read_resource("")

        assert result.success is False
        assert result.error is not None

    def test_read_resource_missing_session_id(self):
        """Test read_resource with missing session ID."""
        result = read_resource("scratchpad:///file.txt")

        assert result.success is False

    def test_read_directory_resource_invalid_scheme(self):
        """Test read_directory_resource with invalid URI scheme."""
        result = read_directory_resource("http://example.com/workspace")

        assert result.success is False

    def test_read_directory_resource_empty_uri(self):
        """Test read_directory_resource with empty URI."""
        result = read_directory_resource("")

        assert result.success is False
        assert result.error is not None


class TestNoSessionManagerError:
    """Tests for missing session manager error scenarios."""

    def test_read_resource_no_session_manager(self):
        """Test read_resource without session manager."""
        set_session_manager(None)

        uri = f"scratchpad://{TEST_SESSION_ID}/file.txt"
        result = read_resource(uri)

        assert result.success is False
        assert "Session manager" in result.error

    def test_read_directory_resource_no_session_manager(self):
        """Test read_directory_resource without session manager."""
        set_session_manager(None)

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_directory_resource(uri)

        assert result.success is False
        assert "Session manager" in result.error
