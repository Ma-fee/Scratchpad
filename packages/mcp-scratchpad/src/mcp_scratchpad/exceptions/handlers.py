"""
Exception handlers for FastMCP tools
"""

import logging
from typing import Any

from fastmcp import Context
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolResult, TextContent

from ..utils import build_error_xml, create_tool_result_xml
from .custom import (
    ConfigurationError,
    FileTooLargeError,
    PermissionDeniedError,
    ScratchpadError,
    ScratchpadFileNotFoundError,
    StorageError,
    ValidationError,
)

logger = logging.getLogger(__name__)


async def handle_tool_exception(
    exc: Exception, tool_name: str, ctx: Context
) -> CallToolResult:
    """Handle exceptions in tool functions"""

    if isinstance(exc, ValidationError):
        await ctx.error(f"Validation error: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"参数验证失败: {exc.message}")],
            isError=True,
        )

    elif isinstance(exc, ScratchpadFileNotFoundError):
        await ctx.error(f"File not found: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"文件未找到: {exc.message}")],
            isError=True,
        )

    elif isinstance(exc, ConfigurationError):
        await ctx.error(f"Configuration error: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"配置错误: {exc.message}")],
            isError=True,
        )

    elif isinstance(exc, FileTooLargeError):
        await ctx.error(f"File too large: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"文件过大: {exc.message}")],
            isError=True,
        )

    elif isinstance(exc, PermissionDeniedError):
        await ctx.error(f"Permission denied: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"权限不足: {exc.message}")],
            isError=True,
        )

    elif isinstance(exc, StorageError):
        await ctx.error(f"Storage error: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"存储错误: {exc.message}")],
            isError=True,
        )

    elif isinstance(exc, ScratchpadError):
        await ctx.error(f"Scratchpad error: {exc.message}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"操作失败: {exc.message}")],
            isError=True,
        )

    else:
        # Unexpected exception
        logger.exception(f"Unexpected error in tool {tool_name}: {exc}")
        await ctx.error(f"Internal error: {str(exc)}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"内部错误: {str(exc)}")],
            isError=True,
        )


async def handle_tool_exception_xml(
    exc: Exception, tool_name: str, ctx: Context
) -> ToolResult:
    """Handle exceptions in tool functions and return XML format"""

    error_code = "UNKNOWN_ERROR"
    if isinstance(exc, ValidationError):
        error_code = "VALIDATION_ERROR"
    elif isinstance(exc, ScratchpadFileNotFoundError):
        error_code = "FILE_NOT_FOUND"
    elif isinstance(exc, ConfigurationError):
        error_code = "CONFIG_ERROR"
    elif isinstance(exc, FileTooLargeError):
        error_code = "FILE_TOO_LARGE"
    elif isinstance(exc, PermissionDeniedError):
        error_code = "PERMISSION_DENIED"
    elif isinstance(exc, StorageError):
        error_code = "STORAGE_ERROR"
    elif isinstance(exc, ScratchpadError):
        error_code = "SCRATCHPAD_ERROR"

    await ctx.error(f"Error in {tool_name}: {exc}")

    # 构建 XML 错误信息
    error_xml = build_error_xml(str(exc), tool_name, error_code)

    return create_tool_result_xml(
        xml_contents=error_xml,
        structured_data={
            "error": str(exc),
            "tool_name": tool_name,
            "error_code": error_code,
        },
    )


def safe_execute_tool(tool_func, *args, ctx: Context = None, **kwargs) -> Any:
    """Safely execute a tool function with error handling"""
    try:
        return tool_func(*args, **kwargs)
    except Exception as exc:
        if ctx:
            return handle_tool_exception(exc, tool_func.__name__, ctx)
        raise
