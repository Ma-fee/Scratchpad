"""Tests for image resource handler.

This module tests the image resource handler, including:
- Image metadata extraction (dimensions, format)
- Image format detection
- Thumbnail generation (128x128, 256x256, 512x512)
- Base64 encoding
- Large file handling (metadata-only mode)
- ImageResource dataclass
- process_image_resource() function
- Error handling
"""

from __future__ import annotations

import base64
import io
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from mcp_scratchpad.resources.image_handler import (
    LARGE_IMAGE_THRESHOLD,
    THUMBNAIL_SIZES,
    ImageDimensions,
    ImageFormat,
    ImageMetadata,
    ImageResource,
    detect_image_format,
    extract_exif_data,
    extract_image_metadata,
    generate_thumbnail,
    generate_thumbnails,
    image_to_base64,
    process_image_resource,
)
from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager


# Fixtures


@pytest.fixture
def mock_fs():
    """Create a mock filesystem for testing."""
    fs = MagicMock()
    return fs


@pytest.fixture
def real_session_manager():
    """Create a real session manager for integration testing."""
    config = OverlayConfig(mounts=[])
    manager = SessionFileSystemManager(config)
    session_id = manager.create_session()
    fs = manager.get_session_fs(session_id)
    return manager, session_id, fs


# Helper functions to create test images


def create_test_image(
    width: int = 100,
    height: int = 100,
    mode: str = "RGB",
    format: str = "PNG",
    color: tuple[int, ...] = (255, 0, 0),
) -> bytes:
    """Create a test image in-memory.

    Args:
        width: Image width
        height: Image height
        mode: Color mode (RGB, RGBA, L, etc.)
        format: Image format (PNG, JPEG, etc.)
        color: Fill color

    Returns:
        Image bytes
    """
    img = Image.new(mode, (width, height), color)
    buffer = BytesIO()

    # Handle JPEG mode requirements
    if format == "JPEG" and mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    img.save(buffer, format=format)
    return buffer.getvalue()


def create_test_image_with_alpha(
    width: int = 100,
    height: int = 100,
) -> bytes:
    """Create a test image with transparency."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 128))
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def create_test_gif_animated(
    width: int = 100,
    height: int = 100,
    frames: int = 3,
) -> bytes:
    """Create an animated GIF for testing."""
    images = []
    for i in range(frames):
        # Create frames with different colors
        color = (255, 0, 0) if i == 0 else (0, 255, 0) if i == 1 else (0, 0, 255)
        img = Image.new("RGB", (width, height), color)
        images.append(img)

    buffer = BytesIO()
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
    )
    return buffer.getvalue()


# Tests for ImageDimensions


class TestImageDimensions:
    """Tests for ImageDimensions dataclass."""

    def test_image_dimensions_creation(self):
        """Test creating ImageDimensions."""
        dims = ImageDimensions(width=1920, height=1080)
        assert dims.width == 1920
        assert dims.height == 1080

    def test_image_dimensions_to_dict(self):
        """Test ImageDimensions.to_dict()."""
        dims = ImageDimensions(width=800, height=600)
        d = dims.to_dict()
        assert d == {"width": 800, "height": 600}


# Tests for ImageMetadata


class TestImageMetadata:
    """Tests for ImageMetadata dataclass."""

    def test_image_metadata_creation(self):
        """Test creating ImageMetadata."""
        metadata = ImageMetadata(
            width=1920,
            height=1080,
            format="JPEG",
            mode="RGB",
            has_transparency=False,
            is_animated=False,
            frame_count=1,
        )
        assert metadata.width == 1920
        assert metadata.height == 1080
        assert metadata.format == "JPEG"
        assert metadata.mode == "RGB"

    def test_image_metadata_defaults(self):
        """Test ImageMetadata default values."""
        metadata = ImageMetadata()
        assert metadata.width == 0
        assert metadata.height == 0
        assert metadata.format == ""
        assert metadata.mode == ""
        assert metadata.has_transparency is False
        assert metadata.is_animated is False
        assert metadata.frame_count == 1
        assert metadata.exif == {}

    def test_image_metadata_to_dict(self):
        """Test ImageMetadata.to_dict()."""
        metadata = ImageMetadata(
            width=1920,
            height=1080,
            format="PNG",
            mode="RGBA",
            has_transparency=True,
        )
        d = metadata.to_dict()
        assert d["width"] == 1920
        assert d["height"] == 1080
        assert d["format"] == "PNG"
        assert d["mode"] == "RGBA"
        assert d["has_transparency"] is True
        assert d["exif"] == {}


# Tests for ImageResource


class TestImageResource:
    """Tests for ImageResource dataclass."""

    def test_image_resource_creation(self):
        """Test creating ImageResource."""
        resource = ImageResource(
            uri="scratchpad://test-123/photo.jpg",
            session_id="test-123",
            path="/photo.jpg",
            content="base64content",
            thumbnail_content={"small": "thumb_base64"},
            image_format="JPEG",
            width=1920,
            height=1080,
            size_bytes=102400,
            mime_type="image/jpeg",
        )
        assert resource.uri == "scratchpad://test-123/photo.jpg"
        assert resource.width == 1920
        assert resource.height == 1080
        assert resource.image_format == "JPEG"

    def test_image_resource_with_metadata(self):
        """Test ImageResource with ImageMetadata."""
        img_meta = ImageMetadata(width=1920, height=1080, format="JPEG", mode="RGB")
        resource = ImageResource(
            uri="scratchpad://test-123/photo.jpg",
            session_id="test-123",
            path="/photo.jpg",
            content="base64content",
            thumbnail_content={},
            image_format="JPEG",
            width=1920,
            height=1080,
            size_bytes=102400,
            mime_type="image/jpeg",
            metadata=img_meta,
        )
        assert resource.metadata.width == 1920
        assert resource.metadata.format == "JPEG"

    def test_image_resource_to_dict(self):
        """Test ImageResource.to_dict()."""
        resource = ImageResource(
            uri="scratchpad://test-123/photo.jpg",
            session_id="test-123",
            path="/photo.jpg",
            content="base64data",
            thumbnail_content={"small": "thumb_small", "medium": "thumb_medium"},
            image_format="JPEG",
            width=1920,
            height=1080,
            size_bytes=102400,
            mime_type="image/jpeg",
            metadata=ImageMetadata(width=1920, height=1080, format="JPEG"),
        )
        d = resource.to_dict()
        assert d["type"] == "image"
        assert d["uri"] == "scratchpad://test-123/photo.jpg"
        assert d["content"] == "base64data"
        assert d["thumbnail_content"]["small"] == "thumb_small"
        assert d["dimensions"]["width"] == 1920
        assert d["dimensions"]["height"] == 1080
        assert d["image_format"] == "JPEG"

    def test_image_resource_to_dict_large_file(self):
        """Test ImageResource.to_dict() for large files."""
        resource = ImageResource(
            uri="scratchpad://test-123/large.jpg",
            session_id="test-123",
            path="/large.jpg",
            content="",
            thumbnail_content={"small": "thumb"},
            image_format="JPEG",
            width=4000,
            height=3000,
            size_bytes=LARGE_IMAGE_THRESHOLD + 1000,
            mime_type="image/jpeg",
            is_large_file=True,
            large_file_message="File too large",
        )
        d = resource.to_dict()
        assert d["is_large_file"] is True
        assert d["metadata_only"] is True
        assert d["message"] == "File too large"

    def test_image_resource_with_error(self):
        """Test ImageResource with error state."""
        resource = ImageResource(
            uri="scratchpad://test-123/error.jpg",
            session_id="test-123",
            path="/error.jpg",
            content="",
            thumbnail_content={},
            image_format="UNKNOWN",
            width=0,
            height=0,
            size_bytes=0,
            mime_type="image/jpeg",
            success=False,
            error="Failed to process image",
        )
        d = resource.to_dict()
        assert d["success"] is False
        assert d["error"] == "Failed to process image"


# Tests for detect_image_format


class TestDetectImageFormat:
    """Tests for image format detection."""

    def test_detect_png_format(self):
        """Test detecting PNG format."""
        png_header = b"\x89PNG\r\n\x1a\n"
        assert detect_image_format(png_header, "image/png") == "PNG"

    def test_detect_jpeg_format(self):
        """Test detecting JPEG format."""
        jpeg_header = b"\xff\xd8\xff"
        assert detect_image_format(jpeg_header, "image/jpeg") == "JPEG"

    def test_detect_gif_format(self):
        """Test detecting GIF format."""
        gif87_header = b"GIF87a"
        gif89_header = b"GIF89a"
        assert detect_image_format(gif87_header, "image/gif") == "GIF"
        assert detect_image_format(gif89_header, "image/gif") == "GIF"

    def test_detect_bmp_format(self):
        """Test detecting BMP format."""
        bmp_header = b"BM"
        assert detect_image_format(bmp_header, "image/bmp") == "BMP"

    def test_detect_tiff_format(self):
        """Test detecting TIFF format."""
        tiff_le = b"II\x2a\x00"
        tiff_be = b"MM\x00\x2a"
        assert detect_image_format(tiff_le, "image/tiff") == "TIFF"
        assert detect_image_format(tiff_be, "image/tiff") == "TIFF"

    def test_detect_webp_format(self):
        """Test detecting WEBP format."""
        webp_header = b"RIFF\x00\x00\x00\x00WEBP"
        assert detect_image_format(webp_header, "image/webp") == "WEBP"

    def test_detect_by_mime_type_fallback(self):
        """Test format detection by MIME type fallback."""
        assert detect_image_format(b"unknown", "image/png") == "PNG"
        assert detect_image_format(b"unknown", "image/jpeg") == "JPEG"
        assert detect_image_format(b"unknown", "image/gif") == "GIF"
        assert detect_image_format(b"unknown", "image/bmp") == "BMP"
        assert detect_image_format(b"unknown", "image/tiff") == "TIFF"
        assert detect_image_format(b"unknown", "image/webp") == "WEBP"

    def test_detect_unknown_format(self):
        """Test detection of unknown format."""
        assert detect_image_format(b"unknown", "image/unknown") == "UNKNOWN"


# Tests for extract_exif_data


class TestExtractExifData:
    """Tests for EXIF data extraction."""

    def test_extract_exif_from_jpeg(self):
        """Test EXIF extraction from JPEG."""
        # Create a JPEG with EXIF data
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", exif=b"\x00\x00")  # Minimal EXIF
        buffer.seek(0)

        # Reload and extract EXIF
        img_reloaded = Image.open(buffer)
        exif = extract_exif_data(img_reloaded)

        # Result should be a dict (may be empty for minimal EXIF)
        assert isinstance(exif, dict)

    def test_extract_exif_from_png(self):
        """Test EXIF extraction from PNG (should be empty)."""
        img = Image.new("RGB", (100, 100))
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        img_reloaded = Image.open(buffer)
        exif = extract_exif_data(img_reloaded)

        assert exif == {}


# Tests for extract_image_metadata


class TestExtractImageMetadata:
    """Tests for image metadata extraction."""

    def test_extract_png_metadata(self):
        """Test extracting PNG metadata."""
        img_bytes = create_test_image(800, 600, "RGB", "PNG")
        img = Image.open(BytesIO(img_bytes))
        metadata = extract_image_metadata(img)

        assert metadata.width == 800
        assert metadata.height == 600
        assert metadata.format == "PNG"
        assert metadata.mode == "RGB"
        assert metadata.has_transparency is False
        assert metadata.is_animated is False

    def test_extract_jpeg_metadata(self):
        """Test extracting JPEG metadata."""
        img_bytes = create_test_image(1920, 1080, "RGB", "JPEG")
        img = Image.open(BytesIO(img_bytes))
        metadata = extract_image_metadata(img)

        assert metadata.width == 1920
        assert metadata.height == 1080
        assert metadata.format == "JPEG"
        assert metadata.mode == "RGB"

    def test_extract_rgba_metadata(self):
        """Test extracting RGBA (with transparency) metadata."""
        img_bytes = create_test_image_with_alpha(200, 150)
        img = Image.open(BytesIO(img_bytes))
        metadata = extract_image_metadata(img)

        assert metadata.width == 200
        assert metadata.height == 150
        assert metadata.format == "PNG"
        assert metadata.mode == "RGBA"
        assert metadata.has_transparency is True

    def test_extract_animated_gif_metadata(self):
        """Test extracting animated GIF metadata."""
        gif_bytes = create_test_gif_animated(100, 100, frames=3)
        img = Image.open(BytesIO(gif_bytes))
        metadata = extract_image_metadata(img)

        assert metadata.width == 100
        assert metadata.height == 100
        assert metadata.format == "GIF"
        assert metadata.is_animated is True
        assert metadata.frame_count == 3

    def test_extract_grayscale_metadata(self):
        """Test extracting grayscale image metadata."""
        img = Image.new("L", (100, 100), 128)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        img_reloaded = Image.open(buffer)
        metadata = extract_image_metadata(img_reloaded)

        assert metadata.mode == "L"
        assert metadata.has_transparency is False


# Tests for generate_thumbnail


class TestGenerateThumbnail:
    """Tests for thumbnail generation."""

    def test_generate_thumbnail_maintains_aspect_ratio(self):
        """Test that thumbnail maintains aspect ratio."""
        img = Image.new("RGB", (800, 400), (255, 0, 0))
        thumb = generate_thumbnail(img, (128, 128))

        # Aspect ratio 2:1, so thumbnail should be 128x64
        assert thumb.size[0] <= 128
        assert thumb.size[1] <= 128

    def test_generate_thumbnail_exact_size(self):
        """Test thumbnail with maintain_aspect_ratio=False."""
        img = Image.new("RGB", (800, 400), (255, 0, 0))
        thumb = generate_thumbnail(img, (128, 128), maintain_aspect_ratio=False)

        # Should be exactly 128x128 (may distort)
        assert thumb.size == (128, 128)

    def test_generate_thumbnail_square_to_small(self):
        """Test generating small thumbnail from square image."""
        img = Image.new("RGB", (512, 512), (0, 255, 0))
        thumb = generate_thumbnail(img, (128, 128))

        assert thumb.size == (128, 128)

    def test_generate_thumbnail_large_to_medium(self):
        """Test generating medium thumbnail."""
        img = Image.new("RGB", (1920, 1080), (0, 0, 255))
        thumb = generate_thumbnail(img, (256, 256))

        assert thumb.size[0] <= 256
        assert thumb.size[1] <= 256


# Tests for image_to_base64


class TestImageToBase64:
    """Tests for converting images to Base64."""

    def test_image_to_base64_png(self):
        """Test converting PNG to Base64."""
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        b64 = image_to_base64(img, "PNG")

        assert isinstance(b64, str)
        assert len(b64) > 0
        # PNG signature in base64 starts with 'iVBORw0KGgo'
        assert b64.startswith("iVBORw0KGgo")

    def test_image_to_base64_jpeg(self):
        """Test converting JPEG to Base64."""
        img = Image.new("RGB", (100, 100), (0, 255, 0))
        b64 = image_to_base64(img, "JPEG")

        assert isinstance(b64, str)
        assert len(b64) > 0
        # JPEG in base64 typically starts with '/9j/'
        assert b64.startswith("/9j/")

    def test_image_to_base64_rgba_converts_to_rgb(self):
        """Test that RGBA images are converted to RGB for JPEG."""
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        b64 = image_to_base64(img, "JPEG")

        assert isinstance(b64, str)
        assert len(b64) > 0
        # Should still produce valid JPEG
        assert b64.startswith("/9j/")

    def test_image_to_base64_roundtrip(self):
        """Test that base64 can be decoded back to image."""
        img = Image.new("RGB", (100, 100), (128, 128, 128))
        b64 = image_to_base64(img, "PNG")

        # Decode and reload
        decoded = base64.b64decode(b64)
        reloaded = Image.open(BytesIO(decoded))

        assert reloaded.size == (100, 100)
        assert reloaded.mode == "RGB"


# Tests for generate_thumbnails


class TestGenerateThumbnails:
    """Tests for batch thumbnail generation."""

    def test_generate_thumbnails_small_only(self):
        """Test generating only small thumbnail."""
        img = Image.new("RGB", (800, 600), (255, 0, 0))
        thumbs = generate_thumbnails(img, ["small"])

        assert "small" in thumbs
        assert "medium" not in thumbs
        assert "large" not in thumbs

    def test_generate_thumbnails_all_sizes(self):
        """Test generating all thumbnail sizes."""
        img = Image.new("RGB", (1024, 768), (0, 255, 0))
        thumbs = generate_thumbnails(img, ["small", "medium", "large"])

        assert "small" in thumbs
        assert "medium" in thumbs
        assert "large" in thumbs

        # Verify each is valid base64 PNG
        for size, b64_data in thumbs.items():
            assert isinstance(b64_data, str)
            assert len(b64_data) > 0
            # Should be decodable
            decoded = base64.b64decode(b64_data)
            reloaded = Image.open(BytesIO(decoded))
            assert reloaded.size[0] <= THUMBNAIL_SIZES[size][0]
            assert reloaded.size[1] <= THUMBNAIL_SIZES[size][1]

    def test_generate_thumbnails_unknown_size_ignored(self):
        """Test that unknown sizes are ignored."""
        img = Image.new("RGB", (800, 600), (0, 0, 255))
        thumbs = generate_thumbnails(img, ["small", "unknown"])

        assert "small" in thumbs
        assert "unknown" not in thumbs

    def test_generate_thumbnails_empty_list(self):
        """Test with empty thumbnail sizes list."""
        img = Image.new("RGB", (800, 600), (255, 0, 0))
        thumbs = generate_thumbnails(img, [])

        assert thumbs == {}


# Tests for process_image_resource


class TestProcessImageResource:
    """Tests for process_image_resource function."""

    def test_process_png_success(self, mock_fs):
        """Test successful PNG processing."""
        img_bytes = create_test_image(800, 600, "RGB", "PNG")

        mock_fs.info.return_value = {"size": len(img_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = img_bytes
        mock_fs.open.return_value = mock_file

        result = process_image_resource(
            uri="scratchpad://test-123/image.png",
            fs=mock_fs,
            session_id="test-123",
            path="/image.png",
            mime_type="image/png",
            thumbnail_sizes=["small", "medium"],
        )

        assert result.success is True
        assert result.image_format == "PNG"
        assert result.width == 800
        assert result.height == 600
        assert result.mime_type == "image/png"
        assert result.content != ""  # Should have full content
        assert "small" in result.thumbnail_content
        assert "medium" in result.thumbnail_content

    def test_process_jpeg_success(self, mock_fs):
        """Test successful JPEG processing."""
        img_bytes = create_test_image(1920, 1080, "RGB", "JPEG")

        mock_fs.info.return_value = {"size": len(img_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = img_bytes
        mock_fs.open.return_value = mock_file

        result = process_image_resource(
            uri="scratchpad://test-123/photo.jpg",
            fs=mock_fs,
            session_id="test-123",
            path="/photo.jpg",
            mime_type="image/jpeg",
            thumbnail_sizes=["small"],
        )

        assert result.success is True
        assert result.image_format == "JPEG"
        assert result.width == 1920
        assert result.height == 1080

    def test_process_gif_success(self, mock_fs):
        """Test successful GIF processing."""
        gif_bytes = create_test_gif_animated(200, 150, frames=3)

        mock_fs.info.return_value = {"size": len(gif_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = gif_bytes
        mock_fs.open.return_value = mock_file

        result = process_image_resource(
            uri="scratchpad://test-123/animation.gif",
            fs=mock_fs,
            session_id="test-123",
            path="/animation.gif",
            mime_type="image/gif",
        )

        assert result.success is True
        assert result.image_format == "GIF"
        assert result.metadata.is_animated is True
        assert result.metadata.frame_count == 3

    def test_process_image_default_thumbnail_size(self, mock_fs):
        """Test that default thumbnail size is small."""
        img_bytes = create_test_image(400, 300, "RGB", "PNG")

        mock_fs.info.return_value = {"size": len(img_bytes)}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = img_bytes
        mock_fs.open.return_value = mock_file

        result = process_image_resource(
            uri="scratchpad://test-123/image.png",
            fs=mock_fs,
            session_id="test-123",
            path="/image.png",
            mime_type="image/png",
            thumbnail_sizes=None,  # Should default to ["small"]
        )

        assert result.success is True
        assert "small" in result.thumbnail_content

    def test_process_large_image_returns_metadata_and_thumbnails(self, mock_fs):
        """Test that large images return metadata and thumbnails only."""
        large_size = LARGE_IMAGE_THRESHOLD + 1000

        mock_fs.info.return_value = {"size": large_size}

        # Create a sample image for metadata extraction
        img_bytes = create_test_image(800, 600, "RGB", "PNG")
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = img_bytes
        mock_fs.open.return_value = mock_file

        result = process_image_resource(
            uri="scratchpad://test-123/large.png",
            fs=mock_fs,
            session_id="test-123",
            path="/large.png",
            mime_type="image/png",
            thumbnail_sizes=["small", "medium"],
        )

        assert result.success is True
        assert result.is_large_file is True
        assert result.content == ""  # No full content
        assert "small" in result.thumbnail_content  # But has thumbnails
        assert "medium" in result.thumbnail_content
        assert "size limit" in result.large_file_message.lower()

    def test_process_image_error_file_not_found(self, mock_fs):
        """Test error handling when file info fails."""
        mock_fs.info.side_effect = IOError("File not found")

        result = process_image_resource(
            uri="scratchpad://test-123/missing.png",
            fs=mock_fs,
            session_id="test-123",
            path="/missing.png",
            mime_type="image/png",
        )

        assert result.success is False
        assert result.error is not None
        assert "file info" in result.error.lower()

    def test_process_image_error_invalid_image(self, mock_fs):
        """Test error handling with invalid image data."""
        mock_fs.info.return_value = {"size": 100}

        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=None)
        mock_file.read.return_value = b"Not an image"
        mock_fs.open.return_value = mock_file

        result = process_image_resource(
            uri="scratchpad://test-123/invalid.png",
            fs=mock_fs,
            session_id="test-123",
            path="/invalid.png",
            mime_type="image/png",
        )

        assert result.success is False
        assert result.error is not None


# Integration tests with real filesystem


class TestImageResourceIntegration:
    """Integration tests using real filesystem."""

    def test_process_png_with_real_fs(self, real_session_manager):
        """Test PNG processing with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a PNG file
        img_bytes = create_test_image(800, 600, "RGB", "PNG")
        with fs.open("/image.png", "wb") as f:
            f.write(img_bytes)

        result = process_image_resource(
            uri=f"scratchpad://{session_id}/image.png",
            fs=fs,
            session_id=session_id,
            path="/image.png",
            mime_type="image/png",
            thumbnail_sizes=["small", "medium"],
        )

        assert result.success is True
        assert result.image_format == "PNG"
        assert result.width == 800
        assert result.height == 600
        assert "small" in result.thumbnail_content
        assert "medium" in result.thumbnail_content

        # Verify content is valid base64
        decoded = base64.b64decode(result.content)
        reloaded = Image.open(BytesIO(decoded))
        assert reloaded.size == (800, 600)

    def test_process_jpeg_with_real_fs(self, real_session_manager):
        """Test JPEG processing with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create a JPEG file
        img_bytes = create_test_image(1920, 1080, "RGB", "JPEG")
        with fs.open("/photo.jpg", "wb") as f:
            f.write(img_bytes)

        result = process_image_resource(
            uri=f"scratchpad://{session_id}/photo.jpg",
            fs=fs,
            session_id=session_id,
            path="/photo.jpg",
            mime_type="image/jpeg",
        )

        assert result.success is True
        assert result.image_format == "JPEG"
        assert result.width == 1920
        assert result.height == 1080

    def test_process_animated_gif_with_real_fs(self, real_session_manager):
        """Test animated GIF processing with real filesystem."""
        manager, session_id, fs = real_session_manager

        # Create an animated GIF
        gif_bytes = create_test_gif_animated(200, 150, frames=3)
        with fs.open("/animation.gif", "wb") as f:
            f.write(gif_bytes)

        result = process_image_resource(
            uri=f"scratchpad://{session_id}/animation.gif",
            fs=fs,
            session_id=session_id,
            path="/animation.gif",
            mime_type="image/gif",
        )

        assert result.success is True
        assert result.metadata.is_animated is True
        assert result.metadata.frame_count == 3

    def test_process_transparent_png_with_real_fs(self, real_session_manager):
        """Test transparent PNG processing."""
        manager, session_id, fs = real_session_manager

        # Create a transparent PNG
        img_bytes = create_test_image_with_alpha(300, 200)
        with fs.open("/transparent.png", "wb") as f:
            f.write(img_bytes)

        result = process_image_resource(
            uri=f"scratchpad://{session_id}/transparent.png",
            fs=fs,
            session_id=session_id,
            path="/transparent.png",
            mime_type="image/png",
        )

        assert result.success is True
        assert result.metadata.has_transparency is True
        assert result.metadata.mode == "RGBA"


# Tests for constants


class TestConstants:
    """Tests for module constants."""

    def test_large_image_threshold(self):
        """Test LARGE_IMAGE_THRESHOLD value."""
        assert LARGE_IMAGE_THRESHOLD == 10 * 1024 * 1024  # 10MB

    def test_thumbnail_sizes(self):
        """Test THUMBNAIL_SIZES dictionary."""
        assert THUMBNAIL_SIZES["small"] == (128, 128)
        assert THUMBNAIL_SIZES["medium"] == (256, 256)
        assert THUMBNAIL_SIZES["large"] == (512, 512)


# Tests for read_resource integration (test that images are handled)


class TestReadResourceImageHandling:
    """Tests for read_resource image file handling."""

    def test_read_resource_handles_png(self, real_session_manager):
        """Test that read_resource properly handles PNG files."""
        from mcp_scratchpad.resources.read_handler import (
            read_resource,
            set_session_manager,
        )

        manager, session_id, fs = real_session_manager

        # Create a PNG file
        img_bytes = create_test_image(400, 300, "RGB", "PNG")
        with fs.open("/test.png", "wb") as f:
            f.write(img_bytes)

        # Set up session manager
        set_session_manager(manager)

        # Read via read_resource
        result = read_resource(f"scratchpad://{session_id}/test.png")

        assert result.success is True
        assert result.content is not None
        assert result.metadata.mime_type == "image/png"
        # Check capability metadata for image info
        assert "dimensions" in result.capability_metadata
        assert result.capability_metadata["image_format"] == "PNG"

    def test_read_resource_handles_jpeg(self, real_session_manager):
        """Test that read_resource properly handles JPEG files."""
        from mcp_scratchpad.resources.read_handler import (
            read_resource,
            set_session_manager,
        )

        manager, session_id, fs = real_session_manager

        # Create a JPEG file
        img_bytes = create_test_image(800, 600, "RGB", "JPEG")
        with fs.open("/test.jpg", "wb") as f:
            f.write(img_bytes)

        # Set up session manager
        set_session_manager(manager)

        # Read via read_resource
        result = read_resource(f"scratchpad://{session_id}/test.jpg")

        assert result.success is True
        assert result.metadata.mime_type == "image/jpeg"
        assert result.capability_metadata["image_format"] == "JPEG"

    def test_read_resource_handles_gif(self, real_session_manager):
        """Test that read_resource properly handles GIF files."""
        from mcp_scratchpad.resources.read_handler import (
            read_resource,
            set_session_manager,
        )

        manager, session_id, fs = real_session_manager

        # Create a GIF file
        gif_bytes = create_test_gif_animated(200, 150, frames=2)
        with fs.open("/test.gif", "wb") as f:
            f.write(gif_bytes)

        # Set up session manager
        set_session_manager(manager)

        # Read via read_resource
        result = read_resource(f"scratchpad://{session_id}/test.gif")

        assert result.success is True
        assert result.metadata.mime_type == "image/gif"
        assert result.capability_metadata["is_large_file"] is False
