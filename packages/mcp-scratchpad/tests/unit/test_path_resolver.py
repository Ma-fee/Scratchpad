"""Tests for path_resolver module."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_scratchpad.path_resolver import (
    PathResolutionError,
    build_uri,
    get_path_description,
    get_relative_path,
    parse_uri,
    resolve_file_path,
)
from mcp_scratchpad.storage import FileSystemStore


class TestParseUri:
    """Test URI parsing."""

    def test_parse_scratchpad_uri_absolute(self):
        """Parse scratchpad:///path/to/file"""
        scheme, path = parse_uri("scratchpad:///path/to/file")
        assert scheme == "scratchpad"
        assert path == "/path/to/file"

    def test_parse_scratchpad_uri_relative(self):
        """Parse scratchpad://path/to/file (without triple slash)"""
        scheme, path = parse_uri("scratchpad://path/to/file")
        assert scheme == "scratchpad"
        assert path == "/path/to/file"

    def test_parse_scratchpad_uri_with_extra_slashes(self):
        """Parse scratchpad://///path/to/file"""
        scheme, path = parse_uri("scratchpad://///path/to/file")
        assert scheme == "scratchpad"
        assert path == "/path/to/file"

    def test_parse_plain_path(self):
        """Plain paths default to scratchpad scheme"""
        scheme, path = parse_uri("path/to/file")
        assert scheme == "scratchpad"
        assert path == "path/to/file"

    def test_parse_absolute_plain_path(self):
        """Plain absolute paths work correctly"""
        scheme, path = parse_uri("/path/to/file")
        assert scheme == "scratchpad"
        assert path == "/path/to/file"

    def test_parse_empty_path_raises(self):
        """Empty path raises error"""
        with pytest.raises(PathResolutionError, match="Empty"):
            parse_uri("")

    def test_parse_unsupported_scheme_raises(self):
        """Unsupported scheme raises error"""
        with pytest.raises(PathResolutionError, match="Unsupported URI scheme"):
            parse_uri("file:///path/to/file")


class TestResolveFilePath:
    """Test path resolution."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a temp store for testing."""
        store = FileSystemStore(base_dir=tmp_path, size_limit_bytes=1024 * 1024)
        store.session_id = "test-session"
        return store

    def test_resolve_relative_path(self, store):
        """Relative path resolves against session dir"""
        resolved = resolve_file_path("reports/file.txt", store)
        expected = store._session_dir() / "reports/file.txt"
        assert resolved == expected.resolve()

    def test_resolve_absolute_path(self, store):
        """Absolute path resolves within session dir"""
        resolved = resolve_file_path("/reports/file.txt", store)
        expected = store._session_dir() / "reports/file.txt"
        assert resolved == expected.resolve()

    def test_resolve_uri_path(self, store):
        """URI path resolves correctly"""
        resolved = resolve_file_path("scratchpad:///reports/file.txt", store)
        expected = store._session_dir() / "reports/file.txt"
        assert resolved == expected.resolve()

    def test_resolve_creates_parent_dirs(self, store):
        """Parent directories are handled correctly"""
        resolved = resolve_file_path("deep/nested/path/file.txt", store)
        expected = store._session_dir() / "deep/nested/path/file.txt"
        assert resolved == expected.resolve()

    def test_resolve_path_traversal_blocked(self, store):
        """Path traversal attack is blocked"""
        with pytest.raises(PathResolutionError, match="outside"):
            resolve_file_path("../../../etc/passwd", store)

    def test_resolve_dot_components_normalized(self, store):
        """Dot and dotdot components are normalized"""
        resolved = resolve_file_path("dir1/../dir2/./file.txt", store)
        expected = store._session_dir() / "dir2/file.txt"
        assert resolved == expected.resolve()

    def test_resolve_backslash_converted(self, store):
        """Backslashes are converted to forward slashes"""
        resolved = resolve_file_path("reports\\file.txt", store)
        expected = store._session_dir() / "reports/file.txt"
        assert resolved == expected.resolve()


class TestGetRelativePath:
    """Test getting relative paths."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a temp store for testing."""
        store = FileSystemStore(base_dir=tmp_path, size_limit_bytes=1024 * 1024)
        store.session_id = "test-session"
        return store

    def test_get_relative_from_session_path(self, store):
        """Get relative path from session directory"""
        full = store._session_dir() / "reports/file.txt"
        rel = get_relative_path(full, store)
        assert rel == "reports/file.txt"

    def test_get_relative_returns_absolute_for_outside_path(self, store):
        """Outside paths are returned as absolute"""
        outside = Path("/outside/session/path.txt")
        rel = get_relative_path(outside, store)
        assert rel == "/outside/session/path.txt"


class TestBuildUri:
    """Test URI building."""

    def test_build_uri_simple(self):
        """Build URI from simple path"""
        uri = build_uri("reports/file.txt")
        assert uri == "scratchpad:///reports/file.txt"

    def test_build_uri_strips_leading_slash(self):
        """Leading slash is stripped from path"""
        uri = build_uri("/reports/file.txt")
        assert uri == "scratchpad:///reports/file.txt"


class TestGetPathDescription:
    """Test parameter description generation."""

    def test_description_contains_uri_format(self):
        """Description mentions URI format"""
        desc = get_path_description()
        assert "scratchpad://" in desc

    def test_description_contains_relative(self):
        """Description mentions relative paths"""
        desc = get_path_description()
        assert "Relative path" in desc

    def test_description_contains_absolute(self):
        """Description mentions absolute paths"""
        desc = get_path_description()
        assert "Absolute path" in desc
