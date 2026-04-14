"""
Tests for SessionFileSystemManager lifecycle implementation.

This module tests the SessionFileSystemManager with full session lifecycle
and metadata tracking, verifying that:
- The manager instantiates correctly with OverlayConfig
- Session lifecycle methods work (create, get, cleanup, list)
- Session metadata is properly tracked
- Session expiration works correctly
- All methods return expected types
"""

from datetime import timedelta
from pathlib import Path

import pytest
from fsspec import AbstractFileSystem

from mcp_scratchpad.config.models import MountConfig, OverlayConfig
from mcp_scratchpad.fs.overlay import OverlayFileSystem
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager, SessionMetadata


class TestSessionFileSystemManagerInstantiation:
    """Tests for manager instantiation with various configurations."""

    def test_manager_instantiates_with_empty_config(self) -> None:
        """Test that manager instantiates with empty OverlayConfig."""
        config = OverlayConfig(mounts=[])
        manager = SessionFileSystemManager(config)

        assert isinstance(manager, SessionFileSystemManager)
        assert manager.config == config
        assert manager.list_sessions() == []

    def test_manager_instantiates_with_mounts(self) -> None:
        """Test that manager instantiates with mount configurations."""
        mounts = [
            MountConfig(
                name="templates",
                source="memory://",
                mount_point="/templates",
                mode="ro",
            ),
        ]
        config = OverlayConfig(mounts=mounts)
        manager = SessionFileSystemManager(config)

        assert isinstance(manager, SessionFileSystemManager)
        assert len(manager.config.mounts) == 1
        assert manager.config.mounts[0].name == "templates"

    def test_manager_initializes_empty_session_dict(self) -> None:
        """Test that manager initializes with empty session tracking."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        assert manager._sessions == {}
        assert manager.list_sessions() == []

    def test_manager_accepts_default_ttl(self) -> None:
        """Test that manager accepts default_session_ttl parameter."""
        config = OverlayConfig()
        ttl = timedelta(minutes=30)
        manager = SessionFileSystemManager(config, default_session_ttl=ttl)

        assert manager._default_session_ttl == ttl


class TestSessionMetadata:
    """Tests for SessionMetadata dataclass."""

    def test_session_metadata_creation(self) -> None:
        """Test creating SessionMetadata with all fields."""
        from datetime import datetime

        now = datetime.now()
        meta = SessionMetadata(
            session_id="test-session-123",
            created_at=now,
            last_accessed=now,
            metadata={"user": "test_user"},
        )

        assert meta.session_id == "test-session-123"
        assert meta.created_at == now
        assert meta.last_accessed == now
        assert meta.metadata == {"user": "test_user"}

    def test_session_metadata_defaults(self) -> None:
        """Test SessionMetadata with default metadata field."""
        from datetime import datetime

        now = datetime.now()
        meta = SessionMetadata(
            session_id="test-session-123",
            created_at=now,
            last_accessed=now,
        )

        assert meta.metadata == {}


class TestSessionCreation:
    """Tests for session creation functionality."""

    def test_create_session_returns_string(self) -> None:
        """Test that create_session returns a string session ID."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id = manager.create_session()

        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID4 length

    def test_create_session_returns_unique_ids(self) -> None:
        """Test that multiple sessions get unique IDs."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id_1 = manager.create_session()
        session_id_2 = manager.create_session()

        assert session_id_1 != session_id_2
        assert len(manager.list_sessions()) == 2

    def test_create_session_stores_session(self) -> None:
        """Test that created session is stored internally."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id = manager.create_session()

        assert session_id in manager._sessions
        sessions = manager.list_sessions()
        assert any(meta.session_id == session_id for meta in sessions)

    def test_create_session_stores_metadata(self) -> None:
        """Test that create_session stores session metadata."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id = manager.create_session(metadata={"user": "test"})

        meta = manager.get_session_metadata(session_id)
        assert meta is not None
        assert meta.session_id == session_id
        assert meta.metadata["user"] == "test"
        assert "created_at" in dir(meta)
        assert "last_accessed" in dir(meta)

    def test_create_session_records_timestamps(self) -> None:
        """Test that create_session records creation and last_accessed timestamps."""
        from datetime import datetime

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        before_create = datetime.now()
        session_id = manager.create_session()
        after_create = datetime.now()

        meta = manager.get_session_metadata(session_id)
        assert meta is not None
        assert before_create <= meta.created_at <= after_create
        assert before_create <= meta.last_accessed <= after_create

    def test_create_session_with_ttl(self) -> None:
        """Test that create_session can accept TTL parameter."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        ttl = timedelta(minutes=30)
        session_id = manager.create_session(ttl=ttl)

        meta = manager.get_session_metadata(session_id)
        assert meta is not None
        assert "expires_at" in meta.metadata
        assert "ttl_seconds" in meta.metadata
        assert meta.metadata["ttl_seconds"] == 1800.0  # 30 minutes in seconds

    def test_create_session_uses_default_ttl(self) -> None:
        """Test that create_session uses manager's default TTL if set."""
        ttl = timedelta(hours=1)
        config = OverlayConfig()
        manager = SessionFileSystemManager(config, default_session_ttl=ttl)

        session_id = manager.create_session()

        meta = manager.get_session_metadata(session_id)
        assert meta is not None
        assert "expires_at" in meta.metadata
        assert meta.metadata["ttl_seconds"] == 3600.0

    def test_create_session_ttl_override(self) -> None:
        """Test that session TTL can override manager default."""
        default_ttl = timedelta(hours=1)
        config = OverlayConfig()
        manager = SessionFileSystemManager(config, default_session_ttl=default_ttl)

        override_ttl = timedelta(minutes=15)
        session_id = manager.create_session(ttl=override_ttl)

        meta = manager.get_session_metadata(session_id)
        assert meta is not None
        assert meta.metadata["ttl_seconds"] == 900.0  # 15 minutes

    def test_create_session_root_listing_includes_workspace(self) -> None:
        """Session overlay root should expose the initialized workspace directory."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id = manager.create_session()
        session_fs = manager.get_session_fs(session_id)

        assert session_fs is not None
        assert "workspace" in session_fs.ls("/", detail=False)


class TestGetSession:
    """Tests for get_session method."""

    def test_get_session_returns_metadata(self) -> None:
        """Test that get_session returns SessionMetadata."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        result = manager.get_session(session_id)

        assert isinstance(result, SessionMetadata)
        assert result.session_id == session_id

    def test_get_session_returns_none_for_nonexistent(self) -> None:
        """Test that get_session returns None for unknown session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        result = manager.get_session("nonexistent-session-id")

        assert result is None

    def test_get_session_updates_last_accessed(self) -> None:
        """Test that get_session updates last_accessed timestamp."""
        import time

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        # Get initial timestamp
        initial_meta = manager.get_session_metadata(session_id)
        assert initial_meta is not None
        initial_access = initial_meta.last_accessed

        # Wait a tiny bit and access again
        time.sleep(0.01)
        updated_meta = manager.get_session(session_id)
        assert updated_meta is not None

        assert updated_meta.last_accessed > initial_access

    def test_get_session_returns_none_for_expired(self) -> None:
        """Test that get_session returns None for expired session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        # Create session with very short TTL
        ttl = timedelta(milliseconds=1)
        session_id = manager.create_session(ttl=ttl)

        import time
        time.sleep(0.01)  # Wait for expiration

        result = manager.get_session(session_id)
        assert result is None


class TestGetSessionFs:
    """Tests for get_session_fs method."""

    def test_get_session_fs_returns_none_for_nonexistent_session(self) -> None:
        """Test that get_session_fs returns None for unknown session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        result = manager.get_session_fs("nonexistent-session-id")

        assert result is None

    def test_get_session_fs_returns_overlay_filesystem_for_existing_session(
        self,
    ) -> None:
        """Test that get_session_fs returns OverlayFileSystem for existing session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        result = manager.get_session_fs(session_id)

        assert isinstance(result, OverlayFileSystem)

    def test_session_overlay_reads_from_lower_and_writes_to_upper(
        self,
        tmp_path: Path,
    ) -> None:
        """Test overlay session can read lower layer and write to upper layer."""
        lower_root = tmp_path / "lower"
        (lower_root / "templates").mkdir(parents=True)
        (lower_root / "templates" / "base.txt").write_text("base", encoding="utf-8")

        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="lower_templates",
                    source=f"file://{lower_root}",
                    mount_point="/",
                    mode="ro",
                )
            ]
        )
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        fs = manager.get_session_fs(session_id)
        assert fs is not None

        assert fs.exists("/templates/base.txt")
        with fs.open("/workspace/new.txt", "w", encoding="utf-8") as handle:
            handle.write("hi")
        assert fs.exists("/workspace/new.txt")

    def test_get_session_fs_returns_none_for_expired(self) -> None:
        """Test that get_session_fs returns None for expired session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        ttl = timedelta(milliseconds=1)
        session_id = manager.create_session(ttl=ttl)

        import time
        time.sleep(0.01)

        result = manager.get_session_fs(session_id)
        assert result is None


class TestCleanupSession:
    """Tests for cleanup_session method."""

    def test_cleanup_session_returns_true_on_success(self) -> None:
        """Test that cleanup_session returns True when session exists."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        result = manager.cleanup_session(session_id)

        assert result is True

    def test_cleanup_session_returns_false_for_nonexistent(self) -> None:
        """Test that cleanup_session returns False for nonexistent session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        result = manager.cleanup_session("nonexistent-session-id")

        assert result is False

    def test_cleanup_session_removes_session(self) -> None:
        """Test that cleanup_session removes the session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        assert session_id in manager._sessions

        manager.cleanup_session(session_id)

        assert session_id not in manager._sessions
        assert manager.get_session_metadata(session_id) is None

    def test_cleanup_session_noop_for_nonexistent_session(self) -> None:
        """Test that cleanup_session is safe for nonexistent session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        # Should not raise
        manager.cleanup_session("nonexistent-session-id")

        # Original session should still exist
        sessions = manager.list_sessions()
        assert any(meta.session_id == session_id for meta in sessions)

    def test_cleanup_session_cleans_only_targeted_session(self) -> None:
        """Test that cleanup_session only removes the targeted session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id_1 = manager.create_session()
        session_id_2 = manager.create_session()

        manager.cleanup_session(session_id_1)

        assert manager.get_session_metadata(session_id_1) is None
        assert manager.get_session_metadata(session_id_2) is not None


class TestListSessions:
    """Tests for list_sessions method."""

    def test_list_sessions_returns_empty_list_initially(self) -> None:
        """Test that list_sessions returns empty list on fresh manager."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        result = manager.list_sessions()

        assert result == []
        assert isinstance(result, list)

    def test_list_sessions_returns_session_metadata(self) -> None:
        """Test that list_sessions returns list of SessionMetadata."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id = manager.create_session()

        result = manager.list_sessions()

        assert len(result) == 1
        assert isinstance(result[0], SessionMetadata)
        assert result[0].session_id == session_id

    def test_list_sessions_returns_multiple_sessions(self) -> None:
        """Test that list_sessions returns metadata for all sessions."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id_1 = manager.create_session()
        session_id_2 = manager.create_session()

        result = manager.list_sessions()

        assert len(result) == 2
        session_ids = {meta.session_id for meta in result}
        assert session_id_1 in session_ids
        assert session_id_2 in session_ids

    def test_list_sessions_excludes_expired_by_default(self) -> None:
        """Test that list_sessions excludes expired sessions by default."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        # Create normal session
        session_id_normal = manager.create_session()

        # Create expired session
        ttl = timedelta(milliseconds=1)
        session_id_expired = manager.create_session(ttl=ttl)

        import time
        time.sleep(0.01)

        result = manager.list_sessions()

        session_ids = {meta.session_id for meta in result}
        assert session_id_normal in session_ids
        assert session_id_expired not in session_ids

    def test_list_sessions_include_expired(self) -> None:
        """Test that list_sessions can include expired sessions."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        ttl = timedelta(milliseconds=1)
        session_id = manager.create_session(ttl=ttl)

        import time
        time.sleep(0.01)

        result = manager.list_sessions(include_expired=True)

        session_ids = {meta.session_id for meta in result}
        assert session_id in session_ids


class TestSessionExpiration:
    """Tests for session expiration functionality."""

    def test_is_session_expired_returns_true_for_nonexistent(self) -> None:
        """Test that is_session_expired returns True for nonexistent session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        result = manager.is_session_expired("nonexistent", 60.0)
        assert result is True

    def test_is_session_expired_with_timeout(self) -> None:
        """Test is_session_expired with timeout threshold."""
        import time

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        # Should not be expired immediately
        assert manager.is_session_expired(session_id, 5.0) is False

        # Wait and check again
        time.sleep(0.1)
        assert manager.is_session_expired(session_id, 0.05) is True

    def test_get_expired_sessions(self) -> None:
        """Test get_expired_sessions method."""
        import time

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        session_id_1 = manager.create_session()
        session_id_2 = manager.create_session()

        time.sleep(0.1)

        expired = manager.get_expired_sessions(0.05)

        assert session_id_1 in expired
        assert session_id_2 in expired

    def test_cleanup_expired_sessions_with_timeout(self) -> None:
        """Test cleanup_expired_sessions with explicit timeout."""
        import time

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        manager.create_session()
        manager.create_session()

        time.sleep(0.1)

        count = manager.cleanup_expired_sessions(timeout_seconds=0.05)

        assert count == 2
        assert manager.list_sessions() == []

    def test_cleanup_expired_sessions_with_ttl(self) -> None:
        """Test cleanup_expired_sessions using TTL metadata."""
        import time

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        # Create session with short TTL
        ttl = timedelta(milliseconds=1)
        session_id = manager.create_session(ttl=ttl)

        time.sleep(0.01)

        count = manager.cleanup_expired_sessions()

        assert count == 1
        assert manager.get_session_metadata(session_id) is None

    def test_cleanup_expired_sessions_no_expired(self) -> None:
        """Test cleanup_expired_sessions when nothing is expired."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        manager.create_session()

        count = manager.cleanup_expired_sessions(timeout_seconds=3600)

        assert count == 0
        assert len(manager.list_sessions()) == 1


class TestSessionWorkspace:
    """Tests for session workspace directory initialization."""

    def test_workspace_directory_exists_after_create(self) -> None:
        """Test that /workspace directory is created for new session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        fs = manager.get_session_fs(session_id)
        assert fs is not None

        assert fs.isdir("/workspace") is True
        assert fs.exists("/workspace") is True

    def test_workspace_is_directory(self) -> None:
        """Test that workspace exists as a directory (not a file)."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        fs = manager.get_session_fs(session_id)
        assert fs is not None

        assert fs.isdir("/workspace") is True
        assert fs.isfile("/workspace") is False


class TestUpdateSessionAccess:
    """Tests for update_session_access method."""

    def test_update_session_access_returns_true(self) -> None:
        """Test that update_session_access returns True for existing session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        result = manager.update_session_access(session_id)
        assert result is True

    def test_update_session_access_returns_false_for_nonexistent(self) -> None:
        """Test that update_session_access returns False for nonexistent session."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        result = manager.update_session_access("nonexistent")
        assert result is False

    def test_update_session_access_updates_timestamp(self) -> None:
        """Test that update_session_access updates the last_accessed timestamp."""
        import time

        config = OverlayConfig()
        manager = SessionFileSystemManager(config)
        session_id = manager.create_session()

        initial_meta = manager.get_session_metadata(session_id)
        assert initial_meta is not None
        initial_access = initial_meta.last_accessed

        time.sleep(0.01)
        manager.update_session_access(session_id)

        updated_meta = manager.get_session_metadata(session_id)
        assert updated_meta is not None
        assert updated_meta.last_accessed > initial_access


class TestManagerStateManagement:
    """Tests for manager state and lifecycle."""

    def test_manager_isolation_between_instances(self) -> None:
        """Test that separate manager instances have isolated state."""
        config = OverlayConfig()
        manager_1 = SessionFileSystemManager(config)
        manager_2 = SessionFileSystemManager(config)

        session_id = manager_1.create_session()

        sessions_1 = {meta.session_id for meta in manager_1.list_sessions()}
        sessions_2 = {meta.session_id for meta in manager_2.list_sessions()}

        assert session_id in sessions_1
        assert session_id not in sessions_2


@pytest.mark.unit
class TestSessionManagerFullLifecycle:
    """Integration-style tests for complete session lifecycle."""

    def test_full_session_lifecycle(self) -> None:
        """Test complete lifecycle: create -> get -> list -> cleanup."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        # Create session
        session_id = manager.create_session()
        sessions = manager.list_sessions()
        assert any(meta.session_id == session_id for meta in sessions)

        # Get session metadata
        meta = manager.get_session(session_id)
        assert isinstance(meta, SessionMetadata)
        assert meta.session_id == session_id

        # Get filesystem
        fs = manager.get_session_fs(session_id)
        assert isinstance(fs, OverlayFileSystem)

        # Workspace should exist
        assert fs.isdir("/workspace") is True

        # Cleanup
        assert manager.cleanup_session(session_id) is True
        assert manager.list_sessions() == []

        # Operations on cleaned session
        assert manager.get_session_fs(session_id) is None
        assert manager.get_session(session_id) is None

    def test_multiple_sessions_lifecycle(self) -> None:
        """Test lifecycle with multiple concurrent sessions."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        # Create multiple sessions
        sessions = [manager.create_session() for _ in range(5)]
        assert len(manager.list_sessions()) == 5

        # Cleanup in reverse order
        for session_id in reversed(sessions):
            assert manager.cleanup_session(session_id) is True

        assert manager.list_sessions() == []

        # Recreating sessions should work
        new_session = manager.create_session()
        assert new_session not in sessions  # Should be different UUID
        assert len(manager.list_sessions()) == 1

    def test_session_with_custom_metadata(self) -> None:
        """Test session creation with custom metadata."""
        config = OverlayConfig()
        manager = SessionFileSystemManager(config)

        custom_meta = {
            "user": "john_doe",
            "project": "test_project",
            "tags": ["test", "dev"],
        }
        session_id = manager.create_session(metadata=custom_meta)

        meta = manager.get_session(session_id)
        assert meta is not None
        assert meta.metadata["user"] == "john_doe"
        assert meta.metadata["project"] == "test_project"
        assert meta.metadata["tags"] == ["test", "dev"]
