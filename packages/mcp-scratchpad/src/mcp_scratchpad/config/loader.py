"""
Configuration loader for overlay filesystem with environment variable support.

This module provides functionality to load overlay filesystem configurations
from YAML files with support for environment variable expansion using
`${VAR}` and `${VAR:default}` syntax.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from mcp_scratchpad.config.models import MountConfig, OverlayConfig
from mcp_scratchpad.exceptions import ConfigurationError

# Regex pattern for environment variable expansion
# Matches ${VAR} or ${VAR:default} syntax
ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")

# Standard config locations in order of precedence
STANDARD_CONFIG_LOCATIONS = [
    Path("./scratchpad.yaml"),
    Path.home() / ".config" / "mcp-scratchpad" / "config.yaml",
    Path("/etc") / "mcp-scratchpad" / "config.yaml",
]


class ConfigValidationError(ConfigurationError):
    """Raised when configuration validation fails during load."""

    pass


def expand_env_vars(value: str) -> str:
    """Expand environment variables in a string.

    Supports two syntaxes:
    - `${VAR}` - expands to value of VAR or empty string if not set
    - `${VAR:default}` - expands to value of VAR or 'default' if not set

    Args:
        value: String potentially containing ${VAR} or ${VAR:default} patterns

    Returns:
        String with all environment variables expanded

    Example:
        >>> os.environ['TEST_VAR'] = 'hello'
        >>> expand_env_vars('${TEST_VAR}')
        'hello'
        >>> expand_env_vars('${UNSET_VAR:default}')
        'default'
    """

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2) if match.group(2) is not None else ""
        return os.environ.get(var_name, default_value)

    return ENV_VAR_PATTERN.sub(replacer, value)


def expand_config_dict(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Recursively expand environment variables in a configuration dictionary.

    Args:
        config_dict: Dictionary potentially containing environment variable patterns

    Returns:
        Dictionary with all string values having environment variables expanded
    """

    def expand_value(value: Any) -> Any:
        if isinstance(value, str):
            return expand_env_vars(value)
        elif isinstance(value, dict):
            return {k: expand_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [expand_value(item) for item in value]
        else:
            return value

    return expand_value(config_dict)


def find_config_file(config_path: Path | str | None = None) -> Path | None:
    """Find configuration file.

    If config_path is provided and exists, returns it directly.
    If config_path is None, searches standard locations in order.

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Path to config file if found, None otherwise
    """
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            return path
        return None

    for location in STANDARD_CONFIG_LOCATIONS:
        if location.exists():
            return location

    return None


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load and parse YAML configuration file.

    Performs environment variable expansion on the raw file content
    before parsing as YAML.

    Args:
        path: Path to YAML config file

    Returns:
        Parsed configuration dictionary with env vars expanded

    Raises:
        FileNotFoundError: If file does not exist (but loader handles this)
        ConfigValidationError: If YAML is invalid
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw_content = f.read()
    except FileNotFoundError:
        raise

    # First expand environment variables in the raw content
    expanded_content = expand_env_vars(raw_content)

    try:
        config_dict = yaml.safe_load(expanded_content)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Invalid YAML in config file '{path}': {e}") from e

    if config_dict is None:
        config_dict = {}

    return config_dict


def load_overlay_config(
    config_path: Path | str | None = None,
) -> OverlayConfig:
    """Load overlay configuration from YAML file.

    Loads configuration from a YAML file with environment variable expansion.
    If no config_path is provided, searches standard locations.
    If no config file is found, returns default OverlayConfig with empty mounts.

    Args:
        config_path: Optional explicit path to config file. If None,
            searches standard locations: ./scratchpad.yaml,
            ~/.config/mcp-scratchpad/config.yaml,
            /etc/mcp-scratchpad/config.yaml

    Returns:
        OverlayConfig instance with loaded configuration

    Raises:
        ConfigValidationError: If YAML is invalid or config validation fails

    Example:
        >>> config = load_overlay_config("/path/to/config.yaml")
        >>> print(config.mounts)
        [MountConfig(...)]
    """
    # Find config file
    found_path = find_config_file(config_path)

    if found_path is None:
        # No config file found - return default empty config
        return OverlayConfig(mounts=[])

    try:
        config_dict = load_yaml_config(found_path)
    except FileNotFoundError:
        # File was found but then deleted (race condition)
        return OverlayConfig(mounts=[])

    overlay_section = config_dict.get("overlay")
    if overlay_section is not None and not isinstance(overlay_section, dict):
        raise ConfigValidationError(
            f"Invalid config in '{found_path}': 'overlay' must be a mapping"
        )

    mounts_data = config_dict.get("mounts", [])

    if not isinstance(mounts_data, list):
        raise ConfigValidationError(
            f"Invalid config in '{found_path}': 'mounts' must be a list"
        )

    mounts = []
    for i, mount_data in enumerate(mounts_data):
        if not isinstance(mount_data, dict):
            raise ConfigValidationError(
                f"Invalid mount at index {i} in '{found_path}': "
                f"expected dict, got {type(mount_data).__name__}"
            )

        try:
            mount = MountConfig.model_validate(mount_data)
        except Exception as e:
            raise ConfigValidationError(
                f"Invalid mount at index {i} in '{found_path}': {e}"
            ) from e

        mounts.append(mount)

    rollout_data = {}
    if overlay_section:
        rollout_value = overlay_section.get("rollout", {}) or {}
        if rollout_value and not isinstance(rollout_value, dict):
            raise ConfigValidationError(
                f"Invalid config in '{found_path}': 'overlay.rollout' must be a mapping"
            )
        rollout_data = rollout_value

    try:
        overlay_config = OverlayConfig(mounts=mounts, rollout=rollout_data)
    except Exception as e:
        raise ConfigValidationError(
            f"Invalid overlay configuration in '{found_path}': {e}"
        ) from e

    return overlay_config
