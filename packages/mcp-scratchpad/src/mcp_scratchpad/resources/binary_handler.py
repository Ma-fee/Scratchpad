"""Binary resource handler for MCP resources.

This module provides specialized handling for binary files, particularly PDFs,
including metadata extraction, text extraction, and Base64 encoding for transport.

Binary Resource Handling Flow:
    1. Detect binary file type from content/mime type
    2. For PDFs: Extract metadata (page count, title, author) and optionally text
    3. For other binaries: Return generic metadata (size, format)
    4. For large files (>5MB): Return metadata only with flag
    5. Encode content as Base64 for transport

Example:
    >>> result = process_pdf_resource(
    ...     uri="scratchpad://abc-123/document.pdf",
    ...     fs=filesystem,
    ...     extract_text=True,
    ...     max_pages=2
    ... )
    >>> result.metadata.pdf_metadata["page_count"]
    42
    >>> result.binary_content[:50]  # Base64 encoded content
    'JVBERi0xLjQKJeLjz9MKMyAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBS...'
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

try:
    from fsspec import AbstractFileSystem
except ImportError:
    # Fallback for type checking when fsspec is not installed
    from typing import Any as AbstractFileSystem

# Large PDF threshold (5MB) - for files larger than this, return metadata only
LARGE_PDF_THRESHOLD = 5 * 1024 * 1024

# Default number of pages to extract text from
DEFAULT_MAX_PAGES = 2


@dataclass(frozen=True)
class PDFMetadata:
    """PDF-specific metadata extracted from the document.

    Attributes:
        page_count: Total number of pages in the PDF
        title: Document title (from PDF metadata, if available)
        author: Document author (from PDF metadata, if available)
        subject: Document subject (from PDF metadata, if available)
        creator: PDF creator application (from PDF metadata, if available)
        producer: PDF producer application (from PDF metadata, if available)
        creation_date: Document creation date (from PDF metadata, if available)
        modification_date: Document modification date (from PDF metadata, if available)
        has_text_content: Whether the PDF contains extractable text

    Example:
        >>> metadata = PDFMetadata(
        ...     page_count=42,
        ...     title="Annual Report 2024",
        ...     author="Acme Corp",
        ... )
    """

    page_count: int = 0
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    creator: str | None = None
    producer: str | None = None
    creation_date: str | None = None
    modification_date: str | None = None
    has_text_content: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert PDF metadata to dictionary."""
        return {
            "page_count": self.page_count,
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "creator": self.creator,
            "producer": self.producer,
            "creation_date": self.creation_date,
            "modification_date": self.modification_date,
            "has_text_content": self.has_text_content,
        }


@dataclass(frozen=True)
class BinaryResource:
    """Result of reading a binary resource (PDF or other binary file).

    This dataclass extends the concept of ResourceReadResult to provide
    specialized handling for binary files, including PDF metadata extraction
    and Base64 encoding for transport.

    Attributes:
        uri: The original scratchpad:// URI
        session_id: The session identifier
        path: The file path within the session
        binary_content: Base64-encoded file content
        binary_format: Detected binary format (PDF, ZIP, etc.)
        mime_type: MIME type of the resource
        size_bytes: File size in bytes
        metadata: Generic file metadata (size, timestamps, etc.)
        pdf_metadata: PDF-specific metadata (only for PDFs)
        extracted_text: Extracted text content (optional, for PDFs)
        is_large_file: Whether the file exceeds size threshold
        large_file_message: Message for large files (if applicable)
        success: Whether the operation succeeded
        error: Error message if the operation failed

    Example:
        >>> result = BinaryResource(
        ...     uri="scratchpad://abc-123/document.pdf",
        ...     session_id="abc-123",
        ...     path="/document.pdf",
        ...     binary_content="JVBERi0xLjQK...",
        ...     binary_format="PDF",
        ...     mime_type="application/pdf",
        ...     size_bytes=102400,
        ...     pdf_metadata=PDFMetadata(page_count=10, title="Report"),
        ...     extracted_text="Introduction...",
        ...     success=True,
        ... )
    """

    uri: str
    session_id: str
    path: str
    binary_content: str  # Base64 encoded
    binary_format: str
    mime_type: str
    size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)
    pdf_metadata: PDFMetadata | None = None
    extracted_text: str | None = None
    is_large_file: bool = False
    large_file_message: str | None = None
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert binary resource to dictionary representation.

        Returns:
            Dictionary with type information and all resource data.
        """
        result: dict[str, Any] = {
            "type": "binary",
            "uri": self.uri,
            "session_id": self.session_id,
            "path": self.path,
            "content": self.binary_content,
            "mime_type": self.mime_type,
            "binary_format": self.binary_format,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata.copy(),
        }

        # Add PDF metadata if available
        if self.pdf_metadata is not None:
            result["pdf_metadata"] = self.pdf_metadata.to_dict()
            pdf_meta = result["metadata"].setdefault("pdf", {})
            pdf_meta.update(self.pdf_metadata.to_dict())

        # Add extracted text if available
        if self.extracted_text is not None:
            result["extracted_text"] = self.extracted_text
            result["metadata"]["extracted_text"] = self.extracted_text

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


def detect_binary_format(content: bytes, mime_type: str, path: str) -> str:
    """Detect binary file format from content, mime type, and path.

    Args:
        content: The file content (first few bytes are examined)
        mime_type: The detected MIME type
        path: The file path (for extension-based detection)

    Returns:
        The detected binary format (PDF, ZIP, etc.)

    Example:
        >>> detect_binary_format(b"%PDF-1.4", "application/pdf", "/doc.pdf")
        'PDF'
        >>> detect_binary_format(b"PK\x03\x04", "application/zip", "/file.zip")
        'ZIP'
    """
    # Check for PDF signature
    if content.startswith(b"%PDF-") or mime_type == "application/pdf":
        return "PDF"

    # Check for ZIP signature
    if content.startswith(b"PK\x03\x04") or mime_type == "application/zip":
        return "ZIP"

    # Check for GZIP signature
    if content.startswith(b"\x1f\x8b") or mime_type == "application/gzip":
        return "GZIP"

    # Check for TAR signature
    if (
        content.startswith(b"ustar\x00")
        or content.startswith(b"ustar  ")
        or mime_type == "application/x-tar"
    ):
        return "TAR"

    # Check for PNG
    if content.startswith(b"\x89PNG\r\n\x1a\n") or mime_type == "image/png":
        return "PNG"

    # Check for JPEG
    if content.startswith(b"\xff\xd8\xff") or mime_type == "image/jpeg":
        return "JPEG"

    # Check for GIF
    if (
        content.startswith(b"GIF87a")
        or content.startswith(b"GIF89a")
        or mime_type == "image/gif"
    ):
        return "GIF"

    # Extension-based fallback
    ext = Path(path).suffix.lower()
    format_map = {
        ".pdf": "PDF",
        ".zip": "ZIP",
        ".gz": "GZIP",
        ".tar": "TAR",
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".gif": "GIF",
        ".webp": "WEBP",
        ".mp3": "MP3",
        ".mp4": "MP4",
        ".doc": "DOC",
        ".docx": "DOCX",
        ".xls": "XLS",
        ".xlsx": "XLSX",
    }

    if ext in format_map:
        return format_map[ext]

    # Default to generic BINARY
    return "BINARY"


def extract_pdf_metadata(content: bytes) -> PDFMetadata:
    """Extract metadata from PDF content.

    Args:
        content: The PDF file content as bytes

    Returns:
        PDFMetadata with extracted information

    Example:
        >>> metadata = extract_pdf_metadata(pdf_bytes)
        >>> metadata.page_count
        42
        >>> metadata.title
        'Document Title'
    """
    try:
        from io import BytesIO

        reader = PdfReader(BytesIO(content))

        # Extract basic info
        page_count = len(reader.pages)

        # Try to extract document metadata
        doc_info = reader.metadata
        title = None
        author = None
        subject = None
        creator = None
        producer = None
        creation_date = None
        modification_date = None

        if doc_info:
            # 安全地获取元数据字段，处理 None 值
            title = _safe_get_pdf_meta(doc_info, "/Title")
            author = _safe_get_pdf_meta(doc_info, "/Author")
            subject = _safe_get_pdf_meta(doc_info, "/Subject")
            creator = _safe_get_pdf_meta(doc_info, "/Creator")
            producer = _safe_get_pdf_meta(doc_info, "/Producer")
            creation_date = _safe_get_pdf_meta(doc_info, "/CreationDate")
            modification_date = _safe_get_pdf_meta(doc_info, "/ModDate")

        # Check if PDF has text content by sampling first page
        has_text = False
        if page_count > 0:
            try:
                first_page = reader.pages[0]
                text = first_page.extract_text()
                has_text = text is not None and len(text.strip()) > 0
            except Exception:
                pass  # 忽略文本提取错误

        return PDFMetadata(
            page_count=page_count,
            title=title,
            author=author,
            subject=subject,
            creator=creator,
            producer=producer,
            creation_date=creation_date,
            modification_date=modification_date,
            has_text_content=has_text,
        )
    except PdfReadError:
        # 无法读取的 PDF，返回基本信息
        return PDFMetadata(page_count=0)
    except Exception:
        # 任何其他错误，返回空元数据
        return PDFMetadata(page_count=0)


def _safe_get_pdf_meta(doc_info: Any, key: str) -> str | None:
    """Safely get a value from PDF metadata dictionary.

    Args:
        doc_info: PDF document info dictionary
        key: Metadata key to retrieve

    Returns:
        String value or None if not available
    """
    try:
        value = doc_info.get(key)
        if value is None:
            return None
        # 处理不同类型的值
        if isinstance(value, str):
            return value
        return str(value)
    except Exception:
        return None


def extract_pdf_text(content: bytes, max_pages: int = DEFAULT_MAX_PAGES) -> str | None:
    """Extract text from PDF content.

    Args:
        content: The PDF file content as bytes
        max_pages: Maximum number of pages to extract text from (default: 2)

    Returns:
        Extracted text from the first N pages, or None if extraction fails

    Example:
        >>> text = extract_pdf_text(pdf_bytes, max_pages=2)
        >>> print(text[:100])
        'Introduction\\nThis document describes...'
    """
    try:
        from io import BytesIO

        reader = PdfReader(BytesIO(content))

        # Extract text from first N pages
        text_parts = []
        pages_to_extract = min(max_pages, len(reader.pages))

        for i in range(pages_to_extract):
            try:
                page = reader.pages[i]
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {i + 1} ---\n{page_text}")
            except Exception as page_error:
                # 跳过无法提取的页面
                text_parts.append(
                    f"--- Page {i + 1} ---\n[Error extracting text: {page_error}]"
                )

        if text_parts:
            return "\n\n".join(text_parts)
        return None

    except Exception:
        return None


def is_binary_file(mime_type: str) -> bool:
    """Determine if a MIME type indicates a binary file.

    Args:
        mime_type: The MIME type to check

    Returns:
        True if the MIME type indicates binary content

    Example:
        >>> is_binary_file("application/pdf")
        True
        >>> is_binary_file("text/plain")
        False
    """
    # Image types
    if mime_type.startswith("image/"):
        return True

    # Audio types
    if mime_type.startswith("audio/"):
        return True

    # Video types
    if mime_type.startswith("video/"):
        return True

    # Application types (some are binary, some are text)
    if mime_type.startswith("application/"):
        text_application_types = {
            "application/json",
            "application/javascript",
            "application/xml",
            "application/x-httpd-php",
            "application/x-sh",
            "application/x-ruby",
        }
        if mime_type not in text_application_types:
            return True

    return False


def process_pdf_resource(
    uri: str,
    fs: AbstractFileSystem,
    session_id: str,
    path: str,
    file_size: int,
    extract_text: bool = True,
    max_pages: int = DEFAULT_MAX_PAGES,
    size_limit: int = LARGE_PDF_THRESHOLD,
) -> BinaryResource:
    """Process a PDF resource and extract metadata.

    For files larger than size_limit, returns metadata only without full content.

    Args:
        uri: The scratchpad:// URI
        fs: The filesystem containing the file
        session_id: The session identifier
        path: The file path within the session
        file_size: The file size in bytes
        extract_text: Whether to extract text from the PDF (default: True)
        max_pages: Maximum number of pages to extract text from (default: 2)
        size_limit: Size threshold for returning metadata only (default: 5MB)

    Returns:
        BinaryResource with PDF metadata and optionally content

    Example:
        >>> result = process_pdf_resource(
        ...     uri="scratchpad://abc-123/doc.pdf",
        ...     fs=filesystem,
        ...     session_id="abc-123",
        ...     path="/doc.pdf",
        ...     file_size=102400,
        ...     extract_text=True,
        ... )
        >>> result.pdf_metadata.page_count
        10
    """
    # Check if file is too large
    if file_size > size_limit:
        # Read just enough to extract metadata
        try:
            with fs.open(path, "rb") as f:
                # Read first 64KB for metadata extraction
                sample_content = f.read(65536)

            pdf_metadata = extract_pdf_metadata(sample_content)

            return BinaryResource(
                uri=uri,
                session_id=session_id,
                path=path,
                binary_content="",  # No content for large files
                binary_format="PDF",
                mime_type="application/pdf",
                size_bytes=file_size,
                metadata={
                    "size": file_size,
                    "format": "PDF",
                },
                pdf_metadata=pdf_metadata,
                is_large_file=True,
                large_file_message=f"PDF exceeds size limit ({file_size} bytes > {size_limit} bytes). Metadata only.",
                success=True,
            )
        except Exception as e:
            return BinaryResource(
                uri=uri,
                session_id=session_id,
                path=path,
                binary_content="",
                binary_format="PDF",
                mime_type="application/pdf",
                size_bytes=file_size,
                is_large_file=True,
                success=False,
                error=f"Failed to read large PDF metadata: {e}",
            )

    # Read full content for normal-sized PDFs
    try:
        with fs.open(path, "rb") as f:
            content = f.read()

        # Extract metadata
        pdf_metadata = extract_pdf_metadata(content)

        # Encode content as Base64
        encoded_content = base64.b64encode(content).decode("ascii")

        # Extract text if requested and PDF has text content
        extracted_text = None
        if extract_text and pdf_metadata.has_text_content:
            extracted_text = extract_pdf_text(content, max_pages)

        return BinaryResource(
            uri=uri,
            session_id=session_id,
            path=path,
            binary_content=encoded_content,
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=file_size,
            metadata={
                "size": file_size,
                "format": "PDF",
                "page_count": pdf_metadata.page_count,
            },
            pdf_metadata=pdf_metadata,
            extracted_text=extracted_text,
            is_large_file=False,
            success=True,
        )

    except Exception as e:
        return BinaryResource(
            uri=uri,
            session_id=session_id,
            path=path,
            binary_content="",
            binary_format="PDF",
            mime_type="application/pdf",
            size_bytes=file_size,
            is_large_file=False,
            success=False,
            error=f"Failed to process PDF: {e}",
        )


def process_binary_resource(
    uri: str,
    fs: AbstractFileSystem,
    session_id: str,
    path: str,
    mime_type: str,
    size_limit: int = LARGE_PDF_THRESHOLD,
) -> BinaryResource:
    """Process a generic binary resource.

    For files larger than size_limit, returns metadata only without full content.

    Args:
        uri: The scratchpad:// URI
        fs: The filesystem containing the file
        session_id: The session identifier
        path: The file path within the session
        mime_type: The MIME type of the file
        size_limit: Size threshold for returning metadata only (default: 5MB)

    Returns:
        BinaryResource with binary content and metadata

    Example:
        >>> result = process_binary_resource(
        ...     uri="scratchpad://abc-123/file.zip",
        ...     fs=filesystem,
        ...     session_id="abc-123",
        ...     path="/file.zip",
        ...     mime_type="application/zip",
        ... )
        >>> result.binary_format
        'ZIP'
    """
    try:
        # Get file size
        info = fs.info(path)
        file_size = info.get("size", 0)

        # Check if file is too large
        if file_size > size_limit:
            # Read first few bytes to detect format
            try:
                with fs.open(path, "rb") as f:
                    sample = f.read(1024)
                binary_format = detect_binary_format(sample, mime_type, path)
            except Exception:
                binary_format = "BINARY"

            return BinaryResource(
                uri=uri,
                session_id=session_id,
                path=path,
                binary_content="",  # No content for large files
                binary_format=binary_format,
                mime_type=mime_type,
                size_bytes=file_size,
                metadata={
                    "size": file_size,
                    "format": binary_format,
                },
                is_large_file=True,
                large_file_message=f"File exceeds size limit ({file_size} bytes > {size_limit} bytes). Metadata only.",
                success=True,
            )

        # Read full content for normal-sized files
        with fs.open(path, "rb") as f:
            content = f.read()

        # Detect format from content
        binary_format = detect_binary_format(content, mime_type, path)

        # Encode content as Base64
        encoded_content = base64.b64encode(content).decode("ascii")

        return BinaryResource(
            uri=uri,
            session_id=session_id,
            path=path,
            binary_content=encoded_content,
            binary_format=binary_format,
            mime_type=mime_type,
            size_bytes=file_size,
            metadata={
                "size": file_size,
                "format": binary_format,
            },
            is_large_file=False,
            success=True,
        )

    except Exception as e:
        return BinaryResource(
            uri=uri,
            session_id=session_id,
            path=path,
            binary_content="",
            binary_format="UNKNOWN",
            mime_type=mime_type,
            size_bytes=0,
            is_large_file=False,
            success=False,
            error=f"Failed to process binary file: {e}",
        )
