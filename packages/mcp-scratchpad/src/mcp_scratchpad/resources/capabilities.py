"""Client capability detection for MCP resources.

This module provides functionality to detect and negotiate client capabilities
for MCP resource handling. It enables servers to adapt resource responses based
on what the client supports (images, binary, subscriptions, etc.).

Example:
    >>> from mcp_scratchpad.resources.capabilities import (
    ...     ClientCapability,
    ...     detect_client_capabilities,
    ...     negotiate_format,
    ... )
    >>> # Detect capabilities from request headers
    >>> caps = detect_client_capabilities(
    ...     headers={"Accept": "image/png, text/plain"},
    ...     user_agent="Claude-Desktop/1.0"
    ... )
    >>> ClientCapability.IMAGES in caps
    True
    >>> # Negotiate best format based on capabilities
    >>> format = negotiate_format("image", caps)
    >>> format
    'image'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ClientCapability(Enum):
    """Client capability flags for MCP resource handling.

    These flags represent features that a client may or may not support
    when receiving resource responses.

    Attributes:
        IMAGES: Client supports image resources (PNG, JPEG, etc.)
        BINARY: Client supports binary resource data
        SUBSCRIPTIONS: Client supports resource subscriptions/notifications
        THUMBNAILS: Client supports thumbnail generation
        XML_FORMAT: Client supports XML wrapper format for structured data
    """

    IMAGES = auto()
    BINARY = auto()
    SUBSCRIPTIONS = auto()
    THUMBNAILS = auto()
    XML_FORMAT = auto()


# Known client capability profiles
CLIENT_PROFILES: dict[str, set[ClientCapability]] = {
    # Claude Desktop supports images, binary, and XML format
    "claude-desktop": {
        ClientCapability.IMAGES,
        ClientCapability.BINARY,
        ClientCapability.XML_FORMAT,
        ClientCapability.THUMBNAILS,
    },
    # Claude Web version may have different capabilities
    "claude-web": {
        ClientCapability.IMAGES,
        ClientCapability.XML_FORMAT,
    },
    # MCP Inspector supports full capabilities
    "mcp-inspector": {
        ClientCapability.IMAGES,
        ClientCapability.BINARY,
        ClientCapability.SUBSCRIPTIONS,
        ClientCapability.THUMBNAILS,
        ClientCapability.XML_FORMAT,
    },
    # Generic MCP client with basic support
    "mcp-client": {
        ClientCapability.IMAGES,
        ClientCapability.BINARY,
        ClientCapability.XML_FORMAT,
    },
}

# User agent patterns for client detection
CLIENT_USER_AGENT_PATTERNS: dict[str, str] = {
    "claude-desktop": "claude-desktop",
    "claude-web": "claude",
    "mcp-inspector": "mcp-inspector",
    "mcp-client": "mcp",
}

# MIME type to capability mapping
MIME_TYPE_CAPABILITIES: dict[str, ClientCapability] = {
    "image/png": ClientCapability.IMAGES,
    "image/jpeg": ClientCapability.IMAGES,
    "image/gif": ClientCapability.IMAGES,
    "image/webp": ClientCapability.IMAGES,
    "image/svg+xml": ClientCapability.IMAGES,
    "image/bmp": ClientCapability.IMAGES,
    "application/octet-stream": ClientCapability.BINARY,
    "application/pdf": ClientCapability.BINARY,
    "application/zip": ClientCapability.BINARY,
    "application/gzip": ClientCapability.BINARY,
    "text/xml": ClientCapability.XML_FORMAT,
    "application/xml": ClientCapability.XML_FORMAT,
}

# Format to required capability mapping
FORMAT_CAPABILITIES: dict[str, ClientCapability | None] = {
    "image": ClientCapability.IMAGES,
    "binary": ClientCapability.BINARY,
    "xml": ClientCapability.XML_FORMAT,
    "text": None,  # Text is always supported
}


def detect_client_capabilities(
    headers: dict[str, str] | None = None,
    user_agent: str | None = None,
) -> set[ClientCapability]:
    """Detect client capabilities from request headers and user agent.

    This function analyzes HTTP headers and user agent string to determine
    which MCP resource capabilities the client supports.

    Args:
        headers: HTTP request headers dictionary (case-insensitive keys)
        user_agent: User agent string from the request

    Returns:
        Set of ClientCapability flags supported by the client

    Example:
        >>> caps = detect_client_capabilities(
        ...     headers={"Accept": "image/png, text/plain"},
        ...     user_agent="Claude-Desktop/1.0"
        ... )
        >>> ClientCapability.IMAGES in caps
        True

        >>> # Minimal client detection
        >>> caps = detect_client_capabilities()
        >>> caps  # Empty set for unknown client
        set()
    """
    capabilities: set[ClientCapability] = set()
    headers = headers or {}

    # Normalize headers to lowercase keys for case-insensitive lookup
    headers_lower = {k.lower(): v for k, v in headers.items()}

    # Detect from user agent
    if user_agent:
        capabilities.update(_detect_from_user_agent(user_agent))

    # Detect from Accept header
    if "accept" in headers_lower:
        capabilities.update(_detect_from_accept_header(headers_lower["accept"]))

    # Detect from X-MCP-Capabilities header (explicit capability declaration)
    if "x-mcp-capabilities" in headers_lower:
        capabilities.update(
            _detect_from_capabilities_header(headers_lower["x-mcp-capabilities"])
        )

    return capabilities


def _detect_from_user_agent(user_agent: str) -> set[ClientCapability]:
    """Detect capabilities from user agent string.

    Args:
        user_agent: User agent string

    Returns:
        Set of detected capabilities
    """
    user_agent_lower = user_agent.lower()
    capabilities: set[ClientCapability] = set()

    # Check for known client profiles
    for client_key, pattern in CLIENT_USER_AGENT_PATTERNS.items():
        if pattern in user_agent_lower:
            if client_key in CLIENT_PROFILES:
                capabilities.update(CLIENT_PROFILES[client_key])
            break  # Use first matching profile

    # Additional heuristics from user agent
    if "image" in user_agent_lower:
        capabilities.add(ClientCapability.IMAGES)
    if "binary" in user_agent_lower:
        capabilities.add(ClientCapability.BINARY)

    return capabilities


def _detect_from_accept_header(accept_header: str) -> set[ClientCapability]:
    """Detect capabilities from Accept header.

    Args:
        accept_header: Value of the Accept header

    Returns:
        Set of detected capabilities
    """
    capabilities: set[ClientCapability] = set()

    if not accept_header:
        return capabilities

    # Parse MIME types from Accept header
    mime_types = [mt.strip() for mt in accept_header.split(",")]

    for mime_type in mime_types:
        # Remove quality value if present
        if ";" in mime_type:
            mime_type = mime_type.split(";")[0].strip()

        # Check for wildcard acceptance
        if mime_type == "*/*":
            capabilities.add(ClientCapability.IMAGES)
            capabilities.add(ClientCapability.BINARY)
            continue

        # Check specific MIME type
        if mime_type in MIME_TYPE_CAPABILITIES:
            capabilities.add(MIME_TYPE_CAPABILITIES[mime_type])

        # Check for image/* pattern
        if mime_type.startswith("image/"):
            capabilities.add(ClientCapability.IMAGES)

        # Check for binary types
        if mime_type.startswith("application/") and mime_type not in (
            "application/json",
            "application/javascript",
            "application/xml",
        ):
            capabilities.add(ClientCapability.BINARY)

    return capabilities


def _detect_from_capabilities_header(capabilities_header: str) -> set[ClientCapability]:
    """Parse explicit capability declarations from X-MCP-Capabilities header.

    Args:
        capabilities_header: Value of the X-MCP-Capabilities header

    Returns:
        Set of detected capabilities
    """
    capabilities: set[ClientCapability] = set()

    if not capabilities_header:
        return capabilities

    # Parse comma-separated capability names
    cap_names = [c.strip().upper() for c in capabilities_header.split(",")]

    for cap_name in cap_names:
        try:
            capability = ClientCapability[cap_name]
            capabilities.add(capability)
        except KeyError:
            # Unknown capability, skip
            continue

    return capabilities


def negotiate_format(
    preferred: str,
    client_caps: set[ClientCapability],
    fallback_chain: list[str] | None = None,
) -> str:
    """Negotiate the best format based on client capabilities.

    This function determines the best format to use for a resource response
    based on what the client supports. It attempts to use the preferred format
    but falls back to supported alternatives if needed.

    Args:
        preferred: Preferred format ("text", "image", "binary", "xml")
        client_caps: Set of client capabilities
        fallback_chain: Optional custom fallback chain (defaults to ["text"])

    Returns:
        The negotiated format string

    Example:
        >>> caps = {ClientCapability.IMAGES, ClientCapability.BINARY}
        >>> negotiate_format("image", caps)
        'image'
        >>> negotiate_format("xml", caps)  # XML not in caps
        'text'
        >>> negotiate_format("binary", set())  # No binary support
        'text'
    """
    # If preferred is text, always allowed
    if preferred == "text":
        return "text"

    # Check if preferred format is supported
    required_cap = FORMAT_CAPABILITIES.get(preferred)
    if required_cap is None or required_cap in client_caps:
        return preferred

    # Build fallback chain
    if fallback_chain is None:
        # Default fallback chain: try binary->image->xml->text
        fallback_chain = []
        if ClientCapability.BINARY in client_caps:
            fallback_chain.append("binary")
        if ClientCapability.IMAGES in client_caps:
            fallback_chain.append("image")
        if ClientCapability.XML_FORMAT in client_caps:
            fallback_chain.append("xml")
        fallback_chain.append("text")  # Always fall back to text

    # Find first supported format in fallback chain
    for fmt in fallback_chain:
        if fmt == "text":
            return "text"
        cap = FORMAT_CAPABILITIES.get(fmt)
        if cap is None or cap in client_caps:
            return fmt

    # Ultimate fallback to text
    return "text"


@dataclass(frozen=True)
class CapabilityMetadata:
    """Capability metadata for resource responses.

    This dataclass contains information about client capabilities
    and format recommendations for resource responses.

    Attributes:
        supported_formats: List of formats supported by the client
        capability_version: Version of the capability system
        recommendations: Dict with format recommendations by content type
        detected_capabilities: Set of raw client capability flags

    Example:
        >>> metadata = CapabilityMetadata(
        ...     supported_formats=["text", "image", "binary"],
        ...     capability_version="1.0",
        ...     recommendations={"image/png": "image", "text/plain": "text"},
        ...     detected_capabilities={ClientCapability.IMAGES},
        ... )
    """

    supported_formats: list[str] = field(default_factory=list)
    capability_version: str = "1.0"
    recommendations: dict[str, str] = field(default_factory=dict)
    detected_capabilities: set[ClientCapability] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary representation."""
        return {
            "supported_formats": self.supported_formats,
            "capability_version": self.capability_version,
            "recommendations": self.recommendations,
            "detected_capabilities": [cap.name for cap in self.detected_capabilities],
        }

    @classmethod
    def from_capabilities(
        cls,
        capabilities: set[ClientCapability],
        mime_type: str | None = None,
    ) -> CapabilityMetadata:
        """Create metadata from a set of capabilities.

        Args:
            capabilities: Set of client capabilities
            mime_type: Optional MIME type for specific recommendations

        Returns:
            CapabilityMetadata instance
        """
        # Build supported formats list
        supported_formats = ["text"]  # Text is always supported
        if ClientCapability.IMAGES in capabilities:
            supported_formats.append("image")
        if ClientCapability.BINARY in capabilities:
            supported_formats.append("binary")
        if ClientCapability.XML_FORMAT in capabilities:
            supported_formats.append("xml")

        # Build recommendations
        recommendations: dict[str, str] = {}

        if mime_type:
            # Determine best format for the specific MIME type
            if mime_type.startswith("image/"):
                recommendations[mime_type] = negotiate_format("image", capabilities)
            elif mime_type in ("application/xml", "text/xml"):
                recommendations[mime_type] = negotiate_format("xml", capabilities)
            elif is_binary_mime_type(mime_type):
                recommendations[mime_type] = negotiate_format("binary", capabilities)
            else:
                recommendations[mime_type] = "text"

        # General recommendations by category
        recommendations.update(
            {
                "image/*": negotiate_format("image", capabilities),
                "text/*": "text",
                "application/*": negotiate_format("binary", capabilities),
            }
        )

        return cls(
            supported_formats=supported_formats,
            capability_version="1.0",
            recommendations=recommendations,
            detected_capabilities=capabilities,
        )


def is_binary_mime_type(mime_type: str) -> bool:
    """Check if a MIME type represents binary content.

    Args:
        mime_type: MIME type string

    Returns:
        True if the MIME type is binary
    """
    if mime_type.startswith("image/"):
        return True
    if mime_type.startswith("audio/"):
        return True
    if mime_type.startswith("video/"):
        return True
    if mime_type in (
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-tar",
    ):
        return True
    if mime_type.startswith("application/") and mime_type not in (
        "application/json",
        "application/javascript",
        "application/xml",
        "application/x-httpd-php",
        "application/x-sh",
        "application/x-ruby",
    ):
        return True
    return False


def get_capability_info_for_resource(
    uri: str,
    mime_type: str,
    client_caps: set[ClientCapability] | None = None,
) -> dict[str, Any]:
    """Get capability information for a resource response.

    This helper function generates capability metadata for inclusion
    in resource responses.

    Args:
        uri: The resource URI
        mime_type: MIME type of the resource
        client_caps: Optional client capabilities (detected if None)

    Returns:
        Dictionary with capability information
    """
    if client_caps is None:
        client_caps = set()

    metadata = CapabilityMetadata.from_capabilities(client_caps, mime_type)

    result: dict[str, Any] = {
        "supported_formats": metadata.supported_formats,
        "capability_version": metadata.capability_version,
        "recommendations": metadata.recommendations,
    }

    # Add subscription info if supported
    if ClientCapability.SUBSCRIPTIONS in client_caps:
        result["subscription_supported"] = True

    # Add thumbnail info if supported and resource is an image
    if ClientCapability.THUMBNAILS in client_caps and mime_type.startswith("image/"):
        result["thumbnail_available"] = True

    return result
