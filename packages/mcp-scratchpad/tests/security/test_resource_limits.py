"""Comprehensive resource limit enforcement tests for OverlayFileSystem.

This test suite validates resource limit enforcement to prevent DoS attacks
via resource exhaustion.

Test categories:
- File size limits
- Directory file count limits
- Directory depth limits
- Total file count limits
- Total size limits
- Integration tests with OverlayFileSystem
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from mcp_scratchpad.exceptions import FileSizeLimitError, ResourceLimitError
from mcp_scratchpad.fs import (
    OverlayFileSystem,
    ResourceLimitEnforcer,
    ResourceLimits,
    create_default_enforcer,
    create_unlimited_enforcer,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# ResourceLimits Configuration Tests
# =============================================================================


class TestResourceLimitsConfig:
    """Test ResourceLimits configuration."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_default_limits(self):
        """默认限制应该被正确设置"""
        limits = ResourceLimits()
        assert limits.max_file_size_bytes == 100 * 1024 * 1024  # 100 MB
        assert limits.max_files_per_directory == 1000
        assert limits.max_directory_depth == 10
        assert limits.max_total_files == 10000
        assert limits.max_total_size_bytes == 1 * 1024 * 1024 * 1024  # 1 GB

    @pytest.mark.security
    @pytest.mark.unit
    def test_custom_limits(self):
        """应该能设置自定义限制"""
        limits = ResourceLimits(
            max_file_size_bytes=50 * 1024 * 1024,  # 50 MB
            max_files_per_directory=100,
            max_directory_depth=5,
            max_total_files=1000,
            max_total_size_bytes=500 * 1024 * 1024,  # 500 MB
        )
        assert limits.max_file_size_bytes == 50 * 1024 * 1024
        assert limits.max_files_per_directory == 100
        assert limits.max_directory_depth == 5
        assert limits.max_total_files == 1000
        assert limits.max_total_size_bytes == 500 * 1024 * 1024

    @pytest.mark.security
    @pytest.mark.unit
    def test_disable_limits(self):
        """设置限制为 None 应该禁用该限制"""
        limits = ResourceLimits(
            max_file_size_bytes=None,
            max_files_per_directory=0,  # 0 也应该禁用
        )
        assert limits.max_file_size_bytes is None
        assert limits.max_files_per_directory == 0
        assert limits.is_limit_enabled("max_file_size_bytes") is False
        assert limits.is_limit_enabled("max_files_per_directory") is False

    @pytest.mark.security
    @pytest.mark.unit
    def test_negative_limit_raises_error(self):
        """负数限制应该抛出错误"""
        with pytest.raises(ValueError):
            ResourceLimits(max_file_size_bytes=-1)

    @pytest.mark.security
    @pytest.mark.unit
    def test_limit_enabled_check(self):
        """is_limit_enabled 应该正确检测限制是否启用"""
        limits = ResourceLimits(
            max_file_size_bytes=100,
            max_files_per_directory=None,
            max_directory_depth=0,
        )
        assert limits.is_limit_enabled("max_file_size_bytes") is True
        assert limits.is_limit_enabled("max_files_per_directory") is False
        assert limits.is_limit_enabled("max_directory_depth") is False


# =============================================================================
# File Size Limit Tests
# =============================================================================


class TestFileSizeLimits:
    """Test file size limit enforcement."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_file_size_within_limit(self):
        """文件大小在限制内应该通过"""
        limits = ResourceLimits(max_file_size_bytes=1000)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # 不应该抛出异常
        enforcer.check_file_size("/test.txt", 500)

    @pytest.mark.security
    @pytest.mark.unit
    def test_file_size_exactly_at_limit(self):
        """文件大小等于限制应该通过"""
        limits = ResourceLimits(max_file_size_bytes=1000)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # 等于限制应该允许
        enforcer.check_file_size("/test.txt", 1000)

    @pytest.mark.security
    @pytest.mark.unit
    def test_file_size_exceeds_limit(self):
        """文件大小超过限制应该抛出异常"""
        limits = ResourceLimits(max_file_size_bytes=1000)
        enforcer = ResourceLimitEnforcer(limits=limits)

        with pytest.raises(FileSizeLimitError) as exc_info:
            enforcer.check_file_size("/test.txt", 1001)

        assert "exceeds limit" in str(exc_info.value)
        assert exc_info.value.file_size == 1001
        assert exc_info.value.size_limit == 1000

    @pytest.mark.security
    @pytest.mark.unit
    def test_disabled_file_size_limit(self):
        """禁用的文件大小限制应该允许任何大小"""
        limits = ResourceLimits(max_file_size_bytes=None)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # 任何大小都应该允许
        enforcer.check_file_size("/test.txt", 1000000000)


# =============================================================================
# Directory Depth Limit Tests
# =============================================================================


class TestDirectoryDepthLimits:
    """Test directory depth limit enforcement."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_depth_within_limit(self):
        """目录深度在限制内应该通过"""
        limits = ResourceLimits(max_directory_depth=5)
        enforcer = ResourceLimitEnforcer(limits=limits)

        enforcer.check_directory_depth("/a/b/c/d")

    @pytest.mark.security
    @pytest.mark.unit
    def test_depth_exactly_at_limit(self):
        """目录深度等于限制应该通过"""
        limits = ResourceLimits(max_directory_depth=4)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # /a/b/c/d 是 4 层深度
        enforcer.check_directory_depth("/a/b/c/d")

    @pytest.mark.security
    @pytest.mark.unit
    def test_depth_exceeds_limit(self):
        """目录深度超过限制应该抛出异常"""
        limits = ResourceLimits(max_directory_depth=3)
        enforcer = ResourceLimitEnforcer(limits=limits)

        with pytest.raises(ResourceLimitError) as exc_info:
            enforcer.check_directory_depth("/a/b/c/d")  # 4 层深度

        assert "depth" in str(exc_info.value).lower()
        assert exc_info.value.resource_type == "directory_depth"

    @pytest.mark.security
    @pytest.mark.unit
    def test_disabled_depth_limit(self):
        """禁用的深度限制应该允许任何深度"""
        limits = ResourceLimits(max_directory_depth=None)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # 任何深度都应该允许
        enforcer.check_directory_depth("/" + "/a" * 100)


# =============================================================================
# Total Files Limit Tests
# =============================================================================


class TestTotalFilesLimits:
    """Test total file count limit enforcement."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_total_files_within_limit(self):
        """总文件数在限制内应该通过"""
        fs = MemoryFileSystem()
        # 创建 5 个文件
        for i in range(5):
            fs.pipe(f"/file{i}.txt", b"content")

        limits = ResourceLimits(max_total_files=10)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        enforcer._check_total_files()

    @pytest.mark.security
    @pytest.mark.unit
    def test_total_files_exceeds_limit(self):
        """总文件数超过限制应该抛出异常"""
        fs = MemoryFileSystem()
        # 创建 15 个文件
        for i in range(15):
            fs.pipe(f"/file{i}.txt", b"content")

        limits = ResourceLimits(max_total_files=10)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        with pytest.raises(ResourceLimitError) as exc_info:
            enforcer._check_total_files()

        assert "exceeds limit" in str(exc_info.value)
        assert exc_info.value.resource_type == "total_files"

    @pytest.mark.security
    @pytest.mark.unit
    def test_total_files_with_directories(self):
        """总文件数计算应该不包括目录"""
        fs = MemoryFileSystem()
        fs.mkdir("/dir1")
        fs.mkdir("/dir2")
        fs.pipe("/dir1/file.txt", b"content")
        fs.pipe("/dir2/file.txt", b"content")
        fs.pipe("/root.txt", b"content")

        limits = ResourceLimits(max_total_files=5)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        # 只有 3 个文件，应该通过
        enforcer._check_total_files()


# =============================================================================
# Total Size Limit Tests
# =============================================================================


class TestTotalSizeLimits:
    """Test total size limit enforcement."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_total_size_within_limit(self):
        """总大小在限制内应该通过"""
        fs = MemoryFileSystem()
        fs.pipe("/file1.txt", b"a" * 100)
        fs.pipe("/file2.txt", b"b" * 100)

        limits = ResourceLimits(max_total_size_bytes=500)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        enforcer._check_total_size()

    @pytest.mark.security
    @pytest.mark.unit
    def test_total_size_exceeds_limit(self):
        """总大小超过限制应该抛出异常"""
        fs = MemoryFileSystem()
        fs.pipe("/file1.txt", b"a" * 600)
        fs.pipe("/file2.txt", b"b" * 500)

        limits = ResourceLimits(max_total_size_bytes=1000)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        with pytest.raises(ResourceLimitError) as exc_info:
            enforcer._check_total_size()

        assert "exceeds limit" in str(exc_info.value)
        assert exc_info.value.resource_type == "total_size"


# =============================================================================
# Write Operation Validation Tests
# =============================================================================


class TestWriteOperationValidation:
    """Test comprehensive write operation validation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_write_operation_valid(self):
        """有效的写操作应该通过"""
        fs = MemoryFileSystem()
        limits = ResourceLimits(
            max_file_size_bytes=1000,
            max_directory_depth=5,
        )
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        enforcer.validate_write_operation("/test.txt", data_size=500, fs=fs)

    @pytest.mark.security
    @pytest.mark.unit
    def test_write_operation_file_size_exceeded(self):
        """写操作文件大小超过限制应该抛出异常"""
        fs = MemoryFileSystem()
        limits = ResourceLimits(max_file_size_bytes=100)
        enforcer = ResourceLimitEnforcer(limits=limits)

        with pytest.raises(FileSizeLimitError):
            enforcer.validate_write_operation("/test.txt", data_size=200, fs=fs)

    @pytest.mark.security
    @pytest.mark.unit
    def test_write_operation_depth_exceeded(self):
        """写操作目录深度超过限制应该抛出异常"""
        fs = MemoryFileSystem()
        limits = ResourceLimits(max_directory_depth=2)
        enforcer = ResourceLimitEnforcer(limits=limits)

        with pytest.raises(ResourceLimitError):
            enforcer.validate_write_operation("/a/b/c/test.txt", data_size=10, fs=fs)


# =============================================================================
# Mkdir Operation Validation Tests
# =============================================================================


class TestMkdirOperationValidation:
    """Test mkdir operation validation."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mkdir_valid(self):
        """有效的 mkdir 操作应该通过"""
        fs = MemoryFileSystem()
        limits = ResourceLimits(max_directory_depth=5)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        enforcer.validate_mkdir_operation("/newdir", fs=fs)

    @pytest.mark.security
    @pytest.mark.unit
    def test_mkdir_depth_exceeded(self):
        """mkdir 目录深度超过限制应该抛出异常"""
        fs = MemoryFileSystem()
        limits = ResourceLimits(max_directory_depth=2)
        enforcer = ResourceLimitEnforcer(limits=limits)

        with pytest.raises(ResourceLimitError):
            enforcer.validate_mkdir_operation("/a/b/c/newdir", fs=fs)


# =============================================================================
# Enforcer Factory Tests
# =============================================================================


class TestEnforcerFactories:
    """Test enforcer factory functions."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_create_default_enforcer(self):
        """create_default_enforcer 应该返回带有默认限制的 enforcer"""
        enforcer = create_default_enforcer()

        assert enforcer.limits.max_file_size_bytes is not None
        assert enforcer.limits.max_files_per_directory is not None

    @pytest.mark.security
    @pytest.mark.unit
    def test_create_unlimited_enforcer(self):
        """create_unlimited_enforcer 应该返回所有限制都为 None 的 enforcer"""
        enforcer = create_unlimited_enforcer()

        assert enforcer.limits.max_file_size_bytes is None
        assert enforcer.limits.max_files_per_directory is None
        assert enforcer.limits.max_directory_depth is None
        assert enforcer.limits.max_total_files is None
        assert enforcer.limits.max_total_size_bytes is None


# =============================================================================
# Resource Stats Tests
# =============================================================================


class TestResourceStats:
    """Test resource statistics."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_get_resource_stats(self):
        """应该返回资源使用统计"""
        fs = MemoryFileSystem()
        fs.pipe("/file1.txt", b"a" * 100)
        fs.pipe("/file2.txt", b"b" * 200)
        fs.mkdir("/dir1")
        fs.pipe("/dir1/file.txt", b"c" * 300)

        limits = ResourceLimits()
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        stats = enforcer.get_resource_stats()

        assert "max_file_size_bytes" in stats
        assert "current_total_files" in stats
        assert "current_total_size" in stats
        assert stats["current_total_files"] == 3
        assert stats["current_total_size"] == 600


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_empty_filesystem(self):
        """空文件系统应该正常工作"""
        fs = MemoryFileSystem()
        limits = ResourceLimits(max_total_files=10)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        # 不应该抛出异常
        enforcer._check_total_files()
        enforcer._check_total_size()

    @pytest.mark.security
    @pytest.mark.unit
    def test_nested_directories(self):
        """嵌套目录应该正确计算深度"""
        fs = MemoryFileSystem()
        fs.mkdir("/level1")
        fs.mkdir("/level1/level2")
        fs.mkdir("/level1/level2/level3")
        fs.pipe("/level1/level2/level3/file.txt", b"content")

        limits = ResourceLimits(max_directory_depth=5)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        # 深度 3，限制 5，应该通过
        enforcer.validate_write_operation("/level1/level2/level3/file.txt", fs=fs)

    @pytest.mark.security
    @pytest.mark.unit
    def test_root_path_depth(self):
        """根路径深度应该正确处理"""
        limits = ResourceLimits(max_directory_depth=1)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # 根目录深度为 0，应该通过
        enforcer.check_directory_depth("/")

    @pytest.mark.security
    @pytest.mark.unit
    def test_single_component_path(self):
        """单组件路径深度应该为 1"""
        limits = ResourceLimits(max_directory_depth=2)
        enforcer = ResourceLimitEnforcer(limits=limits)

        # /file.txt 深度为 1，应该通过
        enforcer.check_directory_depth("/file.txt")

    @pytest.mark.security
    @pytest.mark.unit
    def test_no_upper_fs_stats(self):
        """如果没有 upper_fs，统计应该返回 None"""
        limits = ResourceLimits()
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=None)

        stats = enforcer.get_resource_stats()

        assert stats["current_total_files"] is None
        assert stats["current_total_size"] is None


# =============================================================================
# Integration Tests with OverlayFileSystem
# =============================================================================


class TestOverlayFileSystemIntegration:
    """Integration tests with OverlayFileSystem."""

    @pytest.mark.security
    @pytest.mark.integration
    def test_overlay_with_resource_limits(self):
        """应该能创建带资源限制的 OverlayFileSystem"""
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        limits = ResourceLimits(
            max_file_size_bytes=1000,
            max_directory_depth=5,
        )

        # 创建带有资源限制的 enforcer
        enforcer = ResourceLimitEnforcer(
            limits=limits,
            upper_fs=upper_fs,
        )

        # 验证 enforcer 正常工作
        enforcer.validate_write_operation("/test.txt", data_size=500)

    @pytest.mark.security
    @pytest.mark.integration
    def test_overlay_resource_limits_enforced(self):
        """资源限制应该在 Overlay 操作中被强制执行"""
        upper_fs = MemoryFileSystem()
        lower_fs = MemoryFileSystem()

        limits = ResourceLimits(
            max_file_size_bytes=100,
            max_directory_depth=3,
        )

        enforcer = ResourceLimitEnforcer(
            limits=limits,
            upper_fs=upper_fs,
        )

        # 小文件应该通过
        enforcer.validate_write_operation("/small.txt", data_size=50)

        # 大文件应该被拒绝
        with pytest.raises(FileSizeLimitError):
            enforcer.validate_write_operation("/large.txt", data_size=200)

        # 深层目录应该被拒绝
        with pytest.raises(ResourceLimitError):
            enforcer.validate_write_operation("/a/b/c/d/file.txt", data_size=10)

    @pytest.mark.security
    @pytest.mark.integration
    def test_limitViolation_with_current_count(self):
        """异常应该包含当前值和限制值"""
        fs = MemoryFileSystem()
        # 创建超过限制的文件数
        for i in range(15):
            fs.pipe(f"/file{i}.txt", b"x")

        limits = ResourceLimits(max_total_files=10)
        enforcer = ResourceLimitEnforcer(limits=limits, upper_fs=fs)

        with pytest.raises(ResourceLimitError) as exc_info:
            enforcer._check_total_files()

        assert exc_info.value.current_value == 15
        assert exc_info.value.limit_value == 10
        assert exc_info.value.resource_type == "total_files"
