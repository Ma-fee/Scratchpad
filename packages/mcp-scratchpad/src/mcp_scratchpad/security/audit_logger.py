"""Audit logging and resource lifecycle management for OverlayFileSystem.

This module provides comprehensive audit logging for all resource operations
with lifecycle tracking and automatic cleanup on session expiry.

Features:
- Thread-safe event tracking
- Per-resource and per-session event storage with size limits
- Lifecycle summary generation
- Automatic cleanup on session expiry
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class EventType(Enum):
    """Resource operation event types for audit logging.

    每种操作类型对应一个文件系统操作，用于完整的生命周期追踪。
    """

    CREATE = auto()  # 创建新文件
    READ = auto()  # 读取文件内容
    WRITE = auto()  # 写入/修改文件
    DELETE = auto()  # 删除文件
    COPY = auto()  # 复制文件
    RENAME = auto()  # 重命名文件
    MKDIR = auto()  # 创建目录
    RMDIR = auto()  # 删除目录


@dataclass
class AuditEvent:
    """单个审计事件记录。

    Attributes:
        session_id: Session 标识符
        resource_path: 资源路径
        event_type: 事件类型 (EventType)
        timestamp: 事件发生时间
        details: 额外详情字典
    """

    session_id: str
    resource_path: str
    event_type: EventType
    timestamp: datetime
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """将事件转换为字典格式"""
        return {
            "session_id": self.session_id,
            "resource_path": self.resource_path,
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class ResourceLifecycleTracker:
    """Resource lifecycle tracker with audit logging.

    提供线程安全的资源操作审计追踪，支持：
    - 事件记录（带大小限制）
    - 生命周期摘要生成
    - Session 级事件查询
    - Session 过期自动清理

    Attributes:
        max_events_per_resource: 每个资源的最大事件数（默认 1000）
        max_events_per_session: 每个 session 的最大事件数（默认 10000）
    """

    def __init__(
        self,
        max_events_per_resource: int = 1000,
        max_events_per_session: int = 10000,
    ) -> None:
        """初始化生命周期追踪器。

        Args:
            max_events_per_resource: 每个资源的最大事件数
            max_events_per_session: 每个 session 的最大事件数
        """
        self.max_events_per_resource = max_events_per_resource
        self.max_events_per_session = max_events_per_session

        # 资源路径 -> 事件列表（带大小限制的 deque）
        self._resource_events: dict[str, deque[AuditEvent]] = defaultdict(
            lambda: deque(maxlen=max_events_per_resource)
        )

        # session_id -> 事件列表（带大小限制的 deque）
        self._session_events: dict[str, deque[AuditEvent]] = defaultdict(
            lambda: deque(maxlen=max_events_per_session)
        )

        # 资源路径 -> 访问该资源的 sessions 集合
        self._resource_sessions: dict[str, set[str]] = defaultdict(set)

        # 线程锁，保证线程安全
        self._lock = threading.RLock()

    def track_event(
        self,
        session_id: str,
        resource_path: str,
        event_type: EventType,
        **details: Any,
    ) -> AuditEvent:
        """记录一个资源操作事件。

        这是主要的审计入口点，所有资源操作都应该通过此方法记录。

        Args:
            session_id: Session 标识符
            resource_path: 资源路径
            event_type: 事件类型
            **details: 额外的事件详情（如文件大小、操作结果等）

        Returns:
            创建的 AuditEvent 对象

        Example:
            >>> tracker = ResourceLifecycleTracker()
            >>> event = tracker.track_event(
            ...     session_id="user_123",
            ...     resource_path="/workspace/file.txt",
            ...     event_type=EventType.WRITE,
            ...     size=1024,
            ...     success=True,
            ... )
        """
        with self._lock:
            event = AuditEvent(
                session_id=session_id,
                resource_path=resource_path,
                event_type=event_type,
                timestamp=datetime.now(),
                details=details,
            )

            # 添加到资源事件列表
            self._resource_events[resource_path].append(event)

            # 添加到 session 事件列表
            self._session_events[session_id].append(event)

            # 记录资源被哪些 sessions 访问过
            self._resource_sessions[resource_path].add(session_id)

            return event

    def get_lifecycle_summary(self, resource_path: str) -> dict[str, Any]:
        """获取资源的生命周期摘要。

        Args:
            resource_path: 资源路径

        Returns:
            生命周期摘要字典，包含：
            - first_access: 首次访问时间
            - last_access: 最后访问时间
            - total_events: 总事件数
            - event_counts: 每种事件类型的计数
            - accessing_sessions: 访问该资源的 sessions 列表

        Example:
            >>> summary = tracker.get_lifecycle_summary("/workspace/file.txt")
            >>> print(f"Total events: {summary['total_events']}")
            >>> print(f"Created at: {summary['first_access']}")
        """
        with self._lock:
            events = self._resource_events.get(resource_path, deque())

            if not events:
                return {
                    "first_access": None,
                    "last_access": None,
                    "total_events": 0,
                    "event_counts": {},
                    "accessing_sessions": [],
                }

            # 统计事件类型
            event_counts: dict[str, int] = defaultdict(int)
            for event in events:
                event_counts[event.event_type.name] += 1

            # 获取 sessions
            sessions = list(self._resource_sessions.get(resource_path, set()))

            return {
                "first_access": events[0].timestamp.isoformat() if events else None,
                "last_access": events[-1].timestamp.isoformat() if events else None,
                "total_events": len(events),
                "event_counts": dict(event_counts),
                "accessing_sessions": sessions,
            }

    def get_session_events(
        self,
        session_id: str,
        event_type: EventType | None = None,
    ) -> list[AuditEvent]:
        """获取指定 session 的所有事件。

        Args:
            session_id: Session 标识符
            event_type: 可选的事件类型过滤器

        Returns:
            事件列表（最新的在前）

        Example:
            >>> events = tracker.get_session_events("user_123")
            >>> write_events = tracker.get_session_events("user_123", EventType.WRITE)
        """
        with self._lock:
            events = self._session_events.get(session_id, deque())

            if event_type is not None:
                return [e for e in events if e.event_type == event_type]

            return list(events)

    def get_session_event_count(
        self,
        session_id: str,
        event_type: EventType | None = None,
    ) -> int:
        """获取指定 session 的事件数量。

        Args:
            session_id: Session 标识符
            event_type: 可选的事件类型过滤器

        Returns:
            事件数量
        """
        return len(self.get_session_events(session_id, event_type))

    def cleanup_session(self, session_id: str) -> int:
        """清理指定 session 的所有事件记录。

        当 session 过期时调用此方法清除该 session 的所有审计记录。

        Args:
            session_id: 要清理的 session ID

        Returns:
            清理的事件数量

        Example:
            >>> removed_count = tracker.cleanup_session("user_123")
            >>> print(f"Removed {removed_count} events")
        """
        with self._lock:
            # 获取该 session 的所有事件
            session_events = self._session_events.get(session_id, deque())
            removed_count = len(session_events)

            # 从资源事件列表中移除
            for event in list(session_events):
                resource_path = event.resource_path
                if resource_path in self._resource_events:
                    # 从 deque 中移除特定事件（创建新 deque 更高效）
                    new_deque = deque(
                        [
                            e
                            for e in self._resource_events[resource_path]
                            if e.session_id != session_id
                        ],
                        maxlen=self.max_events_per_resource,
                    )
                    if new_deque:
                        self._resource_events[resource_path] = new_deque
                    else:
                        del self._resource_events[resource_path]

                # 从资源 session 集合中移除
                if resource_path in self._resource_sessions:
                    self._resource_sessions[resource_path].discard(session_id)
                    if not self._resource_sessions[resource_path]:
                        del self._resource_sessions[resource_path]

            # 删除 session 事件列表
            if session_id in self._session_events:
                del self._session_events[session_id]

            return removed_count

    def get_all_tracked_resources(self) -> list[str]:
        """获取所有被追踪的资源路径。

        Returns:
            资源路径列表
        """
        with self._lock:
            return list(self._resource_events.keys())

    def get_all_active_sessions(self) -> list[str]:
        """获取所有活动的 session ID。

        Returns:
            Session ID 列表
        """
        with self._lock:
            return list(self._session_events.keys())

    def get_global_stats(self) -> dict[str, Any]:
        """获取全局统计信息。

        Returns:
            全局统计字典，包含：
            - total_resources: 追踪的资源总数
            - total_sessions: 活动的 session 总数
            - total_events: 总事件数
            - events_per_type: 每种事件类型的计数
        """
        with self._lock:
            total_events = sum(len(events) for events in self._session_events.values())

            # 统计每种事件类型
            events_per_type: dict[str, int] = defaultdict(int)
            for events in self._resource_events.values():
                for event in events:
                    events_per_type[event.event_type.name] += 1

            return {
                "total_resources": len(self._resource_events),
                "total_sessions": len(self._session_events),
                "total_events": total_events,
                "events_per_type": dict(events_per_type),
                "max_events_per_resource": self.max_events_per_resource,
                "max_events_per_session": self.max_events_per_session,
            }

    def clear_all(self) -> None:
        """清除所有追踪数据（用于测试）。

        WARNING: 这会删除所有审计记录！
        """
        with self._lock:
            self._resource_events.clear()
            self._session_events.clear()
            self._resource_sessions.clear()


# =============================================================================
# Helper Functions for Common Use Cases
# =============================================================================


def create_lifecycle_tracker(
    max_events_per_resource: int = 1000,
    max_events_per_session: int = 10000,
) -> ResourceLifecycleTracker:
    """创建生命周期追踪器的工厂函数。

    Args:
        max_events_per_resource: 每个资源的最大事件数
        max_events_per_session: 每个 session 的最大事件数

    Returns:
        ResourceLifecycleTracker 实例
    """
    return ResourceLifecycleTracker(
        max_events_per_resource=max_events_per_resource,
        max_events_per_session=max_events_per_session,
    )


# 全局默认追踪器实例（可选使用）
_default_tracker: ResourceLifecycleTracker | None = None
_default_tracker_lock = threading.Lock()


def get_default_tracker() -> ResourceLifecycleTracker:
    """获取或创建默认的全局追踪器实例。

    Returns:
        ResourceLifecycleTracker 实例
    """
    global _default_tracker

    with _default_tracker_lock:
        if _default_tracker is None:
            _default_tracker = ResourceLifecycleTracker()
        return _default_tracker


def reset_default_tracker() -> None:
    """重置默认追踪器（主要用于测试）。"""
    global _default_tracker

    with _default_tracker_lock:
        if _default_tracker is not None:
            _default_tracker.clear_all()
            _default_tracker = None
