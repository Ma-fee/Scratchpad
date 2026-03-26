"""
Unit tests for capability hints in resource responses.

This module tests that resource responses include proper capability metadata
based on client capabilities.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.resources.read_handler import (
    read_resource,
    set_session_manager,
)
from mcp_scratchpad.resources.capabilities import ClientCapability

# Valid UUID for testing
TEST_SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def mock_fs():
    """Create a mock filesystem for testing."""
    fs = MagicMock()
    return fs


@pytest.fixture
def mock_session_manager(mock_fs):
    """Create a mock session manager for testing."""
    manager = MagicMock()
    manager.get_session_fs.return_value = mock_fs
    return manager


class TestCapabilityHints:
    """Tests for capability hints in resource responses."""

    def test_capability_hints_with_text_file(self, mock_session_manager, mock_fs):
        """Test capability hints for text file."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        client_caps = {ClientCapability.IMAGES, ClientCapability.BINARY}

        result = read_resource(uri, mock_session_manager, client_caps=client_caps)

        assert result.success is True
        assert "capability_metadata" in result.to_dict()
        assert result.capability_metadata is not None

    def test_capability_hints_with_no_capabilities(self, mock_session_manager, mock_fs):
        """Test resource reading without client capabilities."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"

        # No client capabilities provided
        result = read_resource(uri, mock_session_manager, client_caps=None)

        assert result.success is True
        # Should have empty capability metadata when no caps provided
        assert result.capability_metadata == {}

    def test_capability_hints_all_capabilities(self, mock_session_manager, mock_fs):
        """Test capability hints with all capabilities."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        all_caps = {
            ClientCapability.IMAGES,
            ClientCapability.BINARY,
            ClientCapability.SUBSCRIPTIONS,
            ClientCapability.THUMBNAILS,
            ClientCapability.XML_FORMAT,
        }

        result = read_resource(uri, mock_session_manager, client_caps=all_caps)

        assert result.success is True
        assert result.capability_metadata is not None
        # Check that supported_formats is present
        if result.capability_metadata:
            assert "supported_formats" in result.capability_metadata

    def test_capability_hints_includes_recommendations(
        self, mock_session_manager, mock_fs
    ):
        """Test that capability hints include format recommendations."""
        mock_fs.exists.return_value = True
        mock_fs.isdir.return_value = False
        mock_fs.info.return_value = {"size": 100, "type": "file", "mtime": 1609459200}

        mock_content = MagicMock()
        mock_content.__enter__ = MagicMock(return_value=mock_content)
        mock_content.__exit__ = MagicMock(return_value=None)
        mock_content.read.return_value = "Hello, World!"
        mock_fs.open.return_value = mock_content

        uri = f"scratchpad://{TEST_SESSION_ID}/test.txt"
        client_caps = {ClientCapability.IMAGES, ClientCapability.BINARY}

        result = read_resource(uri, mock_session_manager, client_caps=client_caps)

        assert result.success is True
        if result.capability_metadata:
            assert "recommendations" in result.capability_metadata
            # Should have recommendation for text/plain
            recommendations = result.capability_metadata.get("recommendations", {})
            assert "text/plain" in recommendations or "text/*" in recommendations


class TestCapabilityNegotiation:
    """Tests for capability negotiation in resources module."""

    def test_negotiate_format_text_always_supported(self):
        """Test that 'text' format is always supported."""
        from mcp_scratchpad.resources.capabilities import negotiate_format

        # Text should always be returned regardless of caps
        result = negotiate_format("text", set())
        assert result == "text"

    def test_negotiate_format_image_with_capability(self):
        """Test image format negotiation when capability present."""
        from mcp_scratchpad.resources.capabilities import negotiate_format

        caps = {ClientCapability.IMAGES}
        result = negotiate_format("image", caps)
        assert result == "image"

    def test_negotiate_format_image_without_capability(self):
        """Test image format negotiation falls back to text."""
        from mcp_scratchpad.resources.capabilities import negotiate_format

        caps = set()  # No image capability
        result = negotiate_format("image", caps)
        assert result == "text"  # Falls back to text

    def test_negotiate_format_binary_with_capability(self):
        """Test binary format negotiation when capability present."""
        from mcp_scratchpad.resources.capabilities import negotiate_format

        caps = {ClientCapability.BINARY}
        result = negotiate_format("binary", caps)
        assert result == "binary"

    def test_negotiate_format_binary_without_capability(self):
        """Test binary format negotiation falls back to text."""
        from mcp_scratchpad.resources.capabilities import negotiate_format

        caps = set()  # No binary capability
        result = negotiate_format("binary", caps)
        assert result == "text"  # Falls back to text

    def test_capability_metadata_creation(self):
        """Test CapabilityMetadata creation from capabilities."""
        from mcp_scratchpad.resources.capabilities import (
            CapabilityMetadata,
            ClientCapability,
        )

        caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        metadata = CapabilityMetadata.from_capabilities(caps, "image/png")

        assert "image" in metadata.supported_formats
        assert "binary" in metadata.supported_formats
        assert "text" in metadata.supported_formats  # Always included
        assert "image/png" in metadata.recommendations

    def test_capability_metadata_to_dict(self):
        """Test CapabilityMetadata to_dict conversion."""
        from mcp_scratchpad.resources.capabilities import (
            CapabilityMetadata,
            ClientCapability,
        )

        caps = {ClientCapability.IMAGES}
        metadata = CapabilityMetadata.from_capabilities(caps, "image/png")
        result_dict = metadata.to_dict()

        assert "supported_formats" in result_dict
        assert "capability_version" in result_dict
        assert "recommendations" in result_dict
        assert "detected_capabilities" in result_dict
        assert result_dict["detected_capabilities"] == ["IMAGES"]


class TestClientCapabilityDetection:
    """Tests for client capability detection."""

    def test_detect_from_user_agent_claude_desktop(self):
        """Test capability detection from Claude Desktop user agent."""
        from mcp_scratchpad.resources.capabilities import (
            detect_client_capabilities,
            ClientCapability,
        )

        caps = detect_client_capabilities(user_agent="Claude-Desktop/1.0")

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        assert ClientCapability.XML_FORMAT in caps

    def test_detect_from_accept_header_images(self):
        """Test capability detection from Accept header with images."""
        from mcp_scratchpad.resources.capabilities import (
            detect_client_capabilities,
            ClientCapability,
        )

        caps = detect_client_capabilities(headers={"Accept": "image/png, text/plain"})

        assert ClientCapability.IMAGES in caps

    def test_detect_from_accept_header_wildcard(self):
        """Test capability detection from Accept header with wildcard."""
        from mcp_scratchpad.resources.capabilities import (
            detect_client_capabilities,
            ClientCapability,
        )

        caps = detect_client_capabilities(headers={"Accept": "*/*"})

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps

    def test_detect_from_capabilities_header(self):
        """Test capability detection from X-MCP-Capabilities header."""
        from mcp_scratchpad.resources.capabilities import (
            detect_client_capabilities,
            ClientCapability,
        )

        caps = detect_client_capabilities(
            headers={"X-MCP-Capabilities": "IMAGES, BINARY, SUBSCRIPTIONS"}
        )

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        assert ClientCapability.SUBSCRIPTIONS in caps

    def test_detect_no_capabilities_empty_request(self):
        """Test that empty request yields no capabilities."""
        from mcp_scratchpad.resources.capabilities import detect_client_capabilities

        caps = detect_client_capabilities()

        assert len(caps) == 0

    def test_detect_unknown_capability_ignored(self):
        """Test that unknown capabilities are ignored."""
        from mcp_scratchpad.resources.capabilities import (
            detect_client_capabilities,
            ClientCapability,
        )

        caps = detect_client_capabilities(
            headers={"X-MCP-Capabilities": "IMAGES, UNKNOWN_CAPABILITY, BINARY"}
        )

        assert ClientCapability.IMAGES in caps
        assert ClientCapability.BINARY in caps
        # UNKNOWN_CAPABILITY should be ignored, not cause error
        assert len(caps) == 2
