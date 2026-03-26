"""
Configuration management for MCP Scratchpad
"""

from pathlib import Path

from pydantic import ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings


class ServerConfig(BaseSettings):
    """Server configuration with environment variable support"""

    # Basic server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8890, description="Server port")
    transport: str = Field(default="stdio", description="Transport mode")

    # File storage settings
    base_dir: Path | None = Field(
        default=None, description="Base directory for file storage"
    )
    max_file_size: int = Field(
        default=10 * 1024 * 1024, description="Max file size in bytes"
    )

    # Security settings
    allowed_namespaces: list[str] = Field(
        default=["session", "kb"], description="Allowed namespaces"
    )
    enable_path_validation: bool = Field(
        default=True, description="Enable path validation"
    )

    # Diff processing limits
    max_diff_lines: int = Field(
        default=1000, description="Maximum allowed diff line count per request"
    )
    max_diff_bytes: int = Field(
        default=1 * 1024 * 1024, description="Maximum allowed diff size in bytes"
    )

    # Logging settings
    log_level: str = Field(default="INFO", description="Log level")
    log_format: str = Field(default="text", description="Log format (json/text)")

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, v):
        valid_transports = ["stdio", "sse", "http", "streamable-http"]
        if v not in valid_transports:
            raise ValueError(f"transport must be one of {valid_transports}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    @field_validator("base_dir")
    @classmethod
    def resolve_base_dir(cls, v):
        if v is None:
            return Path("out/files").resolve()
        return Path(v).resolve()

    model_config = ConfigDict(
        env_prefix="MCP_SCRATCHPAD_", env_file=".env", case_sensitive=False
    )


# Global configuration instance
config = ServerConfig()
