"""Unit tests for client capability detection.

This module tests the client capability detection system including:
- ClientCapability enum
- detect_client_capabilities() function
- negotiate_format() function
- CapabilityMetadata dataclass
- Integration with read_resource()

Test Coverage:
- Client capability detection from user agent
- Client capability detection from Accept header
- Client capability detection from X-MCP-Capabilities header
- Format negotiation with various capabilities
- CapabilityMetadata creation and serialization
- is_binary_mime_type() helper function
- get_capability_info_for_resource() helper function
- Integration with read_resource() for capability-aware responses
"""

from __future__ import annotations

import pytest

from mcp_scratchpad.resources.capabilities import (
    CLIENT_PROFILES,
    FORMAT_CAPABILITIES,
    MIME_TYPE_CAPABILITIES,
    ClientCapability,
    CapabilityMetadata,
    detect_client_capabilities,
    get_capability_info_for_resource,
    is_binary_mime_type,
    negotiate_format,
)


class TestClientCapabilityEnum:
    """Tests for ClientCapability enum."""

    def test_enum_values_exist(self):
        """Test that all expected capability values exist."""
        assert ClientCapability.IMAGES is not None
        assert ClientCapability.BINARY is not None
        assert ClientCapability.SUBSCRIPTIONS is not None
        assert ClientCapability.THUMBNAILS is not None
        assert ClientCapability.XML_FORMAT is not None

    def test_enum_values_are_unique(self):
        """Test that all enum values are unique."""
        values = [cap for cap in ClientCapability]
        assert len(values) == len(set(values))

    def test_enum_membership_check(self):
        """Test enum membership operations."""
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        assert ClientCapability.XML_FORMAT not in caps


class TestDetectClientCapabilities:
    """Tests for detect_client_capabilities() function."""

    def test_detect_from_claude_desktop_user_agent(self):
        """Test detecting capabilities from Claude Desktop user agent."""
        caps = detect_client_capabilities(user_agent="Claude-Desktop/1.0.0")

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        assert ClientCapability.XML_FORMAT in caps
        assert ClientCapability.THUMBNAILS in caps

    def test_detect_from_claude_web_user_agent(self):
        """Test detecting capabilities from Claude Web user agent."""
        caps = detect_client_capabilities(user_agent="Claude/2.0 (Web)")

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.XML_FORMAT in caps
        # Web version may not support binary directly

    def test_detect_from_mcp_inspector_user_agent(self):
        """Test detecting capabilities from MCP Inspector user agent."""
        caps = detect_client_capabilities(user_agent="mcp-inspector/0.1.0")

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        assert ClientCapability.SUBSCRIPTIONS in caps
        assert ClientCapability.THUMBNAILS in caps
        assert ClientCapability.XML_FORMAT in caps

    def test_detect_from_unknown_user_agent(self):
        """Test detecting capabilities from unknown user agent."""
        caps = detect_client_capabilities(user_agent="UnknownClient/1.0")

        # Unknown user agent should return empty or basic capabilities
        assert isinstance(caps, set)

    def test_detect_from_accept_header_images(self):
        """Test detecting image capability from Accept header."""
        caps = detect_client_capabilities(headers={"Accept": "image/png, image/jpeg"})

        assert ClientCapability.IMAGES in caps

    def test_detect_from_accept_header_wildcard(self):
        """Test detecting capabilities from wildcard Accept header."""
        caps = detect_client_capabilities(headers={"Accept": "*/*"})

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps

    def test_detect_from_accept_header_binary(self):
        """Test detecting binary capability from Accept header."""
        caps = detect_client_capabilities(
            headers={"Accept": "application/pdf, application/zip"}
        )

        assert ClientCapability.BINARY in caps

    def test_detect_from_accept_header_xml(self):
        """Test detecting XML capability from Accept header."""
        caps = detect_client_capabilities(headers={"Accept": "application/xml"})

        assert ClientCapability.XML_FORMAT in caps

    def test_detect_from_capabilities_header(self):
        """Test detecting capabilities from X-MCP-Capabilities header."""
        caps = detect_client_capabilities(
            headers={"X-MCP-Capabilities": "IMAGES, BINARY, SUBSCRIPTIONS"}
        )

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        assert ClientCapability.SUBSCRIPTIONS in caps
        assert ClientCapability.THUMBNAILS not in caps

    def test_detect_from_capabilities_header_single(self):
        """Test detecting single capability from header."""
        caps = detect_client_capabilities(headers={"X-MCP-Capabilities": "XML_FORMAT"})

        assert ClientCapability.XML_FORMAT in caps

    def test_detect_from_both_user_agent_and_headers(self):
        """Test detecting capabilities from both user agent and headers."""
        caps = detect_client_capabilities(
            headers={"Accept": "image/png", "X-MCP-Capabilities": "SUBSCRIPTIONS"},
            user_agent="Claude-Desktop/1.0",
        )

        assert ClientCapability.IMAGES in caps  # From Accept and user agent
        assert ClientCapability.SUBSCRIPTIONS in caps  # From header
        assert ClientCapability.BINARY in caps  # From user agent

    def test_detect_empty_headers(self):
        """Test detecting capabilities with empty headers."""
        caps = detect_client_capabilities(headers={})

        assert isinstance(caps, set)
        assert len(caps) == 0

    def test_detect_none_headers(self):
        """Test detecting capabilities with None headers."""
        caps = detect_client_capabilities(headers=None)

        assert isinstance(caps, set)
        assert len(caps) == 0

    def test_detect_case_insensitive_headers(self):
        """Test that header detection is case-insensitive."""
        caps_lower = detect_client_capabilities(
            headers={"x-mcp-capabilities": "IMAGES"}
        )
        caps_upper = detect_client_capabilities(
            headers={"X-MCP-CAPABILITIES": "IMAGES"}
        )
        caps_mixed = detect_client_capabilities(
            headers={"X-Mcp-Capabilities": "IMAGES"}
        )

        assert caps_lower == caps_upper == caps_mixed
        assert ClientCapability.IMAGES in caps_lower


class TestNegotiateFormat:
    """Tests for negotiate_format() function."""

    def test_negotiate_text_always_allowed(self):
        """Test that text format is always allowed."""
        empty_caps: set[ClientCapability] = set()
        full_caps = {ClientCapability.IMAGES, ClientCapability.BINARY}

        assert negotiate_format("text", empty_caps) == "text"
        assert negotiate_format("text", full_caps) == "text"

    def test_negotiate_image_with_capability(self):
        """Test negotiating image format when supported."""
        caps = {ClientCapability.IMAGES}

        assert negotiate_format("image", caps) == "image"

    def test_negotiate_image_without_capability(self):
        """Test negotiating image format when not supported."""
        caps: set[ClientCapability] = set()

        assert negotiate_format("image", caps) == "text"

    def test_negotiate_binary_with_capability(self):
        """Test negotiating binary format when supported."""
        caps = {ClientCapability.BINARY}

        assert negotiate_format("binary", caps) == "binary"

    def test_negotiate_binary_without_capability(self):
        """Test negotiating binary format when not supported."""
        caps: set[ClientCapability] = set()

        assert negotiate_format("binary", caps) == "text"

    def test_negotiate_xml_with_capability(self):
        """Test negotiating XML format when supported."""
        caps = {ClientCapability.XML_FORMAT}

        assert negotiate_format("xml", caps) == "xml"

    def test_negotiate_xml_without_capability(self):
        """Test negotiating XML format when not supported."""
        caps: set[ClientCapability] = set()

        assert negotiate_format("xml", caps) == "text"

    def test_negotiate_fallback_chain(self):
        """Test fallback chain when preferred not supported."""
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}

        # Prefer binary, should work
        assert negotiate_format("binary", caps) == "binary"

        # Prefer XML but not supported, falls back
        result = negotiate_format("xml", caps)
        assert result in ["binary", "image", "text"]  # One of supported

    def test_negotiate_custom_fallback_chain(self):
        """Test custom fallback chain."""
        caps = {ClientCapability.IMAGES}

        result = negotiate_format(
            "binary", caps, fallback_chain=["xml", "image", "text"]
        )
        # Binary not supported, xml not supported, image supported
        assert result == "image"

    def test_negotiate_empty_fallback_chain(self):
        """Test with empty fallback chain."""
        caps: set[ClientCapability] = set()

        result = negotiate_format("image", caps, fallback_chain=[])
        assert result == "text"  # Ultimate fallback


class TestCapabilityMetadata:
    """Tests for CapabilityMetadata dataclass."""

    def test_metadata_creation(self):
        """Test creating CapabilityMetadata instance."""
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        metadata = CapabilityMetadata(
            supported_formats=["text", "image", "binary"],
            capability_version="1.0",
            recommendations={"image/png": "image"},
            detected_capabilities=caps,
        )

        assert metadata.supported_formats == ["text", "image", "binary"]
        assert metadata.capability_version == "1.0"
        assert metadata.recommendations == {"image/png": "image"}
        assert metadata.detected_capabilities == caps

    def test_metadata_to_dict(self):
        """Test converting metadata to dictionary."""
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        metadata = CapabilityMetadata(
            supported_formats=["text", "image"],
            detected_capabilities=caps,
        )
        result = metadata.to_dict()

        assert result["supported_formats"] == ["text", "image"]
        assert result["capability_version"] == "1.0"
        assert "IMAGES" in result["detected_capabilities"]
        assert "BINARY" in result["detected_capabilities"]

    def test_metadata_default_values(self):
        """Test CapabilityMetadata default values."""
        metadata = CapabilityMetadata()

        assert metadata.supported_formats == []
        assert metadata.capability_version == "1.0"
        assert metadata.recommendations == {}
        assert metadata.detected_capabilities == set()

    def test_metadata_from_capabilities_empty(self):
        """Test creating metadata from empty capabilities."""
        caps: set[ClientCapability] = set()
        metadata = CapabilityMetadata.from_capabilities(caps)

        assert "text" in metadata.supported_formats
        assert "image" not in metadata.supported_formats
        assert "binary" not in metadata.supported_formats

    def test_metadata_from_capabilities_full(self):
        """Test creating metadata from all capabilities."""
        caps = {
            ClientCapability.IMAGES,
            ClientCapability.BINARY,
            ClientCapability.XML_FORMAT,
        }
        metadata = CapabilityMetadata.from_capabilities(caps)

        assert "text" in metadata.supported_formats
        assert "image" in metadata.supported_formats
        assert "binary" in metadata.supported_formats
        assert "xml" in metadata.supported_formats

    def test_metadata_from_capabilities_with_mime_type(self):
        """Test creating metadata with specific MIME type."""
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        metadata = CapabilityMetadata.from_capabilities(caps, "image/png")

        assert "image/png" in metadata.recommendations
        assert metadata.recommendations["image/png"] == "image"
        assert "image/*" in metadata.recommendations


class TestIsBinaryMimeType:
    """Tests for is_binary_mime_type() helper function."""

    def test_image_types_are_binary(self):
        """Test that image MIME types are binary."""
        assert is_binary_mime_type("image/png") is True
        assert is_binary_mime_type("image/jpeg") is True
        assert is_binary_mime_type("image/gif") is True

    def test_audio_types_are_binary(self):
        """Test that audio MIME types are binary."""
        assert is_binary_mime_type("audio/mp3") is True
        assert is_binary_mime_type("audio/wav") is True

    def test_video_types_are_binary(self):
        """Test that video MIME types are binary."""
        assert is_binary_mime_type("video/mp4") is True
        assert is_binary_mime_type("video/avi") is True

    def test_application_octet_stream_is_binary(self):
        """Test that application/octet-stream is binary."""
        assert is_binary_mime_type("application/octet-stream") is True

    def test_pdf_is_binary(self):
        """Test that PDF is binary."""
        assert is_binary_mime_type("application/pdf") is True

    def test_text_types_are_not_binary(self):
        """Test that text types are not binary."""
        assert is_binary_mime_type("text/plain") is False
        assert is_binary_mime_type("text/html") is False
        assert is_binary_mime_type("text/css") is False

    def test_json_is_not_binary(self):
        """Test that JSON is not binary."""
        assert is_binary_mime_type("application/json") is False

    def test_xml_is_not_binary(self):
        """Test that XML is not binary."""
        assert is_binary_mime_type("application/xml") is False
        assert is_binary_mime_type("text/xml") is False

    def test_javascript_is_not_binary(self):
        """Test that JavaScript is not binary."""
        assert is_binary_mime_type("application/javascript") is False


class TestGetCapabilityInfoForResource:
    """Tests for get_capability_info_for_resource() helper function."""

    def test_capability_info_basic(self):
        """Test basic capability info generation."""
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        info = get_capability_info_for_resource(
            "scratchpad://test/file.txt",
            "text/plain",
            caps,
        )

        assert "supported_formats" in info
        assert "capability_version" in info
        assert "recommendations" in info

    def test_capability_info_with_subscriptions(self):
        """Test capability info includes subscription support."""
        caps = {ClientCapability.SUBSCRIPTIONS}
        info = get_capability_info_for_resource(
            "scratchpad://test/file.txt",
            "text/plain",
            caps,
        )

        assert info.get("subscription_supported") is True

    def test_capability_info_without_subscriptions(self):
        """Test capability info without subscription support."""
        caps: set[ClientCapability] = set()
        info = get_capability_info_for_resource(
            "scratchpad://test/file.txt",
            "text/plain",
            caps,
        )

        assert "subscription_supported" not in info

    def test_capability_info_thumbnail_for_image(self):
        """Test thumbnail availability for image with THUMBNAILS capability."""
        caps = {ClientCapability.THUMBNAILS}
        info = get_capability_info_for_resource(
            "scratchpad://test/image.png",
            "image/png",
            caps,
        )

        assert info.get("thumbnail_available") is True

    def test_capability_info_no_thumbnail_for_text(self):
        """Test no thumbnail for text file even with THUMBNAILS capability."""
        caps = {ClientCapability.THUMBNAILS}
        info = get_capability_info_for_resource(
            "scratchpad://test/file.txt",
            "text/plain",
            caps,
        )

        assert "thumbnail_available" not in info

    def test_capability_info_none_capabilities(self):
        """Test capability info with None capabilities."""
        info = get_capability_info_for_resource(
            "scratchpad://test/file.txt",
            "text/plain",
            None,
        )

        assert "supported_formats" in info
        assert "recommendations" in info


class TestClientProfiles:
    """Tests for CLIENT_PROFILES constant."""

    def test_claude_desktop_profile(self):
        """Test Claude Desktop capability profile."""
        profile = CLIENT_PROFILES["claude-desktop"]

        assert ClientCapability.IMAGES in profile
        assert ClientCapability.BINARY in profile
        assert ClientCapability.XML_FORMAT in profile

    def test_mcp_inspector_profile(self):
        """Test MCP Inspector capability profile."""
        profile = CLIENT_PROFILES["mcp-inspector"]

        assert ClientCapability.IMAGES in profile
        assert ClientCapability.BINARY in profile
        assert ClientCapability.SUBSCRIPTIONS in profile
        assert ClientCapability.THUMBNAILS in profile
        assert ClientCapability.XML_FORMAT in profile

    def test_all_profiles_have_images(self):
        """Test that all profiles support images."""
        for profile_name, capabilities in CLIENT_PROFILES.items():
            assert ClientCapability.IMAGES in capabilities, (
                f"{profile_name} missing IMAGES"
            )


class TestConstants:
    """Tests for module constants."""

    def test_mime_type_capabilities_defined(self):
        """Test that MIME type capabilities are defined."""
        assert "image/png" in MIME_TYPE_CAPABILITIES
        assert "image/jpeg" in MIME_TYPE_CAPABILITIES
        assert "application/pdf" in MIME_TYPE_CAPABILITIES
        assert "text/xml" in MIME_TYPE_CAPABILITIES

    def test_format_capabilities_defined(self):
        """Test that format capabilities are defined."""
        assert "image" in FORMAT_CAPABILITIES
        assert "binary" in FORMAT_CAPABILITIES
        assert "xml" in FORMAT_CAPABILITIES
        assert "text" in FORMAT_CAPABILITIES

    def test_format_capabilities_text_is_none(self):
        """Test that text format requires no capability."""
        assert FORMAT_CAPABILITIES["text"] is None


class TestIntegrationWithReadResource:
    """Integration tests with read_resource function."""

    # Valid UUID for testing session IDs
    TEST_SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"

    def test_read_resource_accepts_client_caps(self):
        """Test that read_resource accepts client_caps parameter."""
        from unittest.mock import MagicMock

        from mcp_scratchpad.resources.read_handler import read_resource

        # Create mock session manager
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 13, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        mock_session_manager = MagicMock()
        mock_session_manager.get_session_fs.return_value = mock_fs

        # Test with client_caps
        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        result = read_resource(
            f"scratchpad://{self.TEST_SESSION_ID}/test.txt",
            session_manager=mock_session_manager,
            client_caps=caps,
        )

        assert result.success is True
        assert "capability_metadata" in result.to_dict()

    def test_read_resource_without_client_caps(self):
        """Test that read_resource works without client_caps."""
        from unittest.mock import MagicMock

        from mcp_scratchpad.resources.read_handler import read_resource

        # Create mock session manager
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 13, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        mock_session_manager = MagicMock()
        mock_session_manager.get_session_fs.return_value = mock_fs

        # Test without client_caps
        result = read_resource(
            f"scratchpad://{self.TEST_SESSION_ID}/test.txt",
            session_manager=mock_session_manager,
        )

        assert result.success is True
        # Should not include capability_metadata when client_caps not provided
        assert result.capability_metadata == {}

    def test_read_resource_capability_metadata_content(self):
        """Test that capability metadata contains expected fields."""
        from unittest.mock import MagicMock

        from mcp_scratchpad.resources.read_handler import read_resource

        # Create mock session manager
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 13, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        mock_session_manager = MagicMock()
        mock_session_manager.get_session_fs.return_value = mock_fs

        caps = {ClientCapability.IMAGES, ClientCapability.SUBSCRIPTIONS}
        result = read_resource(
            f"scratchpad://{self.TEST_SESSION_ID}/test.txt",
            session_manager=mock_session_manager,
            client_caps=caps,
        )

        metadata = result.capability_metadata
        assert "supported_formats" in metadata
        assert "capability_version" in metadata
        assert "recommendations" in metadata
        assert metadata.get("subscription_supported") is True
