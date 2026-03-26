"""Image resource handler for MCP resources.

This module provides specialized handling for image files, including metadata extraction,
thumbnail generation, and Base64 encoding for transport.

Image Resource Handling Flow:
    1. Detect image file type from content/mime type
    2. Extract metadata (dimensions, format) using PIL
    3. For large files (>10MB): return metadata only with flag
    4. Generate thumbnails in requested sizes (small, medium, large)
    5. Encode content and thumbnails as Base64 for transport

Supported Formats:
    - PNG, JPEG, GIF, BMP, TIFF, WebP

Example:
    >>> result = process_image_resource(
    ...     uri="scratchpad://abc-123/photo.jpg",
    ...     fs=filesystem,
    ...     session_id="abc-123",
    ...     path="/photo.jpg",
    ...     thumbnail_sizes=["small", "medium"]
    ... )
    >>> result.width
    1920
    >>> result.height
    1080
    >>> result.thumbnail_data["small"][:50]  # Base64 encoded thumbnail
    '/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAA...'
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

from PIL import Image
from PIL.ExifTags import TAGS

try:
    from fsspec import AbstractFileSystem
except ImportError:
    # Fallback for type checking when fsspec is not installed
    from typing import Any as AbstractFileSystem

# Large image threshold (10MB) - for files larger than this, return metadata only
LARGE_IMAGE_THRESHOLD = 10 * 1024 * 1024

# Default thumbnail sizes
THUMBNAIL_SIZES = {
    "small": (128, 128),
    "medium": (256, 256),
    "large": (512, 512),
}


class ImageFormat(Enum):
    """Supported image formats."""

    PNG = "PNG"
    JPEG = "JPEG"
    GIF = "GIF"
    BMP = "BMP"
    TIFF = "TIFF"
    WEBP = "WEBP"


@dataclass(frozen=True)
class ImageDimensions:
    """Image dimensions.

    Attributes:
        width: Image width in pixels
        height: Image height in pixels

    Example:
        >>> dims = ImageDimensions(width=1920, height=1080)
        >>> dims.width
        1920
    """

    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {"width": self.width, "height": self.height}


@dataclass(frozen=True)
class ImageMetadata:
    """Image-specific metadata extracted from the image.

    Attributes:
        width: Image width in pixels
        height: Image height in pixels
        format: Image format (PNG, JPEG, GIF, etc.)
        mode: Color mode (RGB, RGBA, L, etc.)
        has_transparency: Whether the image has transparency
        is_animated: Whether the image is animated (for GIF/WebP)
        frame_count: Number of frames (for animated images)
        exif: EXIF metadata dictionary (for JPEG/TIFF)

    Example:
        >>> metadata = ImageMetadata(
        ...     width=1920,
        ...     height=1080,
        ...     format="JPEG",
        ...     mode="RGB",
        ... )
    """

    width: int = 0
    height: int = 0
    format: str = ""
    mode: str = ""
    has_transparency: bool = False
    is_animated: bool = False
    frame_count: int = 1
    exif: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert image metadata to dictionary."""
        return {
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "mode": self.mode,
            "has_transparency": self.has_transparency,
            "is_animated": self.is_animated,
            "frame_count": self.frame_count,
            "exif": self.exif.copy() if self.exif else {},
        }


@dataclass(frozen=True)
class ImageResource:
    """Result of reading an image resource.

    This dataclass extends the concept of ResourceReadResult to provide
    specialized handling for image files, including metadata extraction,
    thumbnail generation, and Base64 encoding for transport.

    Attributes:
        uri: The original scratchpad:// URI
        session_id: The session identifier
        path: The file path within the session
        content: Base64-encoded full image content
        thumbnail_content: Dictionary of Base64-encoded thumbnails by size
        image_format: Detected image format (PNG, JPEG, GIF, etc.)
        width: Image width in pixels
        height: Image height in pixels
        metadata: Image-specific metadata (ImageMetadata)
        size_bytes: File size in bytes
        mime_type: MIME type of the resource
        is_large_file: Whether the file exceeds size threshold
        large_file_message: Message for large files (if applicable)
        success: Whether the operation succeeded
        error: Error message if the operation failed

    Example:
        >>> result = ImageResource(
        ...     uri="scratchpad://abc-123/photo.jpg",
        ...     session_id="abc-123",
        ...     path="/photo.jpg",
        ...     content="/9j/4AAQSkZJRgABAQAA...",
        ...     thumbnail_content={"small": "...", "medium": "..."},
        ...     image_format="JPEG",
        ...     width=1920,
        ...     height=1080,
        ...     size_bytes=102400,
        ...     success=True,
        ... )
    """

    uri: str
    session_id: str
    path: str
    content: str  # Base64 encoded
    thumbnail_content: dict[str, str]  # Base64 encoded thumbnails
    image_format: str
    width: int
    height: int
    size_bytes: int
    mime_type: str
    metadata: ImageMetadata = field(default_factory=ImageMetadata)
    is_large_file: bool = False
    large_file_message: Optional[str] = None
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert image resource to dictionary representation.

        Returns:
            Dictionary with type information and all resource data.
        """
        result: dict[str, Any] = {
            "type": "image",
            "uri": self.uri,
            "session_id": self.session_id,
            "path": self.path,
            "content": self.content,
            "thumbnail_content": self.thumbnail_content.copy(),
            "image_format": self.image_format,
            "dimensions": {
                "width": self.width,
                "height": self.height,
            },
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata.to_dict(),
        }

        # Add large file information
        if self.is_large_file:
            result["is_large_file"] = True
            result["metadata_only"] = True
            if self.large_file_message:
                result["message"] = self.large_file_message

        result["success"] = self.success
        if self.error:
            result["error"] = self.error

        return result


def detect_image_format(content: bytes, mime_type: str) -> str:
    """Detect image format from content and mime type.

    Args:
        content: The file content (first few bytes are examined)
        mime_type: The detected MIME type

    Returns:
        The detected image format (PNG, JPEG, etc.)

    Example:
        >>> detect_image_format(b"\\x89PNG\\r\\n\\x1a\\n", "image/png")
        'PNG'
        >>> detect_image_format(b"\\xff\\xd8\\xff", "image/jpeg")
        'JPEG'
    """
    # Check magic bytes first
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    elif content.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    elif content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "GIF"
    elif content.startswith(b"BM"):
        return "BMP"
    elif content.startswith(b"II\x2a\x00") or content.startswith(b"MM\x00\x2a"):
        return "TIFF"
    elif (
        content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP"
    ):
        return "WEBP"

    # Fall back to MIME type
    mime_to_format = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/gif": "GIF",
        "image/bmp": "BMP",
        "image/tiff": "TIFF",
        "image/webp": "WEBP",
    }

    return mime_to_format.get(mime_type, "UNKNOWN")


def extract_exif_data(image: Image.Image) -> dict[str, Any]:
    """Extract EXIF data from image.

    Args:
        image: PIL Image object

    Returns:
        Dictionary of EXIF tags and values
    """
    exif_data: dict[str, Any] = {}

    try:
        if hasattr(image, "_getexif") and image._getexif() is not None:
            exif = image._getexif()
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                # Convert bytes to string if necessary
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="ignore")
                    except Exception:
                        value = str(value)
                exif_data[tag] = value
    except Exception:
        pass  # 忽略EXIF提取错误

    return exif_data


def extract_image_metadata(image: Image.Image) -> ImageMetadata:
    """Extract metadata from a PIL Image.

    Args:
        image: PIL Image object

    Returns:
        ImageMetadata with extracted information

    Example:
        >>> img = Image.open("photo.jpg")
        >>> metadata = extract_image_metadata(img)
        >>> metadata.width
        1920
    """
    width, height = image.size
    image_format = image.format if image.format else "UNKNOWN"
    mode = image.mode

    # Check for transparency
    has_transparency = mode in ("RGBA", "P", "LA") or (
        mode == "P" and "transparency" in image.info
    )

    # Check for animation (GIF, WebP)
    is_animated = False
    frame_count = 1
    try:
        is_animated = getattr(image, "is_animated", False)
        frame_count = getattr(image, "n_frames", 1)
    except Exception:
        pass

    # Extract EXIF data
    exif = extract_exif_data(image)

    return ImageMetadata(
        width=width,
        height=height,
        format=image_format,
        mode=mode,
        has_transparency=has_transparency,
        is_animated=is_animated,
        frame_count=frame_count,
        exif=exif,
    )


def generate_thumbnail(
    image: Image.Image,
    size: tuple[int, int],
    maintain_aspect_ratio: bool = True,
) -> Image.Image:
    """Generate a thumbnail from an image.

    Args:
        image: Source PIL Image
        size: Target size (width, height)
        maintain_aspect_ratio: Whether to maintain aspect ratio (default: True)

    Returns:
        Thumbnail PIL Image

    Example:
        >>> img = Image.open("photo.jpg")
        >>> thumb = generate_thumbnail(img, (128, 128))
        >>> thumb.size
        (128, 72)  # Maintains aspect ratio
    """
    # Create a copy to avoid modifying the original
    thumb = image.copy()

    if maintain_aspect_ratio:
        # Use thumbnail() which maintains aspect ratio
        thumb.thumbnail(size, Image.Resampling.LANCZOS)
    else:
        # Resize to exact dimensions (may distort)
        thumb = thumb.resize(size, Image.Resampling.LANCZOS)

    return thumb


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Convert PIL Image to Base64 string.

    Args:
        image: PIL Image object
        format: Output format (PNG, JPEG, etc.)

    Returns:
        Base64-encoded image string

    Example:
        >>> img = Image.new("RGB", (100, 100))
        >>> b64 = image_to_base64(img, "PNG")
        >>> b64.startswith("iVBORw0KGgo")
        True
    """
    buffer = io.BytesIO()

    # Convert mode if necessary for JPEG
    if format == "JPEG" and image.mode in ("RGBA", "P", "LA"):
        # Create a white background for transparency
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        if image.mode in ("RGBA", "LA"):
            # Paste using alpha channel as mask
            background.paste(
                image, mask=image.split()[-1] if image.mode in ("RGBA", "LA") else None
            )
            image = background
        else:
            image = image.convert("RGB")

    # Save with appropriate options
    save_kwargs: dict[str, Any] = {}
    if format == "JPEG":
        save_kwargs["quality"] = 85
        save_kwargs["optimize"] = True

    image.save(buffer, format=format, **save_kwargs)
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def generate_thumbnails(
    image: Image.Image,
    sizes: list[str],
) -> dict[str, str]:
    """Generate thumbnails for requested sizes.

    Args:
        image: Source PIL Image
        sizes: List of size names ("small", "medium", "large")

    Returns:
        Dictionary mapping size names to Base64-encoded thumbnails

    Example:
        >>> img = Image.open("photo.jpg")
        >>> thumbs = generate_thumbnails(img, ["small", "medium"])
        >>> "small" in thumbs
        True
    """
    thumbnails: dict[str, str] = {}

    for size_name in sizes:
        if size_name not in THUMBNAIL_SIZES:
            continue

        size = THUMBNAIL_SIZES[size_name]

        try:
            thumb = generate_thumbnail(image, size)
            # Use same format as original, or PNG as fallback
            output_format = image.format if image.format else "PNG"
            # Convert to supported format string
            if output_format not in ("PNG", "JPEG", "GIF", "BMP", "TIFF", "WEBP"):
                output_format = "PNG"

            b64_data = image_to_base64(thumb, output_format)
            thumbnails[size_name] = b64_data
        except Exception:
            # 跳过无法生成的缩略图
            continue

    return thumbnails


def process_image_resource(
    uri: str,
    fs: AbstractFileSystem,
    session_id: str,
    path: str,
    mime_type: str,
    thumbnail_sizes: Optional[list[str]] = None,
    size_limit: int = LARGE_IMAGE_THRESHOLD,
) -> ImageResource:
    """Process an image resource and extract metadata and thumbnails.

    For files larger than size_limit, returns metadata only without full content.

    Args:
        uri: The scratchpad:// URI
        fs: The filesystem containing the file
        session_id: The session identifier
        path: The file path within the session
        mime_type: The MIME type of the file
        thumbnail_sizes: List of thumbnail sizes to generate (default: ["small"])
        size_limit: Size threshold for returning metadata only (default: 10MB)

    Returns:
        ImageResource with image metadata, content, and thumbnails

    Example:
        >>> result = process_image_resource(
        ...     uri="scratchpad://abc-123/photo.jpg",
        ...     fs=filesystem,
        ...     session_id="abc-123",
        ...     path="/photo.jpg",
        ...     mime_type="image/jpeg",
        ...     thumbnail_sizes=["small", "medium"],
        ... )
        >>> result.width
        1920
        >>> result.height
        1080
        >>> "small" in result.thumbnail_content
        True
    """
    # Set default thumbnail sizes
    if thumbnail_sizes is None:
        thumbnail_sizes = ["small"]

    # Get file info for size check
    try:
        info = fs.info(path)
        file_size = info.get("size", 0)
    except Exception as e:
        return ImageResource(
            uri=uri,
            session_id=session_id,
            path=path,
            content="",
            thumbnail_content={},
            image_format="UNKNOWN",
            width=0,
            height=0,
            size_bytes=0,
            mime_type=mime_type,
            success=False,
            error=f"Failed to get file info: {e}",
        )

    # For large files, read just enough to extract metadata and generate thumbnails
    if file_size > size_limit:
        try:
            with fs.open(path, "rb") as f:
                # Read enough for metadata extraction (first 256KB)
                sample_content = f.read(262144)

            # Load image from sample
            image = Image.open(io.BytesIO(sample_content))
            image_metadata = extract_image_metadata(image)

            # Generate thumbnails from sample
            thumbnails = generate_thumbnails(image, thumbnail_sizes)

            # Detect format
            image_format = detect_image_format(sample_content, mime_type)

            return ImageResource(
                uri=uri,
                session_id=session_id,
                path=path,
                content="",  # No full content for large files
                thumbnail_content=thumbnails,
                image_format=image_format,
                width=image_metadata.width,
                height=image_metadata.height,
                size_bytes=file_size,
                mime_type=mime_type,
                metadata=image_metadata,
                is_large_file=True,
                large_file_message=f"Image exceeds size limit ({file_size} bytes > {size_limit} bytes). Metadata and thumbnails only.",
                success=True,
            )
        except Exception as e:
            return ImageResource(
                uri=uri,
                session_id=session_id,
                path=path,
                content="",
                thumbnail_content={},
                image_format="UNKNOWN",
                width=0,
                height=0,
                size_bytes=file_size,
                mime_type=mime_type,
                is_large_file=True,
                success=False,
                error=f"Failed to process large image: {e}",
            )

    # Read full content for normal-sized images
    try:
        with fs.open(path, "rb") as f:
            content = f.read()

        # Load image
        image = Image.open(io.BytesIO(content))
        image_metadata = extract_image_metadata(image)

        # Encode full image as Base64
        full_image_b64 = base64.b64encode(content).decode("ascii")

        # Generate thumbnails
        thumbnails = generate_thumbnails(image, thumbnail_sizes)

        # Detect format
        image_format = detect_image_format(content, mime_type)

        return ImageResource(
            uri=uri,
            session_id=session_id,
            path=path,
            content=full_image_b64,
            thumbnail_content=thumbnails,
            image_format=image_format,
            width=image_metadata.width,
            height=image_metadata.height,
            size_bytes=file_size,
            mime_type=mime_type,
            metadata=image_metadata,
            is_large_file=False,
            success=True,
        )

    except Exception as e:
        return ImageResource(
            uri=uri,
            session_id=session_id,
            path=path,
            content="",
            thumbnail_content={},
            image_format="UNKNOWN",
            width=0,
            height=0,
            size_bytes=file_size,
            mime_type=mime_type,
            is_large_file=False,
            success=False,
            error=f"Failed to process image: {e}",
        )
