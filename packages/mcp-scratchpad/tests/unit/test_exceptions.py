"""
Unit tests for exception handling
"""

from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, TextContent

from mcp_scratchpad.exceptions import (
    ConfigurationError,
    FileTooLargeError,
    PermissionDeniedError,
    ScratchpadError,
    ScratchpadFileNotFoundError,
    StorageError,
    ValidationError,
    handle_tool_exception,
)


class TestCustomExceptions:
    """Test custom exception classes"""

    @pytest.mark.unit
    def test_scratchpad_exception_base(self):
        """Test base ScratchpadError"""
        exc = ScratchpadError("Test message", "TEST_ERROR", {"detail": "test"})

        assert exc.message == "Test message"
        assert exc.error_code == "TEST_ERROR"
        assert exc.details == {"detail": "test"}
        assert str(exc) == "Test message"

    @pytest.mark.unit
    def test_validation_error(self):
        """Test ValidationError"""
        exc = ValidationError("Invalid input")

        assert isinstance(exc, ScratchpadError)
        assert exc.message == "Invalid input"
        assert exc.error_code == "ValidationError"

    @pytest.mark.unit
    def test_file_not_found_error(self):
        """Test ScratchpadFileNotFoundError"""
        exc = ScratchpadFileNotFoundError("File not found")

        assert isinstance(exc, ScratchpadError)
        assert exc.message == "File not found"
        assert exc.error_code == "ScratchpadFileNotFoundError"

    @pytest.mark.unit
    def test_file_too_large_error(self):
        """Test FileTooLargeError"""
        exc = FileTooLargeError("File too large")

        assert isinstance(exc, ScratchpadError)
        assert exc.message == "File too large"
        assert exc.error_code == "FileTooLargeError"

    @pytest.mark.unit
    def test_permission_denied_error(self):
        """Test PermissionDeniedError"""
        exc = PermissionDeniedError("Access denied")

        assert isinstance(exc, ScratchpadError)
        assert exc.message == "Access denied"
        assert exc.error_code == "PermissionDeniedError"

    @pytest.mark.unit
    def test_storage_error(self):
        """Test StorageError"""
        exc = StorageError("Storage failed")

        assert isinstance(exc, ScratchpadError)
        assert exc.message == "Storage failed"
        assert exc.error_code == "StorageError"

    @pytest.mark.unit
    def test_configuration_error(self):
        """Test ConfigurationError"""
        exc = ConfigurationError("Invalid configuration")

        assert isinstance(exc, ScratchpadError)
        assert exc.message == "Invalid configuration"
        assert exc.error_code == "ConfigurationError"


class TestExceptionHandler:
    """Test exception handler functionality"""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_validation_error(self):
        """Test handling ValidationError"""
        ctx = AsyncMock()
        exc = ValidationError("Invalid session ID")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert "参数验证失败" in result.content[0].text
        assert "Invalid session ID" in result.content[0].text
        ctx.error.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_file_not_found_error(self):
        """Test handling ScratchpadFileNotFoundError"""
        ctx = AsyncMock()
        exc = ScratchpadFileNotFoundError("File not found")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "文件未找到" in result.content[0].text
        assert "File not found" in result.content[0].text
        ctx.error.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_file_too_large_error(self):
        """Test handling FileTooLargeError"""
        ctx = AsyncMock()
        exc = FileTooLargeError("File size exceeds limit")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "文件过大" in result.content[0].text
        assert "File size exceeds limit" in result.content[0].text
        ctx.error.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_permission_denied_error(self):
        """Test handling PermissionDeniedError"""
        ctx = AsyncMock()
        exc = PermissionDeniedError("Access denied")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "权限不足" in result.content[0].text
        assert "Access denied" in result.content[0].text
        ctx.error.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_storage_error(self):
        """Test handling StorageError"""
        ctx = AsyncMock()
        exc = StorageError("Disk full")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "存储错误" in result.content[0].text
        assert "Disk full" in result.content[0].text
        ctx.error.assert_called()

    @pytest.mark.unit
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_generic_scratchpad_exception(self):
        """Test handling generic ScratchpadError"""
        ctx = AsyncMock()
        exc = ScratchpadError("Generic error", "CUSTOM_ERROR")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "操作失败" in result.content[0].text
        assert "Generic error" in result.content[0].text
        ctx.error.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_unexpected_exception(self):
        """Test handling unexpected exception"""
        ctx = AsyncMock()
        exc = ValueError("Unexpected error")

        result = await handle_tool_exception(exc, "test_tool", ctx)

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "内部错误" in result.content[0].text
        assert "Unexpected error" in result.content[0].text
        ctx.error.assert_called()
