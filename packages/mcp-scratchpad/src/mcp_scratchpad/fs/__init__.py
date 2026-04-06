"""
Filesystem module for overlay filesystem support.

This module provides the SessionFileSystemManager for managing
per-session overlay filesystem instances using fsspec.
"""

from .overlay import (
    MemoryPressureConfig,
    MemoryPressureError,
    MemoryStats,
    OverlayFileSystem,
)
from .resource_limits import (
    ResourceLimitEnforcer,
    ResourceLimits,
    create_default_enforcer,
    create_unlimited_enforcer,
)
from .session_manager import OverlayFileSystemProtocol, SessionFileSystemManager
from .unified_adapter import UnifiedReadResult, UnifiedSessionFSAdapter

__all__ = [
    "SessionFileSystemManager",
    "OverlayFileSystemProtocol",
    "UnifiedSessionFSAdapter",
    "UnifiedReadResult",
    "OverlayFileSystem",
    "MemoryPressureConfig",
    "MemoryPressureError",
    "MemoryStats",
    "ResourceLimits",
    "ResourceLimitEnforcer",
    "create_default_enforcer",
    "create_unlimited_enforcer",
]
