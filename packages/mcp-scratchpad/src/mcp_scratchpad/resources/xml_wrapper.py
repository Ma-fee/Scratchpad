"""
XML wrapper for MCP resources.

This module provides XML formatting and parsing for MCP resource data,
standardizing the representation of file resources in XML format.

Features:
    - Convert ResourceReadResult to XML
    - Read resources as XML strings
    - Parse XML back to structured data
    - XML schema validation support
    - Pretty-printed XML output
    - Base64 encoding for binary content

Example:
    >>> from mcp_scratchpad.resources.xml_wrapper import read_resource_as_xml
    >>> xml_string = read_resource_as_xml("scratchpad://abc-123/file.txt")
    >>> print(xml_string)
    <?xml version="1.0" encoding="UTF-8"?>
    <resource type="text">
      <uri>scratchpad://abc-123/file.txt</uri>
      ...
    </resource>
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union
from xml.dom import minidom
from xml.etree import ElementTree as ET

from .read_handler import (
    DirectoryEntry,
    DirectoryListingResult,
    ResourceContent,
    ResourceContentType,
    ResourceMetadata,
    ResourceReadResult,
    read_directory_resource,
    read_resource,
)

logger = logging.getLogger(__name__)

# XML namespace and schema
XML_NAMESPACE = "urn:mcp:scratchpad:resource:1.0"
XML_SCHEMA_VERSION = "1.0"

# XML element names
ELEMENT_RESOURCE = "resource"
ELEMENT_URI = "uri"
ELEMENT_SESSION_ID = "session_id"
ELEMENT_PATH = "path"
ELEMENT_METADATA = "metadata"
ELEMENT_CONTENT = "content"
ELEMENT_SIZE = "size"
ELEMENT_MIMETYPE = "mimetype"
ELEMENT_MODIFIED = "modified"
ELEMENT_CREATED = "created"
ELEMENT_EXTENSION = "extension"
ELEMENT_CONTENT_TYPE = "content_type"
ELEMENT_IS_DIRECTORY = "is_directory"
ELEMENT_IS_BINARY = "is_binary"
ELEMENT_ENCODING = "encoding"
ELEMENT_DATA = "data"
ELEMENT_SUCCESS = "success"
ELEMENT_ERROR = "error"
ELEMENT_ENTRIES = "entries"
ELEMENT_ENTRY = "entry"
ELEMENT_NAME = "name"
ELEMENT_TYPE = "type"
ELEMENT_SUBSCRIPTION_INFO = "subscription_info"
ELEMENT_CAPABILITIES = "capabilities"
ELEMENT_CAPABILITY = "capability"

# Attribute names
ATTR_TYPE = "type"
ATTR_VERSION = "version"
ATTR_ENCODING = "encoding"
ATTR_TIMESTAMP = "timestamp"
ATTR_NAMESPACE = "xmlns"


class XMLResourceError(Exception):
    """Exception raised when XML resource operations fail.

    Attributes:
        message: Error message
        cause: Original exception if any
    """

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


@dataclass
class XMLResourceWrapper:
    """Wrapper for converting resources to XML format.

    This class provides methods to convert various resource types
    (ResourceReadResult, DirectoryListingResult) into well-formed
    XML representations suitable for MCP protocol responses.

    Attributes:
        pretty_print: Whether to pretty-print XML output
        include_xml_declaration: Whether to include XML declaration
        namespace: Optional XML namespace to use

    Example:
        >>> from mcp_scratchpad.resources.xml_wrapper import XMLResourceWrapper
        >>> wrapper = XMLResourceWrapper(pretty_print=True)
        >>> result = read_resource("scratchpad://abc-123/file.txt")
        >>> xml_string = wrapper.to_xml(result)
        >>> print(xml_string)
    """

    pretty_print: bool = True
    include_xml_declaration: bool = True
    namespace: Optional[str] = None  # 默认不使用命名空间，以便简化XML

    def to_xml(
        self,
        resource: Union[ResourceReadResult, DirectoryListingResult, dict[str, Any]],
    ) -> str:
        """Convert a resource to XML string.

        Args:
            resource: The resource to convert (ResourceReadResult, DirectoryListingResult, or dict)

        Returns:
            XML string representation of the resource

        Raises:
            XMLResourceError: If conversion fails

        Example:
            >>> wrapper = XMLResourceWrapper()
            >>> result = read_resource("scratchpad://abc-123/file.txt")
            >>> xml = wrapper.to_xml(result)
        """
        try:
            if isinstance(resource, ResourceReadResult):
                root = self._resource_read_result_to_element(resource)
            elif isinstance(resource, DirectoryListingResult):
                root = self._directory_listing_result_to_element(resource)
            elif isinstance(resource, dict):
                root = self._dict_to_element(resource)
            else:
                raise XMLResourceError(
                    f"Unsupported resource type: {type(resource).__name__}"
                )

            return self._element_to_string(root)
        except Exception as e:
            logger.error(f"Failed to convert resource to XML: {e}")
            raise XMLResourceError(f"Failed to convert to XML: {e}", cause=e) from e

    def _resource_read_result_to_element(
        self, result: ResourceReadResult
    ) -> ET.Element:
        """Convert ResourceReadResult to XML Element."""
        # Determine resource type attribute
        resource_type = self._get_resource_type(result)

        # Create root element
        attribs = {ATTR_TYPE: resource_type}
        if self.namespace:
            attribs[ATTR_NAMESPACE] = self.namespace

        root = ET.Element(ELEMENT_RESOURCE, attribs)

        # Add basic info
        ET.SubElement(root, ELEMENT_URI).text = result.uri
        ET.SubElement(root, ELEMENT_SESSION_ID).text = result.session_id
        ET.SubElement(root, ELEMENT_PATH).text = result.path

        # Add metadata
        metadata_elem = self._resource_metadata_to_element(result.metadata)
        root.append(metadata_elem)

        # Add content
        content_elem = self._resource_content_to_element(result.content)
        root.append(content_elem)

        # Add success/error
        ET.SubElement(root, ELEMENT_SUCCESS).text = str(result.success).lower()
        if result.error:
            ET.SubElement(root, ELEMENT_ERROR).text = result.error

        # Add subscription info if present
        if result.subscription_info:
            sub_elem = self._subscription_info_to_element(result.subscription_info)
            root.append(sub_elem)

        # Add capabilities element (MCP capabilities)
        self._add_capabilities(root, result)

        return root

    def _get_resource_type(self, result: ResourceReadResult) -> str:
        """Determine resource type based on metadata and content."""
        # 首先检查是否为目录类型
        if result.metadata.is_directory:
            return "directory"

        # 检查是否为图像类型（基于MIME类型或content_type）
        if result.metadata.content_type == ResourceContentType.IMAGE.value:
            return "image"
        if result.metadata.mime_type.startswith("image/"):
            return "image"

        # 检查是否为文本类型（非二进制且content_type为text）
        if (
            not result.content.is_binary
            and result.metadata.content_type == ResourceContentType.TEXT.value
        ):
            return "text"

        # 检查是否为二进制内容
        if result.content.is_binary:
            return "binary"

        # 默认为文本类型（对于非二进制、非图像的内容）
        return "text"

    def _resource_metadata_to_element(self, metadata: ResourceMetadata) -> ET.Element:
        """Convert ResourceMetadata to XML Element."""
        meta_elem = ET.Element(ELEMENT_METADATA)

        ET.SubElement(meta_elem, ELEMENT_SIZE).text = str(metadata.size)
        ET.SubElement(meta_elem, ELEMENT_MIMETYPE).text = metadata.mime_type

        if metadata.modified:
            ET.SubElement(meta_elem, ELEMENT_MODIFIED).text = metadata.modified
        if metadata.created:
            ET.SubElement(meta_elem, ELEMENT_CREATED).text = metadata.created
        if metadata.content_type:
            ET.SubElement(meta_elem, ELEMENT_CONTENT_TYPE).text = metadata.content_type
        if metadata.extension:
            ET.SubElement(meta_elem, ELEMENT_EXTENSION).text = metadata.extension
        ET.SubElement(meta_elem, ELEMENT_IS_DIRECTORY).text = str(
            metadata.is_directory
        ).lower()

        return meta_elem

    def _resource_content_to_element(self, content: ResourceContent) -> ET.Element:
        """Convert ResourceContent to XML Element."""
        attribs = {}
        if content.encoding:
            attribs[ATTR_ENCODING] = content.encoding

        content_elem = ET.Element(ELEMENT_CONTENT, attribs)

        # Add encoding info
        ET.SubElement(content_elem, ELEMENT_IS_BINARY).text = str(
            content.is_binary
        ).lower()
        ET.SubElement(content_elem, ELEMENT_SIZE).text = str(content.size_bytes)

        # Add data element
        data_elem = ET.SubElement(content_elem, ELEMENT_DATA)

        # Safely encode content
        if content.is_binary and isinstance(content.data, bytes):
            # Binary content, always base64
            data_elem.text = base64.b64encode(content.data).decode("ascii")
        elif isinstance(content.data, bytes):
            # Non-binary but bytes, try to decode as UTF-8
            try:
                data_elem.text = content.data.decode("utf-8")
            except UnicodeDecodeError:
                # Fall back to base64
                data_elem.text = base64.b64encode(content.data).decode("ascii")
                attribs[ATTR_ENCODING] = "base64"
                content_elem.set(ATTR_ENCODING, "base64")
        else:
            # Text content, handle special XML characters via CDATA or escaping
            data_elem.text = content.data

        return content_elem

    def _subscription_info_to_element(self, info: dict[str, Any]) -> ET.Element:
        """Convert subscription info dict to XML Element."""
        sub_elem = ET.Element(ELEMENT_SUBSCRIPTION_INFO)

        for key, value in info.items():
            child = ET.SubElement(sub_elem, key.replace("-", "_"))
            if isinstance(value, bool):
                child.text = str(value).lower()
            elif isinstance(value, list):
                child.text = ",".join(str(v) for v in value)
            elif value is not None:
                child.text = str(value)

        return sub_elem

    def _add_capabilities(self, root: ET.Element, result: ResourceReadResult) -> None:
        """Add MCP capabilities element to resource."""
        caps_elem = ET.SubElement(root, ELEMENT_CAPABILITIES)

        # Define standard capabilities based on resource type
        capabilities = ["read"]

        if not result.metadata.is_directory and not result.content.is_binary:
            # Text files also support chunk reading
            capabilities.extend(["read_chunk", "read_partial"])

        if result.subscription_info.get("is_subscribed"):
            capabilities.append("subscribe")

        for cap in capabilities:
            ET.SubElement(caps_elem, ELEMENT_CAPABILITY).text = cap

    def _directory_listing_result_to_element(
        self, result: DirectoryListingResult
    ) -> ET.Element:
        """Convert DirectoryListingResult to XML Element."""
        attribs = {ATTR_TYPE: "directory"}
        if self.namespace:
            attribs[ATTR_NAMESPACE] = self.namespace

        root = ET.Element(ELEMENT_RESOURCE, attribs)

        # Add basic info
        ET.SubElement(root, ELEMENT_URI).text = result.uri
        ET.SubElement(root, ELEMENT_SESSION_ID).text = result.session_id
        ET.SubElement(root, ELEMENT_PATH).text = result.path

        # Add metadata
        meta_elem = ET.Element(ELEMENT_METADATA)
        ET.SubElement(meta_elem, ELEMENT_SIZE).text = "0"
        ET.SubElement(meta_elem, ELEMENT_MIMETYPE).text = "inode/directory"
        ET.SubElement(meta_elem, ELEMENT_IS_DIRECTORY).text = "true"
        root.append(meta_elem)

        # Add entries
        entries_elem = ET.SubElement(root, ELEMENT_ENTRIES)
        for entry in result.entries:
            entry_elem = self._directory_entry_to_element(entry)
            entries_elem.append(entry_elem)

        # Add pagination info
        ET.SubElement(root, "total_count").text = str(result.total_count)
        ET.SubElement(root, "has_more").text = str(result.has_more).lower()
        ET.SubElement(root, "offset").text = str(result.offset)
        ET.SubElement(root, "limit").text = str(result.limit)

        # Add success/error
        ET.SubElement(root, ELEMENT_SUCCESS).text = str(result.success).lower()
        if result.error:
            ET.SubElement(root, ELEMENT_ERROR).text = result.error

        # Add capabilities
        caps_elem = ET.SubElement(root, ELEMENT_CAPABILITIES)
        for cap in ["read", "list", "enumerate"]:
            ET.SubElement(caps_elem, ELEMENT_CAPABILITY).text = cap

        return root

    def _directory_entry_to_element(self, entry: DirectoryEntry) -> ET.Element:
        """Convert DirectoryEntry to XML Element."""
        entry_elem = ET.Element(ELEMENT_ENTRY)

        ET.SubElement(entry_elem, ELEMENT_NAME).text = entry.name
        ET.SubElement(entry_elem, ELEMENT_TYPE).text = entry.type
        ET.SubElement(entry_elem, ELEMENT_SIZE).text = str(entry.size)

        if entry.mimetype:
            ET.SubElement(entry_elem, ELEMENT_MIMETYPE).text = entry.mimetype
        if entry.modified_time:
            ET.SubElement(entry_elem, ELEMENT_MODIFIED).text = entry.modified_time

        return entry_elem

    def _dict_to_element(self, data: dict[str, Any]) -> ET.Element:
        """Convert a dict to XML Element (generic conversion)."""
        root = ET.Element(ELEMENT_RESOURCE)

        for key, value in data.items():
            if isinstance(value, dict):
                child = ET.SubElement(root, key)
                self._populate_element_from_dict(child, value)
            elif isinstance(value, list):
                list_elem = ET.SubElement(root, key)
                for item in value:
                    if isinstance(item, dict):
                        self._populate_element_from_dict(
                            ET.SubElement(list_elem, "item"), item
                        )
                    else:
                        ET.SubElement(list_elem, "item").text = str(item)
            else:
                child = ET.SubElement(root, key)
                if value is not None:
                    child.text = str(value)

        return root

    def _populate_element_from_dict(
        self, element: ET.Element, data: dict[str, Any]
    ) -> None:
        """Populate an XML element from dictionary data."""
        for key, value in data.items():
            if isinstance(value, dict):
                child = ET.SubElement(element, key)
                self._populate_element_from_dict(child, value)
            else:
                child = ET.SubElement(element, key)
                if value is not None:
                    child.text = str(value)

    def _element_to_string(self, element: ET.Element) -> str:
        """Convert XML Element to string with optional pretty printing."""
        # Use ElementTree to get basic XML string
        rough_string = ET.tostring(element, encoding="unicode")

        if self.pretty_print:
            # Reparse and pretty print using minidom
            reparsed = minidom.parseString(rough_string)
            pretty = reparsed.toprettyxml(indent="  ")

            # Remove extra blank lines
            lines = [line for line in pretty.split("\n") if line.strip()]
            result = "\n".join(lines)
        else:
            result = rough_string

        if self.include_xml_declaration:
            # Ensure XML declaration has encoding
            if not result.startswith("<?xml"):
                result = '<?xml version="1.0" encoding="UTF-8"?>\n' + result
            elif 'encoding="UTF-8"' not in result:
                # Add encoding if missing
                result = result.replace(
                    '<?xml version="1.0" ?>', '<?xml version="1.0" encoding="UTF-8"?>'
                )

        return result


def read_resource_as_xml(
    uri: str,
    pretty_print: bool = True,
    include_xml_declaration: bool = True,
    **kwargs: Any,
) -> str:
    """Read a resource and return it as XML string.

    This is a convenience function that combines read_resource() with
    XML formatting. It reads the resource and converts it to XML format.

    Args:
        uri: The scratchpad:// URI to read
        pretty_print: Whether to pretty-print the XML output
        include_xml_declaration: Whether to include XML declaration
        **kwargs: Additional arguments passed to read_resource()

    Returns:
        XML string representation of the resource

    Raises:
        XMLResourceError: If reading or conversion fails

    Example:
        >>> xml = read_resource_as_xml("scratchpad://abc-123/file.txt")
        >>> print(xml)
        <?xml version="1.0" encoding="UTF-8"?>
        <resource type="text">
          <uri>scratchpad://abc-123/file.txt</uri>
          ...
        </resource>
    """
    try:
        result = read_resource(uri, **kwargs)

        if not result.success and not result.error:
            result = ResourceReadResult(
                uri=uri,
                session_id="",
                path="",
                content=ResourceContent(
                    data="",
                    encoding="utf-8",
                    is_binary=False,
                    size_bytes=0,
                ),
                metadata=ResourceMetadata(
                    size=0,
                    mime_type="application/octet-stream",
                ),
                success=False,
                error="Unknown error",
            )

        wrapper = XMLResourceWrapper(
            pretty_print=pretty_print,
            include_xml_declaration=include_xml_declaration,
        )
        return wrapper.to_xml(result)
    except Exception as e:
        if isinstance(e, XMLResourceError):
            raise
        logger.error(f"Failed to read resource as XML: {e}")
        raise XMLResourceError(f"Failed to read resource as XML: {e}", cause=e) from e


def read_directory_as_xml(
    uri: str,
    pretty_print: bool = True,
    include_xml_declaration: bool = True,
    limit: int = 100,
    offset: int = 0,
    **kwargs: Any,
) -> str:
    """Read a directory listing and return it as XML string.

    This is a convenience function that combines read_directory_resource()
    with XML formatting.

    Args:
        uri: The scratchpad:// URI to read
        pretty_print: Whether to pretty-print the XML output
        include_xml_declaration: Whether to include XML declaration
        limit: Maximum number of entries to return
        offset: Number of entries to skip
        **kwargs: Additional arguments passed to read_directory_resource()

    Returns:
        XML string representation of the directory listing

    Raises:
        XMLResourceError: If reading or conversion fails

    Example:
        >>> xml = read_directory_as_xml("scratchpad://abc-123/workspace/")
        >>> print(xml)
        <?xml version="1.0" encoding="UTF-8"?>
        <resource type="directory">
          <uri>scratchpad://abc-123/workspace/</uri>
          <entries>
            <entry>
              <name>file.txt</name>
              ...
            </entry>
            ...
          </entries>
          ...
        </resource>
    """
    try:
        result = read_directory_resource(uri, limit=limit, offset=offset, **kwargs)

        wrapper = XMLResourceWrapper(
            pretty_print=pretty_print,
            include_xml_declaration=include_xml_declaration,
        )
        return wrapper.to_xml(result)
    except Exception as e:
        if isinstance(e, XMLResourceError):
            raise
        logger.error(f"Failed to read directory as XML: {e}")
        raise XMLResourceError(f"Failed to read directory as XML: {e}", cause=e) from e


def parse_resource_xml(xml_string: str) -> dict[str, Any]:
    """Parse an XML resource string back to structured data.

    This function parses an XML resource representation and returns
    it as a dictionary. It supports both single resources and
    directory listings.

    Args:
        xml_string: The XML string to parse

    Returns:
        Dictionary representation of the XML resource

    Raises:
        XMLResourceError: If parsing fails

    Example:
        >>> xml = '''<?xml version="1.0" encoding="UTF-8"?>
        ... <resource type="text">
        ...   <uri>scratchpad://abc-123/file.txt</uri>
        ...   <content><data>Hello World</data></content>
        ... </resource>'''
        >>> data = parse_resource_xml(xml)
        >>> data['uri']
        'scratchpad://abc-123/file.txt'
        >>> data['content']['data']
        'Hello World'
    """
    try:
        # Parse XML string
        root = ET.fromstring(xml_string)

        # Check root element
        if root.tag != ELEMENT_RESOURCE:
            raise XMLResourceError(
                f"Expected root element '{ELEMENT_RESOURCE}', got '{root.tag}'"
            )

        # Convert to dict
        result = _element_to_dict(root)

        return result
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        raise XMLResourceError(f"Invalid XML: {e}", cause=e) from e
    except Exception as e:
        if isinstance(e, XMLResourceError):
            raise
        logger.error(f"Failed to parse XML: {e}")
        raise XMLResourceError(f"Failed to parse XML: {e}", cause=e) from e


def _element_to_dict(element: ET.Element) -> dict[str, Any]:
    """Convert an XML element to a dictionary."""
    result: dict[str, Any] = {}

    # Get attributes
    result.update(element.attrib)

    # Process child elements
    children_by_tag: dict[str, list[ET.Element]] = {}
    for child in element:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        children_by_tag.setdefault(tag, []).append(child)

    for tag, children in children_by_tag.items():
        if len(children) == 1:
            # Single child
            result[tag] = (
                _element_to_dict(children[0])
                if list(children[0])
                else children[0].text or ""
            )
        else:
            # Multiple children with same tag
            result[tag] = [
                _element_to_dict(child) if list(child) else child.text or ""
                for child in children
            ]

    return result


def validate_resource_xml(xml_string: str) -> tuple[bool, Optional[str]]:
    """Validate an XML resource string.

    Performs basic structural validation of the XML to ensure
    it represents a valid MCP resource.

    Args:
        xml_string: The XML string to validate

    Returns:
        Tuple of (is_valid, error_message). If is_valid is True,
        error_message is None.

    Example:
        >>> is_valid, error = validate_resource_xml(xml_string)
        >>> if not is_valid:
        ...     print(f"Validation failed: {error}")
    """
    try:
        # Try to parse
        root = ET.fromstring(xml_string)

        # Check root element
        if root.tag != ELEMENT_RESOURCE:
            return (
                False,
                f"Expected root element '{ELEMENT_RESOURCE}', got '{root.tag}'",
            )

        # Check required elements
        required = [ELEMENT_URI]
        for req in required:
            if root.find(f".//{req}") is None:
                return False, f"Missing required element: '{req}'"

        return True, None
    except ET.ParseError as e:
        return False, f"XML parse error: {e}"
    except Exception as e:
        return False, str(e)
