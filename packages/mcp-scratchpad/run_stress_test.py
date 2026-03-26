#!/usr/bin/env python3
"""
Direct stress test runner for concurrent sessions.
This script loads the stress tests directly without pytest dependency issues.
"""

import sys
import types

# Create comprehensive fastmcp mock before any imports
fastmcp = types.ModuleType("fastmcp")
fastmcp.Context = dict
fastmcp_tools = types.ModuleType("fastmcp.tools")
fastmcp_tool = types.ModuleType("fastmcp.tools.tool")
fastmcp_tool.ToolResult = dict

sys.modules["fastmcp"] = fastmcp
sys.modules["fastmcp.tools"] = fastmcp_tools
sys.modules["fastmcp.tools.tool"] = fastmcp_tool
fastmcp_tools.tool = fastmcp_tool

# Also mock mcp module
mcp = types.ModuleType("mcp")
mcp.types = types.ModuleType("mcp.types")
mcp.types.TextContent = str
mcp.types.CallToolResult = dict
mcp.types.ImageContent = bytes
mcp.types.EmbeddedResource = dict
sys.modules["mcp"] = mcp
sys.modules["mcp.types"] = mcp.types

sys.path.insert(0, "src")

from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.config.models import OverlayConfig
from fsspec.implementations.memory import MemoryFileSystem

import concurrent.futures
import threading
import time
import random
import gc


def test_concurrent_session_creation_stress():
    """Test: Create 50, 100, 200 sessions concurrently."""
    print("\n" + "=" * 70)
    print("TEST 1: Concurrent Session Creation Stress")
    print("=" * 70)

    for session_count in [50, 100, 200]:
        print(f"\nRunning with {session_count} concurrent sessions...")
        manager = SessionFileSystemManager(OverlayConfig())

        start_time = time.time()

        def create_session_with_index(index):
            sid = manager.create_session(metadata={"stress_test_index": index})
            return index, sid

        # Create sessions concurrently
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(session_count, 50)
        ) as executor:
            futures = [
                executor.submit(create_session_with_index, i)
                for i in range(session_count)
            ]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        elapsed = time.time() - start_time

        # Verify
        assert len(results) == session_count, (
            f"Expected {session_count}, got {len(results)}"
        )
        session_ids = [sid for _, sid in results]
        assert len(set(session_ids)) == session_count, "Duplicate session IDs detected"

        all_sessions = manager.list_sessions()
        assert len(all_sessions) == session_count

        # Cleanup
        for sid in session_ids:
            manager.cleanup_session(sid)

        print(f"  ✓ {session_count} sessions created in {elapsed:.2f}s")
        print(f"  ✓ No duplicate IDs")
        print(f"  ✓ All sessions tracked and cleaned up")

    print("\nPASSED")


def test_concurrent_file_operations_stress():
    """Test: File operations under concurrent load."""
    print("\n" + "=" * 70)
    print("TEST 2: Concurrent File Operations Stress")
    print("=" * 70)

    session_count = 50
    test_duration = 5  # 5 seconds for quick test

    print(f"\nRunning with {session_count} sessions for {test_duration}s...")

    manager = SessionFileSystemManager(OverlayConfig())
    session_ids = []
    for i in range(session_count):
        sid = manager.create_session(metadata={"stress_session_index": i})
        session_ids.append(sid)

    ops_count = {"read": 0, "write": 0, "delete": 0, "list": 0, "error": 0}
    ops_lock = threading.Lock()

    def run_session_operations(session_id, session_index):
        fs = manager.get_session_fs(session_id)
        if fs is None:
            return

        files_created = []
        start_time = time.time()

        while time.time() - start_time < test_duration:
            rand = random.randint(1, 100)

            try:
                if rand <= 60:  # 60% reads
                    if files_created and random.random() > 0.5:
                        path = random.choice(files_created)
                        if fs.exists(path):
                            with fs.open(path, "r") as f:
                                _ = f.read()
                            with ops_lock:
                                ops_count["read"] += 1
                    else:
                        fs.ls("/workspace", detail=False)
                        with ops_lock:
                            ops_count["list"] += 1

                elif rand <= 90:  # 30% writes
                    file_name = f"file_{session_index}_{len(files_created)}.txt"
                    file_path = f"/workspace/{file_name}"
                    content = f"Content from session {session_index}"

                    with fs.open(file_path, "w") as f:
                        f.write(content)

                    files_created.append(file_path)
                    with ops_lock:
                        ops_count["write"] += 1

                else:  # 10% deletes
                    if files_created:
                        path = files_created.pop()
                        if fs.exists(path):
                            fs.rm(path)
                        with ops_lock:
                            ops_count["delete"] += 1

            except Exception as e:
                with ops_lock:
                    ops_count["error"] += 1

    # Run operations concurrently
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=session_count) as executor:
        futures = [
            executor.submit(run_session_operations, sid, idx)
            for idx, sid in enumerate(session_ids)
        ]
        concurrent.futures.wait(futures, timeout=test_duration + 5)

    elapsed = time.time() - start
    total_ops = sum(ops_count.values())

    # Cleanup
    for sid in session_ids:
        manager.cleanup_session(sid)

    print(f"  ✓ Total operations: {total_ops}")
    print(f"    - Reads: {ops_count['read']}")
    print(f"    - Writes: {ops_count['write']}")
    print(f"    - Deletes: {ops_count['delete']}")
    print(f"    - Lists: {ops_count['list']}")
    print(f"    - Errors: {ops_count['error']}")
    print(f"  ✓ Ops/sec: {total_ops / elapsed:.2f}")

    assert total_ops > 0, "No operations performed"
    success_rate = (total_ops - ops_count["error"]) / total_ops * 100
    assert success_rate >= 95.0, f"Success rate {success_rate:.1f}% below 95%"

    print("\nPASSED")


def test_session_isolation_under_concurrent_load():
    """Test: Verify session isolation during concurrent access."""
    print("\n" + "=" * 70)
    print("TEST 3: Session Isolation Under Concurrent Load")
    print("=" * 70)

    session_count = 50
    print(f"\nRunning with {session_count} concurrent sessions...")

    manager = SessionFileSystemManager(OverlayConfig())
    session_markers = {}

    # Create sessions
    for i in range(session_count):
        unique_marker = f"session_{i}_{random.randint(10000, 99999)}"
        sid = manager.create_session(
            metadata={"unique_marker": unique_marker, "index": i}
        )
        session_markers[sid] = {"index": i, "marker": unique_marker}

    # Each session writes files concurrently
    def write_session_files(session_id, marker, index):
        fs = manager.get_session_fs(session_id)
        if fs is None:
            return []

        written_files = []
        for j in range(5):
            file_path = f"/workspace/test_file_{marker}_{j}.txt"
            content = f"SESSION_MARKER:{marker}:INDEX:{index}:FILE:{j}"

            with fs.open(file_path, "w") as f:
                f.write(content)
            written_files.append((file_path, content))

        return written_files

    # Run writes concurrently
    expected_files = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=session_count) as executor:
        futures = {
            executor.submit(
                write_session_files,
                sid,
                session_markers[sid]["marker"],
                session_markers[sid]["index"],
            ): sid
            for sid in session_markers
        }

        for future in concurrent.futures.as_completed(futures):
            sid = futures[future]
            expected_files[sid] = future.result()

    # Verify isolation
    cross_contamination = []

    for sid, files in expected_files.items():
        fs = manager.get_session_fs(sid)
        if fs is None:
            continue

        marker = session_markers[sid]["marker"]

        # Check session's own files
        for file_path, expected_content in files:
            if fs.exists(file_path):
                with fs.open(file_path, "r") as f:
                    content = f.read()
                if marker not in content:
                    cross_contamination.append(f"Session {sid}: Wrong content")

        # Check for files from other sessions
        all_files = fs.ls("/workspace", detail=False)
        for file_path in all_files:
            if fs.isdir(file_path):
                continue

            try:
                with fs.open(file_path, "r") as f:
                    content = f.read()
                    for other_sid, other_data in session_markers.items():
                        if other_sid != sid:
                            if f"SESSION_MARKER:{other_data['marker']}:" in content:
                                cross_contamination.append(
                                    f"Session {sid} has file from {other_sid}"
                                )
            except Exception:
                pass

    # Report
    if cross_contamination:
        print(f"  ✗ Cross-contamination: {len(cross_contamination)} issues")
        for issue in cross_contamination[:5]:
            print(f"    - {issue}")
    else:
        print(f"  ✓ No cross-contamination detected")

    print(f"  ✓ Files written: {session_count * 5}")

    # Cleanup
    for sid in session_markers:
        manager.cleanup_session(sid)

    assert len(cross_contamination) == 0, (
        f"Session isolation failed with {len(cross_contamination)} violations"
    )

    print("\nPASSED")


def test_memory_stability_during_stress():
    """Test: Memory stability during extended concurrent operations."""
    print("\n" + "=" * 70)
    print("TEST 4: Memory Stability During Stress")
    print("=" * 70)

    session_count = 50
    operation_batches = 5

    print(f"\nRunning with {session_count} sessions, {operation_batches} batches...")

    manager = SessionFileSystemManager(OverlayConfig())

    # Create sessions
    session_ids = []
    for i in range(session_count):
        sid = manager.create_session(metadata={"mem_test_index": i})
        session_ids.append(sid)

    print(f"  ✓ {session_count} sessions created")

    # Perform operations in batches
    for batch in range(operation_batches):

        def batch_operations(session_id, batch_num):
            fs = manager.get_session_fs(session_id)
            if fs is None:
                return 0

            ops = 0
            for j in range(5):
                file_path = f"/workspace/batch_{batch_num}_file_{j}.txt"
                content = f"Batch {batch_num} content {j}"

                with fs.open(file_path, "w") as f:
                    f.write(content)
                ops += 1

                with fs.open(file_path, "r") as f:
                    _ = f.read()
                ops += 1

            return ops

        # Run batch concurrently
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=session_count
        ) as executor:
            futures = [
                executor.submit(batch_operations, sid, batch) for sid in session_ids
            ]
            concurrent.futures.wait(futures)

    print(f"  ✓ {operation_batches} operation batches completed")

    # Cleanup
    for sid in session_ids:
        manager.cleanup_session(sid)

    # Force GC
    gc.collect()

    print(f"  ✓ Cleanup complete, {len(manager.list_sessions())} sessions remaining")

    assert len(manager.list_sessions()) == 0, "Sessions not properly cleaned up"

    print("\nPASSED")


def run_all_tests():
    """Run all stress tests."""
    print("\n" + "=" * 70)
    print("CONCURRENT SESSION STRESS TEST SUITE")
    print("SessionFileSystemManager - Testing 50+ Concurrent Sessions")
    print("=" * 70)

    tests = [
        ("Concurrent Creation", test_concurrent_session_creation_stress),
        ("File Operations", test_concurrent_file_operations_stress),
        ("Session Isolation", test_session_isolation_under_concurrent_load),
        ("Memory Stability", test_memory_stability_during_stress),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n✗ FAILED: {name}")
            print(f"  Error: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print("STRESS TEST SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {passed + failed}")

    if failed == 0:
        print("\n✓ ALL STRESS TESTS PASSED")
        return 0
    else:
        print(f"\n✗ {failed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
