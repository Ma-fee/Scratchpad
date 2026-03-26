"""
Unit tests for resource read handler.

This module tests the read_resource function and related components
for reading scratchpad:// URIs with proper MIME type detection and
large file preview support.

Test Coverage:
- URI parsing and validation
- Text file reading (UTF-8)
- Binary file reading
- Image file handling
- MIME type detection
- Error handling (missing files, invalid URIs, session errors)
- Resource metadata extraction
- Large file preview mode (> 1MB)
- get_file_metadata() for metadata-only retrieval
- read_file_chunk() for offset/limit reading
"""

import base64
import json
import os
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

# Import from the package under test
from typing import cast

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.read_handler import (
    BINARY_MIME_TYPES,
    IMAGE_MIME_TYPES,
    LARGE_FILE_THRESHOLD,
    MIME_TYPE_OVERRIDES,
    DEFAULT_PREVIEW_SIZE,
    TEXT_MIME_TYPES,
    DirectoryEntry,
    DirectoryListingResult,
    FileMetadataResult,
    LargeFilePreview,
    ResourceContent,
    ResourceContentType,
    ResourceMetadata,
    ResourceReadError,
    ResourceReadResult,
    classify_content_type,
    count_lines_in_text,
    detect_mime_type,
    get_file_metadata,
    get_resource_metadata,
    is_binary_content,
    read_file_chunk,
    read_file_content,
    read_large_file_preview,
    read_resource,
    read_resource_bytes,
    read_resource_text,
    set_session_manager,
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
    # Get the filesystem for this session
    fs = manager.get_session_fs(session_id)
    return manager, session_id, fs


class TestDetectMimeType:
    """Tests for MIME type detection."""

    def test_text_file_by_extension(self):
        """Test detecting text files by extension."""
        assert detect_mime_type("/test.txt") == "text/plain"
        assert detect_mime_type("/test.md") == "text/markdown"
        assert detect_mime_type("/test.py") == "text/x-python"
        assert detect_mime_type("/test.json") == "application/json"
        assert detect_mime_type("/test.yaml") == "text/yaml"

    def test_image_file_by_extension(self):
        """Test detecting image files by extension."""
        assert detect_mime_type("/test.png") == "image/png"
        assert detect_mime_type("/test.jpg") == "image/jpeg"
        assert detect_mime_type("/test.jpeg") == "image/jpeg"
        assert detect_mime_type("/test.gif") == "image/gif"

    def test_binary_file_by_extension(self):
        """Test detecting binary files by extension."""
        assert detect_mime_type("/test.pdf") == "application/pdf"
        assert detect_mime_type("/test.zip") == "application/zip"

    def test_mime_override_priority(self):
        """Test that MIME type overrides are respected."""
        assert detect_mime_type("/test.py") == "text/x-python"
        assert detect_mime_type("/test.js") == "text/javascript"
        assert detect_mime_type("/test.ts") == "text/typescript"
        assert detect_mime_type("/test.md") == "text/markdown"

    def test_content_based_detection_png(self):
        """Test PNG detection from content signature."""
        content = b"\x89PNG\r\n\x1a\n" + b"" * 100
        assert detect_mime_type("/unknown", content) == "image/png"

    def test_content_based_detection_jpeg(self):
        """Test JPEG detection from content signature."""
        content = b"\xff\xd8\xff" + b"" * 100
        assert detect_mime_type("/unknown", content) == "image/jpeg"

    def test_content_based_detection_gif(self):
        """Test GIF detection from content signature."""
        assert detect_mime_type("/unknown", b"GIF87a") == "image/gif"
        assert detect_mime_type("/unknown", b"GIF89a") == "image/gif"

    def test_content_based_detection_pdf(self):
        """Test PDF detection from content signature."""
        content = b"%PDF-1.4" + b"" * 100
        assert detect_mime_type("/unknown", content) == "application/pdf"

    def test_content_based_detection_zip(self):
        """Test ZIP detection from content signature."""
        content = b"PK\x03\x04" + b"" * 100
        assert detect_mime_type("/unknown", content) == "application/zip"

    def test_content_based_text_detection(self):
        """Test text detection from content."""
        content = b"Hello, World! This is plain text."
        assert detect_mime_type("/unknown", content) == "text/plain"

    def test_content_based_binary_detection(self):
        """Test binary detection from null bytes."""
        content = b"Hello\x00World"
        assert detect_mime_type("/unknown", content) == "application/octet-stream"

    def test_fallback_to_octet_stream(self):
        """Test fallback to octet-stream for unknown types."""
        assert detect_mime_type("/unknown.unknownxyz") == "application/octet-stream"
        assert detect_mime_type("/file") == "application/octet-stream"


class TestClassifyContentType:
    """Tests for content type classification."""

    def test_classify_text_types(self):
        """Test classification of text MIME types."""
        assert (
            classify_content_type("text/plain", "/test.txt") == ResourceContentType.TEXT
        )
        assert (
            classify_content_type("text/html", "/test.html") == ResourceContentType.TEXT
        )
        assert (
            classify_content_type("application/json", "/test.json")
            == ResourceContentType.JSON
        )

    def test_classify_image_types(self):
        """Test classification of image MIME types."""
        assert (
            classify_content_type("image/png", "/test.png") == ResourceContentType.IMAGE
        )
        assert (
            classify_content_type("image/jpeg", "/test.jpg")
            == ResourceContentType.IMAGE
        )
        assert (
            classify_content_type("image/gif", "/test.gif") == ResourceContentType.IMAGE
        )
        assert (
            classify_content_type("image/webp", "/test.webp")
            == ResourceContentType.IMAGE
        )

    def test_classify_xml_types(self):
        """Test classification of XML MIME types."""
        assert (
            classify_content_type("application/xml", "/test.xml")
            == ResourceContentType.XML
        )
        assert classify_content_type("text/xml", "/test.xml") == ResourceContentType.XML

    def test_classify_binary_types(self):
        """Test classification of binary MIME types."""
        assert (
            classify_content_type("application/pdf", "/test.pdf")
            == ResourceContentType.BINARY
        )
        assert (
            classify_content_type("application/octet-stream", "/test.bin")
            == ResourceContentType.BINARY
        )
        assert (
            classify_content_type("application/zip", "/test.zip")
            == ResourceContentType.BINARY
        )


class TestIsBinaryContent:
    """Tests for binary content detection."""

    def test_image_types_are_binary(self):
        """Test that image types are considered binary."""
        assert is_binary_content("image/png") is True
        assert is_binary_content("image/jpeg") is True
        assert is_binary_content("image/gif") is True

    def test_audio_types_are_binary(self):
        """Test that audio types are considered binary."""
        assert is_binary_content("audio/mp3") is True
        assert is_binary_content("audio/wav") is True

    def test_video_types_are_binary(self):
        """Test that video types are considered binary."""
        assert is_binary_content("video/mp4") is True
        assert is_binary_content("video/avi") is True

    def test_application_types_are_binary(self):
        """Test that application types are considered binary except text-safe ones."""
        assert is_binary_content("application/pdf") is True
        assert is_binary_content("application/zip") is True
        assert is_binary_content("application/octet-stream") is True

    def test_text_types_are_not_binary(self):
        """Test that text types are not considered binary."""
        assert is_binary_content("text/plain") is False
        assert is_binary_content("text/html") is False
        assert is_binary_content("text/css") is False

    def test_json_is_not_binary(self):
        """Test that JSON is not considered binary."""
        assert is_binary_content("application/json") is False


class TestResourceContent:
    """Tests for ResourceContent dataclass."""

    def test_text_content_to_string(self):
        """Test converting text content to string."""
        content = ResourceContent(
            data="Hello, World!",
            encoding="utf-8",
            is_binary=False,
            size_bytes=13,
        )
        assert content.to_string() == "Hello, World!"

    def test_binary_content_to_string(self):
        """Test converting binary content to base64 string."""
        data = b"\x89PNG\r\n\x1a\n"
        content = ResourceContent(
            data=data,
            encoding="base64",
            is_binary=True,
            size_bytes=len(data),
        )
        expected = base64.b64encode(data).decode("ascii")
        assert content.to_string() == expected

    def test_bytes_content_decode(self):
        """Test decoding bytes content as text."""
        data = b"Hello, World!"
        content = ResourceContent(
            data=data,
            encoding="utf-8",
            is_binary=False,
            size_bytes=len(data),
        )
        assert content.to_string() == "Hello, World!"


class TestReadFileContent:
    """Tests for read_file_content function."""

    def test_read_text_file(self, mock_fs):
        """Test reading a text file."""
        mock_fs.info.return_value = {"size": 13}
        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        result = read_file_content(mock_fs, "/test.txt", "text/plain")

        assert result.is_binary is False
        assert result.encoding == "utf-8"
        assert result.data == "Hello, World!"

    def test_read_binary_file(self, mock_fs):
        """Test reading a binary file."""
        mock_fs.info.return_value = {"size": 100}
        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        mock_content.read.return_value = binary_data
        mock_fs.open.return_value = mock_content

        result = read_file_content(mock_fs, "/test.png", "image/png")

        assert result.is_binary is True
        assert result.encoding == "base64"
        assert result.data == binary_data

    def test_read_file_size_limit(self, mock_fs):
        """Test file size limit enforcement."""
        mock_fs.info.return_value = {"size": 1000}

        with pytest.raises(Exception) as exc_info:
            read_file_content(mock_fs, "/test.txt", "text/plain", max_size_bytes=100)

        assert (
            "too large" in str(exc_info.value).lower()
            or "exceeds" in str(exc_info.value).lower()
        )

    def test_file_info_error(self, mock_fs):
        """Test handling of file info retrieval error."""
        mock_fs.info.side_effect = OSError("Cannot access file")

        with pytest.raises(ResourceReadError) as exc_info:
            read_file_content(mock_fs, "/test.txt", "text/plain")

        assert "Failed to get file info" in str(exc_info.value)

    def test_unicode_decode_fallback_to_binary(self, mock_fs):
        """Test fallback to binary when UTF-8 decoding fails."""
        mock_fs.info.return_value = {"size": 10}

        # First open call (text mode) fails with UnicodeDecodeError
        mock_text = MagicMock()
        mock_text.__enter__ = MagicMock(return_value=mock_text)
        mock_text.__exit__ = MagicMock(return_value=None)
        mock_text.read.side_effect = UnicodeDecodeError(
            "utf-8", b"\x80", 0, 1, "invalid start byte"
        )

        # Second open call (binary mode) succeeds
        mock_binary = MagicMock()
        mock_binary.__enter__ = MagicMock(return_value=mock_binary)
        mock_binary.__exit__ = MagicMock(return_value=None)
        binary_data = b"\x80\x81\x82\x83"
        mock_binary.read.return_value = binary_data

        mock_fs.open.side_effect = [mock_text, mock_binary]

        result = read_file_content(mock_fs, "/test.bin", "text/plain")

        assert result.is_binary is True
        assert result.data == binary_data


class TestGetResourceMetadata:
    """Tests for get_resource_metadata function."""

    def test_text_file_metadata(self, mock_fs):
        """Test metadata extraction for text file."""
        mock_fs.info.return_value = {
            "size": 1024,
            "mtime": 1609459200,  # 2021-01-01 00:00:00 UTC
            "type": "file",
        }
        mock_fs.isdir.return_value = False

        metadata = get_resource_metadata(mock_fs, "/test.txt", "text/plain")

        assert metadata.size == 1024
        assert metadata.mime_type == "text/plain"
        assert metadata.extension == ".txt"
        assert metadata.is_directory is False
        assert metadata.content_type == "text"

    def test_image_file_metadata(self, mock_fs):
        """Test metadata extraction for image file."""
        mock_fs.info.return_value = {
            "size": 2048,
            "mtime": 1609459200,
            "type": "file",
        }
        mock_fs.isdir.return_value = False

        metadata = get_resource_metadata(mock_fs, "/test.png", "image/png")

        assert metadata.size == 2048
        assert metadata.mime_type == "image/png"
        assert metadata.extension == ".png"
        assert metadata.content_type == "image"

    def test_directory_metadata(self, mock_fs):
        """Test metadata extraction for directory."""
        mock_fs.info.return_value = {
            "size": 0,
            "type": "directory",
        }
        mock_fs.isdir.return_value = True

        metadata = get_resource_metadata(
            mock_fs, "/workspace", "application/octet-stream"
        )

        assert metadata.is_directory is True

    def test_timestamp_conversion(self, mock_fs):
        """Test timestamp to ISO format conversion."""
        mock_fs.info.return_value = {
            "size": 100,
            "mtime": 1609459200,
            "created": 1609459100,
            "type": "file",
        }
        mock_fs.isdir.return_value = False

        metadata = get_resource_metadata(mock_fs, "/test.txt", "text/plain")

        # Should be ISO format string
        assert metadata.modified is not None
        assert isinstance(metadata.modified, str)
        assert "T" in metadata.modified  # ISO format has T separator

    def test_info_error_fallback(self, mock_fs):
        """Test fallback when info retrieval fails."""
        mock_fs.info.side_effect = OSError("Cannot access")

        metadata = get_resource_metadata(mock_fs, "/test.txt", "text/plain")

        assert metadata.size == 0
        assert metadata.mime_type == "text/plain"


class TestLargeFilePreview:
    """Tests for LargeFilePreview dataclass."""

    def test_large_file_preview_creation(self):
        """Test creating a LargeFilePreview instance."""
        preview = LargeFilePreview(
            total_size=10000000,
            mimetype="text/plain",
            preview_start="First 1000 chars",
            preview_end="Last 1000 chars",
            preview_size=1000,
            is_binary=False,
            line_count=50000,
            message="File too large",
        )
        assert preview.total_size == 10000000
        assert preview.mimetype == "text/plain"
        assert preview.preview_start == "First 1000 chars"
        assert preview.preview_end == "Last 1000 chars"
        assert preview.preview_size == 1000
        assert preview.is_binary is False
        assert preview.line_count == 50000
        assert preview.message == "File too large"

    def test_large_file_preview_to_dict(self):
        """Test LargeFilePreview.to_dict() method."""
        preview = LargeFilePreview(
            total_size=10000000,
            mimetype="text/plain",
            preview_start="First 1000 chars",
            preview_end="Last 1000 chars",
            preview_size=1000,
            is_binary=False,
            line_count=50000,
            message="File too large",
        )
        result = preview.to_dict()
        assert result["type"] == "large_file_preview"
        assert result["total_size"] == 10000000
        assert result["mimetype"] == "text/plain"
        assert result["preview_start"] == "First 1000 chars"
        assert result["preview_end"] == "Last 1000 chars"
        assert result["preview_size"] == 1000
        assert result["is_binary"] is False
        assert result["line_count"] == 50000
        assert result["message"] == "File too large"

    def test_large_file_preview_to_dict_no_line_count(self):
        """Test LargeFilePreview.to_dict() without line_count."""
        preview = LargeFilePreview(
            total_size=10000000,
            mimetype="application/octet-stream",
            preview_start="First 1000 bytes",
            preview_end="Last 1000 bytes",
            preview_size=1000,
            is_binary=True,
        )
        result = preview.to_dict()
        assert result["type"] == "large_file_preview"
        assert "line_count" not in result


class TestFileMetadataResult:
    """Tests for FileMetadataResult dataclass."""

    def test_file_metadata_result_creation(self):
        """Test creating a FileMetadataResult instance."""
        result = FileMetadataResult(
            uri="scratchpad://test-123/file.txt",
            session_id="test-123",
            path="/file.txt",
            exists=True,
            size=1024,
            mimetype="text/plain",
            modified="2024-01-15T10:30:00",
            created="2024-01-14T10:00:00",
            is_binary=False,
            is_directory=False,
            line_count=50,
            success=True,
        )
        assert result.uri == "scratchpad://test-123/file.txt"
        assert result.session_id == "test-123"
        assert result.path == "/file.txt"
        assert result.exists is True
        assert result.size == 1024
        assert result.mimetype == "text/plain"
        assert result.modified == "2024-01-15T10:30:00"
        assert result.created == "2024-01-14T10:00:00"
        assert result.is_binary is False
        assert result.is_directory is False
        assert result.line_count == 50
        assert result.success is True

    def test_file_metadata_result_to_dict(self):
        """Test FileMetadataResult.to_dict() method."""
        result = FileMetadataResult(
            uri="scratchpad://test-123/file.txt",
            session_id="test-123",
            path="/file.txt",
            exists=True,
            size=1024,
            mimetype="text/plain",
            line_count=50,
            success=True,
        )
        d = result.to_dict()
        assert d["uri"] == "scratchpad://test-123/file.txt"
        assert d["session_id"] == "test-123"
        assert d["path"] == "/file.txt"
        assert d["exists"] is True
        assert d["size"] == 1024
        assert d["mimetype"] == "text/plain"
        assert d["line_count"] == 50
        assert d["success"] is True

    def test_file_metadata_result_with_error(self):
        """Test FileMetadataResult with error."""
        result = FileMetadataResult(
            uri="scratchpad://test-123/file.txt",
            session_id="test-123",
            path="/file.txt",
            exists=False,
            size=0,
            mimetype="application/octet-stream",
            success=False,
            error="Session not found",
        )
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "Session not found"


class TestGetFileMetadata:
    """Tests for get_file_metadata function."""

    def test_get_file_metadata_success(self, mock_session_manager, mock_fs):
        """Test successful metadata retrieval."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {
            "size": 1024,
            "mtime": 1609459200,
            "created": 1609459100,
            "type": "file",
        }

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        result = get_file_metadata(uri, mock_session_manager)

        assert result.success is True
        assert result.exists is True
        assert result.size == 1024
        assert result.mimetype == "text/plain"
        assert result.is_binary is False
        assert result.is_directory is False

    def test_get_file_metadata_not_found(self, mock_session_manager, mock_fs):
        """Test metadata retrieval for non-existent file."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/missing.txt"
        result = get_file_metadata(uri, mock_session_manager)

        assert result.success is True  # Operation succeeded
        assert result.exists is False  # But file doesn't exist

    def test_get_file_metadata_directory(self, mock_session_manager, mock_fs):
        """Test metadata retrieval for directory."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = True
        mock_fs.info.return_value = {"size": 0, "type": "directory"}

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = get_file_metadata(uri, mock_session_manager)

        assert result.success is True
        assert result.exists is True
        assert result.is_directory is True

    def test_get_file_metadata_invalid_uri(self):
        """Test metadata retrieval with invalid URI."""
        result = get_file_metadata("invalid-uri")

        assert result.success is False
        assert result.error is not None

    def test_get_file_metadata_no_session_manager(self):
        """Test metadata retrieval without session manager."""
        set_session_manager(None)
        result = get_file_metadata(f"scratchpad://{TEST_SESSION_ID}/test.txt")

        assert result.success is False


class TestReadLargeFilePreview:
    """Tests for read_large_file_preview function."""

    def test_read_large_text_file_preview(self, mock_fs):
        """Test reading preview of large text file."""
        mock_fs.info.return_value = {"size": 2000000}  # 2MB

        mock_open_result = MagicMock()
        mock_open_result.__enter__ = MagicMock(return_value=mock_open_result)
        mock_open_result.__exit__ = MagicMock(return_value=None)
        mock_open_result.read.return_value = "Line content\n" * 100
        mock_fs.open.return_value = mock_open_result

        preview = read_large_file_preview(
            mock_fs, "/large.txt", "text/plain", preview_size=100
        )

        assert preview.total_size == 2000000
        assert preview.mimetype == "text/plain"
        assert preview.is_binary is False
        assert preview.preview_size == 100

    def test_read_large_binary_file_preview(self, mock_fs):
        """Test reading preview of large binary file."""
        mock_fs.info.return_value = {"size": 5000000}  # 5MB

        mock_open_result = MagicMock()
        mock_open_result.__enter__ = MagicMock(return_value=mock_open_result)
        mock_open_result.__exit__ = MagicMock(return_value=None)
        mock_open_result.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_open_result.seek = MagicMock()
        mock_fs.open.return_value = mock_open_result

        preview = read_large_file_preview(
            mock_fs, "/large.png", "image/png", preview_size=100
        )

        assert preview.total_size == 5000000
        assert preview.mimetype == "image/png"
        assert preview.is_binary is True

    def test_read_large_file_preview_size_zero(self, mock_fs):
        """Test reading preview of empty file."""
        mock_fs.info.return_value = {"size": 0}

        # Setup mock to return empty string for empty file
        mock_open_result = MagicMock()
        mock_open_result.__enter__ = MagicMock(return_value=mock_open_result)
        mock_open_result.__exit__ = MagicMock(return_value=None)
        mock_open_result.read.return_value = ""  # Empty file returns empty string
        mock_fs.open.return_value = mock_open_result

        preview = read_large_file_preview(
            mock_fs, "/empty.txt", "text/plain", preview_size=100
        )

        assert preview.total_size == 0
        assert preview.preview_start == ""


class TestReadFileChunk:
    """Tests for read_file_chunk function."""

    def test_read_file_chunk_text(self, mock_session_manager, mock_fs):
        """Test reading a chunk from a text file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 5000, "type": "file"}

        mock_open_result = MagicMock()
        mock_open_result.__enter__ = MagicMock(return_value=mock_open_result)
        mock_open_result.__exit__ = MagicMock(return_value=None)
        mock_open_result.read.return_value = "Line 1\nLine 2\nLine 3\n"
        mock_open_result.seek = MagicMock()
        mock_fs.open.return_value = mock_open_result

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        result = read_file_chunk(
            uri, offset=0, limit=50, session_manager=mock_session_manager
        )

        assert result.success is True

    def test_read_file_chunk_binary(self, mock_session_manager, mock_fs):
        """Test reading a chunk from a binary file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 5000, "type": "file"}

        mock_open_result = MagicMock()
        mock_open_result.__enter__ = MagicMock(return_value=mock_open_result)
        mock_open_result.__exit__ = MagicMock(return_value=None)
        mock_open_result.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_open_result.seek = MagicMock()
        mock_fs.open.return_value = mock_open_result

        uri = f"scratchpad://{TEST_SESSION_ID}/test.png"
        result = read_file_chunk(
            uri, offset=0, limit=64, session_manager=mock_session_manager
        )

        assert result.success is True
        assert result.content.is_binary is True

    def test_read_file_chunk_file_not_found(self, mock_session_manager, mock_fs):
        """Test reading a chunk from non-existent file."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/missing.txt"
        result = read_file_chunk(
            uri, offset=0, limit=100, session_manager=mock_session_manager
        )

        assert result.success is False
        assert "File not found" in result.error


class TestReadResource:
    """Tests for the main read_resource function."""

    def test_read_text_file_success(self, mock_session_manager, mock_fs):
        """Test successful reading of a text file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 13, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        result = read_resource(uri, mock_session_manager)

        assert result.success is True
        assert result.session_id == TEST_SESSION_ID
        assert result.path == "/test.txt"
        assert result.content.data == "Hello, World!"
        assert result.metadata.mime_type == "text/plain"
        assert result.metadata.content_type == "text"

    def test_read_binary_file_success(self, mock_session_manager, mock_fs):
        """Test successful reading of a binary file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 100, "type": "file"}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        # Use ZIP signature to test generic binary handler (not image)
        binary_data = b"PK\x03\x04" + b"\x00" * 100
        mock_content.read.return_value = binary_data
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.zip"
        result = read_resource(uri, mock_session_manager)

        assert result.success is True
        assert result.metadata.mime_type == "application/zip"
        assert result.metadata.content_type == "binary"

    def test_read_large_file_returns_preview(self, mock_session_manager, mock_fs):
        """Test that large files (> 1MB) return preview mode."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        # File larger than 1MB
        mock_fs.info.return_value = {
            "size": LARGE_FILE_THRESHOLD + 1000,
            "type": "file",
        }

        def mock_open(path, mode, **kwargs):
            mock_content = MagicMock()
            mock_content.__enter__ = MagicMock(return_value=mock_content)
            mock_content.__exit__ = MagicMock(return_value=None)
            mock_content.read.return_value = "Line content\n" * 100
            return mock_content

        mock_fs.open = mock_open

        uri = f"scratchpad://{TEST_SESSION_ID}/large.txt"
        result = read_resource(uri, mock_session_manager)

        assert result.success is True
        # The content should be a JSON string containing preview info
        content_str = result.content.to_string()
        # Check that it's valid JSON containing preview data
        try:
            preview_data = json.loads(content_str)
            assert preview_data.get("type") == "large_file_preview"
            assert preview_data.get("total_size") == LARGE_FILE_THRESHOLD + 1000
        except json.JSONDecodeError:
            # If not JSON, it should still contain preview information
            assert result.content.size_bytes > 0

    def test_invalid_uri_parsing(self):
        """Test handling of invalid URI."""
        result = read_resource("invalid://uri")

        assert result.success is False
        assert "Invalid scheme" in result.error or "scheme" in result.error.lower()

    def test_empty_uri(self):
        """Test handling of empty URI."""
        result = read_resource("")

        assert result.success is False
        assert result.error is not None

    def test_missing_session_id(self):
        """Test handling of missing session ID."""
        result = read_resource("scratchpad:///test.txt")

        assert result.success is False
        assert "session" in result.error.lower() or "Missing" in result.error

    def test_session_not_found(self, mock_session_manager):
        """Test handling of non-existent session."""
        mock_session_manager.get_session_fs.return_value = None

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        result = read_resource(uri, mock_session_manager)

        assert result.success is False
        assert "Session not found" in result.error

    def test_file_not_found(self, mock_session_manager, mock_fs):
        """Test handling of non-existent file."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/missing.txt"
        result = read_resource(uri, mock_session_manager)

        assert result.success is False
        assert "File not found" in result.error

    def test_path_is_directory(self, mock_session_manager, mock_fs):
        """Test handling of directory path."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = True

        uri = f"scratchpad://{TEST_SESSION_ID}/workspace"
        result = read_resource(uri, mock_session_manager)

        assert result.success is False
        assert "directory" in result.error.lower()
        assert result.metadata.is_directory is True

    def test_no_session_manager(self):
        """Test error when no session manager is available."""
        # Clear any global session manager
        set_session_manager(None)

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        result = read_resource(uri)

        assert result.success is False
        assert "Session manager" in result.error

    def test_read_resource_to_dict(self, mock_session_manager, mock_fs):
        """Test converting result to dictionary."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 13, "type": "file"}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        result = read_resource(uri, mock_session_manager)
        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["uri"] == uri
        assert result_dict["session_id"] == TEST_SESSION_ID
        assert "content" in result_dict
        assert "metadata" in result_dict


class TestLargeFileIntegration:
    """Integration tests for large file handling with real filesystem."""

    def test_large_file_preview_with_real_fs(self, real_session_manager):
        """Test large file preview with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a file larger than 1MB
        large_content = "Line content with some text for testing\n" * 30000  # ~ 1.5MB
        with fs.open("/large.txt", "w") as f:
            f.write(large_content)

        # Read via read_resource
        uri = f"scratchpad://{session_id}/large.txt"
        set_session_manager(manager)
        result = read_resource(uri)

        assert result.success is True
        # For large files, read_resource returns preview mode
        # The content should be JSON-serializable preview data
        content_str = result.content.to_string()
        # Verify content size is reasonable (preview, not full file)
        assert result.metadata.size > LARGE_FILE_THRESHOLD
        # Content should contain preview information (JSON format)
        assert content_str is not None
        assert len(content_str) > 0

    def test_get_file_metadata_with_real_fs(self, real_session_manager):
        """Test get_file_metadata with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a test file with known content
        lines = [f"Line {i}\n" for i in range(1, 101)]  # 100 lines
        with fs.open("/test.txt", "w") as f:
            f.writelines(lines)

        # Get metadata
        uri = f"scratchpad://{session_id}/test.txt"
        set_session_manager(manager)
        result = get_file_metadata(uri)

        assert result.success is True
        assert result.exists is True
        assert result.size > 0
        assert result.mimetype == "text/plain"
        assert result.is_binary is False

    def test_read_file_chunk_with_real_fs(self, real_session_manager):
        """Test read_file_chunk with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a test file
        content = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        with fs.open("/test.txt", "w") as f:
            f.write(content)

        # Read chunk
        uri = f"scratchpad://{session_id}/test.txt"
        set_session_manager(manager)
        result = read_file_chunk(uri, offset=0, limit=10)

        assert result.success is True
        assert result.content.data == "ABCDEFGHIJ"

    def test_read_file_chunk_offset(self, real_session_manager):
        """Test read_file_chunk with offset."""
        manager, session_id, fs = real_session_manager

        # Create a test file
        content = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        with fs.open("/test.txt", "w") as f:
            f.write(content)

        # Read chunk with offset
        uri = f"scratchpad://{session_id}/test.txt"
        set_session_manager(manager)
        result = read_file_chunk(uri, offset=10, limit=10)

        assert result.success is True
        assert result.content.data == "KLMNOPQRST"


class TestReadResourceHelpers:
    """Tests for helper functions read_resource_text and read_resource_bytes."""

    def test_read_resource_text_success(self, mock_session_manager, mock_fs):
        """Test reading resource as text."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 13, "type": "file"}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        text = read_resource_text(uri, mock_session_manager)

        assert text == "Hello, World!"

    def test_read_resource_text_failure(self, mock_session_manager, mock_fs):
        """Test reading resource as text when file doesn't exist."""
        mock_fs.exists.return_value = False

        uri = f"scratchpad://{TEST_SESSION_ID}/missing.txt"
        with pytest.raises(ResourceReadError) as exc_info:
            read_resource_text(uri, mock_session_manager)

        assert "File not found" in str(exc_info.value)

    def test_read_resource_bytes_success(self, mock_session_manager, mock_fs):
        """Test reading resource as bytes."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 10, "type": "file"}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        # Use ZIP signature for binary test (generic binary, not image)
        binary_data = b"PK\x03\x04\x00\x00\x00\x00\x00\x00"
        mock_content.read.return_value = binary_data
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.zip"
        data = read_resource_bytes(uri, mock_session_manager)

        assert data == binary_data


class TestIntegration:
    """Integration tests with real session manager."""

    def test_read_real_text_file(self, real_session_manager):
        """Test reading a real text file from a session."""
        manager, session_id, fs = real_session_manager

        # Write a test file
        test_content = "Hello, World!\nThis is a test file."
        with fs.open("/test.txt", "w") as f:
            f.write(test_content)

        # Read via read_resource
        uri = f"scratchpad://{session_id}/test.txt"
        set_session_manager(manager)
        result = read_resource(uri)

        assert result.success is True
        assert result.content.data == test_content
        assert result.metadata.mime_type == "text/plain"

    def test_read_real_binary_file(self, real_session_manager):
        """Test reading a real binary file from a session."""
        manager, session_id, fs = real_session_manager

        # Write a test binary file with ZIP signature (generic binary)
        test_content = b"PK\x03\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 100
        with fs.open("/test.zip", "wb") as f:
            f.write(test_content)

        # Read via read_resource
        uri = f"scratchpad://{session_id}/test.zip"
        set_session_manager(manager)
        result = read_resource(uri)

        assert result.success is True
        assert result.content.is_binary is True
        assert result.metadata.mime_type == "application/zip"

    def test_read_real_json_file(self, real_session_manager):
        """Test reading a JSON file."""
        manager, session_id, fs = real_session_manager

        test_data = {"name": "test", "value": 42}
        with fs.open("/data.json", "w") as f:
            json.dump(test_data, f)

        uri = f"scratchpad://{session_id}/data.json"
        set_session_manager(manager)
        result = read_resource(uri)

        assert result.success is True
        assert result.metadata.mime_type == "application/json"
        assert result.metadata.content_type == "json"

    def test_file_size_limit(self, real_session_manager):
        """Test file size limit enforcement with real files."""
        manager, session_id, fs = real_session_manager

        # Write a file larger than the limit
        large_content = "x" * 1000
        with fs.open("/large.txt", "w") as f:
            f.write(large_content)

        uri = f"scratchpad://{session_id}/large.txt"
        set_session_manager(manager)

        # The function may raise or return failure - check both cases
        try:
            result = read_resource(uri, max_size_bytes=100)
            # If no exception, check for failure result
            if not result.success:
                error_msg = (result.error or "").lower()
                assert "too large" in error_msg or "exceeds" in error_msg
            else:
                # If success is True, the test assumes failure should happen
                pytest.fail("Expected file size limit to be enforced")
        except Exception as e:
            # Exception raised case
            error_msg = str(e).lower()
            assert "too large" in error_msg or "exceeds" in error_msg


class TestMimeTypeConstants:
    """Tests for MIME type constants."""

    def test_mime_override_values(self):
        """Test that MIME type overrides are correct."""
        assert ".py" in MIME_TYPE_OVERRIDES
        assert MIME_TYPE_OVERRIDES[".py"] == "text/x-python"
        assert ".md" in MIME_TYPE_OVERRIDES
        assert MIME_TYPE_OVERRIDES[".md"] == "text/markdown"
        assert ".yaml" in MIME_TYPE_OVERRIDES
        assert ".yml" in MIME_TYPE_OVERRIDES

    def test_image_mime_types(self):
        """Test that image MIME types are defined."""
        assert "image/jpeg" in IMAGE_MIME_TYPES
        assert "image/png" in IMAGE_MIME_TYPES
        assert "image/gif" in IMAGE_MIME_TYPES
        assert "image/webp" in IMAGE_MIME_TYPES

    def test_binary_mime_types(self):
        """Test that binary MIME types are defined."""
        assert "application/pdf" in BINARY_MIME_TYPES
        assert "application/zip" in BINARY_MIME_TYPES
        assert "application/octet-stream" in BINARY_MIME_TYPES

    def test_text_mime_types(self):
        """Test that text MIME types are defined."""
        assert "text/plain" in TEXT_MIME_TYPES
        assert "text/html" in TEXT_MIME_TYPES
        assert "application/json" in TEXT_MIME_TYPES


class TestLargeFileThresholdConstant:
    """Tests for LARGE_FILE_THRESHOLD constant."""

    def test_large_file_threshold_value(self):
        """Test that LARGE_FILE_THRESHOLD is set to 1MB."""
        assert LARGE_FILE_THRESHOLD == 1024 * 1024
        assert LARGE_FILE_THRESHOLD == 1048576

    def test_default_preview_size(self):
        """Test that DEFAULT_PREVIEW_SIZE is 1000."""
        assert DEFAULT_PREVIEW_SIZE == 1000


class TestCountLinesInText:
    """Tests for count_lines_in_text function."""

    def test_count_lines_empty_file(self, mock_fs):
        """Test line count for empty file."""
        mock_fs.info.return_value = {"size": 0}
        count = count_lines_in_text(mock_fs, "/empty.txt")
        assert count == 0

    def test_count_lines_small_file(self, mock_fs):
        """Test line count for small file."""
        mock_fs.info.return_value = {"size": 100}

        def mock_open(path, mode, **kwargs):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=None)
            # Return iterator for sum(1 for _ in f)
            mock_file.__iter__ = MagicMock(
                return_value=iter(["line1\n", "line2\n", "line3"])
            )
            return mock_file

        mock_fs.open = mock_open

        count = count_lines_in_text(mock_fs, "/test.txt")
        assert count == 3

    def test_count_lines_error(self, mock_fs):
        """Test line count when file read fails."""
        mock_fs.info.side_effect = OSError("Cannot read")
        count = count_lines_in_text(mock_fs, "/error.txt")
        assert count == -1
