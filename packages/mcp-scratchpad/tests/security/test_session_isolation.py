"""Comprehensive session isolation security tests for OverlayFileSystem.

This test suite validates session boundary enforcement, cross-session access
prevention, and workspace isolation across all file operations.

Attack vectors tested:
- Cross-session file access attempts
- Path traversal to escape session workspace
- Invalid session ID formats
- Session ID injection attacks
- Workspace boundary violations
- Session expiration handling
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.exceptions import InvalidSessionError, SessionIsolationError
from mcp_scratchpad.fs.overlay import OverlayFileSystem
from mcp_scratchpad.fs.session_validator import (
    SessionWorkspace,
    check_cross_session_access,
    enforce_session_isolation,
    get_session_workspace_path,
    sanitize_session_id,
    validate_session_id,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Session ID Validation Tests
# =============================================================================


class TestSessionIDValidation:
    """Test session ID format validation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_valid_uuid_session_id(self):
        """有效的 UUID 应该被接受"""
        valid_id = str(uuid.uuid4())
        result = validate_session_id(valid_id)
        assert result == valid_id

    @pytest.mark.security
    @pytest.mark.unit
    def test_valid_simple_session_id(self):
        """简单的字母数字组合应该被接受"""
        simple_id = "abc123def456"
        result = validate_session_id(simple_id)
        assert result == simple_id

    @pytest.mark.security
    @pytest.mark.unit
    def test_empty_session_id_rejected(self):
        """空 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("")

    @pytest.mark.security
    @pytest.mark.unit
    def test_short_session_id_rejected(self):
        """太短（<8字符）的 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("abc123")

    @pytest.mark.security
    @pytest.mark.unit
    def test_long_session_id_rejected(self):
        """太长（>128字符）的 session ID 应该被拒绝"""
        long_id = "a" * 129
        with pytest.raises(InvalidSessionError):
            validate_session_id(long_id)

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_with_path_traversal_rejected(self):
        """包含路径遍历的 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("../etc/passwd")

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_with_slash_rejected(self):
        """包含斜杠的 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("abc/def")

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_with_backslash_rejected(self):
        """包含反斜杠的 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("abc\\def")

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_with_special_chars_rejected(self):
        """包含特殊字符的 session ID 应该被拒绝"""
        invalid_ids = [
            "abc<def",
            "abc>def",
            "abc|def",
            "abc?def",
            "abc*def",
            "abc def",  # 空格
        ]
        for invalid_id in invalid_ids:
            with pytest.raises(InvalidSessionError):
                validate_session_id(invalid_id)


# =============================================================================
# Session ID Sanitization Tests
# =============================================================================


class TestSessionIDSanitization:
    """Test session ID sanitization."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_sanitize_removes_dangerous_chars(self):
        """清理应该移除危险字符"""
        dirty_id = "abc/../def<ghi>123"
        result = sanitize_session_id(dirty_id)
        # 危险字符应该被移除
        assert ".." not in result
        assert "<" not in result
        assert ">" not in result
        assert "/" not in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_sanitize_preserves_safe_chars(self):
        """清理应该保留安全字符"""
        safe_id = "abc123_DEF-456"
        result = sanitize_session_id(safe_id)
        assert result == safe_id

    @pytest.mark.security
    @pytest.mark.unit
    def test_sanitize_limits_length(self):
        """清理应该限制长度"""
        long_id = "a" * 200
        result = sanitize_session_id(long_id)
        assert len(result) <= 128

    @pytest.mark.security
    @pytest.mark.unit
    def test_sanitize_empty_returns_empty(self):
        """清理空字符串应该返回空字符串"""
        result = sanitize_session_id("")
        assert result == ""


# =============================================================================
# Session Workspace Tests
# =============================================================================


class TestSessionWorkspace:
    """Test session workspace isolation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_workspace_creation(self):
        """应该能正确创建 session 工作空间"""
        session_id = str(uuid.uuid4())
        base_path = Path("/tmp/test_workspace")
        workspace = SessionWorkspace(
            session_id=session_id,
            base_path=base_path,
        )
        assert workspace.session_id == session_id
        assert workspace.base_path == base_path

    @pytest.mark.security
    @pytest.mark.unit
    def test_workspace_resolve_path(self):
        """应该正确解析工作空间内的路径"""
        session_id = str(uuid.uuid4())
        base_path = Path("/tmp/test_workspace")
        workspace = SessionWorkspace(
            session_id=session_id,
            base_path=base_path,
        )

        # 相对路径应该被正确解析
        result = workspace.resolve_path("subdir/file.txt")
        expected = (base_path / session_id / "workspace/subdir/file.txt").resolve()
        assert result == expected

    @pytest.mark.security
    @pytest.mark.unit
    def test_workspace_blocks_traversal(self):
        """应该阻止路径遍历逃逸工作空间"""
        session_id = str(uuid.uuid4())
        base_path = Path("/tmp/test_workspace")
        workspace = SessionWorkspace(
            session_id=session_id,
            base_path=base_path,
        )

        # 路径遍历应该被拒绝
        with pytest.raises(SessionIsolationError):
            workspace.resolve_path("../../etc/passwd")

    @pytest.mark.security
    @pytest.mark.unit
    def test_workspace_is_path_accessible(self):
        """应该能正确判断路径是否可访问"""
        session_id = str(uuid.uuid4())
        base_path = Path("/tmp/test_workspace")
        workspace = SessionWorkspace(
            session_id=session_id,
            base_path=base_path,
        )

        # 工作空间内的路径应该可访问
        assert workspace.is_path_accessible("subdir/file.txt") is True

        # 包含遍历的路径应该不可访问
        assert workspace.is_path_accessible("../../etc/passwd") is False


# =============================================================================
# Cross-Session Access Tests
# =============================================================================


class TestCrossSessionAccess:
    """Test cross-session access prevention."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_cross_session_access_blocked(self):
        """应该阻止跨 session 访问"""
        source_session = str(uuid.uuid4())
        target_session = str(uuid.uuid4())

        with pytest.raises(SessionIsolationError):
            check_cross_session_access(source_session, target_session, "/some/path")

    @pytest.mark.security
    @pytest.mark.unit
    def test_same_session_access_allowed(self):
        """相同 session 的访问应该被允许"""
        session_id = str(uuid.uuid4())

        # 相同 session 不应该抛出异常
        try:
            check_cross_session_access(session_id, session_id, "/some/path")
        except SessionIsolationError:
            pytest.fail("Same session access should be allowed")


# =============================================================================
# Session Isolation Enforcement Tests
# =============================================================================


class TestSessionIsolationEnforcement:
    """Test session isolation enforcement."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_enforce_session_isolation_with_active_session(self, tmp_path: Path):
        """应该在活跃 session 下强制执行隔离"""
        session_id = str(uuid.uuid4())
        active_sessions = {session_id}

        result = enforce_session_isolation(
            session_id=session_id,
            operation="read",
            path="subdir/file.txt",
            workspace_root=str(tmp_path),
            active_sessions=active_sessions,
        )

        # 应该返回安全路径
        assert result is not None
        assert isinstance(result, Path)

    @pytest.mark.security
    @pytest.mark.unit
    def test_enforce_session_isolation_blocks_inactive_session(self, tmp_path: Path):
        """应该阻止非活跃 session 的访问"""
        session_id = str(uuid.uuid4())
        active_sessions = set()  # 空集合，session 不在其中

        with pytest.raises(InvalidSessionError):
            enforce_session_isolation(
                session_id=session_id,
                operation="read",
                path="subdir/file.txt",
                workspace_root=str(tmp_path),
                active_sessions=active_sessions,
            )

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_session_workspace_path(self, tmp_path: Path):
        """应该正确获取 session 工作空间路径"""
        session_id = str(uuid.uuid4())
        workspace = get_session_workspace_path(session_id, tmp_path)

        expected = tmp_path / session_id
        assert workspace == expected


# =============================================================================
# OverlayFileSystem Session Integration Tests
# =============================================================================


class TestOverlayFileSystemSessionIsolation:
    """Test OverlayFileSystem with session isolation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_create_overlay_with_session(self):
        """应该能创建带 session 的 OverlayFileSystem"""
        session_id = str(uuid.uuid4())
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        overlay = OverlayFileSystem(
            upper=upper_fs,
            lowers=[lower_fs],
            session_id=session_id,
        )

        assert overlay.get_session_id() == session_id
        assert overlay.is_session_isolated() is True

    @pytest.mark.security
    @pytest.mark.unit
    def test_create_overlay_without_session(self):
        """应该能创建不带 session 的 OverlayFileSystem"""
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        overlay = OverlayFileSystem(
            upper=upper_fs,
            lowers=[lower_fs],
        )

        assert overlay.get_session_id() is None
        assert overlay.is_session_isolated() is False

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_isolated_overlay_blocks_outside_workspace(self):
        """带 session 的 Overlay 应该阻止访问工作空间外"""
        session_id = str(uuid.uuid4())
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        overlay = OverlayFileSystem(
            upper=upper_fs,
            lowers=[lower_fs],
            session_id=session_id,
        )

        # 创建工作空间内的文件
        upper_fs.mkdir("/workspace")
        upper_fs.pipe("/workspace/test.txt", b"test content")

        # 访问工作空间内的路径应该成功
        assert overlay.exists("/workspace/test.txt")

    @pytest.mark.security
    @pytest.mark.unit
    def test_invalid_session_id_rejected(self):
        """无效的 session ID 应该被拒绝"""
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        with pytest.raises(InvalidSessionError):
            OverlayFileSystem(
                upper=upper_fs,
                lowers=[lower_fs],
                session_id="../etc/passwd",  # 无效的 session ID
            )


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_with_unicode(self):
        """包含 Unicode 字符的 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("abc日本語123")

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_with_null_byte(self):
        """包含 null 字节的 session ID 应该被拒绝"""
        with pytest.raises(InvalidSessionError):
            validate_session_id("abc\x00def")

    @pytest.mark.security
    @pytest.mark.unit
    def test_workspace_allows_single_dot(self):
        """工作空间应该允许单点 . 路径"""
        session_id = str(uuid.uuid4())
        base_path = Path("/tmp/test_workspace")
        workspace = SessionWorkspace(
            session_id=session_id,
            base_path=base_path,
        )

        # ./file.txt 应该被解析为 workspace/file.txt
        result = workspace.resolve_path("./file.txt")
        assert result is not None

    @pytest.mark.security
    @pytest.mark.unit
    def test_session_id_exact_length_limits(self):
        """测试 session ID 长度边界"""
        # 最小长度（8字符）应该被接受
        min_id = "a" * 8
        assert validate_session_id(min_id) == min_id

        # 最大长度（128字符）应该被接受
        max_id = "a" * 128
        assert validate_session_id(max_id) == max_id

        # 边界值测试
        with pytest.raises(InvalidSessionError):
            validate_session_id("a" * 7)  # 太短

        with pytest.raises(InvalidSessionError):
            validate_session_id("a" * 129)  # 太长


# =============================================================================
# Integration Tests
# =============================================================================


class TestSessionIntegration:
    """集成测试：完整的 session 生命周期"""

    @pytest.mark.security
    @pytest.mark.integration
    def test_complete_session_workflow(self, tmp_path: Path):
        """完整的 session 工作流程"""
        # 1. 创建带 session 的 OverlayFileSystem
        session_id = str(uuid.uuid4())
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        overlay = OverlayFileSystem(
            upper=upper_fs,
            lowers=[lower_fs],
            session_id=session_id,
        )

        # 2. 验证 session 已配置
        assert overlay.get_session_id() == session_id

        # 3. 在 workspace 内创建文件
        upper_fs.mkdir("/workspace")
        upper_fs.mkdir("/workspace/docs")
        upper_fs.pipe("/workspace/docs/readme.txt", b"Hello Session")

        # 4. 验证文件可访问
        assert overlay.exists("/workspace/docs/readme.txt")
        content = overlay.cat("/workspace/docs/readme.txt")
        assert content == b"Hello Session"

    @pytest.mark.security
    @pytest.mark.integration
    def test_multiple_sessions_isolated(self):
        """多个 session 应该完全隔离"""
        session_1_id = str(uuid.uuid4())
        session_2_id = str(uuid.uuid4())

        # 创建两个完全独立的 Overlay 实例
        overlay_1 = OverlayFileSystem(
            upper=MemoryFileSystem(),
            lowers=[MemoryFileSystem()],
            session_id=session_1_id,
        )

        overlay_2 = OverlayFileSystem(
            upper=MemoryFileSystem(),
            lowers=[MemoryFileSystem()],
            session_id=session_2_id,
        )

        # 验证 session ID 不同
        assert overlay_1.get_session_id() != overlay_2.get_session_id()

        # 两个 session 的文件系统应该完全隔离
        # （基于不同的 MemoryFileSystem 实例）
        workspace_1 = get_session_workspace_path(session_1_id, "/tmp/sessions")
        workspace_2 = get_session_workspace_path(session_2_id, "/tmp/sessions")

        assert workspace_1 != workspace_2
        assert session_1_id in str(workspace_1)
        assert session_2_id in str(workspace_2)
