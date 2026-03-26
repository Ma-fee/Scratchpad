"""Comprehensive audit logging and lifecycle management tests.

This test suite validates the ResourceLifecycleTracker class including:
- Event tracking for all operation types
- Thread safety
- Size limits enforcement
- Lifecycle summary generation
- Session cleanup on expiry
- Global statistics
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from mcp_scratchpad.security.audit_logger import (
    AuditEvent,
    EventType,
    ResourceLifecycleTracker,
    create_lifecycle_tracker,
    get_default_tracker,
    reset_default_tracker,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# EventType Tests
# =============================================================================


class TestEventType:
    """Test EventType enum."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_event_type_values(self):
        """EventType 应该包含所有必需的操作类型"""
        assert EventType.CREATE
        assert EventType.READ
        assert EventType.WRITE
        assert EventType.DELETE
        assert EventType.COPY
        assert EventType.RENAME
        assert EventType.MKDIR
        assert EventType.RMDIR

    @pytest.mark.security
    @pytest.mark.unit
    def test_event_type_name(self):
        """EventType 应该能获取名称"""
        assert EventType.CREATE.name == "CREATE"
        assert EventType.WRITE.name == "WRITE"
        assert EventType.READ.name == "READ"


# =============================================================================
# Basic Event Tracking Tests
# =============================================================================


class TestEventTracking:
    """Test basic event tracking functionality."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_track_single_event(self):
        """应该能追踪单个事件"""
        tracker = ResourceLifecycleTracker()
        event = tracker.track_event(
            session_id="session_1",
            resource_path="/workspace/file.txt",
            event_type=EventType.CREATE,
            size=1024,
        )

        assert event.session_id == "session_1"
        assert event.resource_path == "/workspace/file.txt"
        assert event.event_type == EventType.CREATE
        assert event.details["size"] == 1024
        assert isinstance(event.timestamp, datetime)

    @pytest.mark.security
    @pytest.mark.unit
    def test_track_multiple_events(self):
        """应该能追踪多个事件"""
        tracker = ResourceLifecycleTracker()

        # 创建文件
        tracker.track_event(
            session_id="session_1",
            resource_path="/workspace/file.txt",
            event_type=EventType.CREATE,
        )

        # 写入文件
        tracker.track_event(
            session_id="session_1",
            resource_path="/workspace/file.txt",
            event_type=EventType.WRITE,
            size=2048,
        )

        # 读取文件
        tracker.track_event(
            session_id="session_1",
            resource_path="/workspace/file.txt",
            event_type=EventType.READ,
        )

        summary = tracker.get_lifecycle_summary("/workspace/file.txt")
        assert summary["total_events"] == 3

    @pytest.mark.security
    @pytest.mark.unit
    def test_track_all_event_types(self):
        """应该能追踪所有事件类型"""
        tracker = ResourceLifecycleTracker()
        path = "/workspace/test.txt"

        for event_type in EventType:
            tracker.track_event(
                session_id="session_1",
                resource_path=path,
                event_type=event_type,
            )

        summary = tracker.get_lifecycle_summary(path)
        assert summary["total_events"] == len(EventType)

        # 验证每种类型都被记录
        for event_type in EventType:
            assert summary["event_counts"][event_type.name] == 1


# =============================================================================
# Lifecycle Summary Tests
# =============================================================================


class TestLifecycleSummary:
    """Test lifecycle summary generation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_lifecycle_summary_for_new_resource(self):
        """新资源的生命周期摘要应该为空"""
        tracker = ResourceLifecycleTracker()
        summary = tracker.get_lifecycle_summary("/workspace/nonexistent.txt")

        assert summary["first_access"] is None
        assert summary["last_access"] is None
        assert summary["total_events"] == 0
        assert summary["event_counts"] == {}
        assert summary["accessing_sessions"] == []

    @pytest.mark.security
    @pytest.mark.unit
    def test_lifecycle_summary_with_events(self):
        """有事件的资源应该返回正确的摘要"""
        tracker = ResourceLifecycleTracker()

        # 创建事件
        event1 = tracker.track_event(
            session_id="session_1",
            resource_path="/workspace/file.txt",
            event_type=EventType.CREATE,
        )
        time.sleep(0.01)  # 确保有时间差

        event2 = tracker.track_event(
            session_id="session_1",
            resource_path="/workspace/file.txt",
            event_type=EventType.WRITE,
        )

        summary = tracker.get_lifecycle_summary("/workspace/file.txt")

        assert summary["total_events"] == 2
        assert summary["event_counts"]["CREATE"] == 1
        assert summary["event_counts"]["WRITE"] == 1
        assert summary["first_access"] == event1.timestamp.isoformat()
        assert summary["last_access"] == event2.timestamp.isoformat()
        assert "session_1" in summary["accessing_sessions"]

    @pytest.mark.security
    @pytest.mark.unit
    def test_multiple_sessions_accessing_same_resource(self):
        """多个 session 访问同一资源应该被记录"""
        tracker = ResourceLifecycleTracker()
        path = "/workspace/shared.txt"

        tracker.track_event("session_1", path, EventType.CREATE)
        tracker.track_event("session_2", path, EventType.READ)
        tracker.track_event("session_3", path, EventType.WRITE)

        summary = tracker.get_lifecycle_summary(path)
        assert len(summary["accessing_sessions"]) == 3
        assert "session_1" in summary["accessing_sessions"]
        assert "session_2" in summary["accessing_sessions"]
        assert "session_3" in summary["accessing_sessions"]


# =============================================================================
# Session Event Tests
# =============================================================================


class TestSessionEvents:
    """Test session-level event queries."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_session_events(self):
        """应该能获取 session 的所有事件"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file1.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file2.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file1.txt", EventType.WRITE)

        events = tracker.get_session_events("session_1")
        assert len(events) == 3

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_session_events_filtered_by_type(self):
        """应该能按事件类型过滤 session 事件"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file1.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file1.txt", EventType.WRITE)
        tracker.track_event("session_1", "/file1.txt", EventType.READ)
        tracker.track_event("session_1", "/file1.txt", EventType.WRITE)

        create_events = tracker.get_session_events("session_1", EventType.CREATE)
        assert len(create_events) == 1

        write_events = tracker.get_session_events("session_1", EventType.WRITE)
        assert len(write_events) == 2

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_session_event_count(self):
        """应该能获取 session 的事件计数"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file.txt", EventType.WRITE)

        assert tracker.get_session_event_count("session_1") == 2
        assert tracker.get_session_event_count("session_1", EventType.WRITE) == 1


# =============================================================================
# Session Cleanup Tests
# =============================================================================


class TestSessionCleanup:
    """Test session expiry cleanup."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_cleanup_session_removes_events(self):
        """清理 session 应该移除所有相关事件"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file1.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file2.txt", EventType.WRITE)
        tracker.track_event("session_2", "/file1.txt", EventType.READ)

        removed = tracker.cleanup_session("session_1")
        assert removed == 2

        # session_1 的事件应该被移除
        assert len(tracker.get_session_events("session_1")) == 0

        # session_2 的事件应该保留
        assert len(tracker.get_session_events("session_2")) == 1

    @pytest.mark.security
    @pytest.mark.unit
    def test_cleanup_session_updates_resource_tracking(self):
        """清理 session 应该更新资源追踪"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/shared.txt", EventType.CREATE)
        tracker.track_event("session_2", "/shared.txt", EventType.READ)

        # 清理前两个 session 都记录
        summary_before = tracker.get_lifecycle_summary("/shared.txt")
        assert len(summary_before["accessing_sessions"]) == 2

        tracker.cleanup_session("session_1")

        # 清理后只有 session_2
        summary_after = tracker.get_lifecycle_summary("/shared.txt")
        assert len(summary_after["accessing_sessions"]) == 1
        assert "session_2" in summary_after["accessing_sessions"]

    @pytest.mark.security
    @pytest.mark.unit
    def test_cleanup_nonexistent_session(self):
        """清理不存在的 session 应该返回 0"""
        tracker = ResourceLifecycleTracker()
        removed = tracker.cleanup_session("nonexistent")
        assert removed == 0


# =============================================================================
# Size Limit Tests
# =============================================================================


class TestSizeLimits:
    """Test event storage size limits."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_resource_event_limit_enforced(self):
        """每个资源的事件数应该受限制"""
        tracker = ResourceLifecycleTracker(max_events_per_resource=3)

        # 添加超过限制的事件
        for i in range(5):
            tracker.track_event("session_1", "/file.txt", EventType.WRITE, index=i)

        summary = tracker.get_lifecycle_summary("/file.txt")
        assert summary["total_events"] == 3  # 只保留最新的 3 个

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_event_limit_enforced(self):
        """每个 session 的事件数应该受限制"""
        tracker = ResourceLifecycleTracker(max_events_per_session=3)

        # 添加超过限制的事件
        for i in range(5):
            tracker.track_event("session_1", f"/file{i}.txt", EventType.CREATE)

        events = tracker.get_session_events("session_1")
        assert len(events) == 3  # 只保留最新的 3 个


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Test thread safety."""

    @pytest.mark.security
    @pytest.mark.slow
    def test_concurrent_event_tracking(self):
        """并发事件追踪应该线程安全"""
        tracker = ResourceLifecycleTracker()
        errors = []
        threads = []

        def track_events(session_id: str, count: int):
            try:
                for i in range(count):
                    tracker.track_event(
                        session_id,
                        f"/file{i % 10}.txt",
                        EventType.WRITE if i % 2 == 0 else EventType.READ,
                        index=i,
                    )
            except Exception as e:
                errors.append(e)

        # 创建多个线程并发追踪事件
        for i in range(5):
            thread = threading.Thread(target=track_events, args=(f"session_{i}", 100))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # 验证事件都被正确记录
        total_events = sum(
            len(tracker.get_session_events(f"session_{i}")) for i in range(5)
        )
        assert total_events == 500

    @pytest.mark.security
    @pytest.mark.slow
    def test_concurrent_read_and_write(self):
        """并发读写应该线程安全"""
        tracker = ResourceLifecycleTracker()
        errors = []
        threads = []

        # 写入线程
        def writer():
            try:
                for i in range(50):
                    tracker.track_event("session_1", "/file.txt", EventType.WRITE)
            except Exception as e:
                errors.append(e)

        # 读取线程
        def reader():
            try:
                for _ in range(50):
                    tracker.get_lifecycle_summary("/file.txt")
                    tracker.get_session_events("session_1")
            except Exception as e:
                errors.append(e)

        threads.append(threading.Thread(target=writer))
        threads.append(threading.Thread(target=reader))

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"


# =============================================================================
# Global Statistics Tests
# =============================================================================


class TestGlobalStatistics:
    """Test global statistics generation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_global_stats_empty(self):
        """空追踪器应该返回零统计"""
        tracker = ResourceLifecycleTracker()
        stats = tracker.get_global_stats()

        assert stats["total_resources"] == 0
        assert stats["total_sessions"] == 0
        assert stats["total_events"] == 0
        assert stats["events_per_type"] == {}

    @pytest.mark.security
    @pytest.mark.unit
    def test_global_stats_with_events(self):
        """有事件的追踪器应该返回正确统计"""
        tracker = ResourceLifecycleTracker()

        # 多个资源的多个事件
        tracker.track_event("session_1", "/file1.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file1.txt", EventType.WRITE)
        tracker.track_event("session_1", "/file2.txt", EventType.CREATE)
        tracker.track_event("session_2", "/file1.txt", EventType.READ)

        stats = tracker.get_global_stats()

        assert stats["total_resources"] == 2  # file1.txt, file2.txt
        assert stats["total_sessions"] == 2  # session_1, session_2
        assert stats["total_events"] == 4
        assert stats["events_per_type"]["CREATE"] == 2
        assert stats["events_per_type"]["WRITE"] == 1
        assert stats["events_per_type"]["READ"] == 1


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Test helper and factory functions."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_create_lifecycle_tracker(self):
        """工厂函数应该能创建配置好的 tracker"""
        tracker = create_lifecycle_tracker(
            max_events_per_resource=100,
            max_events_per_session=1000,
        )

        assert tracker.max_events_per_resource == 100
        assert tracker.max_events_per_session == 1000

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_default_tracker(self):
        """应该能获取默认 tracker 实例"""
        reset_default_tracker()  # 确保干净状态

        tracker1 = get_default_tracker()
        tracker2 = get_default_tracker()

        # 应该是同一个实例
        assert tracker1 is tracker2

    @pytest.mark.security
    @pytest.mark.unit
    def test_reset_default_tracker(self):
        """重置应该清除默认 tracker"""
        tracker1 = get_default_tracker()
        tracker1.track_event("session_1", "/file.txt", EventType.CREATE)

        reset_default_tracker()

        tracker2 = get_default_tracker()
        # 重置后应该是新实例
        assert tracker1 is not tracker2
        # 新实例应该为空
        assert tracker2.get_global_stats()["total_events"] == 0


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_audit_event_to_dict(self):
        """AuditEvent 应该能转换为字典"""
        event = AuditEvent(
            session_id="session_1",
            resource_path="/file.txt",
            event_type=EventType.WRITE,
            timestamp=datetime.now(),
            details={"size": 1024, "success": True},
        )

        d = event.to_dict()
        assert d["session_id"] == "session_1"
        assert d["resource_path"] == "/file.txt"
        assert d["event_type"] == "WRITE"
        assert "timestamp" in d
        assert d["details"]["size"] == 1024

    @pytest.mark.security
    @pytest.mark.unit
    def test_track_event_with_no_details(self):
        """追踪没有详情的事件应该正常工作"""
        tracker = ResourceLifecycleTracker()
        event = tracker.track_event(
            "session_1",
            "/file.txt",
            EventType.READ,
        )

        assert event.details == {}

    @pytest.mark.security
    @pytest.mark.unit
    def test_clear_all(self):
        """clear_all 应该清除所有数据"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file.txt", EventType.CREATE)
        assert tracker.get_global_stats()["total_events"] == 1

        tracker.clear_all()

        assert tracker.get_global_stats()["total_events"] == 0
        assert tracker.get_lifecycle_summary("/file.txt")["total_events"] == 0

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_all_tracked_resources(self):
        """应该返回所有追踪的资源"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file1.txt", EventType.CREATE)
        tracker.track_event("session_1", "/file2.txt", EventType.CREATE)
        tracker.track_event("session_2", "/file3.txt", EventType.CREATE)

        resources = tracker.get_all_tracked_resources()
        assert len(resources) == 3
        assert "/file1.txt" in resources
        assert "/file2.txt" in resources
        assert "/file3.txt" in resources

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_all_active_sessions(self):
        """应该返回所有活动的 session"""
        tracker = ResourceLifecycleTracker()

        tracker.track_event("session_1", "/file.txt", EventType.CREATE)
        tracker.track_event("session_2", "/file.txt", EventType.READ)
        tracker.track_event("session_3", "/file.txt", EventType.WRITE)

        sessions = tracker.get_all_active_sessions()
        assert len(sessions) == 3
        assert "session_1" in sessions
        assert "session_2" in sessions
        assert "session_3" in sessions
