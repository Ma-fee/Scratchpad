"""Read tool - 读取文件内容"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP
from pydantic import Field

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..path_resolver import get_path_description
from ..storage import get_store

if TYPE_CHECKING:
    from ..fs.session_manager import SessionFileSystemManager

DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_BYTES = 50 * 1024

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
        file_path: str = Field(description=get_path_description()),
        session_id: str = Field(description="Session ID for session-scoped reads"),
        offset: int | None = Field(
            default=None, description="The line number to start reading from (0-based)"
        ),
        limit: int | None = Field(
            default=None, description="The number of lines to read (defaults to 2000)"
        ),
    ) -> str:
        """读取文件内容"""
        try:
            if session_manager is None:
                raise ValueError("session_manager is required")

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
                f"{(i + offset + 1):05d}| {line}" for i, line in enumerate(raw_lines)
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

        except Exception as e:
            raise ValueError(f"Error reading file: {e}") from e
