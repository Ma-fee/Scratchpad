"""Session isolation validation for OverlayFileSystem.

This module provides comprehensive session isolation including:
- Session ID validation and sanitization
- Workspace boundary enforcement per session
- Cross-session access prevention
- Session-scoped path resolution
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..exceptions import (
    InvalidSessionError,
    PathTraversalError,
    SessionIsolationError,
    ValidationError,
)

if TYPE_CHECKING:
    pass


# 有效的 session ID 格式: UUID v4 或 URL-safe base64 字符串
SESSION_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9_-]+$"  # 只允许字母、数字、下划线和连字符
)

# Session ID 长度限制
MAX_SESSION_ID_LENGTH = 128
MIN_SESSION_ID_LENGTH = 8


def validate_session_id(session_id: str) -> str:
    """验证和清理 session ID。

    Args:
        session_id: 要验证的 session ID

    Returns:
        清理后的 session ID

    Raises:
        InvalidSessionError: 如果 session ID 格式无效
    """
    if not session_id:
        raise InvalidSessionError("Session ID cannot be empty", session_id=session_id)

    if not isinstance(session_id, str):
        raise InvalidSessionError(
            f"Session ID must be a string, got {type(session_id).__name__}",
            session_id=str(session_id),
        )

    # 检查长度限制
    if len(session_id) < MIN_SESSION_ID_LENGTH:
        raise InvalidSessionError(
            f"Session ID too short: {len(session_id)} < {MIN_SESSION_ID_LENGTH}",
            session_id=session_id,
        )

    if len(session_id) > MAX_SESSION_ID_LENGTH:
        raise InvalidSessionError(
            f"Session ID too long: {len(session_id)} > {MAX_SESSION_ID_LENGTH}",
            session_id=session_id,
        )

    # 检查是否包含危险字符
    if ".." in session_id:
        raise InvalidSessionError(
            "Session ID contains unsafe characters: ..",
            session_id=session_id,
        )

    if "/" in session_id or "\\" in session_id:
        raise InvalidSessionError(
            "Session ID contains path separators",
            session_id=session_id,
        )

    # 检查是否符合允许的字符集
    if not SESSION_ID_PATTERN.match(session_id):
        raise InvalidSessionError(
            "Session ID contains invalid characters. Only alphanumeric, underscore, and hyphen allowed",
            session_id=session_id,
        )

    return session_id


def sanitize_session_id(session_id: str) -> str:
    """清理 session ID，移除不安全字符。

    Args:
        session_id: 原始 session ID

    Returns:
        清理后的 session ID
    """
    if not session_id:
        return ""

    # 移除所有非安全字符
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)

    # 限制长度
    return sanitized[:MAX_SESSION_ID_LENGTH]


@dataclass(frozen=True)
class SessionWorkspace:
    """Session 工作空间定义。

    定义了 session 可以访问的路径范围。
    """

    session_id: str
    base_path: Path
    allowed_prefixes: tuple[str, ...] = ("/workspace",)

    def __post_init__(self) -> None:
        # 验证 session_id 格式
        validate_session_id(self.session_id)

    def resolve_path(self, relative_path: str) -> Path:
        """将相对路径解析为 session 工作空间内的绝对路径。

        Args:
            relative_path: 相对于工作空间的路径

        Returns:
            解析后的绝对路径

        Raises:
            SessionIsolationError: 如果路径超出工作空间边界
            PathTraversalError: 如果路径包含遍历序列
        """
        # 检查路径遍历
        if ".." in relative_path.split("/"):
            raise SessionIsolationError(
                f"Path traversal detected in session {self.session_id}: {relative_path}",
                session_id=self.session_id,
                attempted_path=relative_path,
                workspace=str(self.base_path),
            )

        # 检查允许的访问前缀
        normalized = relative_path.lstrip("/")
        allowed = False
        for prefix in self.allowed_prefixes:
            prefix_normalized = prefix.lstrip("/")
            if normalized.startswith(prefix_normalized) or not prefix_normalized:
                allowed = True
                break

        if not allowed:
            # 如果没有匹配的前缀，默认添加到 workspace
            if not normalized.startswith("workspace"):
                normalized = f"workspace/{normalized}"

        # 构建完整路径
        full_path = self.base_path / normalized

        # 解析并检查是否在边界内
        try:
            resolved = full_path.resolve()
            resolved.relative_to(self.base_path.resolve())
            return resolved
        except ValueError:
            raise SessionIsolationError(
                f"Path escapes session workspace: {relative_path}",
                session_id=self.session_id,
                attempted_path=relative_path,
                workspace=str(self.base_path),
            )

    def is_path_accessible(self, path: str) -> bool:
        """检查路径是否在工作空间内可访问。

        Args:
            path: 要检查的路径

        Returns:
            True 如果路径可访问，False 否则
        """
        try:
            self.resolve_path(path)
            return True
        except (SessionIsolationError, PathTraversalError):
            return False


def validate_session_access(
    session_id: str,
    path: str,
    workspace_root: str | Path,
    active_sessions: set[str] | None = None,
) -> Path:
    """验证 session 对路径的访问权限。

    主要安全检查:
    1. Session ID 格式有效性
    2. Session 是否处于活跃状态
    3. 路径是否在工作空间内
    4. 路径遍历攻击检测

    Args:
        session_id: Session 标识符
        path: 请求访问的路径
        workspace_root: 工作空间根目录
        active_sessions: 活跃 session 集合（可选，如果提供则检查）

    Returns:
        解析后的工作空间内路径

    Raises:
        InvalidSessionError: Session ID 无效或已过期
        SessionIsolationError: 访问超出工作空间边界
        PathTraversalError: 路径包含遍历序列
    """
    # 1. 验证 session ID
    validated_id = validate_session_id(session_id)

    # 2. 检查 session 是否活跃
    if active_sessions is not None and validated_id not in active_sessions:
        raise InvalidSessionError(
            f"Session not found or expired: {session_id}",
            session_id=session_id,
        )

    # 3. 创建 session 工作空间
    base_path = Path(workspace_root).resolve()
    workspace = SessionWorkspace(
        session_id=validated_id,
        base_path=base_path / validated_id,
    )

    # 4. 验证路径
    return workspace.resolve_path(path)


def check_cross_session_access(
    source_session: str,
    target_session: str,
    path: str,
) -> None:
    """检查跨 session 访问是否被允许。

    默认情况下，禁止所有跨 session 访问。

    Args:
        source_session: 源 session ID
        target_session: 目标 session ID
        path: 访问的路径

    Raises:
        SessionIsolationError: 如果尝试跨 session 访问
    """
    if source_session != target_session:
        raise SessionIsolationError(
            f"Cross-session access denied: {source_session} -> {target_session}",
            session_id=source_session,
            attempted_path=path,
        )


def get_session_workspace_path(
    session_id: str,
    base_workspaces: str | Path = "/tmp/sessions",
) -> Path:
    """获取 session 的工作空间路径。

    Args:
        session_id: Session 标识符
        base_workspaces: 工作空间基础目录

    Returns:
        Session 专属工作空间路径
    """
    validated_id = validate_session_id(session_id)
    return Path(base_workspaces).resolve() / validated_id


def enforce_session_isolation(
    session_id: str,
    operation: str,
    path: str,
    workspace_root: str | Path,
    active_sessions: set[str] | None = None,
) -> Path:
    """强制执行 session 隔离策略。

    这是 session 访问的主要入口点，执行完整的验证链。

    Args:
        session_id: Session 标识符
        operation: 操作类型（如 'read', 'write', 'delete'）
        path: 操作目标路径
        workspace_root: 工作空间根目录
        active_sessions: 活跃 session 集合

    Returns:
        验证通过的安全路径

    Raises:
        InvalidSessionError: Session 无效
        SessionIsolationError: 隔离策略被违反
    """
    # 完整验证链
    safe_path = validate_session_access(
        session_id=session_id,
        path=path,
        workspace_root=workspace_root,
        active_sessions=active_sessions,
    )

    # 记录访问（用于审计，如果需要）
    # 这里可以扩展添加日志记录

    return safe_path
