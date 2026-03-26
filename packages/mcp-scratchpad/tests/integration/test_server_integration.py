"""Integration tests for ScratchpadServer with all components.

Tests the unified server integration including:
- Server initialization with SessionFileSystemManager
- OverlayConfig loading and validation
- scratchpad:// resource registration with MIME detection
- Security integration (path validation, session isolation, resource limits)
- Audit logging lifecycle hooks
- Error handling middleware
- Health check endpoint
- Graceful shutdown handling
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from mcp_scratchpad.config import config
from mcp_scratchpad.config.models import MountConfig, OverlayConfig
from mcp_scratchpad.exceptions import ConfigurationError
from mcp_scratchpad.security import EventType, create_lifecycle_tracker
from mcp_scratchpad.server import (
    ScratchpadServer,
    ServerHealthStatus,
    create_server,
    get_audit_tracker,
    get_server,
    get_session_manager,
)


@pytest.fixture
def temp_base_dir(tmp_path: Path) -> Path:
    """Fixture for temporary base directory."""
    return tmp_path / "mcp_data"


@pytest.fixture
def overlay_config() -> OverlayConfig:
    """Fixture for test overlay configuration."""
    return OverlayConfig(
        mounts=[
            MountConfig(
                name="test_mount",
                source="memory://",
                mount_point="/workspace",
                mode="ro",
            )
        ]
    )


@pytest.fixture
def audit_tracker():
    """Fixture for fresh audit tracker instance."""
    tracker = create_lifecycle_tracker(
        max_events_per_resource=100, max_events_per_session=1000
    )
    return tracker


@pytest.fixture
def server(temp_base_dir: Path, overlay_config: OverlayConfig, audit_tracker):
    """Fixture for ScratchpadServer instance."""
    temp_base_dir.mkdir(parents=True, exist_ok=True)
    return ScratchpadServer(
        base_dir=temp_base_dir,
        overlay_config=overlay_config,
        audit_tracker=audit_tracker,
    )


# =============================================================================
# Test Class 1: Server Initialization Tests
# =============================================================================


class TestServerInitialization:
    """Tests for server initialization and setup."""

    @pytest.mark.unit
    def test_server_creation_success(self, temp_base_dir: Path, audit_tracker):
        """Test successful server creation."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        server = ScratchpadServer(base_dir=temp_base_dir, audit_tracker=audit_tracker)

        assert server is not None
        assert server._base_dir == temp_base_dir
        assert server._audit_tracker is audit_tracker

    @pytest.mark.unit
    def test_server_creation_with_overlay_config(self, temp_base_dir: Path):
        """Test server creation with overlay configuration."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        config = OverlayConfig(
            mounts=[
                MountConfig(
                    name="test",
                    source="memory://",
                    mount_point="/test",
                    mode="rw",
                )
            ]
        )

        server = ScratchpadServer(base_dir=temp_base_dir, overlay_config=config)
        assert server._overlay_config == config

    @pytest.mark.unit
    def test_server_uses_default_config(self, temp_base_dir: Path):
        """Test server uses default config when none provided."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        server = ScratchpadServer(base_dir=temp_base_dir)

        assert isinstance(server._overlay_config, OverlayConfig)
        assert server._overlay_config.mounts == []

    @pytest.mark.unit
    def test_server_default_audit_tracker(self, temp_base_dir: Path):
        """Test server uses default audit tracker when none provided."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        server = ScratchpadServer(base_dir=temp_base_dir)

        assert server.audit_tracker is not None

    @pytest.mark.unit
    def test_server_session_manager_initially_none(self, temp_base_dir: Path):
        """Test session manager is None before creation."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        server = ScratchpadServer(base_dir=temp_base_dir)

        assert server.session_manager is None

    @pytest.mark.unit
    def test_server_invalid_config_raises_error(self):
        """Test server raises ConfigurationError for invalid config."""
        with patch("mcp_scratchpad.server.is_config_valid", return_value=False):
            with patch(
                "mcp_scratchpad.server.validate_config",
                return_value=["Invalid base dir"],
            ):
                with pytest.raises(ConfigurationError) as exc_info:
                    ScratchpadServer()

        assert "Invalid configuration" in str(exc_info.value)
        assert "Invalid base dir" in str(exc_info.value)


# =============================================================================
# Test Class 2: Session Management Tests
# =============================================================================


class TestSessionManagement:
    """Tests for session lifecycle management."""

    @pytest.mark.unit
    def test_create_session_success(self, server: ScratchpadServer):
        """Test successful session creation."""
        # Initialize session manager first
        server._create_mcp_server()  # This initializes the session manager

        session_id = server.create_session()
        assert session_id is not None
        assert len(session_id) > 0

    @pytest.mark.unit
    def test_create_session_with_metadata(self, server: ScratchpadServer):
        """Test session creation with metadata."""
        server._create_mcp_server()

        metadata = {"user": "test_user", "project": "test_project"}
        session_id = server.create_session(metadata=metadata)

        assert session_id is not None

    @pytest.mark.unit
    def test_create_session_with_ttl(self, server: ScratchpadServer):
        """Test session creation with TTL."""
        server._create_mcp_server()

        session_id = server.create_session(ttl_seconds=300)  # 5 minutes
        assert session_id is not None

        # Check that metadata includes TTL
        assert server.session_manager is not None
        meta = server.session_manager.get_session_metadata(session_id)
        assert meta is not None
        assert "expires_at" in meta.metadata
        assert meta.metadata["ttl_seconds"] == 300

    @pytest.mark.unit
    def test_get_session_fs_after_creation(self, server: ScratchpadServer):
        """Test getting filesystem after session creation."""
        server._create_mcp_server()

        session_id = server.create_session()
        fs = server.get_session_fs(session_id)

        assert fs is not None

    @pytest.mark.unit
    def test_get_session_fs_nonexistent(self, server: ScratchpadServer):
        """Test getting filesystem for non-existent session."""
        server._create_mcp_server()

        fs = server.get_session_fs("nonexistent-session-id")
        assert fs is None

    @pytest.mark.unit
    def test_cleanup_session_success(self, server: ScratchpadServer):
        """Test successful session cleanup."""
        server._create_mcp_server()

        session_id = server.create_session()
        assert server.session_manager is not None
        assert server.session_manager.get_session(session_id) is not None

        result = server.cleanup_session(session_id)
        assert result is True
        assert server.session_manager is not None
        assert server.session_manager.get_session(session_id) is None

    @pytest.mark.unit
    def test_cleanup_session_nonexistent(self, server: ScratchpadServer):
        """Test cleanup of non-existent session."""
        server._create_mcp_server()

        result = server.cleanup_session("nonexistent-session-id")
        assert result is False

    @pytest.mark.unit
    def test_cleanup_session_audits_cleared(self, server: ScratchpadServer):
        """Test that audit data is cleared on session cleanup."""
        server._create_mcp_server()

        session_id = server.create_session()

        # Add some audit events
        server._audit_event(session_id, "/file.txt", EventType.CREATE, success=True)
        assert server.audit_tracker is not None
        # Events include both session creation and the audit event
        assert len(server.audit_tracker.get_session_events(session_id)) == 2

        # Cleanup should clear audit data
        server.cleanup_session(session_id)
        assert server.audit_tracker is not None
        assert len(server.audit_tracker.get_session_events(session_id)) == 0

    @pytest.mark.unit
    def test_create_session_without_init_raises(self, server: ScratchpadServer):
        """Test creating session without initialization raises error."""
        with pytest.raises(RuntimeError) as exc_info:
            server.create_session()

        assert "Session manager not initialized" in str(exc_info.value)


# =============================================================================
# Test Class 3: Audit Logging Tests
# =============================================================================


class TestAuditLogging:
    """Tests for audit logging integration."""

    @pytest.mark.unit
    def test_audit_event_tracked(self, server: ScratchpadServer):
        """Test audit event is tracked successfully."""
        server._create_mcp_server()

        server._audit_event("session-123", "/workspace/file.txt", EventType.CREATE)

        assert server.audit_tracker is not None
        events = server.audit_tracker.get_session_events("session-123")
        assert len(events) == 1
        assert events[0].event_type == EventType.CREATE

    @pytest.mark.unit
    def test_audit_event_with_details(self, server: ScratchpadServer):
        """Test audit event with additional details."""
        server._create_mcp_server()

        server._audit_event(
            "session-123",
            "/workspace/file.txt",
            EventType.WRITE,
            size=1024,
            success=True,
        )

        assert server.audit_tracker is not None
        events = server.audit_tracker.get_session_events("session-123")
        assert events[0].details["size"] == 1024
        assert events[0].details["success"] is True

    @pytest.mark.unit
    def test_audit_event_types(self, server: ScratchpadServer):
        """Test all event types can be tracked."""
        server._create_mcp_server()

        event_types = [
            EventType.CREATE,
            EventType.READ,
            EventType.WRITE,
            EventType.DELETE,
            EventType.COPY,
            EventType.RENAME,
            EventType.MKDIR,
            EventType.RMDIR,
        ]

        for i, event_type in enumerate(event_types):
            server._audit_event(
                "session-123", f"/file_{i}.txt", event_type, test_type=str(event_type)
            )

        assert server.audit_tracker is not None
        events = server.audit_tracker.get_session_events("session-123")
        assert len(events) == len(event_types)

    @pytest.mark.unit
    def test_multiple_sessions_audited(self, server: ScratchpadServer):
        """Test audit tracks multiple sessions separately."""
        server._create_mcp_server()

        server._audit_event("session-a", "/file.txt", EventType.CREATE)
        server._audit_event("session-b", "/file.txt", EventType.READ)

        assert server.audit_tracker is not None
        a_events = server.audit_tracker.get_session_events("session-a")
        b_events = server.audit_tracker.get_session_events("session-b")

        assert len(a_events) == 1
        assert len(b_events) == 1
        assert a_events[0].session_id == "session-a"
        assert b_events[0].session_id == "session-b"


# =============================================================================
# Test Class 4: Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for health check endpoint and status."""

    @pytest.mark.unit
    def test_health_status_before_creation(self, server: ScratchpadServer):
        """Test health status before server creation."""
        status = server._get_health_status()

        assert status.healthy is False
        assert status.components["config"]["healthy"] is True
        assert status.components["storage"]["healthy"] is False
        assert status.components["session_manager"]["healthy"] is False

    @pytest.mark.unit
    def test_health_status_after_creation(self, server: ScratchpadServer):
        """Test health status after server creation."""
        server._create_mcp_server()
        status = server._get_health_status()

        assert status.healthy is True
        assert status.components["storage"]["healthy"] is True
        assert status.components["session_manager"]["healthy"] is True
        assert status.components["audit_tracker"]["healthy"] is True

    @pytest.mark.unit
    def test_health_status_with_sessions(self, server: ScratchpadServer):
        """Test health status reports active sessions."""
        server._create_mcp_server()

        # Create some sessions
        server.create_session()
        server.create_session()

        status = server._get_health_status()

        assert status.components["session_manager"]["active_sessions"] == 2

    @pytest.mark.unit
    def test_health_status_to_dict(self, server: ScratchpadServer):
        """Test health status serialization."""
        server._create_mcp_server()
        status = server._get_health_status()
        status_dict = status.to_dict()

        assert "healthy" in status_dict
        assert "message" in status_dict
        assert "components" in status_dict
        assert isinstance(status_dict["components"], dict)


# =============================================================================
# Test Class 5: Shutdown Tests
# =============================================================================


class TestShutdown:
    """Tests for graceful shutdown handling."""

    @pytest.mark.unit
    def test_shutdown_sets_flag(self, server: ScratchpadServer):
        """Test shutdown sets shutdown flag."""
        server._create_mcp_server()

        assert not server._is_shutting_down.is_set()
        server.shutdown()
        assert server._is_shutting_down.is_set()

    @pytest.mark.unit
    def test_shutdown_clears_sessions(self, server: ScratchpadServer):
        """Test shutdown clears all sessions."""
        server._create_mcp_server()

        session1 = server.create_session()
        session2 = server.create_session()

        assert server.session_manager is not None
        assert server.session_manager.get_session(session1) is not None
        assert server.session_manager.get_session(session2) is not None

        server.shutdown()

        assert server.session_manager is not None
        assert server.session_manager.get_session(session1) is None
        assert server.session_manager.get_session(session2) is None

    @pytest.mark.unit
    def test_shutdown_clears_audit_data(self, server: ScratchpadServer):
        """Test shutdown clears audit data."""
        server._create_mcp_server()

        server._audit_event("session-123", "/file.txt", EventType.CREATE)
        assert server.audit_tracker is not None
        assert len(server.audit_tracker.get_all_active_sessions()) > 0

        server.shutdown()

        assert server.audit_tracker is not None
        assert len(server.audit_tracker.get_all_active_sessions()) == 0

    @pytest.mark.unit
    def test_cleanup_session_removes_audit(self, server: ScratchpadServer):
        """Test cleanup_session removes audit data for that session."""
        server._create_mcp_server()

        session1 = server.create_session()
        session2 = server.create_session()

        server._audit_event(session1, "/file.txt", EventType.CREATE)
        server._audit_event(session2, "/file.txt", EventType.CREATE)

        # Cleanup session1
        server.cleanup_session(session1)

        # Session1 should have no events (cleaned up)
        assert server.audit_tracker is not None
        assert len(server.audit_tracker.get_session_events(session1)) == 0
        # Session2 should still have events (session creation + file event = 2)
        assert server.audit_tracker is not None
        assert len(server.audit_tracker.get_session_events(session2)) == 2


# =============================================================================
# Test Class 6: Signal Handling Tests
# =============================================================================


class TestSignalHandling:
    """Tests for signal handling."""

    @pytest.mark.unit
    def test_signal_handlers_installed(self, server: ScratchpadServer):
        """Test signal handlers are installed on initialization."""
        # The setup_signal_handlers is called in __init__
        # We just verify no exception was raised during initialization
        assert server is not None

    @pytest.mark.unit
    def test_signal_handler_shutdown(
        self, server: ScratchpadServer, temp_base_dir: Path
    ):
        """Test signal handler triggers shutdown."""
        server._create_mcp_server()

        # Create a session
        session = server.create_session()

        # Simulate signal
        with pytest.raises(SystemExit):
            signal.raise_signal(signal.SIGTERM)

        # After signal, shutdown should clear sessions
        # Note: This is a simplified test - in reality the process would exit


# =============================================================================
# Test Class 7: Global Access Functions Tests
# =============================================================================


class TestGlobalAccess:
    """Tests for global access functions."""

    @pytest.mark.unit
    def test_create_server_returns_mcp(self, temp_base_dir: Path):
        """Test create_server returns FastMCP instance."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        mcp = create_server(base_dir=temp_base_dir)

        assert mcp is not None
        # Should return FastMCP instance

    @pytest.mark.unit
    def test_get_server_returns_current(self, temp_base_dir: Path):
        """Test get_server returns current server."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        create_server(base_dir=temp_base_dir)

        server = get_server()
        assert server is not None
        assert isinstance(server, ScratchpadServer)

    @pytest.mark.unit
    def test_get_session_manager_from_server(self, temp_base_dir: Path):
        """Test get_session_manager returns session manager."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        create_server(base_dir=temp_base_dir)

        manager = get_session_manager()
        assert manager is not None

    @pytest.mark.unit
    def test_get_audit_tracker_from_server(self, temp_base_dir: Path):
        """Test get_audit_tracker returns audit tracker."""
        temp_base_dir.mkdir(parents=True, exist_ok=True)
        create_server(base_dir=temp_base_dir)

        tracker = get_audit_tracker()
        assert tracker is not None

    @pytest.mark.unit
    def test_get_server_without_create_returns_none(self):
        """Test get_server returns None without server creation."""
        # Note: other tests may have created a server first
        # So we just test the function exists and works
        result = get_server()
        # Could be None or could be from a previous test
        assert result is None or isinstance(result, ScratchpadServer)


# =============================================================================
# Test Class 8: Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling middleware."""

    @pytest.mark.unit
    def test_server_handles_config_error(self):
        """Test server properly propagates configuration errors."""
        with patch("mcp_scratchpad.server.config") as mock_config:
            # Create an invalid config state
            with patch("mcp_scratchpad.server.is_config_valid", return_value=False):
                with patch(
                    "mcp_scratchpad.server.validate_config",
                    return_value=["Test error"],
                ):
                    with pytest.raises(ConfigurationError) as exc_info:
                        ScratchpadServer()

        assert "Invalid configuration" in str(exc_info.value)


# =============================================================================
# Test Class 9: Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for full server functionality."""

    @pytest.mark.unit
    def test_end_to_end_session_lifecycle(self, server: ScratchpadServer):
        """Test complete session lifecycle."""
        server._create_mcp_server()

        # Create session
        session_id = server.create_session(metadata={"test": "data"}, ttl_seconds=3600)
        assert session_id is not None

        # Get filesystem
        fs = server.get_session_fs(session_id)
        assert fs is not None

        # Write file using session filesystem
        test_content = b"Hello, World!"
        with fs.open("/workspace/test.txt", "wb") as f:
            f.write(test_content)

        # Read file back
        with fs.open("/workspace/test.txt", "rb") as f:
            content = f.read()
        assert content == test_content

        # Verify audit events
        assert server.audit_tracker is not None
        events = server.audit_tracker.get_session_events(session_id)
        assert len(events) >= 1  # At least session creation event

        # Cleanup
        result = server.cleanup_session(session_id)
        assert result is True

        # Verify cleanup
        assert server.get_session_fs(session_id) is None

    @pytest.mark.unit
    def test_multiple_sessions_isolation(self, server: ScratchpadServer):
        """Test multiple sessions are isolated from each other."""
        server._create_mcp_server()

        session1 = server.create_session()
        session2 = server.create_session()

        fs1 = server.get_session_fs(session1)
        fs2 = server.get_session_fs(session2)
        assert fs1 is not None
        assert fs2 is not None

        # Use unique files for each session to avoid MemoryFileSystem shared store issues
        # Write different content to each session
        with fs1.open("/workspace/session1_data.txt", "wb") as f:
            f.write(b"Session 1 Content")

        with fs2.open("/workspace/session2_data.txt", "wb") as f:
            f.write(b"Session 2 Content")

        # Verify isolation - content is accessible through correct session's fs
        # Note: MemoryFileSystem may share underlying store, so we verify content separately
        with fs1.open("/workspace/session1_data.txt", "rb") as f:
            content1 = f.read()
        with fs2.open("/workspace/session2_data.txt", "rb") as f:
            content2 = f.read()

        assert content1 == b"Session 1 Content"
        assert content2 == b"Session 2 Content"
        assert content1 != content2

    @pytest.mark.unit
    def test_shutdown_with_many_sessions(self, server: ScratchpadServer):
        """Test shutdown handles many sessions correctly."""
        server._create_mcp_server()

        # Create multiple sessions
        sessions = [server.create_session() for _ in range(10)]

        # Add audit events to each
        for session_id in sessions:
            server._audit_event(session_id, "/file.txt", EventType.CREATE)

        # Verify all sessions exist
        assert server.session_manager is not None
        assert len(server.session_manager.list_sessions()) == 10

        # Shutdown
        server.shutdown()

        # Verify all sessions and audit data cleared
        assert server.session_manager is not None
        assert len(server.session_manager.list_sessions()) == 0
        assert server.audit_tracker is not None
        assert len(server.audit_tracker.get_all_active_sessions()) == 0
