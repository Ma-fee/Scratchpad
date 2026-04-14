"""
FastMCP server main entry point with unified component integration.

Provides stdio and SSE transport support, integrating all security
components, audit logging, and resource management into a cohesive server.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import logging
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from .config import config
from .config.models import OverlayConfig
from .config.validation import is_config_valid, validate_config
from .exceptions import (
    ConfigurationError,
)
from .fs.session_manager import SessionFileSystemManager
from .resources import register_scratchpad_resources
from .security import (
    EventType,
    ResourceLifecycleTracker,
    create_secure_log_filter,
    get_default_tracker,
    mask_exception_message,
)
from .storage import FileSystemStore, set_store
from .tools.file_tools import register_file_tools
from .tools.health_tools import register_health_tools

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


# Global session manager for resource handlers
_session_manager: SessionFileSystemManager | None = None
_audit_tracker: ResourceLifecycleTracker | None = None
_shutdown_handlers: list[Callable[[], None]] = []
_is_shutting_down: threading.Event = threading.Event()


def _setup_logging() -> None:
    """Setup logging configuration with security filters."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    if config.log_format == "json":
        try:
            structlog = importlib.import_module("structlog")

            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.PositionalArgumentsFormatter(),
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.UnicodeDecoder(),
                    structlog.processors.JSONRenderer(),
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
        except ImportError:
            # Fallback to standard logging if structlog not available
            logging.basicConfig(
                level=getattr(logging, config.log_level), format=log_format
            )
    else:
        logging.basicConfig(level=getattr(logging, config.log_level), format=log_format)

    # Add secure log filter to root handler for all loggers
    root_logger = logging.getLogger()
    secure_filter = create_secure_log_filter()
    for handler in root_logger.handlers:
        handler.addFilter(secure_filter)


_setup_logging()
logger = logging.getLogger(__name__)


@dataclass
class ServerHealthStatus:
    """Server health status report.

    Attributes:
        healthy: Overall health status.
        components: Health status of individual components.
        message: Optional status message.
    """

    healthy: bool
    components: dict[str, dict[str, Any]]
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert status to dictionary."""
        return {
            "healthy": self.healthy,
            "message": self.message,
            "components": self.components,
        }


class ScratchpadServer:
    """Unified MCP Scratchpad server with integrated security and audit logging.

    This class encapsulates all server logic including:
    - SessionFileSystemManager integration
    - Security component wiring (path validation, session isolation, resource limits)
    - Audit logging lifecycle hooks
    - Error handling middleware
    - Health check endpoint
    - Graceful shutdown handling

    Example:
        >>> server = ScratchpadServer(base_dir=Path("/data"))
        >>> server.start(transport="stdio")
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        overlay_config: OverlayConfig | None = None,
        audit_tracker: ResourceLifecycleTracker | None = None,
    ) -> None:
        """Initialize the ScratchpadServer.

        Args:
            base_dir: Base directory for file storage (defaults to config.base_dir).
            overlay_config: Overlay configuration (creates empty config if None).
            audit_tracker: Audit lifecycle tracker (uses default if None).

        Raises:
            ConfigurationError: If configuration is invalid.
        """
        # Initialize logger early
        self._logger = logging.getLogger(f"{__name__}.ScratchpadServer")

        # Extract workspace directory from overlay config if available
        self._overlay_config = overlay_config or OverlayConfig(mounts=[])
        workspace_base_dir = self._extract_workspace_dir_from_config()
        self._base_dir = base_dir or workspace_base_dir or config.base_dir
        self._mcp: FastMCP | None = None
        self._session_manager: SessionFileSystemManager | None = None
        self._audit_tracker = audit_tracker or get_default_tracker()
        self._store: FileSystemStore | None = None
        self._health_status: ServerHealthStatus | None = None

        # Validate configuration
        if not is_config_valid(config):
            errors = validate_config(config)
            raise ConfigurationError(f"Invalid configuration: {', '.join(errors)}")

        self._setup_signal_handlers()

    def _extract_workspace_dir_from_config(self) -> Path | None:
        """Extract workspace directory from overlay config.

        Looks for a mount with name 'workspace' or mode 'rw' and
        extracts the source path from file:// URLs or plain paths.

        Returns:
            Path object if workspace found, None otherwise.
        """
        from pathlib import Path

        for mount in self._overlay_config.mounts:
            # Look for workspace mount (writable root mount)
            if (
                mount.name == "workspace"
                or mount.mount_point == "/"
                and mount.mode == "rw"
            ):
                source = mount.source
                if source.startswith("file://"):
                    # Extract path from file:// URL
                    path_str = source[7:]  # Remove file:// prefix
                else:
                    path_str = source

                # Resolve the path (handle both relative and absolute)
                path = Path(path_str)
                if not path.is_absolute():
                    # For relative paths, resolve from current working directory
                    path = path.resolve()

                self._logger.debug(f"Extracted workspace directory from config: {path}")
                return path

        return None

    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown signal handlers."""

        def _signal_handler(signum: int, frame: Any) -> None:
            """Handle shutdown signals."""
            sig_name = signal.Signals(signum).name
            self._logger.info(f"Received {sig_name}, initiating graceful shutdown...")
            self._is_shutting_down.set()
            self.shutdown()
            sys.exit(0)

        # Register handlers for SIGINT and SIGTERM
        with contextlib.suppress(ValueError):  # May not work on Windows
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)

    def _audit_event(
        self,
        session_id: str,
        resource_path: str,
        event_type: EventType,
        **details: Any,
    ) -> None:
        """Track an audit event through the lifecycle tracker.

        Args:
            session_id: Session identifier.
            resource_path: Resource path.
            event_type: Type of event.
            **details: Additional event details.
        """
        if self._audit_tracker:
            try:
                self._audit_tracker.track_event(
                    session_id=session_id,
                    resource_path=resource_path,
                    event_type=event_type,
                    **details,
                )
            except Exception as e:
                # Audit logging failures should not break operations
                self._logger.debug(f"Audit tracking failed: {e}")

    def _create_mcp_server(self) -> FastMCP:
        """Create and configure the FastMCP server with all components.

        Returns:
            Configured FastMCP instance.
        """
        self._logger.info(
            f"Creating FastMCP server with base directory: {self._base_dir}"
        )
        mcp = FastMCP("MCP Scratchpad")

        # Initialize storage
        self._store = FileSystemStore(base_dir=self._base_dir)
        set_store(self._store)
        self._logger.info("Storage initialized successfully")

        # Initialize session manager
        try:
            self._session_manager = SessionFileSystemManager(self._overlay_config)
            self._logger.info("SessionFileSystemManager initialized")
        except Exception as exc:
            self._logger.error(f"Failed to initialize SessionFileSystemManager: {exc}")
            raise ConfigurationError(
                f"Failed to initialize session manager: {exc}"
            ) from exc

        # Register resource handlers
        try:
            register_scratchpad_resources(mcp, self._session_manager)
            self._logger.info("MCP Resource handlers registered")
        except Exception as exc:
            self._logger.warning(f"Failed to initialize MCP Resources: {exc}")
            # Continue without resource support - tools still work

        # Register tools with audit logging wrapper
        try:
            self._register_tools_with_audit(mcp)
            register_health_tools(mcp)
            self._logger.info("Tools registered successfully")
        except Exception as exc:
            self._logger.error(f"Failed to register tools: {exc}")
            raise

        # Store reference for tools access
        global _current_server
        _current_server = self

        # Register custom health endpoint
        self._register_health_endpoint(mcp)

        self._logger.info("FastMCP server created successfully")
        self._mcp = mcp
        return mcp

    def _register_tools_with_audit(self, mcp: FastMCP) -> None:
        """Register tools with audit logging integration.

        Args:
            mcp: FastMCP instance.
        """
        # Register file tools first with session manager for overlay support
        register_file_tools(mcp, session_manager=self._session_manager)

        # We rely on individual tool implementations to call audit_event
        # This is a pattern for future extension

    def _register_health_endpoint(self, mcp: FastMCP) -> None:
        """Register custom health check endpoint.

        Args:
            mcp: FastMCP instance.
        """

        @mcp.tool()
        def health_status() -> dict[str, Any]:
            """Get server health status.

            Returns server and component health information.
            """
            return self._get_health_status().to_dict()

    def _get_health_status(self) -> ServerHealthStatus:
        """Get current server health status.

        Returns:
            ServerHealthStatus with component health information.
        """
        components: dict[str, dict[str, Any]] = {
            "storage": {"healthy": self._store is not None},
            "session_manager": {
                "healthy": self._session_manager is not None,
                "active_sessions": (
                    len(self._session_manager.list_sessions())
                    if self._session_manager
                    else 0
                ),
            },
            "audit_tracker": {"healthy": self._audit_tracker is not None},
            "config": {
                "healthy": is_config_valid(config),
                "base_dir": str(self._base_dir),
            },
        }

        healthy = all(c.get("healthy", False) for c in components.values())
        message = "All components healthy" if healthy else "Some components unhealthy"

        return ServerHealthStatus(
            healthy=healthy, components=components, message=message
        )

    @property
    def _is_shutting_down(self) -> threading.Event:
        """Get the shutdown event."""
        return _is_shutting_down

    @property
    def session_manager(self) -> SessionFileSystemManager | None:
        """Get the session manager instance."""
        return self._session_manager

    @property
    def audit_tracker(self) -> ResourceLifecycleTracker | None:
        """Get the audit tracker instance."""
        return self._audit_tracker

    def create_session(
        self,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Create a new session.

        Args:
            metadata: Optional session metadata.
            ttl_seconds: Optional TTL in seconds.

        Returns:
            New session ID.

        Raises:
            RuntimeError: If session manager not initialized.
        """
        if not self._session_manager:
            raise RuntimeError("Session manager not initialized")

        from datetime import timedelta

        ttl = timedelta(seconds=ttl_seconds) if ttl_seconds else None
        session_id = self._session_manager.create_session(metadata=metadata, ttl=ttl)

        self._audit_event(
            session_id=session_id,
            resource_path="/",
            event_type=EventType.CREATE,
            message="Session created",
        )

        self._logger.info(f"Session created: {session_id}")
        return session_id

    def get_session_fs(self, session_id: str) -> AbstractFileSystem | None:
        """Get filesystem for a session.

        Args:
            session_id: Session ID.

        Returns:
            Filesystem instance or None if not found.
        """
        if not self._session_manager:
            return None
        return self._session_manager.get_session_fs(session_id)

    def cleanup_session(self, session_id: str) -> bool:
        """Clean up a session and its resources.

        Args:
            session_id: Session ID to clean up.

        Returns:
            True if session was found and cleaned up.
        """
        if not self._session_manager:
            return False

        # Clean up audit data first
        if self._audit_tracker:
            removed = self._audit_tracker.cleanup_session(session_id)
            self._logger.debug(f"Cleaned up {removed} audit events for {session_id}")

        result = self._session_manager.cleanup_session(session_id)
        if result:
            self._logger.info(f"Session cleaned up: {session_id}")
        return result

    def shutdown(self) -> None:
        """Perform graceful shutdown.

        Cleans up all sessions and resources.
        """
        self._is_shutting_down.set()
        self._logger.info("Shutting down ScratchpadServer...")

        # Clean up all sessions
        if self._session_manager:
            try:
                sessions = self._session_manager.list_sessions()
                for meta in sessions:
                    self.cleanup_session(meta.session_id)
                self._logger.info(f"Cleaned up {len(sessions)} sessions")
            except Exception as e:
                self._logger.warning(f"Error during session cleanup: {e}")

        # Reset audit tracker
        if self._audit_tracker:
            try:
                self._audit_tracker.clear_all()
                self._logger.info("Audit tracker cleared")
            except Exception as e:
                self._logger.warning(f"Error clearing audit tracker: {e}")

        self._logger.info("Shutdown complete")

    def start(
        self,
        transport: str = "stdio",
        host: str | None = None,
        port: int | None = None,
        path: str | None = None,
    ) -> None:
        """Start the MCP server.

        Args:
            transport: Transport type ('stdio', 'sse', 'http', 'streamable-http').
            host: Host address for HTTP/SSE mode.
            port: Port for HTTP/SSE mode.
            path: URL path for HTTP transport (default: /mcp).

        Raises:
            ConfigurationError: If server cannot be started.
        """
        mcp = self._create_mcp_server()

        self._logger.info("Starting MCP Scratchpad server")
        self._logger.info(f"Transport: {transport}")
        self._logger.info(f"Base directory: {self._base_dir}")
        self._logger.info(f"Log level: {config.log_level}")

        try:
            if transport == "stdio":
                self._logger.info("Starting server in stdio mode")
                mcp.run()
            elif transport in ("sse", "http", "streamable-http"):
                host = host or config.host
                port = port or config.port
                path = path or "/mcp"

                # Map 'http' to 'streamable-http' for MCP 2025-03-26 spec
                fastmcp_transport = (
                    "streamable-http" if transport == "http" else transport
                )

                self._logger.info(
                    f"Starting server in {transport} mode on {host}:{port}{path}"
                )
                mcp.run(
                    transport=fastmcp_transport,  # type: ignore[arg-type]
                    host=host,
                    port=port,
                    path=path,
                )
            else:
                raise ConfigurationError(f"Unknown transport: {transport}")
        except ConfigurationError:
            raise
        except Exception as exc:
            self._logger.exception(f"Server runtime error: {exc}")
            raise ConfigurationError(f"Server runtime error: {exc}") from exc


def create_server(base_dir: Path | None = None) -> FastMCP:
    """Create FastMCP server instance.

    Legacy function for backward compatibility.
    For new code, use ScratchpadServer class directly.

    Args:
        base_dir: Base directory for file storage.

    Returns:
        Configured FastMCP instance.
    """
    server = ScratchpadServer(base_dir=base_dir)
    # Initialize the MCP server
    mcp = server._create_mcp_server()

    # Store server instance for access via get_server()
    global _current_server
    _current_server = server

    return mcp


# Global server instance reference for backward compatibility
_current_server: ScratchpadServer | None = None


def get_server() -> ScratchpadServer | None:
    """Get the current server instance.

    Returns:
        Current ScratchpadServer instance or None if not created.
    """
    return _current_server


def get_session_manager() -> SessionFileSystemManager | None:
    """Get the global session manager instance.

    Returns:
        SessionFileSystemManager instance or None if not initialized.
    """
    server = get_server()
    if server:
        return server.session_manager
    # Fallback for legacy compatibility
    return _session_manager


def get_audit_tracker() -> ResourceLifecycleTracker | None:
    """Get the global audit tracker instance.

    Returns:
        ResourceLifecycleTracker instance or None if not initialized.
    """
    server = get_server()
    if server:
        return server.audit_tracker
    return _audit_tracker


def main() -> None:
    """Main entry function with command line argument support."""
    parser = argparse.ArgumentParser(description="MCP Scratchpad FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http", "streamable-http"],
        default=config.transport,
        help="Transport method (stdio, sse, http, streamable-http)",
    )
    parser.add_argument("--host", default=config.host, help="Host address for HTTP/SSE")
    parser.add_argument(
        "--port", type=int, default=config.port, help="Port for HTTP/SSE"
    )
    parser.add_argument(
        "--base-dir", type=str, default=None, help="File storage base directory"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        help="Path to configuration file (YAML). Searches standard locations if not specified.",
    )
    parser.add_argument(
        "--path",
        type=str,
        default="/mcp",
        help="URL path for HTTP transport (default: /mcp)",
    )

    args = parser.parse_args()

    # Load overlay config if specified or from standard locations
    from mcp_scratchpad.config.loader import load_overlay_config

    overlay_config = load_overlay_config(args.config)

    # Override config with command line arguments
    if args.base_dir:
        config.base_dir = Path(args.base_dir).resolve()

    try:
        # Create and start server using new ScratchpadServer class
        # Note: only pass base_dir if explicitly provided via --base-dir
        # otherwise let the server extract it from overlay_config
        server = ScratchpadServer(
            base_dir=config.base_dir if args.base_dir else None,
            overlay_config=overlay_config,
        )
        server.start(
            transport=args.transport,
            host=args.host,
            port=args.port,
            path=args.path,
        )
    except ConfigurationError as exc:
        logger.error(f"Configuration error: {exc}")
        sys.exit(1)
    except Exception as exc:
        # Mask any credentials in error messages
        safe_message = mask_exception_message(exc)
        logger.exception(f"Failed to start server: {safe_message}")
        sys.exit(1)


def main_sse() -> None:
    """Main entry function for SSE mode with default parameters."""
    # Set default arguments for SSE mode
    sys.argv = [
        sys.argv[0],  # script name
        "--transport",
        "sse",
        "--host",
        "0.0.0.0",
        "--port",
        "8892",
    ]
    main()


if __name__ == "__main__":
    # main_sse()
    main()
