"""Tests for binary resource handler.

This module tests the binary resource handler, including:
- PDF metadata extraction
- PDF text extraction
- Binary format detection
- BinaryResource dataclass
- process_pdf_resource() function
- process_binary_resource() function
- Large file handling (metadata-only mode)
- Base64 encoding/decoding
- Error handling
"""

from __future__ import annotations

import base64
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.binary_handler import (
    DEFAULT_MAX_PAGES,
    LARGE_PDF_THRESHOLD,
    BinaryResource,
    PDFMetadata,
    _safe_get_pdf_meta,
    detect_binary_format,
    extract_pdf_metadata,
    extract_pdf_text,
    is_binary_file,
    process_binary_resource,
    process_pdf_resource,
)

# Fixtures


@pytest.fixture
def mock_fs():
    """Create a mock filesystem for testing."""
    fs = MagicMock()
    return fs


@pytest.fixture
def real_session_manager():
    """Create a real session manager for integration testing."""
    config = OverlayConfig(mounts=[])
    manager = SessionFileSystemManager(config)
    session_id = manager.create_session()
    fs = manager.get_session_fs(session_id)
    return manager, session_id, fs


# Helper function to create a minimal PDF


def create_test_pdf(
    num_pages: int = 3,
    title: str | None = "Test Document",
    author: str | None = "Test Author",
) -> bytes:
    """Create a minimal PDF file for testing.

    This creates a valid but minimal PDF structure that can be parsed by PyPDF2.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()

    # Add pages
    for i in range(num_pages):
        # Use indirect approach to add blank pages
        page = writer.add_blank_page(width=612, height=792)  # Letter size

    # Add metadata if provided
    if title or author:
        writer.add_metadata(
            {
                "/Title": title or "",
                "/Author": author or "",
            }
        )

    # Write to bytes
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


# Tests for PDFMetadata


class TestPDFMetadata:
    """Tests for PDFMetadata dataclass."""

    def test_pdf_metadata_creation(self):
        """Test creating a PDFMetadata instance."""
        metadata = PDFMetadata(
            page_count=42,
            title="Test Document",
            author="John Doe",
            subject="Testing",
        )
        assert metadata.page_count == 42
        assert metadata.title == "Test Document"
        assert metadata.author == "John Doe"
        assert metadata.subject == "Testing"

    def test_pdf_metadata_defaults(self):
        """Test PDFMetadata default values."""
        metadata = PDFMetadata()
        assert metadata.page_count == 0
        assert metadata.title is None
        assert metadata.author is None
        assert metadata.has_text_content is False

    def test_pdf_metadata_to_dict(self):
        """Test PDFMetadata.to_dict() method."""
        metadata = PDFMetadata(
            page_count=10,
            title="My PDF",
            author="Author Name",
        )
        d = metadata.to_dict()
        assert d["page_count"] == 10
        assert d["title"] == "My PDF"
        assert d["author"] == "Author Name"
        assert d["subject"] is None


# Tests for BinaryResource


class TestBinaryResource:
    """Tests for BinaryResource dataclass."""

    def test_binary_resource_creation(self):
        """Test creating a BinaryResource instance."""
        resource = BinaryResource(
            uri="scratchpad://test-123/document.pdf",
            session_id="test-123",
            path="/document.pdf",
            binary_content="JVBERi0xLjQK...",
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=102400,
        )
        assert resource.uri == "scratchpad://test-123/document.pdf"
        assert resource.session_id == "test-123"
        assert resource.binary_format == "PDF"
        assert resource.mime_type == "application/pdf"

    def test_binary_resource_with_pdf_metadata(self):
        """Test BinaryResource with PDF metadata."""
        pdf_meta = PDFMetadata(page_count=5, title="Test")
        resource = BinaryResource(
            uri="scratchpad://test-123/doc.pdf",
            session_id="test-123",
            path="/doc.pdf",
            binary_content="content...",
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=1024,
            pdf_metadata=pdf_meta,
        )
        assert resource.pdf_metadata is not None
        assert resource.pdf_metadata.page_count == 5

    def test_binary_resource_to_dict(self):
        """Test BinaryResource.to_dict() method."""
        resource = BinaryResource(
            uri="scratchpad://test-123/doc.pdf",
            session_id="test-123",
            path="/doc.pdf",
            binary_content="base64content",
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=1024,
            pdf_metadata=PDFMetadata(page_count=3, title="Doc"),
        )
        d = resource.to_dict()
        assert d["type"] == "binary"
        assert d["uri"] == "scratchpad://test-123/doc.pdf"
        assert d["mime_type"] == "application/pdf"
        assert d["content"] == "base64content"
        assert d["pdf_metadata"]["page_count"] == 3

    def test_binary_resource_to_dict_large_file(self):
        """Test BinaryResource.to_dict() for large files."""
        resource = BinaryResource(
            uri="scratchpad://test-123/large.pdf",
            session_id="test-123",
            path="/large.pdf",
            binary_content="",
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=LARGE_PDF_THRESHOLD + 1000,
            is_large_file=True,
            large_file_message="File is too large",
        )
        d = resource.to_dict()
        assert d["is_large_file"] is True
        assert d["metadata_only"] is True
        assert d["message"] == "File is too large"

    def test_binary_resource_with_error(self):
        """Test BinaryResource with error state."""
        resource = BinaryResource(
            uri="scratchpad://test-123/error.pdf",
            session_id="test-123",
            path="/error.pdf",
            binary_content="",
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=0,
            success=False,
            error="Failed to read file",
        )
        d = resource.to_dict()
        assert d["success"] is False
        assert d["error"] == "Failed to read file"


# Tests for detect_binary_format


class TestDetectBinaryFormat:
    """Tests for binary format detection."""

    def test_detect_pdf_format(self):
        """Test detecting PDF format."""
        assert detect_binary_format(b"%PDF-1.4", "application/pdf", "/doc.pdf") == "PDF"
        assert (
            detect_binary_format(b"some content", "application/pdf", "/file") == "PDF"
        )

    def test_detect_zip_format(self):
        """Test detecting ZIP format."""
        assert (
            detect_binary_format(b"PK\x03\x04", "application/zip", "/file.zip") == "ZIP"
        )
        assert detect_binary_format(b"data", "application/zip", "/archive.zip") == "ZIP"

    def test_detect_gzip_format(self):
        """Test detecting GZIP format."""
        assert (
            detect_binary_format(b"\x1f\x8b", "application/gzip", "/file.gz") == "GZIP"
        )
        assert (
            detect_binary_format(b"data", "application/gzip", "/archive.gz") == "GZIP"
        )

    def test_detect_png_format(self):
        """Test detecting PNG format."""
        assert (
            detect_binary_format(b"\x89PNG\r\n\x1a\n", "image/png", "/img.png") == "PNG"
        )

    def test_detect_jpeg_format(self):
        """Test detecting JPEG format."""
        assert detect_binary_format(b"\xff\xd8\xff", "image/jpeg", "/img.jpg") == "JPEG"

    def test_detect_by_extension(self):
        """Test format detection by file extension."""
        assert (
            detect_binary_format(b"data", "application/octet-stream", "/file.pdf")
            == "PDF"
        )
        assert (
            detect_binary_format(b"data", "application/octet-stream", "/file.zip")
            == "ZIP"
        )
        assert detect_binary_format(b"data", "image/unknown", "/file.png") == "PNG"
        assert detect_binary_format(b"data", "image/unknown", "/file.jpg") == "JPEG"

    def test_detect_fallback_to_binary(self):
        """Test fallback to generic BINARY."""
        assert (
            detect_binary_format(b"unknown", "application/octet-stream", "/file")
            == "BINARY"
        )


# Tests for extract_pdf_metadata


class TestExtractPdfMetadata:
    """Tests for PDF metadata extraction."""

    def test_extract_pdf_metadata_success(self):
        """Test successful PDF metadata extraction."""
        pdf_bytes = create_test_pdf(
            num_pages=3, title="Test Title", author="Test Author"
        )
        metadata = extract_pdf_metadata(pdf_bytes)

        assert metadata.page_count == 3
        assert metadata.title == "Test Title"
        assert metadata.author == "Test Author"

    def test_extract_pdf_metadata_no_metadata(self):
        """Test PDF metadata extraction when PDF has no metadata."""
        pdf_bytes = create_test_pdf(num_pages=5, title=None, author=None)
        metadata = extract_pdf_metadata(pdf_bytes)

        assert metadata.page_count == 5
        assert metadata.title is None
        assert metadata.author is None

    def test_extract_pdf_metadata_empty_pdf(self):
        """Test PDF metadata extraction with empty/invalid PDF."""
        # Create an invalid PDF
        metadata = extract_pdf_metadata(b"Not a PDF")

        assert metadata.page_count == 0
        assert metadata.title is None

    def test_extract_pdf_has_text_detection(self):
        """Test has_text_content detection."""
        # Create a PDF (blank pages have no text)
        pdf_bytes = create_test_pdf(num_pages=1)
        metadata = extract_pdf_metadata(pdf_bytes)

        # Blank pages have no text
        assert metadata.has_text_content is False


# Tests for extract_pdf_text


class TestExtractPdfText:
    """Tests for PDF text extraction."""

    def test_extract_pdf_text_blank_pages(self):
        """Test text extraction from blank pages."""
        pdf_bytes = create_test_pdf(num_pages=2)
        text = extract_pdf_text(pdf_bytes, max_pages=2)

        # Blank pages should return None or empty
        # PyPDF2 returns None for blank pages
        assert text is None or "--- Page 1 ---" in text

    def test_extract_pdf_text_max_pages(self):
        """Test max_pages limit in text extraction."""
        pdf_bytes = create_test_pdf(num_pages=5)
        text = extract_pdf_text(pdf_bytes, max_pages=2)

        # Should not extract text from all pages
        if text:
            # Count page markers
            page_count = text.count("--- Page")
            assert page_count <= 2

    def test_extract_pdf_text_invalid_pdf(self):
        """Test text extraction from invalid PDF."""
        text = extract_pdf_text(b"Not a PDF", max_pages=2)
        assert text is None


# Tests for is_binary_file


class TestIsBinaryFile:
    """Tests for binary file detection."""

    def test_pdf_is_binary(self):
        """Test that PDF is detected as binary."""
        assert is_binary_file("application/pdf") is True

    def test_zip_is_binary(self):
        """Test that ZIP is detected as binary."""
        assert is_binary_file("application/zip") is True

    def test_image_is_binary(self):
        """Test that images are detected as binary."""
        assert is_binary_file("image/png") is True
        assert is_binary_file("image/jpeg") is True
        assert is_binary_file("image/gif") is True

    def test_audio_video_is_binary(self):
        """Test that audio and video are detected as binary."""
        assert is_binary_file("audio/mp3") is True
        assert is_binary_file("video/mp4") is True

    def test_text_is_not_binary(self):
        """Test that text types are not binary."""
        assert is_binary_file("text/plain") is False
        assert is_binary_file("text/html") is False

    def test_json_is_not_binary(self):
        """Test that JSON is not binary."""
        assert is_binary_file("application/json") is False


# Tests for process_pdf_resource


class TestProcessPdfResource:
    """Tests for PDF resource processing."""

    def test_process_pdf_success(self, mock_fs):
        """Test successful PDF processing."""
        pdf_bytes = create_test_pdf(num_pages=2, title="Test PDF")

        mock_fs.info.return_value = {"size": len(pdf_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = pdf_bytes
        mock_fs.open.return_value = mock_file

        result = process_pdf_resource(
            uri="scratchpad://test-123/doc.pdf",
            fs=mock_fs,
            session_id="test-123",
            path="/doc.pdf",
            file_size=len(pdf_bytes),
            extract_text=True,
            max_pages=2,
        )

        assert result.success is True
        assert result.binary_format == "PDF"
        assert result.mime_type == "application/pdf"
        assert result.pdf_metadata is not None
        assert result.pdf_metadata.page_count == 2

    def test_process_pdf_without_text_extraction(self, mock_fs):
        """Test PDF processing without text extraction."""
        pdf_bytes = create_test_pdf(num_pages=1)

        mock_fs.info.return_value = {"size": len(pdf_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = pdf_bytes
        mock_fs.open.return_value = mock_file

        result = process_pdf_resource(
            uri="scratchpad://test-123/doc.pdf",
            fs=mock_fs,
            session_id="test-123",
            path="/doc.pdf",
            file_size=len(pdf_bytes),
            extract_text=False,  # 不提取文本
        )

        assert result.success is True
        assert result.extracted_text is None  # 不应有提取的文本

    def test_process_large_pdf_returns_metadata_only(self, mock_fs):
        """Test that large PDFs return metadata only."""
        # Create a PDF that's larger than the threshold
        large_size = LARGE_PDF_THRESHOLD + 1000

        mock_fs.info.return_value = {"size": large_size}

        # Only read first 64KB for metadata
        pdf_bytes = create_test_pdf(num_pages=5)
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = pdf_bytes
        mock_fs.open.return_value = mock_file

        result = process_pdf_resource(
            uri="scratchpad://test-123/large.pdf",
            fs=mock_fs,
            session_id="test-123",
            path="/large.pdf",
            file_size=large_size,
        )

        assert result.success is True
        assert result.is_large_file is True
        assert result.binary_content == ""  # No content for large files
        assert "size limit" in result.large_file_message.lower()

    def test_process_pdf_error(self, mock_fs):
        """Test PDF processing error handling."""
        mock_fs.info.return_value = {"size": 1000}
        mock_fs.open.side_effect = OSError("Cannot open file")

        result = process_pdf_resource(
            uri="scratchpad://test-123/error.pdf",
            fs=mock_fs,
            session_id="test-123",
            path="/error.pdf",
            file_size=1000,
        )

        assert result.success is False
        assert result.error is not None


# Tests for process_binary_resource


class TestProcessBinaryResource:
    """Tests for binary resource processing."""

    def test_process_binary_zip(self, mock_fs):
        """Test processing a ZIP file."""
        # Create a simple ZIP file
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("test.txt", "Hello, World!")
        zip_bytes = zip_buffer.getvalue()

        mock_fs.info.return_value = {"size": len(zip_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = zip_bytes
        mock_fs.open.return_value = mock_file

        result = process_binary_resource(
            uri="scratchpad://test-123/archive.zip",
            fs=mock_fs,
            session_id="test-123",
            path="/archive.zip",
            mime_type="application/zip",
        )

        assert result.success is True
        assert result.binary_format == "ZIP"
        assert result.mime_type == "application/zip"
        assert result.binary_content != ""  # Should have base64 content

    def test_process_binary_png(self, mock_fs):
        """Test processing a PNG image."""
        # Simple PNG header
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_fs.info.return_value = {"size": len(png_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = png_bytes
        mock_fs.open.return_value = mock_file

        result = process_binary_resource(
            uri="scratchpad://test-123/image.png",
            fs=mock_fs,
            session_id="test-123",
            path="/image.png",
            mime_type="image/png",
        )

        assert result.success is True
        assert result.binary_format == "PNG"
        assert result.mime_type == "image/png"

    def test_process_large_binary_returns_metadata_only(self, mock_fs):
        """Test that large binary files return metadata only."""
        large_size = LARGE_PDF_THRESHOLD + 1000

        mock_fs.info.return_value = {"size": large_size}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = b"PK\x03\x04"  # ZIP signature
        mock_fs.open.return_value = mock_file

        result = process_binary_resource(
            uri="scratchpad://test-123/large.zip",
            fs=mock_fs,
            session_id="test-123",
            path="/large.zip",
            mime_type="application/zip",
        )

        assert result.success is True
        assert result.is_large_file is True
        assert result.binary_content == ""  # No content for large files

    def test_process_binary_error(self, mock_fs):
        """Test binary processing error handling."""
        mock_fs.info.return_value = {"size": 100}
        mock_fs.open.side_effect = OSError("Cannot open file")

        result = process_binary_resource(
            uri="scratchpad://test-123/error.bin",
            fs=mock_fs,
            session_id="test-123",
            path="/error.bin",
            mime_type="application/octet-stream",
        )

        assert result.success is False
        assert result.error is not None


# Integration tests with real filesystem


class TestBinaryResourceIntegration:
    """Integration tests using real filesystem."""

    def test_process_pdf_with_real_fs(self, real_session_manager):
        """Test PDF processing with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a PDF file
        pdf_bytes = create_test_pdf(num_pages=3, title="Real PDF", author="Real Author")
        with fs.open("/document.pdf", "wb") as f:
            f.write(pdf_bytes)

        result = process_pdf_resource(
            uri=f"scratchpad://{session_id}/document.pdf",
            fs=fs,
            session_id=session_id,
            path="/document.pdf",
            file_size=len(pdf_bytes),
            extract_text=True,
        )

        assert result.success is True
        assert result.binary_format == "PDF"
        assert result.pdf_metadata is not None
        assert result.pdf_metadata.page_count == 3
        assert result.pdf_metadata.title == "Real PDF"
        assert result.pdf_metadata.author == "Real Author"

    def test_process_binary_with_real_fs(self, real_session_manager):
        """Test binary processing with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a ZIP file
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("hello.txt", "Hello, World!")
        zip_bytes = zip_buffer.getvalue()

        with fs.open("/archive.zip", "wb") as f:
            f.write(zip_bytes)

        result = process_binary_resource(
            uri=f"scratchpad://{session_id}/archive.zip",
            fs=fs,
            session_id=session_id,
            path="/archive.zip",
            mime_type="application/zip",
        )

        assert result.success is True
        assert result.binary_format == "ZIP"
        assert result.binary_content != ""

        # Verify content is valid base64
        decoded = base64.b64decode(result.binary_content)
        assert decoded[:4] == b"PK\x03\x04"  # ZIP signature


# Tests for _safe_get_pdf_meta helper


class TestSafeGetPdfMeta:
    """Tests for _safe_get_pdf_meta helper function."""

    def test_safe_get_existing_key(self):
        """Test getting existing key."""
        doc_info = {"/Title": "Test", "/Author": "Author"}
        assert _safe_get_pdf_meta(doc_info, "/Title") == "Test"
        assert _safe_get_pdf_meta(doc_info, "/Author") == "Author"

    def test_safe_get_missing_key(self):
        """Test getting missing key."""
        doc_info = {"/Title": "Test"}
        assert _safe_get_pdf_meta(doc_info, "/Author") is None

    def test_safe_get_none_dict(self):
        """Test with None dictionary."""
        assert _safe_get_pdf_meta(None, "/Title") is None


# Tests for constants


class TestConstants:
    """Tests for module constants."""

    def test_large_pdf_threshold(self):
        """Test LARGE_PDF_THRESHOLD value."""
        assert LARGE_PDF_THRESHOLD == 5 * 1024 * 1024  # 5MB

    def test_default_max_pages(self):
        """Test DEFAULT_MAX_PAGES value."""
        assert DEFAULT_MAX_PAGES == 2


# Tests for read_resource integration (test that binary files are handled)


class TestReadResourceBinaryHandling:
    """Tests for read_resource binary file handling."""

    def test_read_resource_handles_pdf(self, real_session_manager):
        """Test that read_resource properly handles PDF files."""
        from mcp_scratchpad.resources.read_handler import read_resource

        manager, session_id, fs = real_session_manager

        # Create a PDF file
        pdf_bytes = create_test_pdf(num_pages=2, title="Integration Test")
        with fs.open("/test.pdf", "wb") as f:
            f.write(pdf_bytes)

        # Set up session manager
        from mcp_scratchpad.resources.read_handler import set_session_manager

        set_session_manager(manager)

        # Read via read_resource
        result = read_resource(f"scratchpad://{session_id}/test.pdf")

        assert result.success is True
        # For PDFs, should get back binary content as JSON string
        assert result.content is not None

    def test_read_resource_handles_binary(self, real_session_manager):
        """Test that read_resource properly handles binary files."""
        from mcp_scratchpad.resources.read_handler import read_resource

        manager, session_id, fs = real_session_manager

        # Create a binary file (ZIP)
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("test.txt", "content")
        zip_bytes = zip_buffer.getvalue()

        with fs.open("/test.zip", "wb") as f:
            f.write(zip_bytes)

        # Set up session manager
        from mcp_scratchpad.resources.read_handler import set_session_manager

        set_session_manager(manager)

        # Read via read_resource
        result = read_resource(f"scratchpad://{session_id}/test.zip")

        assert result.success is True
        assert result.content is not None
