"""MCP Resources module for scratchpad filesystem access.

This module provides FastMCP resource handlers for accessing scratchpad files
via the scratchpad:// URI scheme.
"""

from .binary_handler import (
    DEFAULT_MAX_PAGES,
    LARGE_PDF_THRESHOLD,
    BinaryResource,
    PDFMetadata,
    detect_binary_format,
    extract_pdf_metadata,
    extract_pdf_text,
    is_binary_file,
    process_binary_resource,
    process_pdf_resource,
)
from .capabilities import (
    CLIENT_PROFILES,
    ClientCapability,
    CapabilityMetadata,
    detect_client_capabilities,
    get_capability_info_for_resource,
    is_binary_mime_type,
    negotiate_format,
)
from .image_handler import (
    LARGE_IMAGE_THRESHOLD,
    THUMBNAIL_SIZES,
    ImageDimensions,
    ImageFormat,
    ImageMetadata,
    ImageResource,
    detect_image_format,
    extract_image_metadata,
    generate_thumbnail,
    generate_thumbnails,
    image_to_base64,
    process_image_resource,
)
from .read_handler import (
    ResourceContent,
    ResourceContentType,
    ResourceMetadata,
    ResourceReadError,
    ResourceReadResult,
    classify_content_type,
    detect_mime_type,
    read_resource,
    read_resource_bytes,
    read_resource_text,
)
from .scratchpad_resources import ResourceError, register_scratchpad_resources
from .subscription import (
    ResourceSubscriptionError,
    ResourceSubscriptionManager,
    Subscription,
    cleanup_session_subscriptions,
    get_resource_subscription_info,
    is_resource_subscribed,
    list_resource_subscriptions,
    subscribe_to_resource,
    unsubscribe_from_resource,
)
from .uri_parser import (
    ScratchpadURI,
    URIParseError,
    build_scratchpad_uri,
    is_valid_scratchpad_uri,
    parse_scratchpad_uri,
)
from .xml_wrapper import (
    XMLResourceError,
    XMLResourceWrapper,
    parse_resource_xml,
    read_directory_as_xml,
    read_resource_as_xml,
    validate_resource_xml,
)

__all__ = [
    # capabilities
    "ClientCapability",
    "CapabilityMetadata",
    "CLIENT_PROFILES",
    "detect_client_capabilities",
    "negotiate_format",
    "is_binary_mime_type",
    "get_capability_info_for_resource",
    # binary_handler
    "BinaryResource",
    "PDFMetadata",
    "process_pdf_resource",
    "process_binary_resource",
    "extract_pdf_metadata",
    "extract_pdf_text",
    "detect_binary_format",
    "is_binary_file",
    "LARGE_PDF_THRESHOLD",
    "DEFAULT_MAX_PAGES",
    # image_handler
    "ImageResource",
    "ImageMetadata",
    "ImageDimensions",
    "ImageFormat",
    "process_image_resource",
    "generate_thumbnail",
    "generate_thumbnails",
    "extract_image_metadata",
    "detect_image_format",
    "image_to_base64",
    "LARGE_IMAGE_THRESHOLD",
    "THUMBNAIL_SIZES",
    # scratchpad_resources
    "register_scratchpad_resources",
    "ResourceError",
    # read_handler
    "ResourceReadError",
    "ResourceReadResult",
    "ResourceContent",
    "ResourceMetadata",
    "ResourceContentType",
    "read_resource",
    "read_resource_text",
    "read_resource_bytes",
    "detect_mime_type",
    "classify_content_type",
    # subscription
    "ResourceSubscriptionManager",
    "ResourceSubscriptionError",
    "Subscription",
    "subscribe_to_resource",
    "unsubscribe_from_resource",
    "get_resource_subscription_info",
    "is_resource_subscribed",
    "list_resource_subscriptions",
    "cleanup_session_subscriptions",
    # uri_parser
    "ScratchpadURI",
    "URIParseError",
    "build_scratchpad_uri",
    "is_valid_scratchpad_uri",
    "parse_scratchpad_uri",
    # xml_wrapper
    "XMLResourceWrapper",
    "XMLResourceError",
    "read_resource_as_xml",
    "read_directory_as_xml",
    "parse_resource_xml",
    "validate_resource_xml",
]
