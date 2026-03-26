"""
Unit tests for configuration module
"""

from pathlib import Path

import pytest

from mcp_scratchpad.config.settings import ServerConfig
from mcp_scratchpad.config.validation import is_config_valid, validate_config


class TestServerConfig:
    """Test ServerConfig functionality"""

    @pytest.mark.unit
    def test_default_config(self):
        """Test default configuration values"""
        config = ServerConfig()

        assert config.host == "0.0.0.0"
        assert config.port == 8890
        assert config.transport == "stdio"
        assert config.max_file_size == 10 * 1024 * 1024
        assert config.allowed_namespaces == ["session", "kb"]
        assert config.log_level == "INFO"
        assert config.enable_path_validation is True

    @pytest.mark.unit
    def test_config_validation_transport(self):
        """Test transport validation"""
        with pytest.raises(ValueError, match="transport must be either"):
            ServerConfig(transport="invalid")

        # Valid transports should not raise
        ServerConfig(transport="stdio")
        ServerConfig(transport="sse")

    @pytest.mark.unit
    def test_config_validation_log_level(self):
        """Test log level validation"""
        with pytest.raises(ValueError, match="log_level must be one of"):
            ServerConfig(log_level="invalid")

        # Valid log levels should not raise
        ServerConfig(log_level="DEBUG")
        ServerConfig(log_level="INFO")
        ServerConfig(log_level="WARNING")
        ServerConfig(log_level="ERROR")
        ServerConfig(log_level="CRITICAL")

    @pytest.mark.unit
    def test_base_dir_resolution(self):
        """Test base directory resolution"""
        # None should resolve to default
        config = ServerConfig(base_dir=None)
        assert config.base_dir == Path("out/files").resolve()

        # Relative path should be resolved
        config = ServerConfig(base_dir="test/files")
        assert config.base_dir.is_absolute()
        assert config.base_dir.name == "files"

        # Absolute path should remain absolute
        abs_path = Path("/tmp/test")
        abs_path.mkdir(
            parents=True, exist_ok=True
        )  # Create directory to avoid FileNotFoundError
        config = ServerConfig(base_dir=abs_path)
        # On macOS, /tmp is often a symlink to /private/tmp
        assert config.base_dir.samefile(abs_path) or config.base_dir == abs_path
        abs_path.rmdir()  # Clean up


class TestConfigValidation:
    """Test configuration validation"""

    @pytest.mark.unit
    def test_valid_config(self, test_config):
        """Test validation of valid configuration"""
        errors = validate_config(test_config)
        assert len(errors) == 0
        assert is_config_valid(test_config) is True

    @pytest.mark.unit
    def test_invalid_max_file_size(self):
        """Test validation of invalid max file size"""
        config = ServerConfig(max_file_size=-1)
        errors = validate_config(config)
        assert any("max_file_size must be positive" in error for error in errors)
        assert is_config_valid(config) is False

    @pytest.mark.unit
    def test_invalid_port(self):
        """Test validation of invalid port"""
        config = ServerConfig(port=0)
        errors = validate_config(config)
        assert any("port must be between 1 and 65535" in error for error in errors)
        assert is_config_valid(config) is False

        config = ServerConfig(port=70000)
        errors = validate_config(config)
        assert any("port must be between 1 and 65535" in error for error in errors)
        assert is_config_valid(config) is False

    @pytest.mark.unit
    def test_invalid_namespaces(self):
        """Test validation of invalid namespaces"""
        config = ServerConfig(allowed_namespaces=[])
        errors = validate_config(config)
        assert any("allowed_namespaces cannot be empty" in error for error in errors)
        assert is_config_valid(config) is False

        config = ServerConfig(allowed_namespaces=[""])
        errors = validate_config(config)
        assert any("namespace names cannot be empty" in error for error in errors)
        assert is_config_valid(config) is False

        config = ServerConfig(allowed_namespaces=["valid/namespace"])
        errors = validate_config(config)
        assert any("cannot contain path separators" in error for error in errors)
        assert is_config_valid(config) is False

    @pytest.mark.unit
    def test_multiple_errors(self):
        """Test validation with multiple errors"""
        config = ServerConfig(max_file_size=-1, port=0, allowed_namespaces=[])
        errors = validate_config(config)
        assert len(errors) >= 3
        assert is_config_valid(config) is False
