"""
Unit tests for configuration loader with environment variable support.
"""

import os
from pathlib import Path

import pytest
import yaml

from mcp_scratchpad.config.loader import (
    ENV_VAR_PATTERN,
    ConfigValidationError,
    expand_config_dict,
    expand_env_vars,
    find_config_file,
    load_overlay_config,
    load_yaml_config,
)
from mcp_scratchpad.config.models import OverlayConfig


class TestEnvVarExpansion:
    """Tests for environment variable expansion functionality."""

    def test_expand_env_vars_basic(self) -> None:
        """Test basic ${VAR} syntax expansion."""
        os.environ["TEST_VAR"] = "hello"
        result = expand_env_vars("${TEST_VAR}")
        assert result == "hello"

    def test_expand_env_vars_with_default_set(self) -> None:
        """Test ${VAR:default} when VAR is set."""
        os.environ["TEST_VAR"] = "custom"
        result = expand_env_vars("${TEST_VAR:default}")
        assert result == "custom"

    def test_expand_env_vars_with_default_unset(self) -> None:
        """Test ${VAR:default} when VAR is not set."""
        os.environ.pop("TEST_UNSET_VAR", None)
        result = expand_env_vars("${TEST_UNSET_VAR:default}")
        assert result == "default"

    def test_expand_env_vars_unset_no_default(self) -> None:
        """Test ${VAR} when VAR is not set."""
        os.environ.pop("TEST_UNSET_VAR", None)
        result = expand_env_vars("${TEST_UNSET_VAR}")
        assert result == ""

    def test_expand_env_vars_multiple(self) -> None:
        """Test multiple vars in same string."""
        os.environ["VAR1"] = "first"
        os.environ["VAR2"] = "second"
        result = expand_env_vars("${VAR1} and ${VAR2}")
        assert result == "first and second"

    def test_expand_env_vars_mixed_with_defaults(self) -> None:
        """Test mixed set/unset vars with defaults."""
        os.environ["SET_VAR"] = "value"
        os.environ.pop("UNSET_VAR", None)
        result = expand_env_vars("prefix/${SET_VAR}/middle/${UNSET_VAR:default}/suffix")
        assert result == "prefix/value/middle/default/suffix"

    def test_expand_env_vars_no_match(self) -> None:
        """Test string without env vars is unchanged."""
        result = expand_env_vars("no variables here")
        assert result == "no variables here"

    def test_expand_env_vars_regex_pattern(self) -> None:
        """Test that regex pattern matches expected formats."""
        # Should match
        assert ENV_VAR_PATTERN.match("${VAR}")
        assert ENV_VAR_PATTERN.match("${VAR:default}")
        assert ENV_VAR_PATTERN.match("${VAR:with:colons}")

        # Should not match
        assert not ENV_VAR_PATTERN.match("$VAR")
        assert not ENV_VAR_PATTERN.match("{VAR}")
        assert not ENV_VAR_PATTERN.match("${}")


class TestConfigDictExpansion:
    """Tests for recursive config dictionary expansion."""

    def test_expand_nested_dict(self) -> None:
        """Test expansion in nested dictionaries."""
        os.environ["SOURCE"] = "file:///custom/path"
        config = {
            "mounts": [
                {"name": "test", "source": "${SOURCE}"},
            ]
        }
        result = expand_config_dict(config)
        assert result["mounts"][0]["source"] == "file:///custom/path"

    def test_expand_deeply_nested(self) -> None:
        """Test expansion in deeply nested structures."""
        os.environ["LEVEL1"] = "value1"
        os.environ["LEVEL2"] = "value2"
        config = {
            "level1": {
                "nested": {"value": "${LEVEL1}"},
                "list": ["${LEVEL2}", "static"],
            }
        }
        result = expand_config_dict(config)
        assert result["level1"]["nested"]["value"] == "value1"
        assert result["level1"]["list"] == ["value2", "static"]

    def test_expand_non_string_values(self) -> None:
        """Test that non-string values are preserved."""
        config = {
            "number": 42,
            "boolean": True,
            "null_value": None,
            "list": [1, 2, 3],
        }
        result = expand_config_dict(config)
        assert result["number"] == 42
        assert result["boolean"] is True
        assert result["null_value"] is None
        assert result["list"] == [1, 2, 3]


class TestFindConfigFile:
    """Tests for config file discovery."""

    def test_explicit_path_exists(self, tmp_path: Path) -> None:
        """Test explicit path returns file if exists."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("mounts: []")
        result = find_config_file(config_file)
        assert result == config_file

    def test_explicit_path_not_exists(self, tmp_path: Path) -> None:
        """Test explicit path returns None if not exists."""
        non_existent = tmp_path / "not_here.yaml"
        result = find_config_file(non_existent)
        assert result is None

    def test_explicit_path_str(self, tmp_path: Path) -> None:
        """Test explicit path can be string."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("mounts: []")
        result = find_config_file(str(config_file))
        assert result == config_file

    def test_none_searches_standard_locations(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test None searches standard locations."""
        # Create config in current directory (will be searched first)
        config_file = tmp_path / "scratchpad.yaml"
        config_file.write_text("mounts: []")

        # Mock the first standard location
        original_cwd = Path.cwd()
        monkeypatch.chdir(tmp_path)
        try:
            result = find_config_file(None)
            assert result == config_file
        finally:
            monkeypatch.chdir(original_cwd)


class TestLoadYamlConfig:
    """Tests for YAML loading with env expansion."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """Test loading valid YAML file."""
        config_file = tmp_path / "config.yaml"
        config_data = {"mounts": [{"name": "test", "source": "file:///test"}]}
        config_file.write_text(yaml.dump(config_data))

        result = load_yaml_config(config_file)
        assert result == config_data

    def test_load_yaml_with_env_expansion(self, tmp_path: Path) -> None:
        """Test loading YAML with env vars expanded."""
        os.environ["MOUNT_PATH"] = "/expanded/path"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
mounts:
  - name: test
    source: file://${MOUNT_PATH}
"""
        )

        result = load_yaml_config(config_file)
        assert result["mounts"][0]["source"] == "file:///expanded/path"

    def test_load_invalid_yaml_raises_error(self, tmp_path: Path) -> None:
        """Test invalid YAML raises ConfigValidationError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: [{")

        with pytest.raises(ConfigValidationError) as exc_info:
            load_yaml_config(config_file)
        assert "Invalid YAML" in str(exc_info.value)

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading empty file returns empty dict."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        result = load_yaml_config(config_file)
        assert result == {}


class TestLoadOverlayConfig:
    """Tests for load_overlay_config function."""

    def test_load_config_from_file(self, tmp_path: Path) -> None:
        """Test loading config from explicit file path."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "mounts": [
                {
                    "name": "base",
                    "source": "file:///base",
                    "mount_point": "/base",
                    "mode": "ro",
                }
            ]
        }
        config_file.write_text(yaml.dump(config_data))

        result = load_overlay_config(config_file)
        assert len(result.mounts) == 1
        assert result.mounts[0].name == "base"
        assert result.mounts[0].source == "file:///base"

    def test_expand_environment_variables_in_config(self, tmp_path: Path) -> None:
        """Test that environment variables are expanded in loaded config."""
        os.environ["TEST_MOUNT_PATH"] = "/tmp/test"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
mounts:
  - name: test
    source: file://${TEST_MOUNT_PATH}
    mount_point: /test
    mode: ro
"""
        )

        result = load_overlay_config(config_file)
        assert result.mounts[0].source == "file:///tmp/test"

    def test_use_default_values_in_env_vars(self, tmp_path: Path) -> None:
        """Test ${VAR:default} syntax works in config."""
        os.environ.pop("UNSET_MOUNT_PATH", None)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
mounts:
  - name: test
    source: file://${UNSET_MOUNT_PATH:/default/path}
    mount_point: /test
    mode: ro
"""
        )

        result = load_overlay_config(config_file)
        assert result.mounts[0].source == "file:///default/path"

    def test_missing_file_returns_default_config(self, tmp_path: Path) -> None:
        """Test missing config file returns default OverlayConfig."""
        non_existent = tmp_path / "not_here.yaml"
        result = load_overlay_config(non_existent)
        assert isinstance(result, OverlayConfig)
        assert result.mounts == []

    def test_no_config_found_returns_default(self) -> None:
        """Test when no config in standard locations returns default."""
        # Temporarily change standard locations to non-existent paths
        import mcp_scratchpad.config.loader as loader

        original_locations = loader.STANDARD_CONFIG_LOCATIONS.copy()
        loader.STANDARD_CONFIG_LOCATIONS = [
            Path("/nonexistent/path1.yaml"),
            Path("/nonexistent/path2.yaml"),
        ]

        try:
            result = load_overlay_config(None)
            assert isinstance(result, OverlayConfig)
            assert result.mounts == []
        finally:
            loader.STANDARD_CONFIG_LOCATIONS = original_locations

    def test_invalid_yaml_raises_clear_error(self, tmp_path: Path) -> None:
        """Test invalid YAML raises ConfigValidationError with clear message."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: [{")

        with pytest.raises(ConfigValidationError) as exc_info:
            load_overlay_config(config_file)
        assert "Invalid YAML" in str(exc_info.value)
        assert str(config_file) in str(exc_info.value)

    def test_invalid_mount_validation_error(self, tmp_path: Path) -> None:
        """Test invalid mount config raises ConfigValidationError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"mounts": [{"name": "", "source": "invalid"}]})
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            load_overlay_config(config_file)
        assert "Invalid mount" in str(exc_info.value)

    def test_invalid_mounts_type_raises_error(self, tmp_path: Path) -> None:
        """Test non-list mounts raises clear error."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"mounts": "not a list"}))

        with pytest.raises(ConfigValidationError) as exc_info:
            load_overlay_config(config_file)
        assert "'mounts' must be a list" in str(exc_info.value)

    def test_duplicate_mount_names_error(self, tmp_path: Path) -> None:
        """Test duplicate mount names in config raises validation error."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mounts": [
                        {
                            "name": "same",
                            "source": "file:///a",
                            "mount_point": "/a",
                        },
                        {
                            "name": "same",
                            "source": "file:///b",
                            "mount_point": "/b",
                        },
                    ]
                }
            )
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            load_overlay_config(config_file)
        assert "Duplicate mount names" in str(exc_info.value)

    def test_multiple_rw_mounts_error(self, tmp_path: Path) -> None:
        """Test multiple RW mounts in config raises validation error."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mounts": [
                        {
                            "name": "a",
                            "source": "file:///a",
                            "mount_point": "/a",
                            "mode": "rw",
                        },
                        {
                            "name": "b",
                            "source": "file:///b",
                            "mount_point": "/b",
                            "mode": "rw",
                        },
                    ]
                }
            )
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            load_overlay_config(config_file)
        assert "Multiple read-write mounts not allowed" in str(exc_info.value)

    def test_complex_config_with_all_fields(self, tmp_path: Path) -> None:
        """Test loading complex config with all mount fields."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mounts": [
                        {
                            "name": "base_templates",
                            "source": "file:///var/templates",
                            "mount_point": "/templates",
                            "mode": "ro",
                            "priority": 10,
                            "options": {"encoding": "utf-8"},
                        },
                        {
                            "name": "workspace",
                            "source": "memory://",
                            "mount_point": "/workspace",
                            "mode": "rw",
                            "priority": 5,
                            "options": {"max_size": 1000000},
                        },
                    ]
                }
            )
        )

        result = load_overlay_config(config_file)
        assert len(result.mounts) == 2
        assert result.mounts[0].name == "base_templates"
        assert result.mounts[1].mode == "rw"
        assert result.mounts[1].options["max_size"] == 1000000


class TestSearchStandardLocations:
    """Tests for standard config location search."""

    def test_discovers_scratchpad_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test discovering ./scratchpad.yaml."""
        config_file = tmp_path / "scratchpad.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mounts": [
                        {
                            "name": "test",
                            "source": "file:///test",
                            "mount_point": "/test",
                            "mode": "ro",
                        }
                    ]
                }
            )
        )

        original_cwd = Path.cwd()
        monkeypatch.chdir(tmp_path)
        try:
            result = load_overlay_config(None)
            assert len(result.mounts) == 1
            assert result.mounts[0].name == "test"
        finally:
            monkeypatch.chdir(original_cwd)

    def test_explicit_path_overrides_search(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test explicit path is used even if standard file exists."""
        # Create standard file
        std_file = tmp_path / "scratchpad.yaml"
        std_file.write_text(yaml.dump({"mounts": [{"name": "std"}]}))

        # Create explicit file
        explicit_file = tmp_path / "explicit.yaml"
        explicit_file.write_text(
            yaml.dump(
                {
                    "mounts": [
                        {
                            "name": "explicit",
                            "source": "file:///explicit",
                            "mount_point": "/explicit",
                            "mode": "ro",
                        }
                    ]
                }
            )
        )

        original_cwd = Path.cwd()
        monkeypatch.chdir(tmp_path)
        try:
            result = load_overlay_config(explicit_file)
            assert result.mounts[0].name == "explicit"
        finally:
            monkeypatch.chdir(original_cwd)
