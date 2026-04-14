"""
Standalone test runner for loader tests - avoids conftest dependencies.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add package to path
sys.path.insert(
    0, "/Users/yuchen.liu/src/yilab/mcp-scratchpad/packages/mcp-scratchpad/src"
)

import yaml
import pytest
from unittest.mock import patch

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
from mcp_scratchpad.config.settings import ServerConfig


def test_expand_env_vars_basic():
    """Test basic ${VAR} syntax expansion."""
    os.environ["TEST_VAR"] = "hello"
    result = expand_env_vars("${TEST_VAR}")
    assert result == "hello", f"Expected 'hello', got '{result}'"
    print("✓ test_expand_env_vars_basic passed")


def test_expand_env_vars_with_default_set():
    """Test ${VAR:default} when VAR is set."""
    os.environ["TEST_VAR2"] = "custom"
    result = expand_env_vars("${TEST_VAR2:default}")
    assert result == "custom", f"Expected 'custom', got '{result}'"
    print("✓ test_expand_env_vars_with_default_set passed")


def test_expand_env_vars_with_default_unset():
    """Test ${VAR:default} when VAR is not set."""
    os.environ.pop("TEST_UNSET_VAR", None)
    result = expand_env_vars("${TEST_UNSET_VAR:default}")
    assert result == "default", f"Expected 'default', got '{result}'"
    print("✓ test_expand_env_vars_with_default_unset passed")


def test_expand_env_vars_unset_no_default():
    """Test ${VAR} when VAR is not set."""
    os.environ.pop("TEST_UNSET_VAR2", None)
    result = expand_env_vars("${TEST_UNSET_VAR2}")
    assert result == "", f"Expected '', got '{result}'"
    print("✓ test_expand_env_vars_unset_no_default passed")


def test_expand_env_vars_multiple():
    """Test multiple vars in same string."""
    os.environ["VAR1"] = "first"
    os.environ["VAR2"] = "second"
    result = expand_env_vars("${VAR1} and ${VAR2}")
    assert result == "first and second", f"Expected 'first and second', got '{result}'"
    print("✓ test_expand_env_vars_multiple passed")


def test_expand_env_vars_mixed_with_defaults():
    """Test mixed set/unset vars with defaults."""
    os.environ["SET_VAR"] = "value"
    os.environ.pop("UNSET_VAR", None)
    result = expand_env_vars("prefix/${SET_VAR}/middle/${UNSET_VAR:default}/suffix")
    assert result == "prefix/value/middle/default/suffix"
    print("✓ test_expand_env_vars_mixed_with_defaults passed")


def test_expand_env_vars_no_match():
    """Test string without env vars is unchanged."""
    result = expand_env_vars("no variables here")
    assert result == "no variables here"
    print("✓ test_expand_env_vars_no_match passed")


def test_expand_env_vars_regex_pattern():
    """Test that regex pattern matches expected formats."""
    # Should match
    assert ENV_VAR_PATTERN.match("${VAR}")
    assert ENV_VAR_PATTERN.match("${VAR:default}")
    assert ENV_VAR_PATTERN.match("${VAR:with:colons}")
    # Should not match
    assert not ENV_VAR_PATTERN.match("$VAR")
    assert not ENV_VAR_PATTERN.match("{VAR}")
    assert not ENV_VAR_PATTERN.match("${}")
    print("✓ test_expand_env_vars_regex_pattern passed")


def test_expand_nested_dict():
    """Test expansion in nested dictionaries."""
    os.environ["SOURCE"] = "file:///custom/path"
    config = {"mounts": [{"name": "test", "source": "${SOURCE}"}]}
    result = expand_config_dict(config)
    assert result["mounts"][0]["source"] == "file:///custom/path"
    print("✓ test_expand_nested_dict passed")


def test_expand_non_string_values():
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
    print("✓ test_expand_non_string_values passed")


def test_find_config_file_explicit_exists(tmp_path: Path):
    """Test explicit path returns file if exists."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("mounts: []")
    result = find_config_file(config_file)
    assert result == config_file
    print("✓ test_find_config_file_explicit_exists passed")


def test_find_config_file_explicit_not_exists(tmp_path: Path):
    """Test explicit path returns None if not exists."""
    non_existent = tmp_path / "not_here.yaml"
    result = find_config_file(non_existent)
    assert result is None
    print("✓ test_find_config_file_explicit_not_exists passed")


def test_load_valid_yaml(tmp_path: Path):
    """Test loading valid YAML file."""
    config_file = tmp_path / "config.yaml"
    config_data = {"mounts": [{"name": "test", "source": "file:///test"}]}
    config_file.write_text(yaml.dump(config_data))
    result = load_yaml_config(config_file)
    assert result == config_data
    print("✓ test_load_valid_yaml passed")


def test_load_yaml_with_env_expansion(tmp_path: Path):
    """Test loading YAML with env vars expanded."""
    os.environ["MOUNT_PATH"] = "/expanded/path"
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
mounts:
  - name: test
    source: file://${MOUNT_PATH}
""")
    result = load_yaml_config(config_file)
    assert result["mounts"][0]["source"] == "file:///expanded/path"
    print("✓ test_load_yaml_with_env_expansion passed")


def test_load_invalid_yaml_raises_error(tmp_path: Path):
    """Test invalid YAML raises ConfigValidationError."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("invalid: yaml: [{")
    try:
        load_yaml_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "Invalid YAML" in str(e)
    print("✓ test_load_invalid_yaml_raises_error passed")


def test_load_empty_file(tmp_path: Path):
    """Test loading empty file returns empty dict."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("")
    result = load_yaml_config(config_file)
    assert result == {}
    print("✓ test_load_empty_file passed")


def test_load_overlay_config_from_file(tmp_path: Path):
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
    print("✓ test_load_overlay_config_from_file passed")


def test_feature_flags_default_false() -> None:
    """Test feature flag defaults are disabled."""
    with patch.dict(os.environ, {}, clear=True):
        config = ServerConfig()

    assert config.feature_unified_overlay_fs is False
    assert config.feature_canonical_uri_only is False
    assert config.feature_event_driven_subscriptions is False
    assert config.feature_dual_write_legacy_store is False
    print("✓ test_feature_flags_default_false passed")


def test_expand_environment_variables_in_config(tmp_path: Path):
    """Test that environment variables are expanded in loaded config."""
    os.environ["TEST_MOUNT_PATH"] = "/tmp/test"
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
mounts:
  - name: test
    source: file://${TEST_MOUNT_PATH}
    mount_point: /test
    mode: ro
""")
    result = load_overlay_config(config_file)
    assert result.mounts[0].source == "file:///tmp/test"
    print("✓ test_expand_environment_variables_in_config passed")


def test_use_default_values_in_env_vars(tmp_path: Path):
    """Test ${VAR:default} syntax works in config."""
    os.environ.pop("UNSET_MOUNT_PATH", None)
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
mounts:
  - name: test
    source: file://${UNSET_MOUNT_PATH:/default/path}
    mount_point: /test
    mode: ro
""")
    result = load_overlay_config(config_file)
    assert result.mounts[0].source == "file:///default/path"
    print("✓ test_use_default_values_in_env_vars passed")


def test_loader_reads_rollout_flags(tmp_path: Path):
    """Test loader parses rollout flag overrides from overlay section."""
    config_file = tmp_path / "scratchpad.yaml"
    config_file.write_text(
        """
overlay:
  rollout:
    unified_overlay_fs: true
    canonical_uri_only: false
    event_driven_subscriptions: true
    dual_write_legacy_store: false
""".strip()
    )

    cfg = load_overlay_config(config_file)
    assert cfg.rollout.unified_overlay_fs is True
    assert cfg.rollout.canonical_uri_only is False
    assert cfg.rollout.event_driven_subscriptions is True
    assert cfg.rollout.dual_write_legacy_store is False
    print("✓ test_loader_reads_rollout_flags passed")


def test_load_overlay_config_accepts_shared_memory_namespace_mapping(
    tmp_path: Path,
):
    """Test loader parses top-level memory publish namespace config."""
    config_path = tmp_path / "scratchpad.yaml"
    config_path.write_text(
        """
overlay:
  rollout: {}
memory:
  publish:
    namespaces:
      users:
        backend: file
        root: /tmp/shared-memory/users
mounts: []
""".strip(),
        encoding="utf-8",
    )

    config = load_overlay_config(config_path)
    assert config.memory.publish.namespaces["users"].backend == "file"
    print("✓ test_load_overlay_config_accepts_shared_memory_namespace_mapping passed")


def test_overlay_section_must_be_mapping(tmp_path: Path):
    """The overlay section must be a mapping if provided."""
    config_file = tmp_path / "scratchpad.yaml"
    config_file.write_text(yaml.dump({"overlay": "not a mapping"}))

    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "overlay" in str(e)


@pytest.mark.parametrize("value", [[], 0, False, ""])
def test_overlay_rollout_must_be_mapping(tmp_path: Path, value):
    """Overlay rollout must be a mapping when defined."""
    config_file = tmp_path / "scratchpad.yaml"
    config_file.write_text(yaml.dump({"overlay": {"rollout": value}}))

    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "overlay.rollout" in str(e)


def test_missing_file_returns_default_config(tmp_path: Path):
    """Test missing config file returns default OverlayConfig."""
    non_existent = tmp_path / "not_here.yaml"
    result = load_overlay_config(non_existent)
    assert isinstance(result, OverlayConfig)
    assert result.mounts == []
    print("✓ test_missing_file_returns_default_config passed")


def test_no_config_found_returns_default():
    """Test when no config in standard locations returns default."""
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
    print("✓ test_no_config_found_returns_default passed")


def test_invalid_yaml_raises_clear_error(tmp_path: Path):
    """Test invalid YAML raises ConfigValidationError with clear message."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("invalid: yaml: [{")
    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "Invalid YAML" in str(e)
        assert str(config_file) in str(e)
    print("✓ test_invalid_yaml_raises_clear_error passed")


def test_invalid_mounts_type_raises_error(tmp_path: Path):
    """Test non-list mounts raises clear error."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"mounts": "not a list"}))
    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "'mounts' must be a list" in str(e)
    print("✓ test_invalid_mounts_type_raises_error passed")


def test_duplicate_mount_names_error(tmp_path: Path):
    """Test duplicate mount names in config raises validation error."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "mounts": [
                    {"name": "same", "source": "file:///a", "mount_point": "/a"},
                    {"name": "same", "source": "file:///b", "mount_point": "/b"},
                ]
            }
        )
    )
    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "Duplicate mount names" in str(e)
    print("✓ test_duplicate_mount_names_error passed")


def test_multiple_rw_mounts_error(tmp_path: Path):
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
    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "Multiple read-write mounts not allowed" in str(e)
    print("✓ test_multiple_rw_mounts_error passed")


def test_complex_config_with_all_fields(tmp_path: Path):
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
    print("✓ test_complex_config_with_all_fields passed")


def test_invalid_mount_validation_error(tmp_path: Path):
    """Test invalid mount config raises ConfigValidationError."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"mounts": [{"name": "", "source": "invalid"}]}))
    try:
        load_overlay_config(config_file)
        raise AssertionError("Should have raised ConfigValidationError")
    except ConfigValidationError as e:
        assert "Invalid mount" in str(e)
    print("✓ test_invalid_mount_validation_error passed")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Running loader.py unit tests")
    print("=" * 60)
    print()

    passed = 0
    failed = 0

    # Environment variable tests
    tests = [
        test_expand_env_vars_basic,
        test_expand_env_vars_with_default_set,
        test_expand_env_vars_with_default_unset,
        test_expand_env_vars_unset_no_default,
        test_expand_env_vars_multiple,
        test_expand_env_vars_mixed_with_defaults,
        test_expand_env_vars_no_match,
        test_expand_env_vars_regex_pattern,
        test_expand_nested_dict,
        test_expand_non_string_values,
    ]

    # Tests that need tmp_path
    tmp_path = Path(tempfile.mkdtemp())
    tmp_tests = [
        test_find_config_file_explicit_exists,
        test_find_config_file_explicit_not_exists,
        test_load_valid_yaml,
        test_load_yaml_with_env_expansion,
        test_load_invalid_yaml_raises_error,
        test_load_empty_file,
        test_load_overlay_config_from_file,
        test_expand_environment_variables_in_config,
        test_use_default_values_in_env_vars,
        test_missing_file_returns_default_config,
        test_invalid_yaml_raises_clear_error,
        test_invalid_mounts_type_raises_error,
        test_duplicate_mount_names_error,
        test_multiple_rw_mounts_error,
        test_complex_config_with_all_fields,
        test_invalid_mount_validation_error,
    ]

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1

    for test in tmp_tests:
        try:
            test(tmp_path)
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1

    # Cleanup
    import shutil

    shutil.rmtree(tmp_path, ignore_errors=True)

    # Tests that need special setup
    try:
        test_no_config_found_returns_default()
        passed += 1
    except Exception as e:
        print(f"✗ test_no_config_found_returns_default FAILED: {e}")
        failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
