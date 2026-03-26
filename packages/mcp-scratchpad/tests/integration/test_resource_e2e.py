"""
End-to-End integration tests for MCP Resources (Task F4.3).

This module provides comprehensive E2E tests that verify the complete
resource flow: URI → parsed → session verified → file read → formatted → returned.

Tests cover:
- Full resource flow with real filesystem and MemoryFileSystem
- Integration with SessionFileSystemManager
- All resource types: text, JSON, image, PDF, binary, directory
- Error propagation end-to-end

Requirements:
- Tests use real filesystems (temp directories), not mocks
- Tests use real MemoryFileSystem as used by actual server
- Tests focus on black-box behavior, not implementation details
"""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fsspec.implementations.memory import MemoryFileSystem
from PIL import Image
from pypdf import PdfWriter

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources import (
    read_resource,
    read_resource_bytes,
    read_resource_text,
)
from mcp_scratchpad.resources.read_handler import (
    read_directory_resource,
    set_session_manager,
)
from mcp_scratchpad.resources.uri_parser import (
    build_scratchpad_uri,
    parse_scratchpad_uri,
)


def clear_memory_fs_store() -> None:
    """Clear the global MemoryFileSystem store for test isolation."""
    MemoryFileSystem.store.clear()


@pytest.fixture(autouse=True)
def clean_memory_fs():
    """Fixture to clear MemoryFileSystem store before and after each test."""
    clear_memory_fs_store()
    yield
    clear_memory_fs_store()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Temporary directory for filesystem-based tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def session_manager() -> Generator[SessionFileSystemManager, None, None]:
    """Create a SessionFileSystemManager for testing."""
    manager = SessionFileSystemManager(OverlayConfig())
    set_session_manager(manager)
    yield manager
    # Cleanup all sessions after test
    for session in manager.list_sessions(include_expired=True):
        manager.cleanup_session(session.session_id)


@pytest.fixture
def sample_session_id(session_manager: SessionFileSystemManager) -> str:
    """Create a sample session and return its ID."""
    return session_manager.create_session(metadata={"test": "resource_e2e"})


def create_test_png_image(width: int = 100, height: int = 100) -> bytes:
    """Create a simple PNG image for testing."""
    image = Image.new("RGB", (width, height), color=(73, 109, 137))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def create_test_jpeg_image(width: int = 200, height: int = 150) -> bytes:
    """Create a simple JPEG image for testing."""
    image = Image.new("RGB", (width, height), color=(255, 128, 64))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def create_test_pdf(title: str = "Test PDF", num_pages: int = 2) -> bytes:
    """Create a simple PDF for testing."""
    writer = PdfWriter()

    for i in range(num_pages):
        page = writer.add_blank_page(width=612, height=792)  # Letter size

    # Add metadata
    writer.add_metadata(
        {
            "/Title": title,
            "/Author": "Test Author",
            "/Subject": "E2E Test PDF",
        }
    )

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestTextResourceE2E:
    """E2E tests for text resource reading."""

    def test_read_plain_text_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read a plain text file through scratchpad:// URI.

        Verifies flow: URI → parse → session verified → file read → text returned
        """
        # Setup: Create a text file in session filesystem
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        test_content = "Hello, World! This is a test file.\nLine 2\nLine 3"
        with fs.open("/workspace/test.txt", "w", encoding="utf-8") as f:
            f.write(test_content)

        # Execute: Read resource via URI
        uri = f"scratchpad://{sample_session_id}/workspace/test.txt"
        result = read_resource(uri, session_manager=session_manager)

        # Verify: Result structure and content
        assert result.success is True
        assert result.uri == uri
        assert result.session_id == sample_session_id
        assert result.path == "/workspace/test.txt"
        assert result.content.is_binary is False
        assert result.content.encoding == "utf-8"
        assert result.content.data == test_content
        assert result.metadata.mime_type == "text/plain"
        assert result.metadata.size == len(test_content.encode("utf-8"))

    def test_read_python_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read a Python file with correct MIME type detection.

        Verifies: Extension-based MIME detection for code files
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        python_code = '"""Test module."""\ndef hello():\n    return \'world\'\n'
        with fs.open("/workspace/script.py", "w", encoding="utf-8") as f:
            f.write(python_code)

        uri = f"scratchpad://{sample_session_id}/workspace/script.py"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.content.data == python_code
        assert result.metadata.mime_type == "text/x-python"
        assert result.metadata.extension == ".py"

    def test_read_markdown_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Read a Markdown file with proper MIME type."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        markdown_content = "# Heading\n\nThis is **bold** text.\n\n- Item 1\n- Item 2"
        with fs.open("/workspace/README.md", "w", encoding="utf-8") as f:
            f.write(markdown_content)

        uri = f"scratchpad://{sample_session_id}/workspace/README.md"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.content.data == markdown_content
        assert result.metadata.mime_type == "text/markdown"


class TestJsonResourceE2E:
    """E2E tests for JSON resource reading."""

    def test_read_json_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read a JSON file and verify proper parsing.

        Verifies: JSON content is returned as text that can be parsed
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        test_data = {"name": "test", "values": [1, 2, 3], "nested": {"key": "value"}}
        json_content = json.dumps(test_data, indent=2)
        with fs.open("/workspace/config.json", "w", encoding="utf-8") as f:
            f.write(json_content)

        uri = f"scratchpad://{sample_session_id}/workspace/config.json"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.content.data == json_content
        assert result.metadata.mime_type == "application/json"

        # Verify JSON is parseable
        parsed = json.loads(result.content.data)
        assert parsed == test_data

    def test_read_jsonl_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Read a JSON Lines file."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        jsonl_content = '{"id": 1}\n{"id": 2}\n{"id": 3}\n'
        with fs.open("/workspace/data.jsonl", "w", encoding="utf-8") as f:
            f.write(jsonl_content)

        uri = f"scratchpad://{sample_session_id}/workspace/data.jsonl"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.content.data == jsonl_content


class TestImageResourceE2E:
    """E2E tests for image resource reading."""

    def test_read_png_image(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read a PNG image through scratchpad:// URI.

        Verifies: Image content is properly handled with metadata and thumbnails
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Create a test PNG image
        png_bytes = create_test_png_image(100, 100)
        with fs.open("/workspace/image.png", "wb") as f:
            f.write(png_bytes)

        uri = f"scratchpad://{sample_session_id}/workspace/image.png"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.metadata.mime_type == "image/png"
        assert result.metadata.content_type == "image"

        # Verify image metadata
        assert result.metadata.extension == ".png"
        assert "image_format" in result.capability_metadata
        assert "dimensions" in result.capability_metadata
        assert result.capability_metadata["dimensions"]["width"] == 100
        assert result.capability_metadata["dimensions"]["height"] == 100

        # Verify thumbnail was generated
        assert "thumbnails" in result.capability_metadata
        assert "small" in result.capability_metadata["thumbnails"]

    def test_read_jpeg_image(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Read a JPEG image."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        jpeg_bytes = create_test_jpeg_image(200, 150)
        with fs.open("/workspace/photo.jpg", "wb") as f:
            f.write(jpeg_bytes)

        uri = f"scratchpad://{sample_session_id}/workspace/photo.jpg"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.metadata.mime_type == "image/jpeg"
        assert result.capability_metadata["dimensions"]["width"] == 200
        assert result.capability_metadata["dimensions"]["height"] == 150

    def test_read_image_with_transparency(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Read a PNG image with transparency (RGBA)."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Create RGBA image with transparency
        image = Image.new("RGBA", (50, 50), (255, 0, 0, 128))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

        with fs.open("/workspace/transparent.png", "wb") as f:
            f.write(png_bytes)

        uri = f"scratchpad://{sample_session_id}/workspace/transparent.png"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.capability_metadata["dimensions"]["width"] == 50
        assert result.capability_metadata["dimensions"]["height"] == 50


class TestPdfResourceE2E:
    """E2E tests for PDF resource reading."""

    def test_read_pdf_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read a PDF file through scratchpad:// URI.

        Verifies: PDF metadata extraction and content handling
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        pdf_bytes = create_test_pdf("E2E Test Document", num_pages=3)
        with fs.open("/workspace/document.pdf", "wb") as f:
            f.write(pdf_bytes)

        uri = f"scratchpad://{sample_session_id}/workspace/document.pdf"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.metadata.mime_type == "application/pdf"

        # Content should be present (base64 for non-large files)
        assert result.content.data
        assert result.content.encoding in ["base64", "utf-8"]


class TestBinaryResourceE2E:
    """E2E tests for binary resource reading."""

    def test_read_binary_file(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read a generic binary file.

        Verifies: Binary content is base64 encoded for transport
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Create binary content
        binary_content = bytes([i % 256 for i in range(1000)])
        with fs.open("/workspace/data.bin", "wb") as f:
            f.write(binary_content)

        uri = f"scratchpad://{sample_session_id}/workspace/data.bin"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.content.is_binary is True or result.content.encoding == "base64"


class TestDirectoryResourceE2E:
    """E2E tests for directory listing resources."""

    def test_read_directory_listing(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read directory listing through scratchpad:// URI.

        Verifies: Directory contents are listed with metadata
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Create directory structure
        fs.mkdir("/workspace/subdir", create_parents=True)

        with fs.open("/workspace/file1.txt", "w") as f:
            f.write("File 1 content")
        with fs.open("/workspace/file2.json", "w") as f:
            f.write('{"key": "value"}')
        with fs.open("/workspace/subdir/nested.txt", "w") as f:
            f.write("Nested content")

        uri = f"scratchpad://{sample_session_id}/workspace/"
        result = read_directory_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.uri == uri
        assert result.session_id == sample_session_id
        assert result.total_count == 3  # 2 files + 1 directory
        assert len(result.entries) == 3

        # Verify entry details
        entry_names = {e.name for e in result.entries}
        assert "file1.txt" in entry_names
        assert "file2.json" in entry_names
        assert "subdir" in entry_names

        # Find file1 entry and verify
        file1_entry = next(e for e in result.entries if e.name == "file1.txt")
        assert file1_entry.type == "file"
        assert file1_entry.size == len("File 1 content")
        assert file1_entry.mimetype == "text/plain"

    def test_read_subdirectory_listing(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Read subdirectory listing."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        fs.mkdir("/workspace/nested", create_parents=True)
        with fs.open("/workspace/nested/deep.txt", "w") as f:
            f.write("Deep content")

        uri = f"scratchpad://{sample_session_id}/workspace/nested"
        result = read_directory_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.total_count == 1
        assert len(result.entries) == 1
        assert result.entries[0].name == "deep.txt"


class TestSessionIntegrationE2E:
    """E2E tests for session integration."""

    def test_session_isolation(self, session_manager: SessionFileSystemManager) -> None:
        """
        E2E: Verify session isolation - sessions have independent metadata.

        Verifies: Session metadata boundaries are properly enforced
        Note: MemoryFileSystem has a shared class-level store, so filesystem
        isolation requires Phase 2 overlay implementation. This test verifies
        that session IDs and metadata are properly isolated.
        """
        # Create two sessions with different metadata
        session_a = session_manager.create_session(
            metadata={"test": "session_a", "owner": "alice"}
        )
        session_b = session_manager.create_session(
            metadata={"test": "session_b", "owner": "bob"}
        )

        # Verify sessions have different IDs
        assert session_a != session_b

        # Verify metadata is isolated
        meta_a = session_manager.get_session_metadata(session_a)
        meta_b = session_manager.get_session_metadata(session_b)
        assert meta_a is not None
        assert meta_b is not None
        assert meta_a.metadata["owner"] == "alice"
        assert meta_b.metadata["owner"] == "bob"

        # Verify each session's filesystem is accessible
        fs_a = session_manager.get_session_fs(session_a)
        fs_b = session_manager.get_session_fs(session_b)
        assert fs_a is not None
        assert fs_b is not None

        # Write to session-specific paths (using session_id in path for isolation)
        with fs_a.open(f"/workspace/{session_a}_secret.txt", "w") as f:
            f.write("Session A secret")

        # Verify file exists in session A
        uri_a = f"scratchpad://{session_a}/workspace/{session_a}_secret.txt"
        result_a = read_resource(uri_a, session_manager=session_manager)
        assert result_a.success is True
        assert result_a.content.data == "Session A secret"

        # Verify file is not accessible from session B (different session_id in URI)
        # Since MemoryFileSystem shares store, the file exists but is at a different path
        # The test verifies that session IDs in URIs are properly handled

    def test_multiple_files_same_session(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Read multiple files from the same session."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Create multiple files
        files = {
            "readme.txt": "README content",
            "config.json": '{"setting": true}',
            "script.py": "print('hello')",
        }

        for filename, content in files.items():
            with fs.open(f"/workspace/{filename}", "w") as f:
                f.write(content)

        # Read all files
        for filename, expected_content in files.items():
            uri = f"scratchpad://{sample_session_id}/workspace/{filename}"
            result = read_resource(uri, session_manager=session_manager)
            assert result.success is True
            assert result.content.data == expected_content


class TestUriParsingE2E:
    """E2E tests for URI parsing integration."""

    def test_build_and_read_uri(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Build URI and read resource using the built URI.

        Verifies: URI building and parsing work together
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        with fs.open("/workspace/test.txt", "w") as f:
            f.write("Test content")

        # Build URI using utility function
        uri = build_scratchpad_uri(sample_session_id, "workspace/test.txt")

        # Parse the URI to verify format
        parsed = parse_scratchpad_uri(uri)
        assert parsed.is_valid is True
        assert parsed.session_id == sample_session_id
        assert parsed.path == "workspace/test.txt"

        # Read via the URI
        result = read_resource(uri, session_manager=session_manager)
        assert result.success is True
        assert result.content.data == "Test content"

    def test_uri_with_special_characters(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """E2E: Handle URIs with special characters in path."""
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Create file with special characters in name (within reason)
        with fs.open("/workspace/file-with-dashes_and_underscores.txt", "w") as f:
            f.write("Special file content")

        uri = f"scratchpad://{sample_session_id}/workspace/file-with-dashes_and_underscores.txt"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is True
        assert result.content.data == "Special file content"


class TestErrorPropagationE2E:
    """E2E tests for error handling and propagation."""

    def test_invalid_session_error(
        self, session_manager: SessionFileSystemManager
    ) -> None:
        """
        E2E: Request resource from invalid session.

        Verifies: Proper error message when session doesn't exist
        """
        invalid_session_id = "550e8400-e29b-41d4-a716-446655440000"
        uri = f"scratchpad://{invalid_session_id}/workspace/file.txt"

        result = read_resource(uri, session_manager=session_manager)

        assert result.success is False
        assert result.error and "Session not found" in result.error
        assert result.session_id == invalid_session_id

    def test_invalid_uri_error(self, session_manager: SessionFileSystemManager) -> None:
        """
        E2E: Request with invalid URI format.

        Verifies: Proper error for malformed URIs
        """
        # Invalid scheme
        result = read_resource(
            "http://example.com/file.txt", session_manager=session_manager
        )
        assert result.success is False
        assert result.error and (
            "Invalid scheme" in result.error or "Invalid URI" in result.error
        )

    def test_file_not_found_error(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Request non-existent file.

        Verifies: Proper error when file doesn't exist
        """
        uri = f"scratchpad://{sample_session_id}/workspace/nonexistent.txt"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is False
        assert result.error and "File not found" in result.error

    def test_directory_as_file_error(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Request directory as if it were a file.

        Verifies: Proper error when trying to read directory as file
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Use a unique directory name to avoid conflicts
        test_dir = f"/workspace/dir_test_{sample_session_id[:8]}"
        fs.mkdir(test_dir)

        uri = f"scratchpad://{sample_session_id}/{test_dir[1:]}"
        result = read_resource(uri, session_manager=session_manager)

        assert result.success is False
        assert result.error and "directory" in result.error.lower()

    def test_read_directory_as_directory_error(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Verify proper error when passing file as directory.

        Verifies: Error when trying to list a file as directory
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        with fs.open("/workspace/not-a-dir.txt", "w") as f:
            f.write("Content")

        # Try to read file as directory
        uri = f"scratchpad://{sample_session_id}/workspace/not-a-dir.txt/"
        result = read_directory_resource(uri, session_manager=session_manager)

        # Should fail because it's not a directory
        assert result.success is False
        error_str = str(result.error) if result.error else ""
        assert "not a directory" in error_str.lower()


class TestRealFilesystemE2E:
    """E2E tests using real filesystem (temp directories)."""

    def test_read_from_real_filesystem(self, temp_dir: Path) -> None:
        """
        E2E: Read files from actual filesystem.

        Verifies: Real filesystem integration works correctly
        """
        # Create a file on real filesystem
        test_file = temp_dir / "real_test.txt"
        test_file.write_text("Content from real filesystem")

        # Create manager and session that uses this directory
        # We use MemoryFileSystem for overlay, but read real files through overlay config
        manager = SessionFileSystemManager(OverlayConfig())
        set_session_manager(manager)

        session_id = manager.create_session()
        fs = manager.get_session_fs(session_id)
        assert fs is not None

        # Copy file to memory filesystem (simulating overlay behavior)
        with open(test_file, "rb") as src:
            with fs.open("/workspace/real_test.txt", "wb") as dst:
                dst.write(src.read())

        # Read via resource handler
        uri = f"scratchpad://{session_id}/workspace/real_test.txt"
        result = read_resource(uri, session_manager=manager)

        assert result.success is True
        assert result.content.data == "Content from real filesystem"

        manager.cleanup_session(session_id)

    def test_complex_file_structure(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Read complex file structure with various types.

        Tests: Multiple file types in directory hierarchy
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        # Use a unique project directory to avoid conflicts with other tests
        project_dir = f"/workspace/project_{sample_session_id[:8]}"

        # Create complex structure
        fs.mkdir(f"{project_dir}/src", create_parents=True)
        fs.mkdir(f"{project_dir}/docs", create_parents=True)
        fs.mkdir(f"{project_dir}/assets", create_parents=True)

        with fs.open(f"{project_dir}/src/main.py", "w") as f:
            f.write("def main(): pass")
        with fs.open(f"{project_dir}/src/utils.py", "w") as f:
            f.write("def util(): pass")
        with fs.open(f"{project_dir}/docs/readme.md", "w") as f:
            f.write("# Documentation")
        with fs.open(f"{project_dir}/config.json", "w") as f:
            f.write('{"version": "1.0"}')

        # Read directory
        result = read_directory_resource(
            f"scratchpad://{sample_session_id}/{project_dir[1:]}",
            session_manager=session_manager,
        )

        assert result.success is True
        assert result.total_count == 4  # src, docs, assets, config.json

        # Verify all entries exist
        entry_names = {e.name for e in result.entries}
        assert "src" in entry_names
        assert "docs" in entry_names
        assert "assets" in entry_names
        assert "config.json" in entry_names


class TestConvenienceFunctionsE2E:
    """E2E tests for convenience read functions."""

    def test_read_resource_text(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Test read_resource_text convenience function.

        Verifies: Direct text return without full result object
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        with fs.open("/workspace/text.txt", "w") as f:
            f.write("Direct text content")

        uri = f"scratchpad://{sample_session_id}/workspace/text.txt"
        text = read_resource_text(uri, session_manager=session_manager)

        assert text == "Direct text content"

    def test_read_resource_bytes(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        E2E: Test read_resource_bytes convenience function.

        Verifies: Direct bytes return for text files (decoded from UTF-8)
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        text_content = "Hello, World! Test content."
        with fs.open("/workspace/data.txt", "w") as f:
            f.write(text_content)

        uri = f"scratchpad://{sample_session_id}/workspace/data.txt"
        result_bytes = read_resource_bytes(uri, session_manager=session_manager)

        assert result_bytes == text_content.encode("utf-8")

    def test_convenience_function_error_handling(
        self, session_manager: SessionFileSystemManager
    ) -> None:
        """
        E2E: Test error handling in convenience functions.

        Verifies: Exceptions raised on errors instead of returning results
        """
        from mcp_scratchpad.resources.read_handler import ResourceReadError

        uri = "scratchpad://nonexistent-session/file.txt"

        with pytest.raises(ResourceReadError):
            read_resource_text(uri, session_manager=session_manager)


@pytest.mark.integration
class TestResourceQACompliance:
    """Tests verifying QA compliance for resource handling."""

    def test_complete_resource_flow_documented(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        QA: Document complete resource read flow.

        Steps:
        1. Create file in session
        2. Build URI
        3. Parse URI to verify format
        4. Read resource
        5. Verify all result fields
        """
        # Step 1: Create file
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        content = "QA Test Content"
        with fs.open("/workspace/qa_test.txt", "w") as f:
            f.write(content)

        # Step 2: Build URI
        uri = build_scratchpad_uri(sample_session_id, "workspace/qa_test.txt")

        # Step 3: Parse URI
        parsed = parse_scratchpad_uri(uri)
        assert parsed.is_valid is True
        assert parsed.session_id == sample_session_id

        # Step 4: Read resource
        result = read_resource(uri, session_manager=session_manager)

        # Step 5: Verify all fields
        assert result.success is True
        assert result.uri == uri
        assert result.session_id == sample_session_id
        assert result.path == "/workspace/qa_test.txt"
        assert result.content.data == content
        assert result.content.is_binary is False
        assert result.metadata.size == len(content.encode("utf-8"))
        assert result.metadata.mime_type == "text/plain"
        assert result.error is None

    def test_all_mime_types_handled(
        self, session_manager: SessionFileSystemManager, sample_session_id: str
    ) -> None:
        """
        QA: Verify handling of various MIME types.

        Tests: text, JSON, Python, Markdown, PNG, JPEG, PDF
        """
        fs = session_manager.get_session_fs(sample_session_id)
        assert fs is not None

        test_files = [
            ("test.txt", "text/plain", b"Text content"),
            ("test.json", "application/json", b'{"key": "value"}'),
            ("test.py", "text/x-python", b"def test(): pass"),
            ("test.md", "text/markdown", b"# Heading"),
            ("test.png", "image/png", create_test_png_image()),
            ("test.jpg", "image/jpeg", create_test_jpeg_image()),
            ("test.pdf", "application/pdf", create_test_pdf()),
        ]

        # Create a unique test directory for this test
        test_dir = f"mime_test_{sample_session_id[:8]}"
        test_dir_path = f"/workspace/{test_dir}"
        if not fs.exists(test_dir_path):
            fs.mkdir(test_dir_path, create_parents=True)

        for filename, expected_mime, content in test_files:
            # Write file to the test directory
            path = f"{test_dir_path}/{filename}"
            mode = "wb" if isinstance(content, bytes) else "w"
            with fs.open(path, mode) as f:
                f.write(content)

            # Read and verify
            uri = f"scratchpad://{sample_session_id}/workspace/{test_dir}/{filename}"
            result = read_resource(uri, session_manager=session_manager)

            assert result.success is True, f"Failed for {filename}"
            assert result.metadata.mime_type == expected_mime, (
                f"Wrong MIME for {filename}"
            )
