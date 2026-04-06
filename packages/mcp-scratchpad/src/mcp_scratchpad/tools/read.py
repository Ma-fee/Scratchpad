"""Read tool - 读取文件内容"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from pydantic import Field

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..path_resolver import PathResolutionError, get_path_description, resolve_file_path
from ..storage import get_store

if TYPE_CHECKING:
    from ..fs.session_manager import SessionFileSystemManager

DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_BYTES = 50 * 1024

IGNORE_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    ".git/",
    "dist/",
    "build/",
    "target/",
    "vendor/",
    "bin/",
    "obj/",
    ".idea/",
    ".vscode/",
    ".zig-cache/",
    "zig-out",
    ".coverage",
    "coverage/",
    "vendor/",
    "tmp/",
    "temp/",
    ".cache/",
    "cache/",
    "logs/",
    ".venv/",
    "venv/",
    "env/",
]


def is_binary_file(filepath: str) -> bool:
    """检查文件是否为二进制文件"""
    ext = Path(filepath).suffix.lower()
    binary_extensions = {
        ".zip",
        ".tar",
        ".gz",
        ".exe",
        ".dll",
        ".so",
        ".class",
        ".jar",
        ".war",
        ".7z",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".bin",
        ".dat",
        ".obj",
        ".o",
        ".a",
        ".lib",
        ".wasm",
        ".pyc",
        ".pyo",
    }
    if ext in binary_extensions:
        return True

    try:
        with open(filepath, "rb") as f:
            chunk = f.read(4096)
            if not chunk:
                return False

            null_count = chunk.count(b"\x00")
            if null_count > 0:
                return True

            non_printable = sum(1 for b in chunk if b < 9 or (13 < b < 32))
            return non_printable / len(chunk) > 0.3
    except Exception:
        return False


def _resolve_overlay_path(file_path: str, session_manager) -> Path | None:
    """Resolve a path to an overlay filesystem mount.

    Args:
        file_path: The path to resolve (e.g., "/config/diag-agent-v2.yaml")
        session_manager: SessionFileSystemManager with mount configuration

    Returns:
        Path object if file exists in overlay, None otherwise
    """
    from pathlib import Path

    if not session_manager:
        return None

    # Check each mount to see if the path matches
    for mount in session_manager.config.mounts:
        mount_point = mount.mount_point
        if file_path.startswith(mount_point) or (
            mount_point == "/" and not file_path.startswith("/.")
        ):
            # Get the mount's filesystem path
            mount_fs_path = session_manager._mount_paths.get(mount.name)
            if not mount_fs_path:
                continue

            # Calculate the relative path within the mount
            if mount_point == "/":
                rel_path = file_path.lstrip("/")
            else:
                rel_path = file_path[len(mount_point) :].lstrip("/")

            # Build full filesystem path
            full_path = Path(mount_fs_path) / rel_path

            if full_path.exists():
                return full_path

    return None


def register_read(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    @mcp.tool(
        name="read",
        description=(
            "Read a file content. "
            "Assume this tool is able to read all files. If the User provides a path to a file assume that path is valid. "
            "It is okay to read a file that does not exist; an error will be returned.\n\n"
            "Usage:\n"
            "- The file_path parameter must be a relative path. eg, reports/test_file.txt\n"
            "- By default, it reads up to 2000 lines starting from the beginning of the file\n"
            "- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters\n"
            "- Any lines longer than 2000 characters will be truncated\n"
            "- Results are returned using cat -n format, with line numbers starting at 1\n"
            "- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.\n"
            "- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.\n"
            "- You can read image files using this tool."
        ),
    )
    async def read(
        session_id: str | None = Field(
            default=None,
            description="Session ID for session-scoped reads (optional)",
        ),
        file_path: str = Field(description=get_path_description()),
        offset: int | None = Field(
            default=None, description="The line number to start reading from (0-based)"
        ),
        limit: int | None = Field(
            default=None, description="The number of lines to read (defaults to 2000)"
        ),
    ) -> str:
        """读取文件内容"""
        try:
            if session_id and session_manager is not None:
                adapter = UnifiedSessionFSAdapter(
                    session_manager=session_manager,
                    store=get_store(),
                    unified_enabled=True,
                )
                result = adapter.read_text(session_id, file_path)
                lines = result.content.splitlines()
                offset = offset or 0
                limit = limit or DEFAULT_READ_LIMIT

                raw_lines = []
                bytes_count = 0
                truncated_by_bytes = False

                for i in range(offset, min(len(lines), offset + limit)):
                    line = lines[i]
                    if len(line) > MAX_LINE_LENGTH:
                        line = line[:MAX_LINE_LENGTH] + "..."
                    line_size = len(line.encode("utf-8")) + (1 if raw_lines else 0)

                    if bytes_count + line_size > MAX_BYTES:
                        truncated_by_bytes = True
                        break

                    raw_lines.append(line)
                    bytes_count += line_size

                content = "\n".join(
                    f"{(i + offset + 1):05d}| {line}"
                    for i, line in enumerate(raw_lines)
                )

                output = f"<file>\n{content}\n"
                total_lines = len(lines)
                last_read_line = offset + len(raw_lines)
                has_more_lines = total_lines > last_read_line

                if truncated_by_bytes:
                    output += (
                        f"\n\n(Output truncated at {MAX_BYTES} bytes. "
                        f"Use 'offset' parameter to read beyond line {last_read_line})"
                    )
                elif has_more_lines:
                    output += (
                        "\n\n(File has more lines. Use 'offset' parameter to read "
                        f"beyond line {last_read_line})"
                    )
                else:
                    output += f"\n\n(End of file - total {total_lines} lines)"

                output += "\n</file>"
                return output

            try:
                filepath = resolve_file_path(file_path, get_store())
            except PathResolutionError as e:
                raise ValueError(f"Invalid path: {e}") from e

            # 检查文件是否存在
            if not filepath.exists():
                # 尝试从 overlay 文件系统读取
                overlay_path = _resolve_overlay_path(file_path, session_manager)
                if overlay_path and overlay_path.exists():
                    filepath = overlay_path
                else:
                    # 尝试提供文件建议
                    dir_path = filepath.parent
                    if dir_path.exists():
                        base_name = filepath.name.lower()
                        suggestions = []
                        try:
                            for entry in dir_path.iterdir():
                                if (
                                    base_name in entry.name.lower()
                                    or entry.name.lower() in base_name
                                ):
                                    suggestions.append(str(entry))
                        except Exception:
                            pass

                        if suggestions:
                            raise ValueError(
                                f"File not found: {file_path}\n\nDid you mean one of these?\n"
                                + "\n".join(suggestions[:3])
                            )

                    raise FileNotFoundError(f"File not found: {file_path}")

            # 检查是否为图片
            image_extensions = {
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".bmp",
                ".webp",
                ".svg",
            }
            if filepath.suffix.lower() in image_extensions:
                try:
                    with open(filepath, "rb") as f:
                        image_data = f.read()
                        mime_type = f"image/{filepath.suffix[1:]}"
                        return f"Image read successfully\n\nMIME type: {mime_type}\nSize: {len(image_data)} bytes\n\nBase64 data available for display."
                except Exception as e:
                    raise ValueError(f"Failed to read image file: {e}") from e

            # 检查是否为二进制文件
            if is_binary_file(str(filepath)):
                raise ValueError(f"Cannot read binary file: {file_path}")

            # 读取文本文件
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            # 应用偏移和限制
            offset = offset or 0
            limit = limit or DEFAULT_READ_LIMIT

            raw_lines = []
            bytes_count = 0
            truncated_by_bytes = False

            for i in range(offset, min(len(lines), offset + limit)):
                line = lines[i]
                if len(line) > MAX_LINE_LENGTH:
                    line = line[:MAX_LINE_LENGTH] + "...\n"
                line_size = len(line.encode("utf-8")) + (1 if raw_lines else 0)

                if bytes_count + line_size > MAX_BYTES:
                    truncated_by_bytes = True
                    break

                raw_lines.append(line.rstrip("\n"))
                bytes_count += line_size

            # 格式化输出
            content = "\n".join(
                f"{(i + offset + 1):05d}| {line}" for i, line in enumerate(raw_lines)
            )

            output = f"<file>\n{content}\n"

            total_lines = len(lines)
            last_read_line = offset + len(raw_lines)
            has_more_lines = total_lines > last_read_line

            if truncated_by_bytes:
                output += f"\n\n(Output truncated at {MAX_BYTES} bytes. Use 'offset' parameter to read beyond line {last_read_line})"
            elif has_more_lines:
                output += f"\n\n(File has more lines. Use 'offset' parameter to read beyond line {last_read_line})"
            else:
                output += f"\n\n(End of file - total {total_lines} lines)"

            output += "\n</file>"

            return output

        except Exception as e:
            raise ValueError(f"Error reading file: {e}") from e
