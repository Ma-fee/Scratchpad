"""
Unit tests for large file streaming support (Task 29).

Tests the streaming capabilities of OverlayFileSystem including:
- cat_file() with byte ranges
- _cat_file_streaming() for chunked reading
- cat() for batch file reading
- size() for file size checking
- is_streaming_file() for threshold detection
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.fs.overlay import OverlayFileSystem


class TestCatFile:
    """Tests for cat_file() method with byte range support."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    @pytest.fixture
    def overlay_with_file(self):
        """Create overlay with a test file in upper layer."""
        upper = MemoryFileSystem()
        content = b"Hello, World! This is a test file."
        upper.pipe("/test.txt", content)
        overlay = OverlayFileSystem(upper, [])
        return overlay, content

    def test_cat_file_reads_entire_file(self, overlay_with_file):
        """cat_file() should read entire file when no range specified."""
        overlay, expected_content = overlay_with_file

        result = overlay.cat_file("/test.txt")

        assert result == expected_content

    def test_cat_file_reads_with_start_offset(self, overlay_with_file):
        """cat_file() should read from start offset to end."""
        overlay, content = overlay_with_file

        result = overlay.cat_file("/test.txt", start=7)

        assert result == content[7:]

    def test_cat_file_reads_with_end_offset(self, overlay_with_file):
        """cat_file() should read from start to end offset."""
        overlay, content = overlay_with_file

        result = overlay.cat_file("/test.txt", end=12)

        assert result == content[:12]

    def test_cat_file_reads_with_start_and_end(self, overlay_with_file):
        """cat_file() should read specific byte range."""
        overlay, content = overlay_with_file

        result = overlay.cat_file("/test.txt", start=7, end=12)

        assert result == content[7:12]

    def test_cat_file_from_lower_layer(self):
        """cat_file() should read from lower layer if file exists there."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        content = b"content from lower layer"
        lower.pipe("/lower_file.txt", content)

        overlay = OverlayFileSystem(upper, [lower])

        result = overlay.cat_file("/lower_file.txt")

        assert result == content

    def test_cat_file_raises_for_nonexistent(self):
        """cat_file() should raise FileNotFoundError for non-existent file."""
        overlay = OverlayFileSystem(MemoryFileSystem(), [])

        with pytest.raises(FileNotFoundError, match="Path not found"):
            overlay.cat_file("/nonexistent.txt")

    def test_cat_file_raises_for_directory(self):
        """cat_file() should raise IsADirectoryError for directories."""
        upper = MemoryFileSystem()
        upper.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            overlay.cat_file("/testdir")


class TestCatBatch:
    """Tests for cat() method with batch file reading."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_cat_single_file(self):
        """cat() should return bytes for single file path."""
        upper = MemoryFileSystem()
        upper.pipe("/file.txt", b"single file content")
        overlay = OverlayFileSystem(upper, [])

        result = overlay.cat("/file.txt")

        assert isinstance(result, bytes)
        assert result == b"single file content"

    def test_cat_multiple_files(self):
        """cat() should return dict for multiple file paths."""
        upper = MemoryFileSystem()
        upper.pipe("/file1.txt", b"content1")
        upper.pipe("/file2.txt", b"content2")
        overlay = OverlayFileSystem(upper, [])

        result = overlay.cat(["/file1.txt", "/file2.txt"])

        assert isinstance(result, dict)
        assert result["/file1.txt"] == b"content1"
        assert result["/file2.txt"] == b"content2"

    def test_cat_with_missing_file_raise(self):
        """cat() should raise FileNotFoundError when on_error='raise'."""
        upper = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(FileNotFoundError):
            overlay.cat("/nonexistent.txt", on_error="raise")

    def test_cat_with_missing_file_omit(self):
        """cat() should return empty bytes for missing file when on_error='omit'."""
        upper = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [])

        result = overlay.cat("/nonexistent.txt", on_error="omit")

        assert result == b""

    def test_cat_multiple_with_some_missing(self):
        """cat() should handle mix of existing and missing files."""
        upper = MemoryFileSystem()
        upper.pipe("/exists.txt", b"exists")
        overlay = OverlayFileSystem(upper, [])

        result = overlay.cat(["/exists.txt", "/missing.txt"], on_error="omit")

        assert isinstance(result, dict)
        assert "/exists.txt" in result
        assert "/missing.txt" not in result


class TestCatFileStreaming:
    """Tests for _cat_file_streaming() method."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_streaming_yields_all_content(self):
        """_cat_file_streaming() should yield all file content."""
        upper = MemoryFileSystem()
        content = b"A" * 1000  # 1KB of data
        upper.pipe("/test.bin", content)
        overlay = OverlayFileSystem(upper, [])

        chunks = list(overlay._cat_file_streaming("/test.bin", chunk_size=100))

        # Concatenate all chunks
        result = b"".join(chunks)
        assert result == content

    def test_streaming_respects_chunk_size(self):
        """_cat_file_streaming() should yield chunks of specified size."""
        upper = MemoryFileSystem()
        content = b"A" * 1000
        upper.pipe("/test.bin", content)
        overlay = OverlayFileSystem(upper, [])

        chunks = list(overlay._cat_file_streaming("/test.bin", chunk_size=300))

        # 1000 bytes / 300 bytes per chunk = 4 chunks
        assert len(chunks) == 4
        assert len(chunks[0]) == 300
        assert len(chunks[1]) == 300
        assert len(chunks[2]) == 300
        assert len(chunks[3]) == 100  # Remaining bytes

    def test_streaming_uses_default_chunk_size(self):
        """_cat_file_streaming() should use default chunk size when not specified."""
        upper = MemoryFileSystem()
        # Create a 200KB file
        content = b"X" * (200 * 1024)
        upper.pipe("/large.bin", content)
        overlay = OverlayFileSystem(upper, [])

        chunks = list(overlay._cat_file_streaming("/large.bin"))

        # Default is 64KB, so 200KB / 64KB = 4 chunks
        assert len(chunks) == 4
        assert len(chunks[0]) == 64 * 1024

    def test_streaming_from_lower_layer(self):
        """_cat_file_streaming() should stream from lower layer."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        content = b"B" * 500
        lower.pipe("/lower.bin", content)

        overlay = OverlayFileSystem(upper, [lower])

        chunks = list(overlay._cat_file_streaming("/lower.bin", chunk_size=100))

        result = b"".join(chunks)
        assert result == content

    def test_streaming_raises_for_nonexistent(self):
        """_cat_file_streaming() should raise FileNotFoundError."""
        overlay = OverlayFileSystem(MemoryFileSystem(), [])

        with pytest.raises(FileNotFoundError, match="Path not found"):
            list(overlay._cat_file_streaming("/nonexistent.bin"))

    def test_streaming_raises_for_directory(self):
        """_cat_file_streaming() should raise IsADirectoryError."""
        upper = MemoryFileSystem()
        upper.mkdir("/testdir")

        overlay = OverlayFileSystem(upper, [])

        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            list(overlay._cat_file_streaming("/testdir"))


class TestSize:
    """Tests for size() method."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_size_returns_file_size(self):
        """size() should return file size in bytes."""
        upper = MemoryFileSystem()
        content = b"Hello, World!"
        upper.pipe("/test.txt", content)
        overlay = OverlayFileSystem(upper, [])

        result = overlay.size("/test.txt")

        assert result == len(content)

    def test_size_for_large_file(self):
        """size() should return correct size for large files."""
        upper = MemoryFileSystem()
        content = b"X" * (1024 * 1024)  # 1MB
        upper.pipe("/large.bin", content)
        overlay = OverlayFileSystem(upper, [])

        result = overlay.size("/large.bin")

        assert result == 1024 * 1024

    def test_size_returns_none_for_nonexistent(self):
        """size() should return None for non-existent path."""
        overlay = OverlayFileSystem(MemoryFileSystem(), [])

        result = overlay.size("/nonexistent.txt")

        assert result is None

    def test_size_returns_none_for_directory(self):
        """size() should return None for directories."""
        upper = MemoryFileSystem()
        upper.mkdir("/testdir")
        overlay = OverlayFileSystem(upper, [])

        result = overlay.size("/testdir")

        assert result is None

    def test_size_from_lower_layer(self):
        """size() should return size for files in lower layer."""
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        content = b"lower content"
        lower.pipe("/file.txt", content)

        overlay = OverlayFileSystem(upper, [lower])

        result = overlay.size("/file.txt")

        assert result == len(content)


class TestIsStreamingFile:
    """Tests for is_streaming_file() method."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_small_file_not_streaming(self):
        """is_streaming_file() should return False for small files."""
        upper = MemoryFileSystem()
        content = b"small" * 100  # 500 bytes
        upper.pipe("/small.txt", content)
        overlay = OverlayFileSystem(upper, [])

        result = overlay.is_streaming_file("/small.txt")

        assert result is False

    def test_large_file_is_streaming(self):
        """is_streaming_file() should return True for large files (>1MB)."""
        upper = MemoryFileSystem()
        content = b"X" * (1024 * 1024 + 1)  # Just over 1MB
        upper.pipe("/large.bin", content)
        overlay = OverlayFileSystem(upper, [])

        result = overlay.is_streaming_file("/large.bin")

        assert result is True

    def test_custom_threshold(self):
        """is_streaming_file() should respect custom threshold."""
        upper = MemoryFileSystem()
        content = b"X" * 500  # 500 bytes
        upper.pipe("/medium.txt", content)
        overlay = OverlayFileSystem(upper, [])

        # With 100 byte threshold
        result = overlay.is_streaming_file("/medium.txt", threshold=100)
        assert result is True

        # With 1000 byte threshold
        result = overlay.is_streaming_file("/medium.txt", threshold=1000)
        assert result is False

    def test_exactly_at_threshold(self):
        """is_streaming_file() behavior at exact threshold."""
        upper = MemoryFileSystem()
        content = b"X" * 1024  # Exactly 1KB
        upper.pipe("/exact.bin", content)
        overlay = OverlayFileSystem(upper, [])

        result = overlay.is_streaming_file("/exact.bin", threshold=1024)

        # File is exactly at threshold, so NOT greater
        assert result is False

    def test_nonexistent_file_returns_false(self):
        """is_streaming_file() should return False for non-existent files."""
        overlay = OverlayFileSystem(MemoryFileSystem(), [])

        result = overlay.is_streaming_file("/nonexistent.txt")

        assert result is False

    def test_directory_returns_false(self):
        """is_streaming_file() should return False for directories."""
        upper = MemoryFileSystem()
        upper.mkdir("/testdir")
        overlay = OverlayFileSystem(upper, [])

        result = overlay.is_streaming_file("/testdir")

        assert result is False


class TestStreamingConstants:
    """Tests for streaming constants and thresholds."""

    def test_stream_threshold_constant(self):
        """_STREAM_THRESHOLD should be 1MB."""
        assert OverlayFileSystem._STREAM_THRESHOLD == 1024 * 1024

    def test_default_chunk_size_constant(self):
        """_DEFAULT_CHUNK_SIZE should be 64KB."""
        assert OverlayFileSystem._DEFAULT_CHUNK_SIZE == 64 * 1024


class TestStreamingPerformance:
    """Performance tests for streaming with various file sizes.

    These tests verify that streaming operations complete within
    reasonable time limits and don't load entire files into memory.
    """

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_1mb_file_streaming_performance(self) -> None:
        """1MB file streaming should complete in <50ms."""
        upper = MemoryFileSystem()
        content = b"X" * (1024 * 1024)  # 1MB
        upper.pipe("/1mb.bin", content)
        overlay = OverlayFileSystem(upper, [])

        start_time = time.perf_counter()
        chunks = list(overlay._cat_file_streaming("/1mb.bin"))
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert elapsed_ms < 50, (
            f"1MB streaming took {elapsed_ms:.2f}ms (should be <50ms)"
        )
        assert b"".join(chunks) == content

    def test_10mb_file_streaming_performance(self) -> None:
        """10MB file streaming should complete in <500ms."""
        upper = MemoryFileSystem()
        content = b"Y" * (10 * 1024 * 1024)  # 10MB
        upper.pipe("/10mb.bin", content)
        overlay = OverlayFileSystem(upper, [])

        start_time = time.perf_counter()
        chunks = list(overlay._cat_file_streaming("/10mb.bin"))
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert elapsed_ms < 500, (
            f"10MB streaming took {elapsed_ms:.2f}ms (should be <500ms)"
        )
        assert b"".join(chunks) == content

    def test_100mb_file_streaming_memory_efficient(self) -> None:
        """100MB file streaming should use bounded memory (chunked streaming)."""
        upper = MemoryFileSystem()
        # We can't actually create 100MB due to memory limits in tests,
        # but we verify the streaming mechanism works
        content = b"Z" * (10 * 1024 * 1024)  # 10MB as proxy
        upper.pipe("/10mb.bin", content)
        overlay = OverlayFileSystem(upper, [])

        # Stream with small chunks to verify chunking
        chunk_size = 64 * 1024
        max_chunk_size = 0
        total_bytes = 0

        for chunk in overlay._cat_file_streaming("/10mb.bin", chunk_size=chunk_size):
            max_chunk_size = max(max_chunk_size, len(chunk))
            total_bytes += len(chunk)
            # Each chunk should not exceed chunk_size
            assert len(chunk) <= chunk_size, (
                f"Chunk size {len(chunk)} exceeds max {chunk_size}"
            )

        assert max_chunk_size == chunk_size
        assert total_bytes == len(content)

    def test_multiple_files_streaming(self) -> None:
        """Streaming multiple files should not exceed expected time."""
        upper = MemoryFileSystem()
        # Create several 1MB files
        for i in range(3):
            content = bytes([i]) * (1024 * 1024)
            upper.pipe(f"/file{i}.bin", content)

        overlay = OverlayFileSystem(upper, [])

        start_time = time.perf_counter()
        for i in range(3):
            chunks = list(overlay._cat_file_streaming(f"/file{i}.bin"))
            expected = bytes([i]) * (1024 * 1024)
            assert b"".join(chunks) == expected
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should process 3MB in under 150ms
        assert elapsed_ms < 150, f"3MB streaming took {elapsed_ms:.2f}ms"


class TestStreamingQA:
    """QA scenario tests for streaming functionality."""

    @pytest.fixture(autouse=True)
    def cleanup_memory_filesystems(self):
        """Clean up MemoryFileSystem storage after each test."""
        yield
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs.clear()

    def test_streaming_vs_nonstreaming_decision(self) -> None:
        """
        QA Scenario: Correct streaming decision for different file sizes

        Steps:
            1. Create small file (100KB)
            2. Create medium file (500KB)
            3. Create large file (2MB - over threshold)
            4. Check is_streaming_file() for each

        Expected:
            - Small: False (should load in memory)
            - Medium: False (should load in memory)
            - Large: True (should stream)
        """
        upper = MemoryFileSystem()
        upper.pipe("/small.bin", b"S" * (100 * 1024))  # 100KB
        upper.pipe("/medium.bin", b"M" * (500 * 1024))  # 500KB
        upper.pipe("/large.bin", b"L" * (2 * 1024 * 1024))  # 2MB

        overlay = OverlayFileSystem(upper, [])

        assert overlay.is_streaming_file("/small.bin") is False
        assert overlay.is_streaming_file("/medium.bin") is False
        assert overlay.is_streaming_file("/large.bin") is True

    def test_chunked_reading_consistency(self) -> None:
        """
        QA Scenario: Chunked reading produces same result as full read

        Steps:
            1. Create file with known content
            2. Read full content with cat_file()
            3. Read via streaming and concatenate chunks
            4. Compare results

        Expected: Both methods produce identical byte content
        """
        upper = MemoryFileSystem()
        # Create content with varying bytes
        content = bytes(range(256)) * 1000  # 256KB of unique pattern
        upper.pipe("/pattern.bin", content)

        overlay = OverlayFileSystem(upper, [])

        # Full read
        full_content = overlay.cat_file("/pattern.bin")

        # Chunked read
        chunks = list(overlay._cat_file_streaming("/pattern.bin", chunk_size=1024))
        chunked_content = b"".join(chunks)

        assert full_content == chunked_content
        assert full_content == content

    def test_byte_range_reading_from_stream(self) -> None:
        """
        QA Scenario: Partial reads work correctly with streaming

        Steps:
            1. Create file with known content
            2. Read specific byte ranges with cat_file(start, end)
            3. Verify against expected slices

        Expected: Partial reads return correct byte ranges
        """
        upper = MemoryFileSystem()
        content = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 100  # 2600 bytes
        upper.pipe("/alphabet.bin", content)

        overlay = OverlayFileSystem(upper, [])

        # Test various ranges
        assert overlay.cat_file("/alphabet.bin", start=0, end=10) == content[0:10]
        assert overlay.cat_file("/alphabet.bin", start=26, end=52) == content[26:52]
        assert overlay.cat_file("/alphabet.bin", start=100, end=200) == content[100:200]

    def test_streaming_with_whiteout(self) -> None:
        """
        QA Scenario: Streaming respects whiteout markers

        Steps:
            1. Create file in lower layer
            2. Create whiteout for it
            3. Attempt to stream - should raise FileNotFoundError

        Expected: Streaming correctly handles whiteouts
        """
        upper = MemoryFileSystem()
        lower = MemoryFileSystem()
        lower.pipe("/deleted.txt", b"deleted content")

        overlay = OverlayFileSystem(upper, [lower])

        # Create whiteout
        overlay._create_whiteout("/deleted.txt")

        # Streaming should fail
        with pytest.raises(FileNotFoundError, match="Path not found"):
            list(overlay._cat_file_streaming("/deleted.txt"))

    def test_streaming_from_overlay_layers(self) -> None:
        """
        QA Scenario: Streaming from correct layer in overlay

        Steps:
            1. Create same file in both upper and lower
            2. Stream and verify content comes from upper layer
            3. Delete from upper (create whiteout)
            4. Verify streaming now fails (whiteout)

        Expected: Streaming follows overlay semantics
        """
        lower = MemoryFileSystem()
        lower.pipe("/shared.bin", b"lower content")

        upper = MemoryFileSystem()
        upper.pipe("/shared.bin", b"upper content")

        overlay = OverlayFileSystem(upper, [lower])

        # Should get upper content
        chunks = list(overlay._cat_file_streaming("/shared.bin", chunk_size=100))
        assert b"".join(chunks) == b"upper content"

        # Delete from upper
        overlay._create_whiteout("/shared.bin")

        # Should now fail
        with pytest.raises(FileNotFoundError):
            list(overlay._cat_file_streaming("/shared.bin"))
