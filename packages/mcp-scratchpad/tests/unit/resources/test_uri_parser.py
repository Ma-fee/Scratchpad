"""Tests for scratchpad:// URI parser.

Test coverage includes:
- Valid URI parsing
- UUID validation
- Path normalization
- Path traversal prevention
- Edge cases (empty path, root path, trailing slashes)
- Special characters in paths
- URL encoding
"""

import pytest
from mcp_scratchpad.resources.uri_parser import (
    parse_scratchpad_uri,
    is_valid_scratchpad_uri,
    build_scratchpad_uri,
    ScratchpadURI,
    _is_valid_uuid,
    _normalize_path,
    URIParseError,
)


# ============================================================================
# Test Constants
# ============================================================================

VALID_SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"
VALID_SESSION_ID_NO_DASHES = "550e8400e29b41d4a716446655440000"
ANOTHER_VALID_SESSION_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


# ============================================================================
# UUID Validation Tests
# ============================================================================


class TestUUIDValidation:
    """Test UUID validation."""

    def test_valid_uuid_with_dashes(self):
        """Test valid UUID with standard dashes format."""
        assert _is_valid_uuid(VALID_SESSION_ID) is True

    def test_valid_uuid_without_dashes(self):
        """Test valid UUID without dashes."""
        assert _is_valid_uuid(VALID_SESSION_ID_NO_DASHES) is True

    def test_invalid_uuid_wrong_length(self):
        """Test UUID with wrong length."""
        assert _is_valid_uuid("550e8400-e29b-41d4") is False

    def test_invalid_uuid_non_hex(self):
        """Test UUID with non-hex characters."""
        assert _is_valid_uuid("550e8400-e29b-41d4-a716-44665544000g") is False

    def test_invalid_uuid_empty(self):
        """Test empty UUID."""
        assert _is_valid_uuid("") is False

    def test_invalid_uuid_none(self):
        """Test None as UUID."""
        assert _is_valid_uuid(None) is False

    def test_invalid_uuid_with_extra_dashes(self):
        """Test UUID with extra dashes."""
        assert _is_valid_uuid("550e8400-e29b-41d4-a716-446655-440000") is False

    def test_uuid_version_1(self):
        """Test UUID v1 is accepted."""
        assert _is_valid_uuid("6ba7b810-9dad-11d1-80b4-00c04fd430c8") is True

    def test_uuid_version_4(self):
        """Test UUID v4 is accepted."""
        assert _is_valid_uuid("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11") is True

    def test_uppercase_uuid(self):
        """Test uppercase UUID is valid."""
        assert _is_valid_uuid(VALID_SESSION_ID.upper()) is True


# ============================================================================
# Path Normalization Tests
# ============================================================================


class TestPathNormalization:
    """Test path normalization."""

    def test_simple_path(self):
        """Test simple path normalization."""
        assert _normalize_path("file.txt") == "file.txt"

    def test_path_with_leading_slash(self):
        """Test path with leading slash."""
        assert _normalize_path("/file.txt") == "file.txt"

    def test_nested_path(self):
        """Test nested directory path."""
        assert _normalize_path("dir/subdir/file.txt") == "dir/subdir/file.txt"

    def test_path_with_dot(self):
        """Test path with single dot."""
        assert _normalize_path("./file.txt") == "file.txt"

    def test_path_with_dot_in_middle(self):
        """Test path with dot in middle."""
        assert _normalize_path("dir/./file.txt") == "dir/file.txt"

    def test_path_with_double_dot(self):
        """Test path with parent directory reference."""
        assert _normalize_path("dir/subdir/../file.txt") == "dir/file.txt"

    def test_empty_path(self):
        """Test empty path."""
        assert _normalize_path("") == ""

    def test_root_path(self):
        """Test root path."""
        assert _normalize_path("/") == ""

    def test_path_with_trailing_slash(self):
        """Test path with trailing slash."""
        assert _normalize_path("dir/subdir/") == "dir/subdir"

    def test_path_multiple_slashes(self):
        """Test path with multiple consecutive slashes."""
        assert _normalize_path("dir//subdir///file.txt") == "dir/subdir/file.txt"

    def test_path_traversal_blocked(self):
        """Test path traversal beyond root is blocked."""
        with pytest.raises(URIParseError) as exc_info:
            _normalize_path("../file.txt")
        assert "Path traversal detected" in str(exc_info.value)

    def test_path_traversal_in_middle_blocked(self):
        """Test path traversal beyond root in middle of path."""
        with pytest.raises(URIParseError) as exc_info:
            _normalize_path("dir/../../../file.txt")
        assert "Path traversal detected" in str(exc_info.value)

    def test_valid_parent_directory(self):
        """Test valid use of parent directory within bounds."""
        assert _normalize_path("dir/subdir/../file.txt") == "dir/file.txt"

    def test_url_encoded_path(self):
        """Test URL-encoded path is decoded."""
        assert _normalize_path("file%20name.txt") == "file name.txt"

    def test_path_with_special_chars(self):
        """Test path with special characters."""
        assert _normalize_path("file-name_test.txt") == "file-name_test.txt"


# ============================================================================
# Valid URI Parsing Tests
# ============================================================================


class TestValidURIParsing:
    """Test parsing of valid scratchpad:// URIs."""

    def test_simple_file(self):
        """Test simple file URI."""
        uri = f"scratchpad://{VALID_SESSION_ID}/file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.error is None
        assert result.session_id == VALID_SESSION_ID
        assert result.path == "file.txt"
        assert result.original_uri == uri

    def test_nested_path(self):
        """Test nested directory path."""
        uri = f"scratchpad://{VALID_SESSION_ID}/dir/subdir/file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == "dir/subdir/file.txt"

    def test_root_path_only(self):
        """Test URI with root path only."""
        uri = f"scratchpad://{VALID_SESSION_ID}/"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == ""

    def test_no_trailing_slash(self):
        """Test URI without trailing slash."""
        uri = f"scratchpad://{VALID_SESSION_ID}"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == ""

    def test_uuid_without_dashes(self):
        """Test URI with UUID without dashes."""
        uri = f"scratchpad://{VALID_SESSION_ID_NO_DASHES}/file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.session_id == VALID_SESSION_ID_NO_DASHES

    def test_path_with_special_chars(self):
        """Test URI with special characters in path."""
        uri = f"scratchpad://{VALID_SESSION_ID}/file-name_test.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == "file-name_test.txt"

    def test_path_with_url_encoding(self):
        """Test URI with URL-encoded characters."""
        uri = f"scratchpad://{VALID_SESSION_ID}/file%20name.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == "file name.txt"

    def test_path_with_dot_normalized(self):
        """Test path with dot is normalized."""
        uri = f"scratchpad://{VALID_SESSION_ID}/./file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == "file.txt"

    def test_path_with_double_dot_normalized(self):
        """Test path with parent directory is normalized."""
        uri = f"scratchpad://{VALID_SESSION_ID}/dir/../file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is True
        assert result.path == "file.txt"


# ============================================================================
# Invalid URI Parsing Tests
# ============================================================================


class TestInvalidURIParsing:
    """Test parsing of invalid URIs."""

    def test_wrong_scheme(self):
        """Test URI with wrong scheme."""
        uri = f"http://{VALID_SESSION_ID}/file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False
        assert "Invalid scheme" in result.error
        assert "http" in result.error

    def test_empty_uri(self):
        """Test empty URI."""
        result = parse_scratchpad_uri("")

        assert result.is_valid is False
        assert "cannot be empty" in result.error

    def test_missing_session_id(self):
        """Test URI without session ID."""
        uri = "scratchpad:///file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False
        assert "Missing session_id" in result.error

    def test_invalid_session_id_not_uuid(self):
        """Test URI with invalid session ID."""
        uri = "scratchpad://invalid-session/file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False
        assert "Invalid session_id" in result.error
        assert "not a valid UUID" in result.error

    def test_invalid_session_id_wrong_length(self):
        """Test URI with wrong length session ID."""
        uri = "scratchpad://550e8400-e29b-41d4/file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False

    def test_path_traversal_detected(self):
        """Test URI with path traversal is rejected."""
        uri = f"scratchpad://{VALID_SESSION_ID}/../file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False
        assert "Path traversal detected" in result.error

    def test_deep_path_traversal_detected(self):
        """Test URI with deep path traversal is rejected."""
        uri = f"scratchpad://{VALID_SESSION_ID}/dir/../../../file.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False
        assert "Path traversal detected" in result.error

    def test_url_encoded_traversal_blocked(self):
        """Test URL-encoded path traversal is blocked."""
        uri = f"scratchpad://{VALID_SESSION_ID}/..%2F..%2Ffile.txt"
        result = parse_scratchpad_uri(uri)

        assert result.is_valid is False
        assert "Path traversal detected" in result.error


# ============================================================================
# Quick Validation Tests
# ============================================================================


class TestIsValidScratchpadURI:
    """Test quick URI validation."""

    def test_valid_uri_returns_true(self):
        """Test valid URI returns True."""
        uri = f"scratchpad://{VALID_SESSION_ID}/file.txt"
        assert is_valid_scratchpad_uri(uri) is True

    def test_invalid_uri_returns_false(self):
        """Test invalid URI returns False."""
        assert is_valid_scratchpad_uri("invalid://test") is False

    def test_empty_uri_returns_false(self):
        """Test empty URI returns False."""
        assert is_valid_scratchpad_uri("") is False


# ============================================================================
# URI Builder Tests
# ============================================================================


class TestBuildScratchpadURI:
    """Test building scratchpad:// URIs."""

    def test_build_simple_uri(self):
        """Test building simple URI."""
        uri = build_scratchpad_uri(VALID_SESSION_ID, "file.txt")
        assert uri == f"scratchpad://{VALID_SESSION_ID}/file.txt"

    def test_build_root_uri(self):
        """Test building root URI."""
        uri = build_scratchpad_uri(VALID_SESSION_ID)
        assert uri == f"scratchpad://{VALID_SESSION_ID}/"

    def test_build_root_uri_with_empty_path(self):
        """Test building URI with empty path string."""
        uri = build_scratchpad_uri(VALID_SESSION_ID, "")
        assert uri == f"scratchpad://{VALID_SESSION_ID}/"

    def test_build_nested_uri(self):
        """Test building nested path URI."""
        uri = build_scratchpad_uri(VALID_SESSION_ID, "dir/subdir/file.txt")
        assert uri == f"scratchpad://{VALID_SESSION_ID}/dir/subdir/file.txt"

    def test_path_is_normalized(self):
        """Test path is normalized during build."""
        uri = build_scratchpad_uri(VALID_SESSION_ID, "./dir/../file.txt")
        assert uri == f"scratchpad://{VALID_SESSION_ID}/file.txt"

    def test_invalid_session_id_raises_error(self):
        """Test invalid session ID raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_scratchpad_uri("invalid-session", "file.txt")
        assert "Invalid session_id" in str(exc_info.value)

    def test_leading_slash_removed(self):
        """Test leading slash is removed from path."""
        uri = build_scratchpad_uri(VALID_SESSION_ID, "/file.txt")
        assert uri == f"scratchpad://{VALID_SESSION_ID}/file.txt"


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases."""

    def test_path_with_multiple_dots(self):
        """Test path with multiple dots in filename."""
        uri = f"scratchpad://{VALID_SESSION_ID}/file.name.with.dots.txt"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.path == "file.name.with.dots.txt"

    def test_path_with_single_dot_dir(self):
        """Test path with . directory references."""
        uri = f"scratchpad://{VALID_SESSION_ID}/./dir/././file.txt"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.path == "dir/file.txt"

    def test_path_going_up_and_down(self):
        """Test path that goes up and then down."""
        uri = f"scratchpad://{VALID_SESSION_ID}/dir1/dir2/../dir3/file.txt"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.path == "dir1/dir3/file.txt"

    def test_unicode_in_path(self):
        """Test path with unicode characters."""
        uri = f"scratchpad://{VALID_SESSION_ID}/ファイル.txt"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.path == "ファイル.txt"

    def test_very_long_path(self):
        """Test very long path."""
        long_path = "/".join(["dir"] * 50) + "/file.txt"
        uri = f"scratchpad://{VALID_SESSION_ID}/{long_path}"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.path == long_path.lstrip("/")

    def test_special_characters_in_path(self):
        """Test various special characters in path."""
        # These should be URL-encoded in practice, but we test decoding
        uri = f"scratchpad://{VALID_SESSION_ID}/path%2Bfile.txt"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.path == "path+file.txt"

    def test_session_id_uppercase(self):
        """Test uppercase session ID is valid."""
        uri = f"scratchpad://{VALID_SESSION_ID.upper()}/file.txt"
        result = parse_scratchpad_uri(uri)
        assert result.is_valid is True
        assert result.session_id == VALID_SESSION_ID.upper()


# ============================================================================
# Return Type Tests
# ============================================================================


class TestReturnType:
    """Test return type structure."""

    def test_return_type_is_scratchpad_uri(self):
        """Test return type is ScratchpadURI dataclass."""
        uri = f"scratchpad://{VALID_SESSION_ID}/file.txt"
        result = parse_scratchpad_uri(uri)

        assert isinstance(result, ScratchpadURI)

    def test_scratchpad_uri_is_frozen(self):
        """Test ScratchpadURI is immutable."""
        uri = ScratchpadURI(
            session_id=VALID_SESSION_ID,
            path="file.txt",
            is_valid=True,
            error=None,
            original_uri=f"scratchpad://{VALID_SESSION_ID}/file.txt",
        )

        with pytest.raises(AttributeError):
            uri.path = "other.txt"

    def test_scratchpad_uri_equality(self):
        """Test ScratchpadURI equality."""
        uri1 = parse_scratchpad_uri(f"scratchpad://{VALID_SESSION_ID}/file.txt")
        uri2 = parse_scratchpad_uri(f"scratchpad://{VALID_SESSION_ID}/file.txt")

        assert uri1 == uri2
