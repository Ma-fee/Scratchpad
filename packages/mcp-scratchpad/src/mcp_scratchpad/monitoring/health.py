"""
Health check functionality for MCP Scratchpad
"""

import datetime
import logging
from pathlib import Path
from typing import Any

from ..config.settings import config
from ..storage import get_store

logger = logging.getLogger(__name__)


class HealthChecker:
    """Health checker for MCP Scratchpad"""

    def __init__(self):
        self.start_time = datetime.datetime.now(datetime.UTC)

    def check_storage(self) -> dict[str, Any]:
        """Check storage health"""
        try:
            store = get_store()
            base_dir = store.base_dir

            # Check if base directory exists and is writable
            if not base_dir.exists():
                return {
                    "status": "unhealthy",
                    "message": f"Base directory does not exist: {base_dir}",
                }

            if not base_dir.is_dir():
                return {
                    "status": "unhealthy",
                    "message": f"Base path is not a directory: {base_dir}",
                }

            # Test write access
            test_file = base_dir / ".health_check"
            try:
                test_file.write_text("health_check")
                test_file.unlink()
            except Exception as exc:
                return {
                    "status": "unhealthy",
                    "message": f"Cannot write to base directory: {exc}",
                }

            return {
                "status": "healthy",
                "base_directory": str(base_dir),
                "free_space": self._get_free_space(base_dir),
            }

        except Exception as exc:
            logger.error(f"Storage health check failed: {exc}")
            return {"status": "unhealthy", "message": f"Storage check failed: {exc}"}

    def check_configuration(self) -> dict[str, Any]:
        """Check configuration health"""
        try:
            from ..config.validation import validate_config

            errors = validate_config(config)
            if errors:
                return {
                    "status": "unhealthy",
                    "message": "Configuration validation failed",
                    "errors": errors,
                }

            return {
                "status": "healthy",
                "transport": config.transport,
                "max_file_size": config.max_file_size,
                "allowed_namespaces": config.allowed_namespaces,
            }

        except Exception as exc:
            logger.error(f"Configuration health check failed: {exc}")
            return {
                "status": "unhealthy",
                "message": f"Configuration check failed: {exc}",
            }

    def get_uptime(self) -> str:
        """Get server uptime"""
        uptime = datetime.datetime.now(datetime.UTC) - self.start_time
        return str(uptime).split(".")[0]  # Remove microseconds

    def get_system_info(self) -> dict[str, Any]:
        """Get system information"""
        return {
            "start_time": self.start_time.isoformat() + "Z",
            "uptime": self.get_uptime(),
            "version": "2.1.0",
            "python_version": f"{datetime.datetime.now().year}",  # Simple version check
        }

    def comprehensive_health_check(self) -> dict[str, Any]:
        """Perform comprehensive health check"""
        storage_health = self.check_storage()
        config_health = self.check_configuration()
        system_info = self.get_system_info()

        # Determine overall status
        overall_status = "healthy"
        unhealthy_components = []

        if storage_health["status"] != "healthy":
            overall_status = "unhealthy"
            unhealthy_components.append("storage")

        if config_health["status"] != "healthy":
            overall_status = "unhealthy"
            unhealthy_components.append("configuration")

        return {
            "status": overall_status,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
            "components": {"storage": storage_health, "configuration": config_health},
            "system": system_info,
            "unhealthy_components": unhealthy_components,
        }

    def _get_free_space(self, path: Path) -> int | None:
        """Get free space in bytes for the given path"""
        try:
            import shutil

            return shutil.disk_usage(path).free
        except Exception:
            return None


# Global health checker instance
health_checker = HealthChecker()
