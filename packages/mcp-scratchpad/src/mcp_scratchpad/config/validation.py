"""
Configuration validation utilities
"""

from .settings import ServerConfig


def validate_config(config: ServerConfig) -> list[str]:
    """
    Validate configuration and return list of errors

    Args:
        config: Server configuration instance

    Returns:
        List of validation error messages
    """
    errors = []

    # Validate file size
    if config.max_file_size <= 0:
        errors.append("max_file_size must be positive")

    if config.max_file_size > 100 * 1024 * 1024:  # 100MB
        errors.append("max_file_size should not exceed 100MB for performance reasons")

    # Validate port
    if config.port < 1 or config.port > 65535:
        errors.append("port must be between 1 and 65535")

    # Validate namespaces
    if not config.allowed_namespaces:
        errors.append("allowed_namespaces cannot be empty")

    for namespace in config.allowed_namespaces:
        if not namespace or not namespace.strip():
            errors.append("namespace names cannot be empty")
        if "/" in namespace or "\\" in namespace:
            errors.append(f"namespace '{namespace}' cannot contain path separators")

    # Validate base directory
    if config.base_dir and not config.base_dir.parent.exists():
        errors.append(f"base directory parent does not exist: {config.base_dir.parent}")

    return errors


def is_config_valid(config: ServerConfig) -> bool:
    """
    Check if configuration is valid

    Args:
        config: Server configuration instance

    Returns:
        True if configuration is valid, False otherwise
    """
    return len(validate_config(config)) == 0
