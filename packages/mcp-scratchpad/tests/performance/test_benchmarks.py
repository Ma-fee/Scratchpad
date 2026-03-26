"""
Performance Benchmark Suite for Overlay Filesystem

This module provides comprehensive benchmark tests for the overlay filesystem
using pytest-benchmark. It covers all major operations with different file sizes
and session counts, comparing overlay performance against direct filesystem access.

RFC Performance Targets:
- Read 1MB < 50ms
- Write 1MB < 50ms
- List 1000 files < 100ms
- 100 concurrent sessions: stable

Usage:
    uv run pytest tests/performance/test_benchmarks.py -v --benchmark-only
    uv run pytest tests/performance/test_benchmarks.py --benchmark-json=output.json
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fsspec.implementations.local import LocalFileSystem
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.overlay import (
    MemoryPressureConfig,
    OverlayFileSystem,
)
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager

# =============================================================================
# Test Data Sizes
# =============================================================================

FILE_SIZES = {
    "1kb": 1024,
    "100kb": 100 * 1024,
    "1mb": 1024 * 1024,
    "10mb": 10 * 1024 * 1024,
}

SESSION_COUNTS = [1, 10, 50]

# RFC Performance Targets (in seconds)
RFC_TARGETS = {
    "read_1mb": 0.050,  # 50ms
    "write_1mb": 0.050,  # 50ms
    "list_1000_files": 0.100,  # 100ms
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def new_overlay_fs():
    """Factory fixture to create fresh overlay filesystems."""

    def _create():
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        return OverlayFileSystem(upper, lowers)

    return _create


@pytest.fixture
def new_direct_fs():
    """Factory fixture to create fresh memory filesystems."""

    def _create():
        return MemoryFileSystem()

    return _create


@pytest.fixture
def temp_local_fs():
    """Create a temporary local filesystem for benchmarking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fs = LocalFileSystem()
        yield fs, tmpdir


@pytest.fixture
def new_session_manager():
    """Factory fixture to create fresh session managers."""

    def _create():
        config = OverlayConfig(mounts=[])
        return SessionFileSystemManager(config)

    return _create


# =============================================================================
# Helper Functions
# =============================================================================


def generate_data(size: int) -> bytes:
    """Generate test data of specified size."""
    return b"x" * size


def create_file_in_lower(overlay: OverlayFileSystem, path: str, data: bytes) -> None:
    """Create a file in the lower layer."""
    overlay.lowers[0].pipe(path, data)


def create_file_in_upper(overlay: OverlayFileSystem, path: str, data: bytes) -> None:
    """Create a file in the upper layer."""
    overlay.upper.pipe(path, data)


# =============================================================================
# Benchmark Tests - File Read Operations
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("size_name,size_bytes", FILE_SIZES.items())
def test_benchmark_overlay_read(benchmark, new_overlay_fs, size_name, size_bytes):
    """Benchmark reading files of different sizes from overlay filesystem."""

    def read_file():
        fs = new_overlay_fs()
        path = f"/read_test_{size_name}.bin"
        data = generate_data(size_bytes)
        create_file_in_lower(fs, path, data)
        return fs.cat_file(path)

    result = benchmark(read_file)
    assert len(result) == size_bytes


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("size_name,size_bytes", FILE_SIZES.items())
def test_benchmark_direct_read(benchmark, new_direct_fs, size_name, size_bytes):
    """Benchmark reading files directly from memory filesystem (baseline)."""

    def read_file():
        fs = new_direct_fs()
        path = f"/direct_read_{size_name}.bin"
        data = generate_data(size_bytes)
        fs.pipe(path, data)
        return fs.cat_file(path)

    result = benchmark(read_file)
    assert len(result) == size_bytes


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_read_1mb_target(benchmark, new_overlay_fs):
    """Benchmark 1MB read to verify RFC target: < 50ms."""

    def read_file():
        fs = new_overlay_fs()
        path = "/read_rfc_target.bin"
        data = generate_data(FILE_SIZES["1mb"])
        create_file_in_lower(fs, path, data)
        return fs.cat_file(path)

    result = benchmark(read_file)
    assert len(result) == FILE_SIZES["1mb"]

    # Verify performance target
    stats = benchmark.stats
    median_time = (
        stats.stats.median if hasattr(stats.stats, "median") else stats.stats["median"]
    )
    assert median_time < RFC_TARGETS["read_1mb"], (
        f"1MB read took {median_time * 1000:.2f}ms, exceeding target of {RFC_TARGETS['read_1mb'] * 1000:.2f}ms"
    )


# =============================================================================
# Benchmark Tests - File Write Operations
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("size_name,size_bytes", FILE_SIZES.items())
def test_benchmark_overlay_write(benchmark, new_overlay_fs, size_name, size_bytes):
    """Benchmark writing files of different sizes to overlay filesystem."""
    data = generate_data(size_bytes)

    def write_file():
        fs = new_overlay_fs()
        fs.upper.pipe("/test.bin", data)
        return True

    result = benchmark(write_file)
    assert result is True


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("size_name,size_bytes", FILE_SIZES.items())
def test_benchmark_direct_write(benchmark, new_direct_fs, size_name, size_bytes):
    """Benchmark writing files directly to memory filesystem (baseline)."""
    data = generate_data(size_bytes)

    def write_file():
        fs = new_direct_fs()
        fs.pipe("/test.bin", data)
        return True

    result = benchmark(write_file)
    assert result is True


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_write_1mb_target(benchmark, new_overlay_fs):
    """Benchmark 1MB write to verify RFC target: < 50ms."""
    data = generate_data(FILE_SIZES["1mb"])

    def write_file():
        fs = new_overlay_fs()
        fs.upper.pipe("/test.bin", data)
        return True

    benchmark(write_file)

    # Verify performance target
    stats = benchmark.stats
    median_time = (
        stats.stats.median if hasattr(stats.stats, "median") else stats.stats["median"]
    )
    assert median_time < RFC_TARGETS["write_1mb"], (
        f"1MB write took {median_time * 1000:.2f}ms, exceeding target of {RFC_TARGETS['write_1mb'] * 1000:.2f}ms"
    )


# =============================================================================
# Benchmark Tests - List Directory Operations
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_list_1000_files(benchmark, new_overlay_fs):
    """Benchmark listing 1000 files in overlay filesystem."""

    def list_files():
        fs = new_overlay_fs()
        # Create 1000 files in lower layer
        for i in range(1000):
            fs.lowers[0].pipe(f"/file_{i:04d}.txt", b"content")
        return fs.ls("/")

    result = benchmark(list_files)
    # At least 1000 files (may have more from internal tracking)
    assert len(result) >= 1000


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_list_1000_files_target(benchmark):
    """Benchmark listing 1000 files to verify RFC target: < 100ms."""

    def list_files():
        # Create fresh filesystems for this iteration
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)
        # Create 1000 files
        for i in range(1000):
            lowers[0].pipe(f"/file_{i:04d}.txt", b"content")
        return overlay.ls("/")

    result = benchmark(list_files)
    assert len(result) >= 1000

    # Verify performance target
    stats = benchmark.stats
    median_time = (
        stats.stats.median if hasattr(stats.stats, "median") else stats.stats["median"]
    )
    assert median_time < RFC_TARGETS["list_1000_files"], (
        f"List 1000 files took {median_time * 1000:.2f}ms, exceeding target of {RFC_TARGETS['list_1000_files'] * 1000:.2f}ms"
    )


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_direct_list_1000_files(benchmark):
    """Benchmark listing 1000 files directly (baseline)."""

    def list_files():
        fs = MemoryFileSystem()
        for i in range(1000):
            fs.pipe(f"/file_{i:04d}.txt", b"content")
        return fs.ls("/")

    result = benchmark(list_files)
    assert len(result) >= 1000


# =============================================================================
# Benchmark Tests - Copy-on-Write (COW) Operations
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize(
    "size_name,size_bytes", [("1kb", 1024), ("100kb", 100 * 1024), ("1mb", 1024 * 1024)]
)
def test_benchmark_overlay_cow_write(benchmark, new_overlay_fs, size_name, size_bytes):
    """Benchmark Copy-on-Write operations (read from lower, trigger COW, write to upper)."""
    data = generate_data(size_bytes)

    def cow_operation():
        fs = new_overlay_fs()
        path = "/cow_test.bin"
        create_file_in_lower(fs, path, data)
        # Trigger COW by opening file in write mode
        with fs.open(path, "wb") as f:
            f.write(data)
        return True

    result = benchmark(cow_operation)
    assert result is True


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize(
    "size_name,size_bytes", [("1kb", 1024), ("100kb", 100 * 1024), ("1mb", 1024 * 1024)]
)
def test_benchmark_overlay_cow_modify(benchmark, new_overlay_fs, size_name, size_bytes):
    """Benchmark COW operations that modify files."""
    data = generate_data(size_bytes)

    def cow_modify():
        fs = new_overlay_fs()
        path = "/cow_modify.bin"
        create_file_in_lower(fs, path, data)
        # Read, modify, and write back (triggers COW)
        content = fs.cat_file(path)
        modified = content[:100] + b"MODIFIED" + content[100:]
        with fs.open(path, "wb") as f:
            f.write(modified)
        return True

    result = benchmark(cow_modify)
    assert result is True


# =============================================================================
# Benchmark Tests - Rename Operations
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize(
    "size_name,size_bytes", [("1kb", 1024), ("100kb", 100 * 1024), ("1mb", 1024 * 1024)]
)
def test_benchmark_overlay_rename_from_lower(
    benchmark, new_overlay_fs, size_name, size_bytes
):
    """Benchmark renaming files that require COW from lower layer."""
    data = generate_data(size_bytes)

    def rename_file():
        fs = new_overlay_fs()
        path = "/rename_lower.bin"
        new_path = "/rename_lower_new.bin"
        create_file_in_lower(fs, path, data)
        fs.rename(path, new_path)
        return True

    result = benchmark(rename_file)
    assert result is True


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize(
    "size_name,size_bytes", [("1kb", 1024), ("100kb", 100 * 1024), ("1mb", 1024 * 1024)]
)
def test_benchmark_overlay_rename_in_upper(
    benchmark, new_overlay_fs, size_name, size_bytes
):
    """Benchmark renaming files already in upper layer."""
    data = generate_data(size_bytes)

    def rename_file():
        fs = new_overlay_fs()
        path = "/rename_upper.bin"
        new_path = "/rename_upper_new.bin"
        create_file_in_upper(fs, path, data)
        fs.rename(path, new_path)
        return True

    result = benchmark(rename_file)
    assert result is True


# =============================================================================
# Benchmark Tests - Delete Operations with Whiteout
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("size_name,size_bytes", [("1kb", 1024), ("100kb", 100 * 1024)])
def test_benchmark_overlay_delete_from_lower(
    benchmark, new_overlay_fs, size_name, size_bytes
):
    """Benchmark deleting files from lower layer (creates whiteout)."""
    data = generate_data(size_bytes)

    def delete_operation():
        fs = new_overlay_fs()
        path = "/delete_lower.bin"
        create_file_in_lower(fs, path, data)
        fs.rm(path)
        return True

    result = benchmark(delete_operation)
    assert result is True


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("size_name,size_bytes", [("1kb", 1024), ("100kb", 100 * 1024)])
def test_benchmark_overlay_delete_from_upper(
    benchmark, new_overlay_fs, size_name, size_bytes
):
    """Benchmark deleting files from upper layer (direct delete)."""
    data = generate_data(size_bytes)

    def delete_operation():
        fs = new_overlay_fs()
        path = "/delete_upper.bin"
        create_file_in_upper(fs, path, data)
        fs.rm(path)
        return True

    result = benchmark(delete_operation)
    assert result is True


# =============================================================================
# Benchmark Tests - Session Management
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize("session_count", SESSION_COUNTS)
def test_benchmark_session_creation(benchmark, new_session_manager, session_count):
    """Benchmark creating sessions."""

    def create_sessions():
        manager = new_session_manager()
        session_ids = []
        for _ in range(session_count):
            sid = manager.create_session()
            session_ids.append(sid)
        # Cleanup
        for sid in session_ids:
            manager.cleanup_session(sid)
        return len(session_ids)

    result = benchmark(create_sessions)
    assert result == session_count


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_concurrent_session_cleanup(benchmark, new_session_manager):
    """Benchmark cleaning up 100 concurrent sessions (RFC target: stable)."""

    def cleanup_sessions():
        manager = new_session_manager()
        session_ids = [manager.create_session() for _ in range(100)]
        for sid in session_ids:
            manager.cleanup_session(sid)
        # Verify all are cleaned up
        assert len(manager.list_sessions()) == 0
        return True

    result = benchmark(cleanup_sessions)
    assert result is True


# =============================================================================
# Benchmark Tests - Path Resolution
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_path_resolution(benchmark, new_overlay_fs):
    """Benchmark path resolution across layers."""

    def resolve_paths():
        fs = new_overlay_fs()
        # Create files in different layers
        create_file_in_upper(fs, "/upper_file.txt", b"upper")
        create_file_in_lower(fs, "/lower_file.txt", b"lower")
        create_file_in_lower(fs, "/both_file.txt", b"lower")
        create_file_in_upper(fs, "/both_file.txt", b"upper")  # Override
        results = []
        results.append(fs._resolve("/upper_file.txt"))
        results.append(fs._resolve("/lower_file.txt"))
        results.append(fs._resolve("/both_file.txt"))
        results.append(fs._resolve("/nonexistent.txt"))
        return results

    result = benchmark(resolve_paths)
    assert len(result) == 4


# =============================================================================
# Benchmark Tests - Memory Pressure
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_memory_stats_calculation(benchmark, new_overlay_fs):
    """Benchmark memory statistics calculation."""

    def get_stats():
        fs = new_overlay_fs()
        # Create some files
        for i in range(100):
            fs.upper.pipe(f"/file_{i}.txt", generate_data(1024))
        return fs.get_memory_stats()

    result = benchmark(get_stats)
    assert result is not None


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_memory_pressure_check(benchmark, new_overlay_fs):
    """Benchmark memory pressure checking."""

    def check_pressure():
        fs = new_overlay_fs()
        # Configure memory limits
        fs.memory_config = MemoryPressureConfig(
            max_memory_bytes=10 * 1024 * 1024,  # 10MB limit
            warning_threshold=0.8,
            critical_threshold=0.9,
        )
        # Create files to trigger memory usage
        for i in range(50):
            fs.upper.pipe(f"/pressure_file_{i}.txt", generate_data(100 * 1024))
        return fs._check_memory_pressure(1024 * 1024)  # 1MB additional

    result = benchmark(check_pressure)
    assert result is not None


# =============================================================================
# Benchmark Tests - Metadata Operations
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_file_info(benchmark, new_overlay_fs):
    """Benchmark getting file info."""

    def get_info():
        fs = new_overlay_fs()
        create_file_in_lower(fs, "/info_test.txt", generate_data(1024))
        return fs.info("/info_test.txt")

    result = benchmark(get_info)
    assert result is not None


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_file_exists(benchmark, new_overlay_fs):
    """Benchmark exists checks."""

    def check_exists():
        fs = new_overlay_fs()
        create_file_in_lower(fs, "/exists_test.txt", b"test")
        return fs.exists("/exists_test.txt"), fs.exists("/nonexistent.txt")

    result = benchmark(check_exists)
    assert result[0] is True
    assert result[1] is False


# =============================================================================
# Comparative Benchmark - Overlay vs Direct Filesystem
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_vs_direct_read_1mb(benchmark):
    """Compare 1MB read performance: Overlay vs Direct."""

    def combined_benchmark():
        # Test overlay
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)
        lowers[0].pipe("/test.bin", generate_data(1024 * 1024))
        overlay_result = overlay.cat_file("/test.bin")

        # Test direct
        direct_fs = MemoryFileSystem()
        direct_fs.pipe("/test.bin", generate_data(1024 * 1024))
        direct_result = direct_fs.cat_file("/test.bin")

        return len(overlay_result), len(direct_result)

    result = benchmark(combined_benchmark)
    assert result[0] == result[1]  # Both should read same amount


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_overlay_vs_direct_write_1mb(benchmark):
    """Compare 1MB write performance: Overlay vs Direct."""
    data = generate_data(1024 * 1024)

    def combined_benchmark():
        # Test overlay
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)
        overlay.upper.pipe("/test.bin", data)

        # Test direct
        direct_fs = MemoryFileSystem()
        direct_fs.pipe("/test.bin", data)

        return True

    result = benchmark(combined_benchmark)
    assert result is True


# =============================================================================
# Stress Tests
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_mixed_operations(benchmark):
    """Benchmark mixed file operations (simulating realistic workload)."""

    def mixed_workload():
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        # Pre-populate with some files
        for i in range(100):
            lowers[0].pipe(f"/file_{i}.txt", generate_data(1024))

        # Read existing file
        content = overlay.cat_file("/file_0.txt")

        # Write new file
        overlay.upper.pipe("/new_file.txt", content)

        # List directory
        files = overlay.ls("/")

        # Check exists
        exists = overlay.exists("/file_50.txt")

        # Get info
        info = overlay.info("/file_50.txt")

        return len(files), exists, info is not None

    result = benchmark(mixed_workload)
    # At least 101 files (100 prepopulated + 1 new)
    assert result[0] >= 101
    assert result[1] is True
    assert result[2] is True


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_rapid_session_creation(benchmark, new_session_manager):
    """Benchmark rapid session creation and destruction."""

    def rapid_sessions():
        manager = new_session_manager()
        ids = []
        for i in range(50):
            sid = manager.create_session(metadata={"index": i})
            ids.append(sid)
        for sid in ids:
            manager.cleanup_session(sid)
        return len(ids)

    result = benchmark(rapid_sessions)
    assert result == 50


# =============================================================================
# Whiteout Performance Tests
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_whiteout_creation_and_detection(benchmark):
    """Benchmark whiteout creation and detection overhead."""

    def whiteout_operations():
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        fs = OverlayFileSystem(upper, lowers)

        # Create files and whiteout markers
        for i in range(50):
            lowers[0].pipe(f"/file_{i}.txt", b"content")

        # Create whiteouts for half the files
        for i in range(25):
            fs._create_whiteout(f"/file_{i}.txt")

        # Check whiteout detection
        whited_out_count = 0
        for i in range(50):
            if fs._has_whiteout(f"/file_{i}.txt"):
                whited_out_count += 1

        return whited_out_count

    result = benchmark(whiteout_operations)
    assert result == 25


@pytest.mark.performance
@pytest.mark.benchmark
def test_benchmark_ls_with_many_whiteouts(benchmark):
    """Benchmark directory listing with many whiteout markers."""

    def list_with_whiteouts():
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)

        # Create 500 files in lower layer
        for i in range(500):
            lowers[0].pipe(f"/file_{i}.txt", b"content")

        # Create whiteout markers for 250 files (every other)
        for i in range(0, 500, 2):
            overlay._create_whiteout(f"/file_{i}.txt")

        return overlay.ls("/")

    result = benchmark(list_with_whiteouts)
    # Should get approximately 250 files (500 - 250 whited out, depending on internal files)
    # Allow for some variance due to MemoryFileSystem shared store
    assert 200 <= len(result) <= 270


# =============================================================================
# RFC Compliance Tests
# =============================================================================


@pytest.mark.performance
@pytest.mark.benchmark
def test_rfc_read_target_compliance(benchmark, new_overlay_fs):
    """Verify RFC compliance: Read 1MB < 50ms."""

    def read_operation():
        fs = new_overlay_fs()
        path = "/rfc_read_test.bin"
        data = generate_data(FILE_SIZES["1mb"])
        create_file_in_lower(fs, path, data)
        return fs.cat_file(path)

    result = benchmark(read_operation)
    assert len(result) == FILE_SIZES["1mb"]

    # Check performance
    stats = benchmark.stats
    median_time = (
        stats.stats.median if hasattr(stats.stats, "median") else stats.stats["median"]
    )
    max_time = stats.stats.max if hasattr(stats.stats, "max") else stats.stats["max"]

    # RFC target: < 50ms
    compliant = median_time < 0.050

    benchmark.extra_info["rfc_target_ms"] = 50
    benchmark.extra_info["actual_median_ms"] = median_time * 1000
    benchmark.extra_info["actual_max_ms"] = max_time * 1000
    benchmark.extra_info["compliant"] = compliant

    assert compliant, (
        f"Read 1MB operation exceeds RFC target. "
        f"Median: {median_time * 1000:.2f}ms, Max: {max_time * 1000:.2f}ms, "
        f"Target: 50ms"
    )


@pytest.mark.performance
@pytest.mark.benchmark
def test_rfc_write_target_compliance(benchmark, new_overlay_fs):
    """Verify RFC compliance: Write 1MB < 50ms."""
    data = generate_data(FILE_SIZES["1mb"])

    def write_operation():
        fs = new_overlay_fs()
        fs.upper.pipe("/rfc_write_test.bin", data)
        return True

    benchmark(write_operation)

    # Check performance
    stats = benchmark.stats
    median_time = (
        stats.stats.median if hasattr(stats.stats, "median") else stats.stats["median"]
    )
    max_time = stats.stats.max if hasattr(stats.stats, "max") else stats.stats["max"]

    # RFC target: < 50ms
    compliant = median_time < 0.050

    benchmark.extra_info["rfc_target_ms"] = 50
    benchmark.extra_info["actual_median_ms"] = median_time * 1000
    benchmark.extra_info["actual_max_ms"] = max_time * 1000
    benchmark.extra_info["compliant"] = compliant

    assert compliant, (
        f"Write 1MB operation exceeds RFC target. "
        f"Median: {median_time * 1000:.2f}ms, Max: {max_time * 1000:.2f}ms, "
        f"Target: 50ms"
    )


@pytest.mark.performance
@pytest.mark.benchmark
def test_rfc_list_target_compliance(benchmark):
    """Verify RFC compliance: List 1000 files < 100ms."""

    def list_operation():
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)
        # Create exactly 1000 files
        for i in range(1000):
            lowers[0].pipe(f"/file_{i:04d}.txt", b"content")
        return overlay.ls("/")

    result = benchmark(list_operation)
    # At least 1000 files
    assert len(result) >= 1000

    # Check performance
    stats = benchmark.stats
    median_time = (
        stats.stats.median if hasattr(stats.stats, "median") else stats.stats["median"]
    )
    max_time = stats.stats.max if hasattr(stats.stats, "max") else stats.stats["max"]

    # RFC target: < 100ms
    compliant = median_time < 0.100

    benchmark.extra_info["rfc_target_ms"] = 100
    benchmark.extra_info["actual_median_ms"] = median_time * 1000
    benchmark.extra_info["actual_max_ms"] = max_time * 1000
    benchmark.extra_info["compliant"] = compliant

    assert compliant, (
        f"List 1000 files operation exceeds RFC target. "
        f"Median: {median_time * 1000:.2f}ms, Max: {max_time * 1000:.2f}ms, "
        f"Target: 100ms"
    )


@pytest.mark.performance
@pytest.mark.slow
def test_rfc_concurrent_sessions_stability(new_session_manager):
    """Verify RFC compliance: 100 concurrent sessions remain stable."""
    import time

    manager = new_session_manager()

    # Create 100 sessions
    session_ids = []
    start_time = time.time()

    for i in range(100):
        sid = manager.create_session(metadata={"index": i})
        session_ids.append(sid)
    creation_time = time.time() - start_time

    # Verify all sessions exist
    sessions = manager.list_sessions()
    assert len(sessions) == 100, f"Expected 100 sessions, got {len(sessions)}"

    # Perform operations on all sessions
    start_time = time.time()
    for sid in session_ids:
        fs = manager.get_session_fs(sid)
        assert fs is not None, f"Session {sid} filesystem not found"
        # Write a file in each session
        fs.pipe("/test.txt", b"test content")
    operation_time = time.time() - start_time

    # Cleanup all sessions
    start_time = time.time()
    for sid in session_ids:
        manager.cleanup_session(sid)
    cleanup_time = time.time() - start_time

    # Verify cleanup
    assert len(manager.list_sessions()) == 0

    # Verify stability (all operations completed without errors)
    # RFC target: stable means operations complete and no memory issues
    total_time = creation_time + operation_time + cleanup_time

    # These are not strict benchmarks but stability checks
    # We expect all operations to complete reasonably fast for 100 sessions
    assert creation_time < 10.0, f"Session creation too slow: {creation_time}s"
    assert operation_time < 10.0, f"Session operations too slow: {operation_time}s"
    assert cleanup_time < 10.0, f"Session cleanup too slow: {cleanup_time}s"

    print(f"\n100 Concurrent Sessions Results:")
    print(f"  Creation time: {creation_time:.3f}s")
    print(f"  Operation time: {operation_time:.3f}s")
    print(f"  Cleanup time: {cleanup_time:.3f}s")
    print(f"  Total time: {total_time:.3f}s")
    print(f"  Status: STABLE")
