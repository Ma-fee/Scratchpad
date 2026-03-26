"""
Resource subscription and notification system for MCP resources.

This module provides functionality to subscribe to resource changes and receive
notifications when files are modified. It implements polling-based change detection
using file modification times and sizes.

Features:
    - Subscribe to resource changes with callbacks
    - Automatic change detection via polling (5s default)
    - Thread-safe subscription management
    - Subscription cleanup on session expiration

Example:
    >>> from mcp_scratchpad.resources.subscription import subscribe_to_resource
    >>> def on_change(uri, content):
    ...     print(f"Resource {uri} changed!")
    ...
    >>> sub_id = subscribe_to_resource("scratchpad://abc-123/file.txt", on_change)
    >>> # Later...
    >>> unsubscribe_from_resource(sub_id)

Architecture:
    - ResourceSubscriptionManager: Thread-safe manager for subscriptions
    - Subscription: Dataclass representing a single subscription
    - Polling thread: Background thread that checks for file changes
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Protocol

from ..exceptions import ScratchpadError
from .uri_parser import ScratchpadURI, parse_scratchpad_uri

logger = logging.getLogger(__name__)


# Type aliases
CallbackType = Callable[[str, Any], None]
"""Type for resource change callbacks: callback(uri, content) -> None"""


@dataclass
class Subscription:
    """Represents a single resource subscription.

    Attributes:
        subscription_id: Unique identifier for this subscription (UUID)
        uri: The scratchpad:// URI being monitored
        callback: Function to call when resource changes
        created_at: Timestamp when subscription was created
        last_modified: Last known modification time of the resource
        last_size: Last known size of the resource
        poll_interval: Polling interval in seconds
        metadata: Optional metadata dictionary
        is_active: Whether this subscription is still active

    Example:
        >>> sub = Subscription(
        ...     subscription_id="abc-123",
        ...     uri="scratchpad://session/file.txt",
        ...     callback=my_callback
        ... )
    """

    subscription_id: str
    uri: str
    callback: CallbackType
    created_at: datetime = field(default_factory=datetime.now)
    last_modified: Optional[str] = None
    last_size: int = 0
    poll_interval: float = 5.0
    metadata: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert subscription to dictionary representation."""
        return {
            "subscription_id": self.subscription_id,
            "uri": self.uri,
            "created_at": self.created_at.isoformat(),
            "last_modified": self.last_modified,
            "last_size": self.last_size,
            "poll_interval": self.poll_interval,
            "is_active": self.is_active,
        }


class SessionManagerProvider(Protocol):
    """Protocol for accessing session filesystem.

    This protocol allows the subscription manager to access filesystems
    for checking file modification times and sizes.
    """

    def get_session_fs(self, session_id: str) -> Any | None:
        """Get filesystem for a session."""
        ...


@dataclass
class ResourceState:
    """Tracks the state of a resource for change detection.

    Attributes:
        uri: The resource URI
        mtime: Last modification timestamp (ISO format)
        size: File size in bytes
        content_hash: Optional content hash for deep comparison
    """

    uri: str
    mtime: Optional[str] = None
    size: int = 0
    content_hash: Optional[str] = None

    def has_changed(self, other: ResourceState) -> bool:
        """Check if resource state has changed.

        Args:
            other: Another ResourceState to compare against

        Returns:
            True if mtime or size differs, False otherwise
        """
        return self.mtime != other.mtime or self.size != other.size


class ResourceSubscriptionManager:
    """Thread-safe manager for resource subscriptions.

    This class manages active subscriptions, polls resources for changes,
    and invokes callbacks when changes are detected. It runs a background
    polling thread that wakes up periodically to check subscribed resources.

    Attributes:
        _subscriptions: Dict mapping subscription_id to Subscription
        _uri_subscriptions: Dict mapping URI to set of subscription_ids
        _resource_states: Dict mapping URI to ResourceState
        _lock: Threading lock for synchronized access
        _poll_thread: Background polling thread
        _stop_event: Event to signal thread termination
        _default_poll_interval: Default polling interval in seconds
        _session_manager: Optional session manager for filesystem access
        _running: Whether the polling thread is running

    Example:
        >>> manager = ResourceSubscriptionManager()
        >>> sub_id = manager.subscribe("scratchpad://abc/file.txt", callback)
        >>> # ... later ...
        >>> manager.unsubscribe(sub_id)
        >>> manager.shutdown()
    """

    def __init__(
        self,
        default_poll_interval: float = 5.0,
        session_manager: SessionManagerProvider | None = None,
    ) -> None:
        """Initialize the subscription manager.

        Args:
            default_poll_interval: Default interval between polls in seconds
            session_manager: Optional session manager for filesystem access
        """
        self._subscriptions: dict[str, Subscription] = {}
        self._uri_subscriptions: dict[str, set[str]] = {}
        self._resource_states: dict[str, ResourceState] = {}
        self._lock = threading.RLock()
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._default_poll_interval = default_poll_interval
        self._session_manager = session_manager
        self._running = False

        logger.debug(
            f"ResourceSubscriptionManager initialized (poll_interval={default_poll_interval}s)"
        )

    def _ensure_polling(self) -> None:
        """Ensure the polling thread is running."""
        if not self._running:
            self._start_polling()

    def _start_polling(self) -> None:
        """Start the background polling thread."""
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._stop_event.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="ResourceSubscriptionPoller",
                daemon=True,
            )
            self._running = True
            self._poll_thread.start()
            logger.debug("Resource polling thread started")

    def _stop_polling(self) -> None:
        """Stop the background polling thread."""
        if self._running:
            self._running = False
            self._stop_event.set()
            if self._poll_thread and self._poll_thread.is_alive():
                self._poll_thread.join(timeout=2.0)
            logger.debug("Resource polling thread stopped")

    def _poll_loop(self) -> None:
        """Main polling loop running in background thread."""
        while self._running and not self._stop_event.is_set():
            try:
                self._check_all_resources()
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")

            # Wait for next poll or stop signal
            self._stop_event.wait(timeout=self._default_poll_interval)

    def _check_all_resources(self) -> None:
        """Check all subscribed resources for changes."""
        with self._lock:
            # Get copy of URIs to avoid modification during iteration
            uris = list(self._uri_subscriptions.keys())

        for uri in uris:
            self._check_resource(uri)

    def _check_resource(self, uri: str) -> None:
        """Check a single resource for changes.

        Args:
            uri: The resource URI to check
        """
        try:
            # Get current resource state
            current_state = self._get_resource_state(uri)

            if current_state is None:
                # Cannot access resource, skip
                return

            with self._lock:
                previous_state = self._resource_states.get(uri)

                if previous_state is None:
                    # First time checking this resource
                    self._resource_states[uri] = current_state
                    return

                # Check for changes
                if previous_state.has_changed(current_state):
                    # Resource changed - notify subscribers
                    self._resource_states[uri] = current_state
                    self._notify_subscribers(uri, current_state)

        except Exception as e:
            logger.warning(f"Error checking resource {uri}: {e}")

    def _get_resource_state(self, uri: str) -> ResourceState | None:
        """Get current state of a resource.

        Args:
            uri: The resource URI

        Returns:
            ResourceState if accessible, None otherwise
        """
        try:
            # Parse URI
            parsed = parse_scratchpad_uri(uri)
            if not parsed.is_valid or not parsed.session_id:
                return None

            # Get filesystem
            if self._session_manager is None:
                # Try to get global session manager
                try:
                    from ..server import get_session_manager

                    session_manager = get_session_manager()
                except ImportError:
                    session_manager = None
            else:
                session_manager = self._session_manager

            if session_manager is None:
                return None

            fs = session_manager.get_session_fs(parsed.session_id)
            if fs is None:
                return None

            # Get file path
            path = "/" + parsed.path

            # Check if file exists
            if not fs.exists(path) or fs.isdir(path):
                return None

            # Get file info
            info = fs.info(path)

            # Extract modification info
            mtime = info.get("mtime")
            size = info.get("size", 0)

            # Convert mtime to ISO format string
            mtime_str = None
            if mtime:
                try:
                    if isinstance(mtime, (int, float)):
                        mtime_str = datetime.fromtimestamp(mtime).isoformat()
                    else:
                        mtime_str = str(mtime)
                except Exception:
                    pass

            return ResourceState(uri=uri, mtime=mtime_str, size=size)

        except Exception as e:
            logger.debug(f"Failed to get resource state for {uri}: {e}")
            return None

    def _notify_subscribers(self, uri: str, state: ResourceState) -> None:
        """Notify all subscribers of a resource change.

        Args:
            uri: The resource URI that changed
            state: The new resource state
        """
        with self._lock:
            subscription_ids = self._uri_subscriptions.get(uri, set()).copy()

        for sub_id in subscription_ids:
            self._notify_subscriber(sub_id, uri, state)

    def _notify_subscriber(
        self, subscription_id: str, uri: str, state: ResourceState
    ) -> None:
        """Notify a single subscriber of a resource change.

        Args:
            subscription_id: The subscription ID
            uri: The resource URI
            state: The new resource state
        """
        with self._lock:
            subscription = self._subscriptions.get(subscription_id)

        if subscription is None or not subscription.is_active:
            return

        try:
            # Update subscription state
            subscription.last_modified = state.mtime
            subscription.last_size = state.size

            # Build notification data
            notification = {
                "uri": uri,
                "timestamp": datetime.now().isoformat(),
                "last_modified": state.mtime,
                "size": state.size,
                "subscription_id": subscription_id,
            }

            # Invoke callback
            subscription.callback(uri, notification)

        except Exception as e:
            logger.error(
                f"Error invoking callback for subscription {subscription_id}: {e}"
            )

    def subscribe(
        self,
        uri: str,
        callback: CallbackType,
        poll_interval: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Subscribe to a resource.

        Creates a new subscription for the given URI. The callback will be
        invoked whenever the resource is modified.

        Args:
            uri: The scratchpad:// URI to subscribe to
            callback: Function to call when resource changes
            poll_interval: Optional custom polling interval (seconds)
            metadata: Optional metadata dictionary

        Returns:
            subscription_id: Unique identifier for this subscription

        Raises:
            ValueError: If URI is invalid
            ResourceSubscriptionError: If subscription cannot be created

        Example:
            >>> def on_change(uri, data):
            ...     print(f"Changed: {uri}")
            ...     print(f"New size: {data['size']}")
            >>> sub_id = manager.subscribe("scratchpad://abc/file.txt", on_change)
        """
        # Validate URI
        parsed = parse_scratchpad_uri(uri)
        if not parsed.is_valid:
            raise ValueError(f"Invalid URI: {uri}")

        if not parsed.session_id:
            raise ValueError(f"URI missing session_id: {uri}")

        # Generate subscription ID
        subscription_id = str(uuid.uuid4())

        # Create subscription
        subscription = Subscription(
            subscription_id=subscription_id,
            uri=uri,
            callback=callback,
            poll_interval=poll_interval or self._default_poll_interval,
            metadata=metadata or {},
            is_active=True,
        )

        with self._lock:
            # Store subscription
            self._subscriptions[subscription_id] = subscription

            # Add to URI index
            if uri not in self._uri_subscriptions:
                self._uri_subscriptions[uri] = set()
            self._uri_subscriptions[uri].add(subscription_id)

        # Get initial resource state
        initial_state = self._get_resource_state(uri)
        if initial_state:
            subscription.last_modified = initial_state.mtime
            subscription.last_size = initial_state.size
            with self._lock:
                self._resource_states[uri] = initial_state

        # Ensure polling is running
        self._ensure_polling()

        logger.info(f"Created subscription {subscription_id} for {uri}")
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from a resource.

        Removes the subscription and stops monitoring the resource
        if no other subscriptions remain.

        Args:
            subscription_id: The subscription ID to remove

        Returns:
            True if subscription was found and removed, False otherwise

        Example:
            >>> manager.unsubscribe("abc-123-def")
            True
        """
        with self._lock:
            subscription = self._subscriptions.get(subscription_id)
            if subscription is None:
                return False

            # Mark as inactive
            subscription.is_active = False

            # Remove from subscriptions dict
            del self._subscriptions[subscription_id]

            # Remove from URI index
            uri = subscription.uri
            if uri in self._uri_subscriptions:
                self._uri_subscriptions[uri].discard(subscription_id)
                # Clean up empty sets
                if not self._uri_subscriptions[uri]:
                    del self._uri_subscriptions[uri]
                    # Also clean up resource state if no more subscribers
                    if uri in self._resource_states:
                        del self._resource_states[uri]

        # Stop polling if no more subscriptions
        if not self._subscriptions:
            self._stop_polling()

        logger.info(f"Removed subscription {subscription_id}")
        return True

    def get_subscription(self, subscription_id: str) -> Subscription | None:
        """Get subscription by ID.

        Args:
            subscription_id: The subscription ID

        Returns:
            Subscription if found, None otherwise
        """
        with self._lock:
            return self._subscriptions.get(subscription_id)

    def list_subscriptions(
        self,
        uri: str | None = None,
        active_only: bool = True,
    ) -> list[Subscription]:
        """List all subscriptions.

        Args:
            uri: Optional URI filter (returns only subscriptions for this URI)
            active_only: If True, return only active subscriptions

        Returns:
            List of subscriptions
        """
        with self._lock:
            if uri:
                subscription_ids = self._uri_subscriptions.get(uri, set())
                subscriptions = [
                    self._subscriptions[sid]
                    for sid in subscription_ids
                    if sid in self._subscriptions
                ]
            else:
                subscriptions = list(self._subscriptions.values())

            if active_only:
                subscriptions = [s for s in subscriptions if s.is_active]

            return subscriptions

    def cleanup_session_subscriptions(self, session_id: str) -> int:
        """Remove all subscriptions for a session.

        Called when a session expires to clean up associated subscriptions.

        Args:
            session_id: The session ID to clean up

        Returns:
            Number of subscriptions removed
        """
        with self._lock:
            # Find subscriptions for this session
            to_remove = []
            for sub_id, sub in self._subscriptions.items():
                parsed = parse_scratchpad_uri(sub.uri)
                if parsed.session_id == session_id:
                    to_remove.append(sub_id)

            # Remove each subscription
            count = 0
            for sub_id in to_remove:
                if self.unsubscribe(sub_id):
                    count += 1

            return count

    def shutdown(self) -> None:
        """Shutdown the subscription manager.

        Stops the polling thread and clears all subscriptions.
        """
        self._stop_polling()

        with self._lock:
            # Clear all subscriptions
            self._subscriptions.clear()
            self._uri_subscriptions.clear()
            self._resource_states.clear()

        logger.info("ResourceSubscriptionManager shut down")

    def is_resource_subscribed(self, uri: str) -> bool:
        """Check if a resource has active subscriptions.

        Args:
            uri: The resource URI

        Returns:
            True if there are active subscriptions for this URI
        """
        with self._lock:
            subscription_ids = self._uri_subscriptions.get(uri, set())
            return any(
                self._subscriptions.get(
                    sid, Subscription("", "", lambda u, d: None)
                ).is_active
                for sid in subscription_ids
            )

    def get_resource_subscription_info(self, uri: str) -> dict[str, Any]:
        """Get subscription information for a resource.

        Args:
            uri: The resource URI

        Returns:
            Dictionary with subscription info:
                - is_subscribed: Whether resource has subscriptions
                - subscription_count: Number of subscriptions
                - subscription_ids: List of subscription IDs
                - last_modified: Last known modification time
        """
        with self._lock:
            subscription_ids = list(self._uri_subscriptions.get(uri, set()))
            resource_state = self._resource_states.get(uri)

            return {
                "is_subscribed": bool(subscription_ids),
                "subscription_count": len(subscription_ids),
                "subscription_ids": subscription_ids,
                "last_modified": resource_state.mtime if resource_state else None,
            }


# Global subscription manager instance
_global_subscription_manager: ResourceSubscriptionManager | None = None


def get_subscription_manager() -> ResourceSubscriptionManager:
    """Get the global subscription manager instance.

    Creates the manager if it doesn't exist.

    Returns:
        ResourceSubscriptionManager instance
    """
    global _global_subscription_manager
    if _global_subscription_manager is None:
        _global_subscription_manager = ResourceSubscriptionManager()
    return _global_subscription_manager


def set_subscription_manager(manager: ResourceSubscriptionManager | None) -> None:
    """Set the global subscription manager instance.

    Used primarily for testing.

    Args:
        manager: The subscription manager to use, or None to clear
    """
    global _global_subscription_manager
    _global_subscription_manager = manager


class ResourceSubscriptionError(ScratchpadError):
    """Exception raised for resource subscription errors.

    Attributes:
        message: Error message
        subscription_id: Optional subscription ID related to the error
    """

    def __init__(
        self,
        message: str,
        subscription_id: str | None = None,
    ):
        super().__init__(message)
        self.subscription_id = subscription_id


def subscribe_to_resource(
    uri: str,
    callback: CallbackType,
    poll_interval: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Subscribe to a resource for change notifications.

    Creates a subscription that monitors the resource for changes.
    When changes are detected (based on mtime/size), the callback
    is invoked with the URI and change notification data.

    Args:
        uri: The scratchpad:// URI to subscribe to
        callback: Function to call when resource changes.
                 Signature: callback(uri: str, data: dict) -> None
        poll_interval: Optional custom polling interval in seconds (default: 5)
        metadata: Optional metadata dictionary for the subscription

    Returns:
        subscription_id: Unique identifier for this subscription

    Raises:
        ValueError: If URI is invalid
        ResourceSubscriptionError: If subscription cannot be created

    Example:
        >>> def on_file_change(uri, data):
        ...     print(f"File {uri} changed at {data['last_modified']}")
        ...     print(f"New size: {data['size']} bytes")
        ...
        >>> sub_id = subscribe_to_resource(
        ...     "scratchpad://abc-123/config.json",
        ...     on_file_change
        ... )
        >>> print(f"Subscribed with ID: {sub_id}")
    """
    manager = get_subscription_manager()
    return manager.subscribe(
        uri=uri,
        callback=callback,
        poll_interval=poll_interval,
        metadata=metadata,
    )


def unsubscribe_from_resource(subscription_id: str) -> bool:
    """Unsubscribe from a resource.

    Removes the subscription and stops monitoring the resource
    if no other subscriptions remain.

    Args:
        subscription_id: The subscription ID returned by subscribe_to_resource()

    Returns:
        True if subscription was found and removed, False otherwise

    Example:
        >>> sub_id = subscribe_to_resource(uri, callback)
        >>> # ... later ...
        >>> success = unsubscribe_from_resource(sub_id)
        >>> print(f"Unsubscribed: {success}")
    """
    manager = get_subscription_manager()
    return manager.unsubscribe(subscription_id)


def get_resource_subscription_info(uri: str) -> dict[str, Any]:
    """Get subscription information for a resource.

    Args:
        uri: The scratchpad:// URI

    Returns:
        Dictionary with subscription info:
            - is_subscribed: Whether resource has subscriptions
            - subscription_count: Number of subscriptions
            - subscription_ids: List of subscription IDs
            - last_modified: Last known modification time
    """
    manager = get_subscription_manager()
    return manager.get_resource_subscription_info(uri)


def is_resource_subscribed(uri: str) -> bool:
    """Check if a resource has active subscriptions.

    Args:
        uri: The scratchpad:// URI

    Returns:
        True if there are active subscriptions for this resource
    """
    manager = get_subscription_manager()
    return manager.is_resource_subscribed(uri)


def list_resource_subscriptions(
    uri: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """List all resource subscriptions.

    Args:
        uri: Optional URI filter
        active_only: If True, return only active subscriptions

    Returns:
        List of subscription dictionaries
    """
    manager = get_subscription_manager()
    subscriptions = manager.list_subscriptions(uri, active_only)
    return [sub.to_dict() for sub in subscriptions]


def cleanup_session_subscriptions(session_id: str) -> int:
    """Remove all subscriptions for a session.

    Typically called by the session manager when a session expires.

    Args:
        session_id: The session ID to clean up

    Returns:
        Number of subscriptions removed
    """
    manager = get_subscription_manager()
    return manager.cleanup_session_subscriptions(session_id)
