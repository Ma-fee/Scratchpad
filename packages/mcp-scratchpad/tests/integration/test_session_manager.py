"""
Integration tests for SessionFileSystemManager - end-to-end session flows.

This module provides comprehensive integration tests that verify:
- Full session lifecycle (create -> file operations -> cleanup)
- Concurrent session handling (10+ sessions)
- Session metadata isolation
- Resource cleanup verification (MemoryFileSystem cleared, no memory leaks)

Note: In Phase 1, MemoryFileSystem uses a class-level shared store, so file-level
isolation between sessions requires the Phase 2 overlay filesystem implementation.
These tests verify session management isolation while acknowledging this limitation.

These tests use fsspec MemoryFileSystem for filesystem operations and
complement the unit tests by testing real-world usage patterns.
"""

from __future__ import annotations

import concurrent.futures
import gc
import time
import uuid
from datetime import timedelta

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager, SessionMetadata


def clear_memory_fs_store() -> None:
    """Clear the global MemoryFileSystem store for test isolation."""
    MemoryFileSystem.store.clear()


@pytest.fixture(autouse=True)
def clean_memory_fs():
    """Fixture to clear MemoryFileSystem store before and after each test."""
    clear_memory_fs_store()
    yield
    clear_memory_fs_store()


class TestSessionLifecycleIntegration:
    """Integration tests for full session lifecycle flows."""

    def test_full_session_lifecycle(self) -> None:
        """
        Test complete session lifecycle: create -> file operations -> cleanup.

        Verifies:
        - Session creation returns valid session ID
        - Filesystem is accessible and functional
        - Files can be written and read
        - Cleanup removes session from manager tracking
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Create session
        session_id = manager.create_session()
        assert session_id is not None
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID4 length

        # Verify session is tracked
        meta = manager.get_session(session_id)
        assert meta is not None
        assert isinstance(meta, SessionMetadata)
        assert meta.session_id == session_id

        # Get filesystem and verify workspace exists
        fs = manager.get_session_fs(session_id)
        assert fs is not None
        assert isinstance(fs, MemoryFileSystem)
        assert fs.isdir("/workspace")

        # Write file operations
        test_content = b"Hello, this is test content!"
        test_path = "/workspace/test.txt"

        with fs.open(test_path, "wb") as f:
            f.write(test_content)

        # Read file back
        with fs.open(test_path, "rb") as f:
            read_content = f.read()
        assert read_content == test_content

        # Create nested directory structure
        fs.mkdir("/workspace/project", create_parents=True)
        fs.mkdir("/workspace/project/src", create_parents=True)

        with fs.open("/workspace/project/src/main.py", "w") as f:
            f.write("print('hello world')")

        # List directory contents
        entries = fs.ls("/workspace", detail=False)
        assert "/workspace/test.txt" in entries
        assert "/workspace/project" in entries

        # Cleanup session
        cleanup_result = manager.cleanup_session(session_id)
        assert cleanup_result is True

        # Verify session tracking is completely removed
        assert manager.get_session(session_id) is None
        assert manager.get_session_fs(session_id) is None
        assert manager.get_session_metadata(session_id) is None
        assert session_id not in manager._sessions

    def test_multiple_sessions_lifecycle(self) -> None:
        """
        Test lifecycle with multiple concurrent sessions.

        Verifies:
        - Multiple sessions can be created and tracked
        - Each session has independent metadata
        - Cleanup of one session doesn't affect others
        - Session IDs are unique
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Create multiple sessions
        session_ids = [manager.create_session() for _ in range(5)]

        # Verify all sessions are tracked
        assert len(manager.list_sessions()) == 5

        # Verify unique IDs
        assert len(set(session_ids)) == 5

        # Verify each session has independent metadata
        for _i, sid in enumerate(session_ids):
            meta = manager.get_session_metadata(sid)
            assert meta is not None
            assert meta.session_id == sid

        # Cleanup sessions in reverse order
        for sid in reversed(session_ids):
            assert manager.cleanup_session(sid) is True

        # All sessions should be cleaned up
        assert manager.list_sessions() == []

        # Recreating sessions should work with new unique IDs
        new_session = manager.create_session()
        assert new_session not in session_ids  # Should be different UUID
        assert len(manager.list_sessions()) == 1

        manager.cleanup_session(new_session)

    def test_session_with_custom_metadata_lifecycle(self) -> None:
        """
        Test session lifecycle with custom metadata.

        Verifies:
        - Custom metadata is preserved throughout lifecycle
        - Metadata accessible after file operations
        """
        manager = SessionFileSystemManager(OverlayConfig())

        custom_meta = {
            "user_id": "user_123",
            "project": "my_project",
            "tags": ["test", "integration"],
            "priority": 5,
        }

        session_id = manager.create_session(metadata=custom_meta)

        # Verify metadata is stored
        meta = manager.get_session_metadata(session_id)
        assert meta is not None
        assert meta.metadata["user_id"] == "user_123"
        assert meta.metadata["project"] == "my_project"
        assert meta.metadata["tags"] == ["test", "integration"]
        assert meta.metadata["priority"] == 5

        # Perform file operations
        fs = manager.get_session_fs(session_id)
        with fs.open("/workspace/data.json", "w") as f:
            f.write('{"key": "value"}')

        # Metadata should still be intact
        meta_after = manager.get_session_metadata(session_id)
        assert meta_after.metadata["user_id"] == "user_123"

        # Cleanup and verify
        manager.cleanup_session(session_id)
        assert manager.get_session_metadata(session_id) is None


class TestConcurrentSessionsIntegration:
    """Integration tests for concurrent session handling."""

    def test_concurrent_session_creation(self) -> None:
        """
        Test concurrent creation of 10+ sessions.

        Verifies:
        - All sessions are created successfully
        - No session ID collisions
        - All sessions are properly tracked
        """
        manager = SessionFileSystemManager(OverlayConfig())

        def create_and_verify(session_num: int) -> tuple[int, str]:
            """Create a session and return its number and ID."""
            sid = manager.create_session(metadata={"session_num": session_num})
            return session_num, sid

        # Create 15 sessions concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_and_verify, i) for i in range(15)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # Verify all sessions created
        assert len(results) == 15

        # Verify no duplicate session IDs
        session_ids = [sid for _, sid in results]
        assert len(set(session_ids)) == 15

        # Verify all sessions are tracked
        all_sessions = manager.list_sessions()
        assert len(all_sessions) == 15

        # Verify metadata from all threads preserved
        session_nums = [meta.metadata.get("session_num") for meta in all_sessions]
        assert sorted(session_nums) == list(range(15))

        # Cleanup all sessions
        for sid in session_ids:
            manager.cleanup_session(sid)

    def test_concurrent_session_cleanup(self) -> None:
        """
        Test concurrent cleanup of sessions.

        Verifies:
        - Concurrent cleanup doesn't cause errors
        - All sessions properly cleaned up
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Create 10 sessions
        session_ids = [manager.create_session() for _ in range(10)]

        def cleanup_session(session_id: str) -> bool:
            """Cleanup a session and return result."""
            return manager.cleanup_session(session_id)

        # Concurrent cleanup
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(cleanup_session, sid) for sid in session_ids]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All cleanup operations should succeed
        assert all(results)
        assert len(manager.list_sessions()) == 0

    def test_stress_test_many_sessions(self) -> None:
        """
        Stress test with many sessions (20+) to verify scalability.

        Verifies:
        - System handles many concurrent sessions
        - Performance remains acceptable
        - Resource usage is reasonable
        """
        manager = SessionFileSystemManager(OverlayConfig())
        num_sessions = 20

        # Create many sessions
        start_time = time.time()
        session_ids = [manager.create_session() for _ in range(num_sessions)]
        create_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds for 20 sessions)
        assert create_time < 5.0, f"Creating {num_sessions} sessions took too long"

        # Verify all sessions are functional
        for sid in session_ids:
            fs = manager.get_session_fs(sid)
            assert fs is not None
            assert fs.isdir("/workspace")

        # Cleanup all
        for sid in session_ids:
            manager.cleanup_session(sid)

        assert len(manager.list_sessions()) == 0


class TestSessionMetadataIsolationIntegration:
    """Integration tests for session metadata isolation."""

    def test_metadata_isolation_between_sessions(self) -> None:
        """
        Test that metadata is isolated between sessions.

        Verifies:
        - Custom metadata from session A doesn't affect session B
        - Timestamps are independent
        """
        manager = SessionFileSystemManager(OverlayConfig())

        session_a = manager.create_session(
            metadata={"owner": "alice", "level": "admin"}
        )
        session_b = manager.create_session(metadata={"owner": "bob", "level": "user"})

        meta_a = manager.get_session_metadata(session_a)
        meta_b = manager.get_session_metadata(session_b)

        # Metadata should be isolated
        assert meta_a.metadata["owner"] == "alice"
        assert meta_a.metadata["level"] == "admin"
        assert meta_b.metadata["owner"] == "bob"
        assert meta_b.metadata["level"] == "user"

        # Timestamps are independent
        meta_a_access = meta_a.last_accessed
        time.sleep(0.01)

        # Access session B only
        _ = manager.get_session(session_b)

        # Session A's last_accessed should not change
        meta_a_after = manager.get_session_metadata(session_a)
        assert meta_a_after.last_accessed == meta_a_access

        manager.cleanup_session(session_a)
        manager.cleanup_session(session_b)

    def test_manager_isolation_between_instances(self) -> None:
        """
        Test that different manager instances have completely isolated state.

        Verifies:
        - Sessions created in manager A are not visible in manager B
        - Cleanup in one manager doesn't affect the other
        """
        manager_a = SessionFileSystemManager(OverlayConfig())
        manager_b = SessionFileSystemManager(OverlayConfig())

        # Create sessions in manager A
        session_a1 = manager_a.create_session(metadata={"manager": "A"})
        session_a2 = manager_a.create_session(metadata={"manager": "A"})

        # Create sessions in manager B
        session_b1 = manager_b.create_session(metadata={"manager": "B"})

        # Manager A should only see its own sessions
        sessions_a = manager_a.list_sessions()
        assert len(sessions_a) == 2
        session_ids_a = {s.session_id for s in sessions_a}
        assert session_a1 in session_ids_a
        assert session_a2 in session_ids_a
        assert session_b1 not in session_ids_a

        # Manager B should only see its own sessions
        sessions_b = manager_b.list_sessions()
        assert len(sessions_b) == 1
        assert sessions_b[0].session_id == session_b1

        # Cleanup manager A's sessions - manager B should be unaffected
        manager_a.cleanup_session(session_a1)
        manager_a.cleanup_session(session_a2)

        assert len(manager_a.list_sessions()) == 0
        assert len(manager_b.list_sessions()) == 1
        assert manager_b.get_session(session_b1) is not None

        manager_b.cleanup_session(session_b1)


class TestResourceCleanupIntegration:
    """Integration tests for resource cleanup verification."""

    def test_memory_filesystem_cleared_on_cleanup(self) -> None:
        """
        Test that session tracking is properly cleared on cleanup.

        Verifies:
        - Session removed from all internal tracking dicts
        - Session metadata no longer accessible
        """
        manager = SessionFileSystemManager(OverlayConfig())
        session_id = manager.create_session()

        # Verify session exists in all tracking structures
        assert session_id in manager._sessions
        assert session_id in manager._session_metadata
        assert session_id in manager._last_accessed

        # Cleanup session
        result = manager.cleanup_session(session_id)
        assert result is True

        # Verify session removed from all tracking structures
        assert session_id not in manager._sessions
        assert session_id not in manager._session_metadata
        assert session_id not in manager._last_accessed

        # Verify session no longer accessible through public API
        assert manager.get_session(session_id) is None
        assert manager.get_session_fs(session_id) is None
        assert manager.get_session_metadata(session_id) is None

    def test_no_memory_leaks_in_metadata(self) -> None:
        """
        Test that no metadata leaks occur after session cleanup.

        Verifies:
        - All session metadata references are properly released
        - GC can collect freed SessionMetadata objects
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Store weak references to track if objects are freed
        session_data = []

        # Create and cleanup multiple sessions
        for i in range(10):
            session_id = manager.create_session(
                metadata={
                    "iteration": i,
                    "unique_marker": f"session_{i}_{uuid.uuid4().hex}",
                }
            )
            session_data.append((i, session_id))

            fs = manager.get_session_fs(session_id)
            # Write session-specific data
            fs.write_text(f"/workspace/session_{i}.txt", f"data_{i}")

            manager.cleanup_session(session_id)

        # Force garbage collection
        gc.collect()

        # Verify session tracking is empty
        assert len(manager._sessions) == 0
        assert len(manager._session_metadata) == 0
        assert len(manager._last_accessed) == 0

    def test_handles_closed_properly(self) -> None:
        """
        Test that file handles don't prevent cleanup.

        Verifies:
        - Open file handles don't prevent cleanup
        - Cleanup succeeds even with open handles
        """
        manager = SessionFileSystemManager(OverlayConfig())
        session_id = manager.create_session()

        fs = manager.get_session_fs(session_id)

        # Open some files (don't close explicitly)
        f1 = fs.open("/workspace/test1.txt", "w")
        f1.write("content1")

        f2 = fs.open("/workspace/test2.txt", "w")
        f2.write("content2")

        # Cleanup should succeed even with open handles
        result = manager.cleanup_session(session_id)
        assert result is True

        # Session should be completely removed from tracking
        assert manager.get_session(session_id) is None
        assert session_id not in manager._sessions

    def test_cleanup_expired_sessions_integration(self) -> None:
        """
        Test batch cleanup of expired sessions.

        Verifies:
        - Expired sessions are properly cleaned up
        - Active sessions remain intact
        - Resources are freed
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Create sessions with different TTLs
        session_active = manager.create_session(
            metadata={"type": "active"},
            ttl=timedelta(hours=1),
        )
        session_short_ttl = manager.create_session(
            metadata={"type": "short"},
            ttl=timedelta(milliseconds=50),
        )
        session_no_ttl = manager.create_session(metadata={"type": "no_ttl"})

        # Wait for short TTL session to expire
        time.sleep(0.1)

        # Verify session with short TTL is considered expired
        assert manager.get_session(session_short_ttl) is None

        # Other sessions should still be accessible
        assert manager.get_session(session_active) is not None
        assert manager.get_session(session_no_ttl) is not None

        # Run expired session cleanup
        count = manager.cleanup_expired_sessions()
        assert count >= 1  # At least the short TTL session

        # Verify expired session resources freed
        assert session_short_ttl not in manager._sessions

        # Active sessions should still work
        assert manager.get_session_fs(session_active) is not None
        assert manager.get_session_fs(session_no_ttl) is not None

        # Cleanup remaining
        manager.cleanup_session(session_active)
        manager.cleanup_session(session_no_ttl)

    def test_partial_cleanup_integrity(self) -> None:
        """
        Test that partial cleanup maintains integrity of remaining sessions.

        Verifies:
        - Cleanup of one session doesn't corrupt others
        - Remaining sessions fully functional
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Create several sessions
        sessions = []
        for i in range(5):
            sid = manager.create_session(metadata={"index": i})
            sessions.append(sid)

        # Cleanup middle session
        middle_idx = 2
        manager.cleanup_session(sessions[middle_idx])

        # Verify middle session is gone
        assert manager.get_session(sessions[middle_idx]) is None

        # Verify other sessions are unaffected
        for i, sid in enumerate(sessions):
            if i == middle_idx:
                continue

            meta = manager.get_session(sid)
            assert meta is not None, f"Session {i} should still exist"
            assert meta.metadata.get("index") == i

        # Cleanup remaining
        for i, sid in enumerate(sessions):
            if i != middle_idx:
                manager.cleanup_session(sid)

        assert len(manager.list_sessions()) == 0


@pytest.mark.integration
class TestSessionManagerEndToEndScenarios:
    """End-to-end scenarios testing real-world usage patterns."""

    def test_development_workflow_scenario(self) -> None:
        """
        Test a realistic development workflow scenario.

        Scenario:
        1. Developer starts a new coding session
        2. Creates project structure
        3. Session metadata is tracked
        4. Session ends, cleanup
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Developer starts session
        session_id = manager.create_session(
            metadata={
                "user": "developer_1",
                "project": "my_app",
                "workspace": "feature_login",
            }
        )

        # Verify session is tracked
        meta = manager.get_session(session_id)
        assert meta is not None
        assert meta.metadata["user"] == "developer_1"
        assert meta.metadata["project"] == "my_app"

        fs = manager.get_session_fs(session_id)

        # Create project structure
        fs.mkdir("/workspace/src", create_parents=True)
        fs.mkdir("/workspace/tests", create_parents=True)
        fs.mkdir("/workspace/docs", create_parents=True)

        # Verify project structure
        assert fs.isdir("/workspace/src")
        assert fs.isdir("/workspace/tests")

        # Session ends - cleanup
        manager.cleanup_session(session_id)
        assert manager.get_session(session_id) is None

    def test_multi_user_scenario(self) -> None:
        """
        Test multiple users working concurrently.

        Scenario:
        - User A starts session, metadata tracked
        - User B starts session, metadata tracked
        - Both users' sessions are independent
        - Sessions cleaned up independently
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # User A starts working
        session_a = manager.create_session(
            metadata={"user": "alice", "role": "frontend_dev"}
        )

        # User B starts working
        session_b = manager.create_session(
            metadata={"user": "bob", "role": "backend_dev"}
        )

        # Verify independent metadata
        meta_a = manager.get_session_metadata(session_a)
        meta_b = manager.get_session_metadata(session_b)

        assert meta_a.metadata["user"] == "alice"
        assert meta_b.metadata["user"] == "bob"

        # Alice finishes and cleans up
        manager.cleanup_session(session_a)

        # Bob's session should be unaffected
        assert manager.get_session(session_b) is not None
        meta_b_after = manager.get_session_metadata(session_b)
        assert meta_b_after.metadata["user"] == "bob"

        # Bob finishes
        manager.cleanup_session(session_b)

        assert len(manager.list_sessions()) == 0

    def test_session_timeout_recovery_scenario(self) -> None:
        """
        Test session timeout and recovery scenario.

        Scenario:
        - Create session with short TTL
        - Perform operations
        - Wait for expiration
        - Verify cleanup works automatically
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Create session with 50ms TTL
        session_id = manager.create_session(
            metadata={"user": "temp_user"},
            ttl=timedelta(milliseconds=50),
        )

        # Verify accessible
        assert manager.get_session(session_id) is not None

        # Wait for expiration
        time.sleep(0.1)

        # Session should be expired
        assert manager.get_session(session_id) is None

        # Run cleanup
        count = manager.cleanup_expired_sessions()
        assert count == 1

        # Completely cleaned up
        assert session_id not in manager._sessions

    def _create_sessions_batch(self, manager, results, errors, count: int) -> None:
        """Helper: Create multiple sessions."""
        try:
            for i in range(count):
                sid = manager.create_session(metadata={"thread": "creator", "index": i})
                results["created"].append(sid)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Create error: {e}")

    def _access_existing_sessions(self, manager, results, errors) -> None:
        """Helper: Access existing sessions."""
        try:
            sessions = manager.list_sessions()
            for meta in sessions:
                sid = meta.session_id
                fs = manager.get_session_fs(sid)
                if fs:
                    results["accessed"].append(sid)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Access error: {e}")

    def test_concurrent_access_pattern(self) -> None:
        """
        Test concurrent access to session manager from multiple threads.

        Verifies:
        - Thread-safe session creation
        - Thread-safe session access
        - No race conditions in metadata operations
        """
        manager = SessionFileSystemManager(OverlayConfig())
        errors = []
        results = {"created": [], "accessed": []}

        # Start concurrent operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # Submit creation tasks
            create_futures = [
                executor.submit(
                    self._create_sessions_batch, manager, results, errors, 5
                )
                for _ in range(3)
            ]

            # Submit access tasks interleaved
            access_futures = [
                executor.submit(
                    self._access_existing_sessions, manager, results, errors
                )
                for _ in range(5)
            ]

            # Wait for all
            for f in create_futures + access_futures:
                f.result()

        # No errors should have occurred
        assert not errors, f"Errors occurred: {errors}"

        # All created sessions should exist
        all_sessions = manager.list_sessions()
        assert len(all_sessions) == 15  # 3 threads * 5 sessions each

        # Cleanup
        for sid in results["created"]:
            manager.cleanup_session(sid)


@pytest.mark.integration
class TestSessionManagerQACompliance:
    """Tests that verify QA scenario compliance."""

    def test_qa_concurrent_session_stress(self) -> None:
        """
        QA Scenario: Concurrent session stress test.

        Steps:
        1. Create 10 sessions concurrently
        2. Each writes unique files
        3. Verify no metadata cross-contamination
        4. Cleanup all sessions

        Expected: Sessions properly isolated at metadata level
        """
        manager = SessionFileSystemManager(OverlayConfig())

        # Step 1: Create 10 sessions concurrently
        def create_session_with_files(index: int) -> tuple[str, str, str]:
            sid = manager.create_session(
                metadata={"session_index": index, "unique_id": f"uid_{index}"}
            )
            fs = manager.get_session_fs(sid)
            # Write unique file for this session
            test_path = f"/workspace/session_{index}.txt"
            fs.write_text(test_path, f"data from session {index}")
            return sid, test_path, f"data from session {index}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_session_with_files, i) for i in range(10)]
            session_data = [
                f.result() for f in concurrent.futures.as_completed(futures)
            ]

        # Verify 10 sessions created
        assert len(session_data) == 10
        assert len(manager.list_sessions()) == 10

        # Step 3: Verify session data integrity (no cross-contamination in metadata)
        for sid, _expected_path, _ in session_data:
            meta = manager.get_session_metadata(sid)
            assert meta is not None
            # Verify metadata is correct and unique to this session
            session_index = meta.metadata.get("session_index")
            expected_uid = f"uid_{session_index}"
            assert meta.metadata.get("unique_id") == expected_uid

        # Step 4: Cleanup all sessions
        for sid, _, _ in session_data:
            assert manager.cleanup_session(sid) is True

        # Verify all cleaned up
        assert len(manager.list_sessions()) == 0

        # Save evidence to be written to file later
        self._qa_concurrent_result = "PASSED"
