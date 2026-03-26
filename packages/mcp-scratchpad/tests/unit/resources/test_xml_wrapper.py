"""Tests for XML resource wrapper module.

This module tests the XMLResourceWrapper class and related functions
to ensure proper XML formatting and parsing of MCP resources.
"""

from __future__ import annotations

import base64
import pytest
from xml.etree import ElementTree as ET

from mcp_scratchpad.resources.read_handler import (
    DirectoryEntry,
    DirectoryListingResult,
    ResourceContent,
    ResourceContentType,
    ResourceMetadata,
    ResourceReadResult,
)
from mcp_scratchpad.resources.xml_wrapper import (
    ELEMENT_CAPABILITIES,
    ELEMENT_CAPABILITY,
    ELEMENT_CONTENT,
    ELEMENT_CONTENT_TYPE,
    ELEMENT_CREATED,
    ELEMENT_DATA,
    ELEMENT_ENTRIES,
    ELEMENT_ENTRY,
    ELEMENT_ERROR,
    ELEMENT_EXTENSION,
    ELEMENT_IS_BINARY,
    ELEMENT_IS_DIRECTORY,
    ELEMENT_METADATA,
    ELEMENT_MIMETYPE,
    ELEMENT_MODIFIED,
    ELEMENT_NAME,
    ELEMENT_PATH,
    ELEMENT_RESOURCE,
    ELEMENT_SESSION_ID,
    ELEMENT_SIZE,
    ELEMENT_SUCCESS,
    ELEMENT_TYPE,
    ELEMENT_URI,
    XML_NAMESPACE,
    XMLResourceError,
    XMLResourceWrapper,
    _element_to_dict,
    parse_resource_xml,
    validate_resource_xml,
)


class TestXMLResourceWrapper:
    """Test XMLResourceWrapper class."""

    @pytest.mark.unit
    def test_wrapper_initialization(self) -> None:
        """Test XMLResourceWrapper initialization with default values."""
        wrapper = XMLResourceWrapper()
        assert wrapper.pretty_print is True
        assert wrapper.include_xml_declaration is True
        assert wrapper.namespace is None  # 默认不使用命名空间

    @pytest.mark.unit
    def test_wrapper_initialization_custom(self) -> None:
        """Test XMLResourceWrapper initialization with custom values."""
        wrapper = XMLResourceWrapper(
            pretty_print=False,
            include_xml_declaration=False,
            namespace="custom:namespace",
        )
        assert wrapper.pretty_print is False
        assert wrapper.include_xml_declaration is False
        assert wrapper.namespace == "custom:namespace"

    @pytest.mark.unit
    def test_wrapper_namespace_none(self) -> None:
        """Test XMLResourceWrapper with no namespace."""
        wrapper = XMLResourceWrapper(namespace=None)
        assert wrapper.namespace is None


class TestResourceToXML:
    """Test converting ResourceReadResult to XML."""

    @pytest.fixture
    def sample_text_result(self) -> ResourceReadResult:
        """Create a sample text file ResourceReadResult."""
        return ResourceReadResult(
            uri="scratchpad://abc-123/workspace/file.txt",
            session_id="abc-123",
            path="/workspace/file.txt",
            content=ResourceContent(
                data="Hello, World!",
                encoding="utf-8",
                is_binary=False,
                size_bytes=13,
            ),
            metadata=ResourceMetadata(
                size=13,
                mime_type="text/plain",
                modified="2024-01-15T10:30:00",
                created="2024-01-15T10:00:00",
                content_type="text",
                extension=".txt",
                is_directory=False,
            ),
            success=True,
            error=None,
        )

    @pytest.fixture
    def sample_binary_result(self) -> ResourceReadResult:
        """Create a sample binary file ResourceReadResult."""
        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        return ResourceReadResult(
            uri="scratchpad://abc-123/workspace/image.png",
            session_id="abc-123",
            path="/workspace/image.png",
            content=ResourceContent(
                data=binary_data,
                encoding="base64",
                is_binary=True,
                size_bytes=len(binary_data),
            ),
            metadata=ResourceMetadata(
                size=len(binary_data),
                mime_type="image/png",
                modified="2024-01-15T11:00:00",
                content_type="image",
                extension=".png",
                is_directory=False,
            ),
            success=True,
            error=None,
        )

    @pytest.fixture
    def sample_error_result(self) -> ResourceReadResult:
        """Create a sample error ResourceReadResult."""
        return ResourceReadResult(
            uri="scratchpad://abc-123/nonexistent.txt",
            session_id="abc-123",
            path="/nonexistent.txt",
            content=ResourceContent(
                data="",
                encoding="utf-8",
                is_binary=False,
                size_bytes=0,
            ),
            metadata=ResourceMetadata(
                size=0,
                mime_type="application/octet-stream",
                is_directory=False,
            ),
            success=False,
            error="File not found: /nonexistent.txt",
        )

    @pytest.mark.unit
    def test_text_resource_to_xml(self, sample_text_result: ResourceReadResult) -> None:
        """Test converting text resource to XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_text_result)

        # Check XML declaration
        assert xml_string.startswith('<?xml version="1.0" encoding="UTF-8"?>')

        # Parse and verify structure
        root = ET.fromstring(xml_string)
        assert root.tag == ELEMENT_RESOURCE
        assert root.get("type") == "text"

        # Check URI
        uri_elem = root.find(f".//{ELEMENT_URI}")
        assert uri_elem is not None
        assert uri_elem.text == "scratchpad://abc-123/workspace/file.txt"

        # Check session ID
        session_elem = root.find(f".//{ELEMENT_SESSION_ID}")
        assert session_elem is not None
        assert session_elem.text == "abc-123"

        # Check path
        path_elem = root.find(f".//{ELEMENT_PATH}")
        assert path_elem is not None
        assert path_elem.text == "/workspace/file.txt"

    @pytest.mark.unit
    def test_text_resource_content_xml(
        self, sample_text_result: ResourceReadResult
    ) -> None:
        """Test text resource content in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_text_result)

        root = ET.fromstring(xml_string)

        # Check content
        content_elem = root.find(f".//{ELEMENT_CONTENT}")
        assert content_elem is not None
        assert content_elem.get("encoding") == "utf-8"

        # Check data
        data_elem = content_elem.find(f".//{ELEMENT_DATA}")
        assert data_elem is not None
        assert data_elem.text == "Hello, World!"

        # Check is_binary
        is_binary_elem = content_elem.find(f".//{ELEMENT_IS_BINARY}")
        assert is_binary_elem is not None
        assert is_binary_elem.text == "false"

    @pytest.mark.unit
    def test_text_resource_metadata_xml(
        self, sample_text_result: ResourceReadResult
    ) -> None:
        """Test text resource metadata in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_text_result)

        root = ET.fromstring(xml_string)

        metadata_elem = root.find(f".//{ELEMENT_METADATA}")
        assert metadata_elem is not None

        # Check size
        size_elem = metadata_elem.find(f".//{ELEMENT_SIZE}")
        assert size_elem is not None
        assert size_elem.text == "13"

        # Check MIME type
        mimetype_elem = metadata_elem.find(f".//{ELEMENT_MIMETYPE}")
        assert mimetype_elem is not None
        assert mimetype_elem.text == "text/plain"

        # Check modified
        modified_elem = metadata_elem.find(f".//{ELEMENT_MODIFIED}")
        assert modified_elem is not None
        assert modified_elem.text == "2024-01-15T10:30:00"

        # Check created
        created_elem = metadata_elem.find(f".//{ELEMENT_CREATED}")
        assert created_elem is not None
        assert created_elem.text == "2024-01-15T10:00:00"

        # Check extension
        ext_elem = metadata_elem.find(f".//{ELEMENT_EXTENSION}")
        assert ext_elem is not None
        assert ext_elem.text == ".txt"

    @pytest.mark.unit
    def test_binary_resource_to_xml(
        self, sample_binary_result: ResourceReadResult
    ) -> None:
        """Test converting binary image resource to XML with base64 encoding."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_binary_result)

        root = ET.fromstring(xml_string)
        # PNG images are detected as type "image", not "binary"
        assert root.get("type") == "image"

        # Check content encoding
        content_elem = root.find(f".//{ELEMENT_CONTENT}")
        assert content_elem is not None
        assert content_elem.get("encoding") == "base64"

        # Check data is base64 encoded
        data_elem = content_elem.find(f".//{ELEMENT_DATA}")
        assert data_elem is not None
        expected_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR").decode(
            "ascii"
        )
        assert data_elem.text == expected_b64

    @pytest.mark.unit
    def test_error_resource_to_xml(
        self, sample_error_result: ResourceReadResult
    ) -> None:
        """Test error resource includes error message in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_error_result)

        root = ET.fromstring(xml_string)

        # Check success is false
        success_elem = root.find(f".//{ELEMENT_SUCCESS}")
        assert success_elem is not None
        assert success_elem.text == "false"

        # Check error message
        error_elem = root.find(f".//{ELEMENT_ERROR}")
        assert error_elem is not None
        assert error_elem.text == "File not found: /nonexistent.txt"

    @pytest.mark.unit
    def test_resource_capabilities(
        self, sample_text_result: ResourceReadResult
    ) -> None:
        """Test resource capabilities are included in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_text_result)

        root = ET.fromstring(xml_string)

        caps_elem = root.find(f".//{ELEMENT_CAPABILITIES}")
        assert caps_elem is not None

        capabilities = [
            cap.text for cap in caps_elem.findall(f".//{ELEMENT_CAPABILITY}")
        ]
        assert "read" in capabilities
        assert "read_chunk" in capabilities
        assert "read_partial" in capabilities

    @pytest.mark.unit
    def test_resource_with_subscription_info(
        self, sample_text_result: ResourceReadResult
    ) -> None:
        """Test resource with subscription info converts to XML."""
        result = ResourceReadResult(
            uri=sample_text_result.uri,
            session_id=sample_text_result.session_id,
            path=sample_text_result.path,
            content=sample_text_result.content,
            metadata=sample_text_result.metadata,
            success=True,
            subscription_info={
                "is_subscribed": True,
                "subscription_count": 2,
                "subscription_ids": ["sub1", "sub2"],
                "last_modified": "2024-01-15T12:00:00",
            },
        )

        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(result)

        root = ET.fromstring(xml_string)

        sub_elem = root.find(".//subscription_info")
        assert sub_elem is not None

        is_sub_elem = sub_elem.find("is_subscribed")
        assert is_sub_elem is not None
        assert is_sub_elem.text == "true"


class TestDirectoryToXML:
    """Test converting DirectoryListingResult to XML."""

    @pytest.fixture
    def sample_directory_result(self) -> DirectoryListingResult:
        """Create a sample directory listing result."""
        return DirectoryListingResult(
            uri="scratchpad://abc-123/workspace/",
            session_id="abc-123",
            path="/workspace/",
            entries=[
                DirectoryEntry(
                    name="file1.txt",
                    type="file",
                    size=1024,
                    mimetype="text/plain",
                    modified_time="2024-01-15T10:30:00",
                ),
                DirectoryEntry(
                    name="subdir",
                    type="directory",
                    size=0,
                    mimetype=None,
                    modified_time="2024-01-15T10:00:00",
                ),
                DirectoryEntry(
                    name="image.png",
                    type="file",
                    size=2048,
                    mimetype="image/png",
                    modified_time=None,
                ),
            ],
            total_count=3,
            has_more=False,
            offset=0,
            limit=100,
            success=True,
            error=None,
        )

    @pytest.mark.unit
    def test_directory_to_xml_type(
        self, sample_directory_result: DirectoryListingResult
    ) -> None:
        """Test directory result has correct XML type."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_directory_result)

        root = ET.fromstring(xml_string)
        assert root.get("type") == "directory"

    @pytest.mark.unit
    def test_directory_entries_xml(
        self, sample_directory_result: DirectoryListingResult
    ) -> None:
        """Test directory entries in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_directory_result)

        root = ET.fromstring(xml_string)

        entries_elem = root.find(f".//{ELEMENT_ENTRIES}")
        assert entries_elem is not None

        entries = entries_elem.findall(f".//{ELEMENT_ENTRY}")
        assert len(entries) == 3

        # Check first entry (file)
        first_entry = entries[0]
        name_elem = first_entry.find(f"{ELEMENT_NAME}")
        assert name_elem is not None
        assert name_elem.text == "file1.txt"

        type_elem = first_entry.find(f"{ELEMENT_TYPE}")
        assert type_elem is not None
        assert type_elem.text == "file"

        size_elem = first_entry.find(f"{ELEMENT_SIZE}")
        assert size_elem is not None
        assert size_elem.text == "1024"

    @pytest.mark.unit
    def test_directory_pagination_xml(
        self, sample_directory_result: DirectoryListingResult
    ) -> None:
        """Test directory pagination info in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_directory_result)

        root = ET.fromstring(xml_string)

        total_elem = root.find(".//total_count")
        assert total_elem is not None
        assert total_elem.text == "3"

        has_more_elem = root.find(".//has_more")
        assert has_more_elem is not None
        assert has_more_elem.text == "false"

        offset_elem = root.find(".//offset")
        assert offset_elem is not None
        assert offset_elem.text == "0"

        limit_elem = root.find(".//limit")
        assert limit_elem is not None
        assert limit_elem.text == "100"

    @pytest.mark.unit
    def test_directory_capabilities(
        self, sample_directory_result: DirectoryListingResult
    ) -> None:
        """Test directory capabilities in XML."""
        wrapper = XMLResourceWrapper()
        xml_string = wrapper.to_xml(sample_directory_result)

        root = ET.fromstring(xml_string)

        caps_elem = root.find(f".//{ELEMENT_CAPABILITIES}")
        assert caps_elem is not None

        capabilities = [
            cap.text for cap in caps_elem.findall(f".//{ELEMENT_CAPABILITY}")
        ]
        assert "read" in capabilities
        assert "list" in capabilities
        assert "enumerate" in capabilities


class TestDictToXML:
    """Test converting generic dictionaries to XML."""

    @pytest.mark.unit
    def test_simple_dict_to_xml(self) -> None:
        """Test converting a simple dictionary to XML."""
        wrapper = XMLResourceWrapper()
        data = {"name": "test", "value": "123"}

        xml_string = wrapper.to_xml(data)
        root = ET.fromstring(xml_string)

        assert root.tag == ELEMENT_RESOURCE

        name_elem = root.find("name")
        assert name_elem is not None
        assert name_elem.text == "test"

        value_elem = root.find("value")
        assert value_elem is not None
        assert value_elem.text == "123"

    @pytest.mark.unit
    def test_nested_dict_to_xml(self) -> None:
        """Test converting a nested dictionary to XML."""
        wrapper = XMLResourceWrapper()
        data = {"outer": {"inner": "value"}}

        xml_string = wrapper.to_xml(data)
        root = ET.fromstring(xml_string)

        outer_elem = root.find("outer")
        assert outer_elem is not None

        inner_elem = outer_elem.find("inner")
        assert inner_elem is not None
        assert inner_elem.text == "value"

    @pytest.mark.unit
    def test_list_in_dict_to_xml(self) -> None:
        """Test converting a dictionary with list values to XML."""
        wrapper = XMLResourceWrapper()
        data = {"items": ["a", "b", "c"]}

        xml_string = wrapper.to_xml(data)
        root = ET.fromstring(xml_string)

        items_elem = root.find("items")
        assert items_elem is not None

        item_elems = items_elem.findall("item")
        assert len(item_elems) == 3
        assert item_elems[0].text == "a"
        assert item_elems[1].text == "b"
        assert item_elems[2].text == "c"

    @pytest.mark.unit
    def test_unsupported_type_raises_error(self) -> None:
        """Test that unsupported resource types raise XMLResourceError."""
        wrapper = XMLResourceWrapper()

        with pytest.raises(XMLResourceError):
            wrapper.to_xml("invalid type")


class TestParseResourceXML:
    """Test parsing XML back to structured data."""

    @pytest.mark.unit
    def test_parse_simple_xml(self) -> None:
        """Test parsing a simple XML resource."""
        xml_string = """<?xml version="1.0" encoding="UTF-8"?>
        <resource type="text">
            <uri>scratchpad://abc-123/file.txt</uri>
            <session_id>abc-123</session_id>
            <content>
                <data>Hello World</data>
            </content>
        </resource>"""

        result = parse_resource_xml(xml_string)

        assert result.get("type") == "text"
        assert result.get("uri") == "scratchpad://abc-123/file.txt"
        assert result.get("session_id") == "abc-123"
        assert result.get("content", {}).get("data") == "Hello World"

    @pytest.mark.unit
    def test_parse_with_multiple_capabilities(self) -> None:
        """Test parsing XML with multiple capabilities."""
        xml_string = """<?xml version="1.0" encoding="UTF-8"?>
        <resource type="text">
            <uri>scratchpad://abc-123/file.txt</uri>
            <capabilities>
                <capability>read</capability>
                <capability>write</capability>
                <capability>delete</capability>
            </capabilities>
        </resource>"""

        result = parse_resource_xml(xml_string)

        caps = result.get("capabilities", {}).get("capability", [])
        assert isinstance(caps, list)
        assert len(caps) == 3
        assert caps[0] == "read"
        assert caps[1] == "write"
        assert caps[2] == "delete"

    @pytest.mark.unit
    def test_parse_directory_xml(self) -> None:
        """Test parsing directory XML."""
        xml_string = """<?xml version="1.0" encoding="UTF-8"?>
        <resource type="directory">
            <uri>scratchpad://abc-123/workspace/</uri>
            <entries>
                <entry>
                    <name>file1.txt</name>
                    <type>file</type>
                    <size>1024</size>
                </entry>
                <entry>
                    <name>subdir</name>
                    <type>directory</type>
                    <size>0</size>
                </entry>
            </entries>
            <total_count>2</total_count>
        </resource>"""

        result = parse_resource_xml(xml_string)

        assert result.get("type") == "directory"

        entries = result.get("entries", {}).get("entry", [])
        assert len(entries) == 2
        assert entries[0].get("name") == "file1.txt"
        assert entries[1].get("name") == "subdir"

    @pytest.mark.unit
    def test_parse_invalid_xml_raises_error(self) -> None:
        """Test that invalid XML raises XMLResourceError."""
        invalid_xml = "<not valid xml"

        with pytest.raises(XMLResourceError):
            parse_resource_xml(invalid_xml)

    @pytest.mark.unit
    def test_parse_wrong_root_element_raises_error(self) -> None:
        """Test that wrong root element raises XMLResourceError."""
        xml_string = "<wrong_root></wrong_root>"

        with pytest.raises(XMLResourceError):
            parse_resource_xml(xml_string)


class TestValidateResourceXML:
    """Test XML validation."""

    @pytest.mark.unit
    def test_validate_valid_xml(self) -> None:
        """Test validating valid resource XML."""
        xml_string = """<?xml version="1.0" encoding="UTF-8"?>
        <resource type="text">
            <uri>scratchpad://abc-123/file.txt</uri>
            <content>
                <data>Hello</data>
            </content>
        </resource>"""

        is_valid, error = validate_resource_xml(xml_string)
        assert is_valid is True
        assert error is None

    @pytest.mark.unit
    def test_validate_missing_uri(self) -> None:
        """Test validation fails for missing URI element."""
        xml_string = """<?xml version="1.0" encoding="UTF-8"?>
        <resource type="text">
            <content>
                <data>Hello</data>
            </content>
        </resource>"""

        is_valid, error = validate_resource_xml(xml_string)
        assert is_valid is False
        assert error is not None
        assert "uri" in error.lower()

    @pytest.mark.unit
    def test_validate_invalid_xml(self) -> None:
        """Test validation fails for invalid XML."""
        is_valid, error = validate_resource_xml("<invalid")
        assert is_valid is False
        assert error is not None

    @pytest.mark.unit
    def test_validate_wrong_root(self) -> None:
        """Test validation fails for wrong root element."""
        is_valid, error = validate_resource_xml(
            "<notresource><uri>test</uri></notresource>"
        )
        assert is_valid is False
        assert error is not None


class TestHelperElementToDict:
    """Test the _element_to_dict helper function."""

    @pytest.mark.unit
    def test_element_with_text(self) -> None:
        """Test converting element with text content."""
        xml_string = "<root><item>text</item></root>"
        element = ET.fromstring(xml_string)

        result = _element_to_dict(element)
        assert result.get("item") == "text"

    @pytest.mark.unit
    def test_element_with_attributes(self) -> None:
        """Test converting element with attributes."""
        xml_string = '<root type="test" version="1.0"></root>'
        element = ET.fromstring(xml_string)

        result = _element_to_dict(element)
        assert result.get("type") == "test"
        assert result.get("version") == "1.0"

    @pytest.mark.unit
    def test_element_with_namespace(self) -> None:
        """Test converting element with namespace."""
        xml_string = '<root xmlns="urn:test"><item>value</item></root>'
        element = ET.fromstring(xml_string)

        result = _element_to_dict(element)
        # Namespaced elements are handled separately
        assert "item" in result


class TestXMLResourceError:
    """Test XMLResourceError exception."""

    @pytest.mark.unit
    def test_error_with_message(self) -> None:
        """Test creating error with message."""
        error = XMLResourceError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.cause is None

    @pytest.mark.unit
    def test_error_with_cause(self) -> None:
        """Test creating error with cause."""
        cause = ValueError("Original error")
        error = XMLResourceError("Wrapped error", cause=cause)
        assert error.cause is cause

    @pytest.mark.unit
    def test_error_can_be_raised(self) -> None:
        """Test error can be raised and caught."""
        with pytest.raises(XMLResourceError):
            raise XMLResourceError("Test error")


class TestXMLWrapperUtilities:
    """Test XML wrapper utility methods."""

    @pytest.mark.unit
    def test_get_resource_type_text(self) -> None:
        """Test detecting text resource type."""
        wrapper = XMLResourceWrapper()
        result = ResourceReadResult(
            uri="test",
            session_id="test",
            path="test",
            content=ResourceContent(
                data="text",
                encoding="utf-8",
                is_binary=False,
                size_bytes=4,
            ),
            metadata=ResourceMetadata(
                size=4,
                mime_type="text/plain",
                content_type="text",
                is_directory=False,
            ),
            success=True,
        )

        resource_type = wrapper._get_resource_type(result)
        assert resource_type == "text"

    @pytest.mark.unit
    def test_get_resource_type_binary(self) -> None:
        """Test detecting binary resource type."""
        wrapper = XMLResourceWrapper()
        result = ResourceReadResult(
            uri="test",
            session_id="test",
            path="test",
            content=ResourceContent(
                data=b"\x00\x01\x02",
                encoding="base64",
                is_binary=True,
                size_bytes=3,
            ),
            metadata=ResourceMetadata(
                size=3,
                mime_type="application/octet-stream",
                is_directory=False,
            ),
            success=True,
        )

        resource_type = wrapper._get_resource_type(result)
        assert resource_type == "binary"

    @pytest.mark.unit
    def test_get_resource_type_directory(self) -> None:
        """Test detecting directory resource type."""
        wrapper = XMLResourceWrapper()
        result = ResourceReadResult(
            uri="test",
            session_id="test",
            path="test",
            content=ResourceContent(
                data="",
                encoding="utf-8",
                is_binary=False,
                size_bytes=0,
            ),
            metadata=ResourceMetadata(
                size=0,
                mime_type="inode/directory",
                is_directory=True,
            ),
            success=False,
            error="Path is a directory",
        )

        resource_type = wrapper._get_resource_type(result)
        assert resource_type == "directory"

    @pytest.mark.unit
    def test_get_resource_type_image(self) -> None:
        """Test detecting image resource type."""
        wrapper = XMLResourceWrapper()
        result = ResourceReadResult(
            uri="test",
            session_id="test",
            path="test.png",
            content=ResourceContent(
                data=b"\x89PNG",
                encoding="base64",
                is_binary=True,
                size_bytes=4,
            ),
            metadata=ResourceMetadata(
                size=4,
                mime_type="image/png",
                content_type="image",
                is_directory=False,
            ),
            success=True,
        )

        resource_type = wrapper._get_resource_type(result)
        assert resource_type == "image"
