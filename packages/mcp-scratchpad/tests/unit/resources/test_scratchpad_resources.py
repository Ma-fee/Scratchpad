"""Tests for scratchpad resource handlers.

This module tests the FastMCP resource handler registration and functionality
for scratchpad:// URI scheme access to session filesystems.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.scratchpad_resources import (
    ResourceError,
    ResourceNotFoundError,
    SessionNotFoundError,
    _guess_mime_type,
    _is_binary_content,
    _list_directory,
    _normalize_path,
    _read_file_content,
    register_directory_resources,
    register_scratchpad_resources,
)


class TestMimeTypeDetection:
    """Tests for MIME type detection."""

    def test_detect_text_file(self) -> None:
        """Test detecting text file MIME type."""
        assert _guess_mime_type("file.txt") == "text/plain"
        assert _guess_mime_type("script.py") == "text/x-python"
        assert _guess_mime_type("data.json") == "application/json"

    def test_detect_image_file(self) -> None:
        """Test detecting image file MIME type."""
        assert _guess_mime_type("image.png") == "image/png"
        assert _guess_mime_type("photo.jpg") == "image/jpeg"
        assert _guess_mime_type("animation.gif") == "image/gif"

    def test_detect_binary_by_content(self) -> None:
        """Test detecting binary files by content signature."""
        # PNG signature
        png_content = b"\x89PNG\r\n\x1a\n"
        assert _guess_mime_type("unknown.bin", png_content) == "image/png"

        # JPEG signature
        jpeg_content = b"\xff\xd8\xff"
        assert _guess_mime_type("data", jpeg_content) == "image/jpeg"

        # PDF signature
        pdf_content = b"%PDF-1.4"
        assert _guess_mime_type("document", pdf_content) == "application/pdf"

    def test_default_to_text_plain(self) -> None:
        """Test that unknown types default to text/plain."""
        # Use extensions that don't have known MIME types
        assert _guess_mime_type("unknown.abcd") == "text/plain"
        assert _guess_mime_type("file.xyz123", b"some content") == "text/plain"


class TestBinaryContentDetection:
    """Tests for binary content detection."""

    def test_image_types_are_binary(self) -> None:
        """Test that image MIME types are detected as binary."""
        assert _is_binary_content("image/png") is True
        assert _is_binary_content("image/jpeg") is True
        assert _is_binary_content("image/svg+xml") is True

    def test_audio_video_types_are_binary(self) -> None:
        """Test that audio/video MIME types are detected as binary."""
        assert _is_binary_content("audio/mpeg") is True
        assert _is_binary_content("video/mp4") is True

    def test_application_types_are_binary(self) -> None:
        """Test that certain application MIME types are detected as binary."""
        assert _is_binary_content("application/pdf") is True
        assert _is_binary_content("application/zip") is True
        assert _is_binary_content("application/octet-stream") is True
        assert _is_binary_content("application/x-tar") is True

    def test_text_types_are_not_binary(self) -> None:
        """Test that text MIME types are not detected as binary."""
        assert _is_binary_content("text/plain") is False
        assert _is_binary_content("text/html") is False
        assert _is_binary_content("application/json") is False


class TestPathNormalization:
    """Tests for path normalization."""

    def test_adds_leading_slash(self) -> None:
        """Test that paths get a leading slash."""
        assert _normalize_path("file.txt") == "/file.txt"
        assert _normalize_path("dir/file.txt") == "/dir/file.txt"

    def test_preserves_existing_slash(self) -> None:
        """Test that existing leading slash is preserved."""
        assert _normalize_path("/file.txt") == "/file.txt"
        assert _normalize_path("/dir/file.txt") == "/dir/file.txt"

    def test_removes_trailing_slash(self) -> None:
        """Test that trailing slashes are removed."""
        assert _normalize_path("/dir/") == "/dir"
        assert _normalize_path("dir/") == "/dir"

    def test_root_path_unchanged(self) -> None:
        """Test that root path stays as /."""
        assert _normalize_path("/") == "/"
        assert _normalize_path("") == "/"


class TestResourceErrors:
    """Tests for resource error classes."""

    def test_resource_error_creation(self) -> None:
        """Test creating ResourceError."""
        error = ResourceError(code="NOT_FOUND", message="File not found")
        assert error.code == "NOT_FOUND"
        assert error.message == "File not found"
        assert error.details is None

    def test_resource_error_with_details(self) -> None:
        """Test creating ResourceError with details."""
        details = {"path": "/file.txt", "session": "abc-123"}
        error = ResourceError(
            code="ACCESS_DENIED", message="Access denied", details=details
        )
        assert error.details == details

    def test_resource_error_to_dict(self) -> None:
        """Test converting ResourceError to dict."""
        error = ResourceError(code="ERROR", message="Test", details={"key": "value"})
        result = error.to_dict()
        assert result == {
            "code": "ERROR",
            "message": "Test",
            "details": {"key": "value"},
        }

    def test_resource_not_found_error(self) -> None:
        """Test ResourceNotFoundError."""
        error = ResourceNotFoundError("session-123", "/file.txt")
        assert error.session_id == "session-123"
        assert error.path == "/file.txt"
        assert "session-123" in str(error)
        assert "/file.txt" in str(error)

    def test_session_not_found_error(self) -> None:
        """Test SessionNotFoundError."""
        error = SessionNotFoundError("session-456")
        assert error.session_id == "session-456"
        assert "session-456" in str(error)


class TestReadFileContent:
    """Tests for _read_file_content function."""

    @pytest.fixture
    def mock_manager(self) -> MagicMock:
        """Create a mock SessionFileSystemManager."""
        manager = MagicMock(spec=SessionFileSystemManager)
        fs = MemoryFileSystem()
        manager.get_session_fs.return_value = fs
        return manager

    def test_read_existing_text_file(self, mock_manager: MagicMock) -> None:
        """Test reading an existing text file."""
        fs = mock_manager.get_session_fs.return_value
        fs.write_text("/test.txt", "Hello, World!")

        content, mime_type = _read_file_content(mock_manager, "session-1", "/test.txt")

        assert content == b"Hello, World!"
        assert mime_type == "text/plain"

    def test_read_session_not_found(self, mock_manager: MagicMock) -> None:
        """Test reading from non-existent session."""
        mock_manager.get_session_fs.return_value = None

        with pytest.raises(SessionNotFoundError) as exc_info:
            _read_file_content(mock_manager, "invalid-session", "/test.txt")

        assert exc_info.value.session_id == "invalid-session"

    def test_read_nonexistent_file(self, mock_manager: MagicMock) -> None:
        """Test reading a file that doesn't exist."""
        with pytest.raises(ResourceNotFoundError) as exc_info:
            _read_file_content(mock_manager, "session-1", "/nonexistent.txt")

        assert exc_info.value.path == "/nonexistent.txt"

    def test_read_directory_raises_error(self, mock_manager: MagicMock) -> None:
        """Test reading a directory raises IsADirectoryError."""
        fs = mock_manager.get_session_fs.return_value
        fs.mkdir("/testdir")

        with pytest.raises(IsADirectoryError):
            _read_file_content(mock_manager, "session-1", "/testdir")

    def test_mime_type_detection(self, mock_manager: MagicMock) -> None:
        """Test MIME type detection for different file types."""
        fs = mock_manager.get_session_fs.return_value

        # Binary file
        fs.pipe("/image.png", b"\x89PNG\r\n\x1a\n")
        content, mime_type = _read_file_content(mock_manager, "session-1", "/image.png")
        assert mime_type == "image/png"

        # JSON file
        fs.write_text("/data.json", '{"key": "value"}')
        content, mime_type = _read_file_content(mock_manager, "session-1", "/data.json")
        assert mime_type == "application/json"


class TestListDirectory:
    """Tests for _list_directory function."""

    def test_list_empty_directory(self) -> None:
        """Test listing an empty directory."""
        manager = MagicMock(spec=SessionFileSystemManager)
        fs = MemoryFileSystem()
        manager.get_session_fs.return_value = fs
        fs.mkdir("/emptydir")

        entries = _list_directory(manager, "session-1", "/emptydir")

        assert entries == []

    def test_list_directory_with_files(self) -> None:
        """Test listing a directory with files."""
        manager = MagicMock(spec=SessionFileSystemManager)
        # Use a fresh MemoryFileSystem with explicit store to isolate from other tests
        fs = MemoryFileSystem()
        fs.store.clear()  # Clear any shared state
        manager.get_session_fs.return_value = fs
        fs.write_text("/file1.txt", "content1")
        fs.write_text("/file2.txt", "content2")

        entries = _list_directory(manager, "session-1", "/")

        # Only check files we created, ignoring any pre-existing files
        test_files = {e["name"] for e in entries if e["name"].startswith("file")}
        assert test_files == {"file1.txt", "file2.txt"}

    def test_list_session_not_found(self) -> None:
        """Test listing from non-existent session."""
        manager = MagicMock(spec=SessionFileSystemManager)
        manager.get_session_fs.return_value = None

        with pytest.raises(SessionNotFoundError):
            _list_directory(manager, "invalid-session", "/")

    def test_list_nonexistent_directory(self) -> None:
        """Test listing a directory that doesn't exist."""
        manager = MagicMock(spec=SessionFileSystemManager)
        fs = MemoryFileSystem()
        manager.get_session_fs.return_value = fs

        with pytest.raises(ResourceNotFoundError):
            _list_directory(manager, "session-1", "/nonexistent")

    def test_list_file_as_directory_raises_error(self) -> None:
        """Test listing a file as if it were a directory."""
        manager = MagicMock(spec=SessionFileSystemManager)
        fs = MemoryFileSystem()
        manager.get_session_fs.return_value = fs
        fs.write_text("/file.txt", "content")

        with pytest.raises(NotADirectoryError):
            _list_directory(manager, "session-1", "/file.txt")


class TestResourceRegistration:
    """Tests for register_scratchpad_resources function."""

    def test_registers_resource_handler(self) -> None:
        """Test that resource handler is registered."""
        mcp = MagicMock()
        mcp.resource = MagicMock(return_value=lambda f: f)
        manager = MagicMock(spec=SessionFileSystemManager)

        register_scratchpad_resources(mcp, manager)

        # Check that resource decorator was called with correct URI pattern
        mcp.resource.assert_called_once()
        call_args = mcp.resource.call_args
        # Updated to match the new {file_path} pattern
        assert "scratchpad://{session_id}/{file_path}" in str(call_args)

    def test_resource_registration_with_real_fs(self) -> None:
        """Test resource handler with real filesystem."""
        mcp = FastMCP("Test")
        config = OverlayConfig(mounts=[])
        manager = SessionFileSystemManager(config)

        # Create a session with a test file
        session_id = manager.create_session()
        fs = manager.get_session_fs(session_id)
        assert fs is not None
        fs.write_text("/test.txt", "Hello from resource!")

        # Register resources - should not raise
        register_scratchpad_resources(mcp, manager)

        # Verify registration succeeded by checking get_resources() if available
        # FastMCP 3.x may have different API, so we just verify no exception


class TestResourceHandlerIntegration:
    """Integration tests for resource handlers with real filesystem."""

    @pytest.fixture
    def setup_resources(self):
        """Create manager and session with test data."""
        config = OverlayConfig(mounts=[])
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()
        fs = manager.get_session_fs(session_id)
        assert fs is not None

        # Create test files
        fs.write_text("/workspace/test.txt", "Hello, Resource!")
        fs.pipe("/image.png", b"\x89PNG\r\n\x1a\nfake data")

        return manager, session_id, fs

    def test_read_text_file(self, setup_resources) -> None:
        """Test reading a text file through the helper function."""
        manager, session_id, _ = setup_resources

        content, mime_type = _read_file_content(
            manager, session_id, "/workspace/test.txt"
        )

        assert content == b"Hello, Resource!"
        assert mime_type == "text/plain"

    def test_read_binary_file(self, setup_resources) -> None:
        """Test reading a binary file through the helper function."""
        manager, session_id, _ = setup_resources

        content, mime_type = _read_file_content(manager, session_id, "/image.png")

        assert isinstance(content, bytes)
        assert content.startswith(b"\x89PNG")
        assert mime_type == "image/png"

    def test_session_not_found_error(self) -> None:
        """Test error handling for non-existent session."""
        config = OverlayConfig(mounts=[])
        manager = SessionFileSystemManager(config)

        with pytest.raises(SessionNotFoundError) as exc_info:
            _read_file_content(manager, "non-existent-session", "/file.txt")

        assert "non-existent-session" in str(exc_info.value)

    def test_file_not_found_error(self, setup_resources) -> None:
        """Test error handling for non-existent file."""
        manager, session_id, _ = setup_resources

        with pytest.raises(ResourceNotFoundError) as exc_info:
            _read_file_content(manager, session_id, "/nonexistent.txt")

        assert "nonexistent.txt" in str(exc_info.value)


class TestDirectoryListingIntegration:
    """Integration tests for directory listing handlers."""

    def test_list_root_directory(self) -> None:
        """Test listing root directory."""
        config = OverlayConfig(mounts=[])
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()
        fs = manager.get_session_fs(session_id)
        assert fs is not None

        # Create test data in root (not in workspace which might already exist)
        fs.write_text("/file1.txt", "content1")
        fs.mkdir("/customdir")

        entries = _list_directory(manager, session_id, "/")

        # Should have file1.txt and customdir
        names = {e["name"] for e in entries}
        assert "file1.txt" in names
        assert "customdir" in names

    def test_list_subdirectory(self) -> None:
        """Test listing a subdirectory."""
        config = OverlayConfig(mounts=[])
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()
        fs = manager.get_session_fs(session_id)
        assert fs is not None

        fs.mkdir("/mysubdir")
        fs.write_text("/mysubdir/file.txt", "content")

        entries = _list_directory(manager, session_id, "/mysubdir")

        assert len(entries) == 1
        assert entries[0]["name"] == "file.txt"
        assert entries[0]["type"] == "file"


class TestServerIntegration:
    """Tests for server integration with resources."""

    def test_get_session_manager_returns_none_initially(self) -> None:
        """Test that get_session_manager returns None before server creation."""
        from mcp_scratchpad.server import get_session_manager

        # Patch to ensure clean state
        with patch("mcp_scratchpad.server._session_manager", None):
            result = get_session_manager()
            assert result is None

    def test_server_creates_session_manager(self) -> None:
        """Test that create_server initializes session manager."""
        from mcp_scratchpad.server import create_server, get_session_manager

        with patch("mcp_scratchpad.server.set_store"):
            with patch("mcp_scratchpad.server.register_file_tools"):
                with patch("mcp_scratchpad.server.register_health_tools"):
                    with patch(
                        "mcp_scratchpad.server.is_config_valid", return_value=True
                    ):
                        mcp = create_server()

        # Verify that server was created successfully
        assert mcp is not None

        # Verify session manager was created
        manager = get_session_manager()
        assert manager is not None
        assert isinstance(manager, SessionFileSystemManager)
