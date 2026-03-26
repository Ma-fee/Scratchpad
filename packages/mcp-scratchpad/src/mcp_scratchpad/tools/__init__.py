# FastMCP 工具模块
from .file_tools import register_file_tools
from .health_tools import register_health_tools

__all__ = ["register_file_tools", "register_health_tools"]
