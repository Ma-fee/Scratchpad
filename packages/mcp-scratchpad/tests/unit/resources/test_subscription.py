"""
Unit tests for resource subscription and notification system.

This module tests the subscription functionality including:
- Subscription creation and management
- Change detection via polling
- Thread safety
- Callback invocation
- Integration with read handler
- Session cleanup

Test Coverage:
    - Subscribe/unsubscribe operations
    - Resource change detection
    - Polling mechanism
    - Thread-safe subscription tracking
    - Subscription info in resource responses
    - Error handling
    - Edge cases (duplicate URIs, invalid URIs, etc.)
"""

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.read_handler import ResourceReadResult, read_resource
from mcp_scratchpad.resources.subscription import (
    ResourceState,
    ResourceSubscriptionError,
    ResourceSubscriptionManager,
    Subscription,
    cleanup_session_subscriptions,
    get_resource_subscription_info,
    is_resource_subscribed,
    list_resource_subscriptions,
    set_subscription_manager,
    subscribe_to_resource,
    unsubscribe_from_resource,
)

# Valid UUID for testing
TEST_SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_URI = f"scratchpad://{TEST_SESSION_ID}/test.txt"


@pytest.fixture
def subscription_manager():
    """Create a subscription manager for testing."""
    manager = ResourceSubscriptionManager(default_poll_interval=0.1)
    original = set_subscription_manager(manager)
    yield manager
    manager.shutdown()
    set_subscription_manager(None)


@pytest.fixture
def mock_session_manager():
    """Create a mock session manager."""
    manager = MagicMock()
    return manager


@pytest.fixture
def real_session_manager():
    """Create a real session manager with filesystem."""
    config = OverlayConfig(mounts=[])
    manager = SessionFileSystemManager(config)
    session_id = manager.create_session()
    fs = manager.get_session_fs(session_id)
    return manager, session_id, fs


@pytest.fixture
def mock_callback():
    """Create a mock callback function."""
    return MagicMock()


class TestSubscriptionDataclass:
    """Tests for Subscription dataclass."""

    def test_subscription_creation(self):
        """Test creating a subscription instance."""
        callback = lambda u, d: None
        sub = Subscription(
            subscription_id="test-123",
            uri=TEST_URI,
            callback=callback,
            poll_interval=2.0,
        )

        assert sub.subscription_id == "test-123"
        assert sub.uri == TEST_URI
        assert sub.callback == callback
        assert sub.poll_interval == 2.0
        assert sub.is_active is True
        assert isinstance(sub.created_at, datetime)

    def test_subscription_to_dict(self):
        """Test converting subscription to dictionary."""
        sub = Subscription(
            subscription_id="test-123",
            uri=TEST_URI,
            callback=lambda u, d: None,
            last_modified="2024-01-01T00:00:00",
            last_size=100,
        )

        data = sub.to_dict()
        assert data["subscription_id"] == "test-123"
        assert data["uri"] == TEST_URI
        assert data["last_modified"] == "2024-01-01T00:00:00"
        assert data["last_size"] == 100
        assert data["is_active"] is True


class TestResourceState:
    """Tests for ResourceState dataclass."""

    def test_resource_state_creation(self):
        """Test creating resource state."""
        state = ResourceState(uri=TEST_URI, mtime="2024-01-01T00:00:00", size=100)
        assert state.uri == TEST_URI
        assert state.mtime == "2024-01-01T00:00:00"
        assert state.size == 100

    def test_has_changed_same_state(self):
        """Test comparison with identical state."""
        state1 = ResourceState(uri=TEST_URI, mtime="2024-01-01T00:00:00", size=100)
        state2 = ResourceState(uri=TEST_URI, mtime="2024-01-01T00:00:00", size=100)
        assert not state1.has_changed(state2)

    def test_has_changed_different_mtime(self):
        """Test detection of mtime change."""
        state1 = ResourceState(uri=TEST_URI, mtime="2024-01-01T00:00:00", size=100)
        state2 = ResourceState(uri=TEST_URI, mtime="2024-01-02T00:00:00", size=100)
        assert state1.has_changed(state2)

    def test_has_changed_different_size(self):
        """Test detection of size change."""
        state1 = ResourceState(uri=TEST_URI, mtime="2024-01-01T00:00:00", size=100)
        state2 = ResourceState(uri=TEST_URI, mtime="2024-01-01T00:00:00", size=200)
        assert state1.has_changed(state2)


class TestResourceSubscriptionManager:
    """Tests for ResourceSubscriptionManager."""

    def test_manager_initialization(self):
        """Test manager creation with default values."""
        manager = ResourceSubscriptionManager()
        assert manager._default_poll_interval == 5.0
        assert manager._running is False
        manager.shutdown()

    def test_manager_custom_poll_interval(self):
        """Test manager creation with custom poll interval."""
        manager = ResourceSubscriptionManager(default_poll_interval=1.5)
        assert manager._default_poll_interval == 1.5
        manager.shutdown()

    def test_subscribe_creates_subscription(self, subscription_manager):
        """Test subscribing creates a subscription."""
        callback = MagicMock()

        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        assert sub_id is not None
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

        sub = subscription_manager.get_subscription(sub_id)
        assert sub is not None
        assert sub.uri == TEST_URI
        assert sub.callback == callback

    def test_subscribe_invalid_uri(self, subscription_manager):
        """Test subscribing with invalid URI raises error."""
        callback = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            subscription_manager.subscribe("invalid://uri", callback)

        assert "Invalid URI" in str(exc_info.value)

    def test_subscribe_missing_session_id(self, subscription_manager):
        """Test subscribing with URI missing session_id raises error."""
        callback = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            subscription_manager.subscribe("scratchpad:///test.txt", callback)

        # The URI parser returns "Missing session_id" or "Invalid URI"
        error_str = str(exc_info.value).lower()
        assert "session_id" in error_str or "invalid uri" in error_str

    def test_unsubscribe_removes_subscription(self, subscription_manager):
        """Test unsubscribing removes the subscription."""
        callback = MagicMock()
        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        result = subscription_manager.unsubscribe(sub_id)

        assert result is True
        assert subscription_manager.get_subscription(sub_id) is None

    def test_unsubscribe_nonexistent(self, subscription_manager):
        """Test unsubscribing non-existent subscription returns False."""
        result = subscription_manager.unsubscribe("nonexistent-id")
        assert result is False

    def test_list_subscriptions(self, subscription_manager):
        """Test listing subscriptions."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        sub_id1 = subscription_manager.subscribe(TEST_URI, callback1)
        sub_id2 = subscription_manager.subscribe(TEST_URI, callback1)

        subs = subscription_manager.list_subscriptions()

        assert len(subs) == 2
        assert any(s.subscription_id == sub_id1 for s in subs)
        assert any(s.subscription_id == sub_id2 for s in subs)

    def test_list_subscriptions_filter_by_uri(self, subscription_manager):
        """Test listing subscriptions filtered by URI."""
        callback = MagicMock()
        uri1 = f"scratchpad://{TEST_SESSION_ID}/file1.txt"
        uri2 = f"scratchpad://{TEST_SESSION_ID}/file2.txt"

        sub_id1 = subscription_manager.subscribe(uri1, callback)
        sub_id2 = subscription_manager.subscribe(uri2, callback)

        subs_uri1 = subscription_manager.list_subscriptions(uri=uri1)

        assert len(subs_uri1) == 1
        assert subs_uri1[0].subscription_id == sub_id1

    def test_list_subscriptions_active_only(self, subscription_manager):
        """Test listing only active subscriptions."""
        callback = MagicMock()
        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        # Unsubscribe
        subscription_manager.unsubscribe(sub_id)

        all_subs = subscription_manager.list_subscriptions(active_only=False)
        active_subs = subscription_manager.list_subscriptions(active_only=True)

        # After unsubscribe, index is cleaned so count may be 0
        assert len(active_subs) == 0

    def test_is_resource_subscribed(self, subscription_manager):
        """Test checking if resource is subscribed."""
        callback = MagicMock()

        assert not subscription_manager.is_resource_subscribed(TEST_URI)

        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        assert subscription_manager.is_resource_subscribed(TEST_URI)

        subscription_manager.unsubscribe(sub_id)
        assert not subscription_manager.is_resource_subscribed(TEST_URI)

    def test_get_resource_subscription_info(self, subscription_manager):
        """Test getting subscription info for a resource."""
        callback = MagicMock()

        info = subscription_manager.get_resource_subscription_info(TEST_URI)
        assert info["is_subscribed"] is False
        assert info["subscription_count"] == 0

        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        info = subscription_manager.get_resource_subscription_info(TEST_URI)
        assert info["is_subscribed"] is True
        assert info["subscription_count"] == 1
        assert sub_id in info["subscription_ids"]

    def test_shutdown_clears_subscriptions(self, subscription_manager):
        """Test shutdown clears all subscriptions."""
        callback = MagicMock()
        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        subscription_manager.shutdown()

        assert subscription_manager.get_subscription(sub_id) is None
        assert len(subscription_manager.list_subscriptions()) == 0

    def test_thread_safe_subscription(self, subscription_manager):
        """Test thread-safe subscription operations."""
        errors = []
        subscribed_ids = []

        def subscribe_worker():
            try:
                callback = MagicMock()
                sub_id = subscription_manager.subscribe(TEST_URI, callback)
                subscribed_ids.append(sub_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=subscribe_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(subscribed_ids) == 10
        assert len(set(subscribed_ids)) == 10  # All unique


class TestPollingAndChangeDetection:
    """Tests for polling mechanism and change detection."""

    def test_polling_starts_on_subscribe(self, subscription_manager):
        """Test that polling thread starts when subscribing."""
        callback = MagicMock()

        assert not subscription_manager._running

        subscription_manager.subscribe(TEST_URI, callback)

        # Give thread time to start
        time.sleep(0.2)
        assert subscription_manager._running

    def test_polling_stops_on_unsubscribe_all(self, subscription_manager):
        """Test that polling stops when all subscriptions removed."""
        callback = MagicMock()
        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        time.sleep(0.2)
        assert subscription_manager._running

        subscription_manager.unsubscribe(sub_id)

        time.sleep(0.3)
        assert not subscription_manager._running

    def test_callback_invoked_on_change(self, real_session_manager):
        """Test callback is invoked when file changes."""
        manager, session_id, fs = real_session_manager

        # Create subscription manager with short poll interval
        sub_manager = ResourceSubscriptionManager(
            default_poll_interval=0.1, session_manager=manager
        )

        # Create a file
        uri = f"scratchpad://{session_id}/test.txt"
        with fs.open("/test.txt", "w") as f:
            f.write("initial content")

        callback = MagicMock()
        sub_id = sub_manager.subscribe(uri, callback)

        # Wait for initial poll
        time.sleep(0.3)

        # Modify file
        with fs.open("/test.txt", "w") as f:
            f.write("modified content")

        # Wait for change detection
        time.sleep(0.3)

        # Callback should have been called
        assert callback.called

        sub_manager.shutdown()

    def test_multiple_subscribers_notified(self, real_session_manager):
        """Test all subscribers are notified of changes."""
        manager, session_id, fs = real_session_manager

        sub_manager = ResourceSubscriptionManager(
            default_poll_interval=0.1, session_manager=manager
        )

        uri = f"scratchpad://{session_id}/test.txt"
        with fs.open("/test.txt", "w") as f:
            f.write("content")

        callback1 = MagicMock()
        callback2 = MagicMock()
        sub_id1 = sub_manager.subscribe(uri, callback1)
        sub_id2 = sub_manager.subscribe(uri, callback2)

        time.sleep(0.3)

        # Modify file
        with fs.open("/test.txt", "w") as f:
            f.write("modified")

        time.sleep(0.3)

        # Both callbacks should have been called
        assert callback1.called
        assert callback2.called

        sub_manager.shutdown()


class TestSessionCleanup:
    """Tests for session cleanup functionality."""

    def test_cleanup_session_subscriptions(self, subscription_manager):
        """Test cleaning up subscriptions for a session."""
        callback = MagicMock()
        session_id1 = "550e8400-e29b-41d4-a716-446655440001"
        session_id2 = "550e8400-e29b-41d4-a716-446655440002"
        uri1 = f"scratchpad://{session_id1}/file.txt"
        uri2 = f"scratchpad://{session_id2}/file.txt"

        sub_id1 = subscription_manager.subscribe(uri1, callback)
        sub_id2 = subscription_manager.subscribe(uri2, callback)

        count = subscription_manager.cleanup_session_subscriptions(session_id1)

        assert count == 1
        assert subscription_manager.get_subscription(sub_id1) is None
        assert subscription_manager.get_subscription(sub_id2) is not None

    def test_cleanup_session_multiple_subscriptions(self, subscription_manager):
        """Test cleaning up multiple subscriptions for same session."""
        callback = MagicMock()
        session_id1 = "550e8400-e29b-41d4-a716-446655440001"
        session_id2 = "550e8400-e29b-41d4-a716-446655440002"
        uri1 = f"scratchpad://{session_id1}/file1.txt"
        uri2 = f"scratchpad://{session_id1}/file2.txt"
        uri3 = f"scratchpad://{session_id2}/file.txt"

        sub_id1 = subscription_manager.subscribe(uri1, callback)
        sub_id2 = subscription_manager.subscribe(uri2, callback)
        sub_id3 = subscription_manager.subscribe(uri3, callback)

        count = subscription_manager.cleanup_session_subscriptions(session_id1)

        assert count == 2
        assert subscription_manager.get_subscription(sub_id1) is None
        assert subscription_manager.get_subscription(sub_id2) is None
        assert subscription_manager.get_subscription(sub_id3) is not None


class TestGlobalFunctions:
    """Tests for global subscription functions."""

    def test_subscribe_to_resource(self, subscription_manager):
        """Test global subscribe_to_resource function."""
        callback = MagicMock()

        sub_id = subscribe_to_resource(TEST_URI, callback)

        assert sub_id is not None
        assert subscription_manager.get_subscription(sub_id) is not None

    def test_unsubscribe_from_resource(self, subscription_manager):
        """Test global unsubscribe_from_resource function."""
        callback = MagicMock()
        sub_id = subscribe_to_resource(TEST_URI, callback)

        result = unsubscribe_from_resource(sub_id)

        assert result is True
        assert subscription_manager.get_subscription(sub_id) is None

    def test_is_resource_subscribed_global(self, subscription_manager):
        """Test global is_resource_subscribed function."""
        callback = MagicMock()

        assert not is_resource_subscribed(TEST_URI)

        sub_id = subscribe_to_resource(TEST_URI, callback)

        assert is_resource_subscribed(TEST_URI)

    def test_get_resource_subscription_info_global(self, subscription_manager):
        """Test global get_resource_subscription_info function."""
        callback = MagicMock()
        sub_id = subscribe_to_resource(TEST_URI, callback)

        info = get_resource_subscription_info(TEST_URI)

        assert info["is_subscribed"] is True
        assert info["subscription_count"] == 1

    def test_list_resource_subscriptions_global(self, subscription_manager):
        """Test global list_resource_subscriptions function."""
        callback = MagicMock()
        sub_id = subscribe_to_resource(TEST_URI, callback)

        subs = list_resource_subscriptions()

        assert len(subs) == 1
        assert subs[0]["subscription_id"] == sub_id

    def test_cleanup_session_subscriptions_global(self, subscription_manager):
        """Test global cleanup_session_subscriptions function."""
        callback = MagicMock()
        session_id = "550e8400-e29b-41d4-a716-44665544000a"
        uri = f"scratchpad://{session_id}/file.txt"
        sub_id = subscribe_to_resource(uri, callback)

        count = cleanup_session_subscriptions(session_id)

        assert count == 1
        assert subscription_manager.get_subscription(sub_id) is None


class TestIntegrationWithReadHandler:
    """Tests for integration with read handler."""

    def test_resource_response_includes_subscription_info(
        self, real_session_manager, subscription_manager
    ):
        """Test that read_resource includes subscription info."""
        manager, session_id, fs = real_session_manager

        # Create a file
        with fs.open("/test.txt", "w") as f:
            f.write("test content")

        # Subscribe to the resource
        from mcp_scratchpad.resources.read_handler import set_session_manager

        set_subscription_manager(subscription_manager)
        set_session_manager(manager)

        callback = MagicMock()
        sub_id = subscribe_to_resource(f"scratchpad://{session_id}/test.txt", callback)

        # Read the resource
        uri = f"scratchpad://{session_id}/test.txt"
        result = read_resource(uri, session_manager=manager)

        assert result.success is True
        assert "subscription_info" in result.to_dict()
        info = result.subscription_info
        assert info["is_subscribed"] is True
        assert info["subscription_count"] == 1
        assert sub_id in info["subscription_ids"]

    def test_resource_response_no_subscription(self, real_session_manager):
        """Test that read_resource handles no subscription gracefully."""
        manager, session_id, fs = real_session_manager

        # Create a file (no subscription)
        with fs.open("/test.txt", "w") as f:
            f.write("test content")

        from mcp_scratchpad.resources.read_handler import set_session_manager

        set_session_manager(manager)

        uri = f"scratchpad://{session_id}/test.txt"
        result = read_resource(uri, session_manager=manager)

        assert result.success is True
        info = result.subscription_info
        assert info["is_subscribed"] is False
        assert info["subscription_count"] == 0


class TestErrorHandling:
    """Tests for error handling."""

    def test_callback_exception_handled(self, real_session_manager):
        """Test that callback exceptions are handled gracefully."""
        manager, session_id, fs = real_session_manager

        sub_manager = ResourceSubscriptionManager(
            default_poll_interval=0.1, session_manager=manager
        )

        uri = f"scratchpad://{session_id}/test.txt"
        with fs.open("/test.txt", "w") as f:
            f.write("content")

        bad_callback = MagicMock(side_effect=Exception("Callback failed"))
        sub_id = sub_manager.subscribe(uri, bad_callback)

        time.sleep(0.3)

        # Modify file - should not crash
        with fs.open("/test.txt", "w") as f:
            f.write("modified")

        time.sleep(0.3)

        # Callback should have been called and failed, but no crash
        assert bad_callback.called
        assert sub_manager.get_subscription(sub_id) is not None

        sub_manager.shutdown()

    def test_resource_state_unavailable(self, subscription_manager):
        """Test handling when resource state cannot be determined."""
        callback = MagicMock()

        # Subscribe to non-existent session
        sub_id = subscription_manager.subscribe(TEST_URI, callback)

        # Should not crash, subscription created
        assert sub_id is not None
        sub = subscription_manager.get_subscription(sub_id)
        assert sub is not None


class TestResourceSubscriptionError:
    """Tests for ResourceSubscriptionError."""

    def test_error_with_subscription_id(self):
        """Test error with subscription ID."""
        error = ResourceSubscriptionError("Something failed", subscription_id="sub-123")
        assert str(error) == "Something failed"
        assert error.subscription_id == "sub-123"

    def test_error_without_subscription_id(self):
        """Test error without subscription ID."""
        error = ResourceSubscriptionError("Something failed")
        assert str(error) == "Something failed"
        assert error.subscription_id is None


class TestEdgeCases:
    """Tests for edge cases."""

    def test_subscribe_same_uri_multiple_times(self, subscription_manager):
        """Test subscribing to same URI multiple times."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        sub_id1 = subscription_manager.subscribe(TEST_URI, callback1)
        sub_id2 = subscription_manager.subscribe(TEST_URI, callback2)

        assert sub_id1 != sub_id2
        assert len(subscription_manager.list_subscriptions(uri=TEST_URI)) == 2

    def test_unsubscribe_one_of_many(self, subscription_manager):
        """Test unsubscribing one of multiple subscriptions for same URI."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        sub_id1 = subscription_manager.subscribe(TEST_URI, callback1)
        sub_id2 = subscription_manager.subscribe(TEST_URI, callback2)

        result = subscription_manager.unsubscribe(sub_id1)

        assert result is True
        assert subscription_manager.get_subscription(sub_id1) is None
        assert subscription_manager.get_subscription(sub_id2) is not None
        assert subscription_manager.is_resource_subscribed(TEST_URI)

    def test_empty_metadata(self, subscription_manager):
        """Test subscription with empty metadata."""
        callback = MagicMock()

        sub_id = subscription_manager.subscribe(TEST_URI, callback, metadata={})

        sub = subscription_manager.get_subscription(sub_id)
        assert sub.metadata == {}

    def test_custom_poll_interval(self, subscription_manager):
        """Test subscription with custom poll interval."""
        callback = MagicMock()

        sub_id = subscription_manager.subscribe(TEST_URI, callback, poll_interval=10.0)

        sub = subscription_manager.get_subscription(sub_id)
        assert sub.poll_interval == 10.0

    def test_subscription_preserves_metadata(self, subscription_manager):
        """Test that metadata is preserved in subscription."""
        callback = MagicMock()
        metadata = {"user": "test_user", "priority": "high"}

        sub_id = subscription_manager.subscribe(TEST_URI, callback, metadata=metadata)

        sub = subscription_manager.get_subscription(sub_id)
        assert sub.metadata == metadata
