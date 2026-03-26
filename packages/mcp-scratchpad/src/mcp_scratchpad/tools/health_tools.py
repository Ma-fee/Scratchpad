"""
Health check tools for FastMCP
"""

import logging
from typing import Any

from fastmcp import Context, FastMCP

from ..exceptions import handle_tool_exception
from ..exceptions.custom import ConfigurationError, StorageError
from ..monitoring.health import health_checker

logger = logging.getLogger(__name__)


def register_health_tools(mcp: FastMCP) -> None:
    """Register health check tools to FastMCP server"""

    @mcp.tool(name="scratchpad_health_check")
    async def health_check(ctx: Context) -> dict[str, Any]:
        """Perform comprehensive health check of the MCP Scratchpad server"""
        logger.info("Performing health check")
        await ctx.info("Performing comprehensive health check")

        try:
            health_result = health_checker.comprehensive_health_check()
            await _report_health_status(ctx, health_result)
            return health_result

        except (StorageError, ConfigurationError) as exc:
            return await _handle_business_logic_error(exc, ctx, "health_check")

        except Exception as exc:
            logger.exception("Health check system error")
            return await handle_tool_exception(exc, "health_check", ctx)

    @mcp.tool(name="scratchpad_system_info")
    async def system_info(ctx: Context) -> dict[str, Any]:
        """Get system information and server status"""
        logger.info("Getting system info")
        await ctx.info("Retrieving system information")

        try:
            return health_checker.get_system_info()
        except Exception as exc:
            logger.exception("Failed to get system info")
            return await handle_tool_exception(exc, "system_info", ctx)

    @mcp.tool(name="scratchpad_storage_status")
    async def storage_status(ctx: Context) -> dict[str, Any]:
        """Check storage system status"""
        logger.info("Checking storage status")
        await ctx.info("Checking storage system health")

        try:
            storage_health = health_checker.check_storage()
            await _report_storage_status(ctx, storage_health)
            return storage_health

        except (StorageError, OSError, PermissionError) as exc:
            return await _handle_storage_error(exc, ctx)

        except Exception as exc:
            logger.exception("Storage status check system error")
            return await handle_tool_exception(exc, "storage_status", ctx)


async def _report_health_status(ctx: Context, health_result: dict[str, Any]) -> None:
    """Report health check status based on results"""
    if health_result["status"] == "healthy":
        await ctx.info("All systems healthy")
    else:
        await ctx.warning(
            f"Health issues detected: {health_result['unhealthy_components']}"
        )


async def _report_storage_status(ctx: Context, storage_health: dict[str, Any]) -> None:
    """Report storage status based on results"""
    if storage_health["status"] == "healthy":
        await ctx.info("Storage system healthy")
    else:
        await ctx.warning(f"Storage issues: {storage_health['message']}")


async def _handle_business_logic_error(
    exc: Exception, ctx: Context, tool_name: str
) -> dict[str, Any]:
    """Handle business logic exceptions for health checks"""
    logger.exception(f"{tool_name} business logic failed")
    await ctx.error(f"{tool_name} failed: {exc}")
    try:
        system_info = health_checker.get_system_info()
    except Exception:
        system_info = {"start_time": "unknown"}

    return {
        "status": "unhealthy",
        "timestamp": system_info.get("start_time", "unknown"),
        "error": str(exc),
        "components": {},
        "system": system_info,
        "unhealthy_components": [tool_name],
    }


async def _handle_storage_error(exc: Exception, ctx: Context) -> dict[str, Any]:
    """Handle storage-related exceptions"""
    logger.exception("Storage status check business logic failed")
    await ctx.error(f"Storage status check failed: {exc}")
    return {"status": "unhealthy", "message": f"Storage check failed: {exc}"}
