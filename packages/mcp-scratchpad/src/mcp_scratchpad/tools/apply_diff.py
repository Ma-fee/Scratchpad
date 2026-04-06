"""ApplyPatchSimple tool - 简化版补丁工具（仅支持 Update）"""

from __future__ import annotations

import os
import re
from typing import Annotated
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from ..exceptions import ValidationError
from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..path_resolver import get_path_description
from ..storage import get_store

if TYPE_CHECKING:
    from ..fs.session_manager import SessionFileSystemManager


def _clean_header_path(path: str) -> str:
    stripped = path.strip()
    if stripped.startswith("a/") or stripped.startswith("b/"):
        return stripped[2:]
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
        if stripped.startswith("a/") or stripped.startswith("b/"):
            stripped = stripped[2:]
    return stripped


def normalize_unicode(text: str) -> str:
    """标准化 Unicode 标点符号为 ASCII 等价物"""
    # 单引号
    text = re.sub(r"[\u2018\u2019\u201A\u201B]", "'", text)
    # 双引号
    text = re.sub(r"[\u201C\u201D\u201E\u201F]", '"', text)
    # 破折号
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015]", "-", text)
    # 省略号
    text = re.sub(r"\u2026", "...", text)
    # 不换行空格
    text = re.sub(r"\u00A0", " ", text)
    return text


def try_match(
    lines: list[str],
    pattern: list[str],
    start_index: int,
    compare_func,
    eof: bool = False,
) -> int:
    """尝试匹配模式"""
    # 如果有 EOF 锚点，先从文件末尾尝试匹配
    if eof:
        from_end = len(lines) - len(pattern)
        if from_end >= start_index:
            matches = True
            for j in range(len(pattern)):
                if not compare_func(lines[from_end + j], pattern[j]):
                    matches = False
                    break
            if matches:
                return from_end

    # 从 start_index 开始向前搜索
    for i in range(start_index, len(lines) - len(pattern) + 1):
        matches = True
        for j in range(len(pattern)):
            if not compare_func(lines[i + j], pattern[j]):
                matches = False
                break
        if matches:
            return i

    return -1


def seek_sequence(
    lines: list[str], pattern: list[str], start_index: int, eof: bool = False
) -> int:
    """查找序列，使用多轮匹配策略"""
    if len(pattern) == 0:
        return -1

    # 第 1 轮: 精确匹配
    exact = try_match(lines, pattern, start_index, lambda a, b: a == b, eof)
    if exact != -1:
        return exact

    # 第 2 轮: rstrip (去除尾部空白)
    rstrip = try_match(
        lines, pattern, start_index, lambda a, b: a.rstrip() == b.rstrip(), eof
    )
    if rstrip != -1:
        return rstrip

    # 第 3 轮: trim (去除首尾空白)
    trim = try_match(
        lines, pattern, start_index, lambda a, b: a.strip() == b.strip(), eof
    )
    if trim != -1:
        return trim

    # 第 4 轮: Unicode 标准化后匹配
    normalized = try_match(
        lines,
        pattern,
        start_index,
        lambda a, b: normalize_unicode(a.strip()) == normalize_unicode(b.strip()),
        eof,
    )
    return normalized


def parse_update_chunks(diff: str, start_idx: int = 0) -> list[dict]:
    """解析更新文件的 chunks"""
    lines = diff.splitlines()
    chunks = []
    i = start_idx
    header_seen = False
    while i < len(lines) and not lines[i].startswith("***"):
        line = lines[i]
        if line.startswith("--- "):
            if header_seen:
                raise ValidationError("apply_diff only supports one file diff")
            old_path = _clean_header_path(line[4:].strip())
            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                raise ValidationError("Diff header missing matching +++ line")
            new_path = _clean_header_path(lines[i][4:].strip())

            if old_path == "/dev/null" or new_path == "/dev/null":
                raise ValidationError(
                    "Diff cannot create or delete files via apply_diff"
                )

            header_seen = True
            i += 1
            continue
        if lines[i].startswith("@@"):
            if not header_seen or not old_path or not new_path:
                raise ValidationError(
                    "Diff missing ---/+++ header before hunk definition"
                )
            hunk_header_re = re.compile(
                r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)"
            )
            match = hunk_header_re.match(line)
            if not match:
                raise ValidationError(f"Invalid hunk header: {line}")

            # 解析上下文行
            context_line = match.group(5).strip()
            i += 1

            old_lines = []
            new_lines = []
            is_end_of_file = False

            # 解析变更行
            while (
                i < len(lines)
                and not lines[i].startswith("@@")
                and not lines[i].startswith("***")
            ):
                change_line = lines[i]

                if change_line == "*** End of File":
                    is_end_of_file = True
                    i += 1
                    break

                if change_line.startswith(" "):
                    # 保留行 - 同时出现在旧和新中
                    content = change_line[1:]
                    old_lines.append(content)
                    new_lines.append(content)
                elif change_line.startswith("-"):
                    # 删除行 - 只在旧中
                    old_lines.append(change_line[1:])
                elif change_line.startswith("+"):
                    # 添加行 - 只在新中
                    new_lines.append(change_line[1:])

                i += 1

            chunks.append(
                {
                    "old_lines": old_lines,
                    "new_lines": new_lines,
                    "change_context": context_line if context_line else None,
                    "is_end_of_file": is_end_of_file if is_end_of_file else None,
                }
            )
        else:
            i += 1

    return chunks


def parse_patch(patch_text: str) -> dict:
    """解析补丁文本（仅支持 Update）"""
    # 移除 heredoc 格式
    heredoc_match = re.match(
        r"^(?:cat\s+)?<<['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", patch_text.strip()
    )
    if heredoc_match:
        patch_text = heredoc_match.group(2)

    lines = patch_text.split("\n")

    # 查找 Begin/End 标记
    begin_marker = "*** Begin Patch"
    end_marker = "*** End Patch"

    begin_idx = -1
    end_idx = -1
    for idx, line in enumerate(lines):
        if line.strip() == begin_marker:
            begin_idx = idx
        elif line.strip() == end_marker:
            end_idx = idx

    if begin_idx == -1 or end_idx == -1 or begin_idx >= end_idx:
        raise ValueError("Invalid patch format: missing Begin/End markers")

    # 解析 Update File 操作
    i = begin_idx + 1
    file_path = None
    chunks = []

    while i < end_idx:
        line = lines[i].strip()

        if line.startswith("*** Update File:"):
            file_path = line[16:].strip()
            i += 1
            chunks, i = parse_update_chunks(lines, i)
        else:
            i += 1

    if not file_path:
        raise ValueError("No Update File operation found in patch")

    return {
        "file_path": file_path,
        "chunks": chunks,
    }


def compute_replacements(
    original_lines: list[str], file_path: str, chunks: list[dict]
) -> list[tuple[int, int, list[str]]]:
    """计算替换位置"""
    replacements = []
    line_index = 0

    for chunk in chunks:
        # 处理基于上下文的定位
        if chunk.get("change_context"):
            context_idx = seek_sequence(
                original_lines, [chunk["change_context"]], line_index
            )
            if context_idx == -1:
                raise ValueError(
                    f"Failed to find context '{chunk['change_context']}' in {file_path}"
                )
            line_index = context_idx + 1

        # 处理纯添加（没有 old_lines）
        if len(chunk["old_lines"]) == 0:
            insertion_idx = len(original_lines)
            if len(original_lines) > 0 and original_lines[-1] == "":
                insertion_idx = len(original_lines) - 1
            replacements.append((insertion_idx, 0, chunk["new_lines"]))
            continue

        # 尝试匹配 old_lines
        pattern = chunk["old_lines"]
        new_slice = chunk["new_lines"]
        found = seek_sequence(
            original_lines, pattern, line_index, chunk.get("is_end_of_file", False)
        )

        # 如果没找到，重试（去除末尾空行）
        if found == -1 and len(pattern) > 0 and pattern[-1] == "":
            pattern = pattern[:-1]
            if len(new_slice) > 0 and new_slice[-1] == "":
                new_slice = new_slice[:-1]
            found = seek_sequence(
                original_lines, pattern, line_index, chunk.get("is_end_of_file", False)
            )

        if found != -1:
            replacements.append((found, len(pattern), new_slice))
            line_index = found + len(pattern)
        else:
            raise ValueError(
                f"Failed to find expected lines in {file_path}:\n"
                + "\n".join(chunk["old_lines"])
            )

    # 按索引排序
    replacements.sort(key=lambda x: x[0])

    return replacements


def apply_replacements(
    lines: list[str], replacements: list[tuple[int, int, list[str]]]
) -> list[str]:
    """应用替换"""
    result = lines.copy()

    # 反向应用替换以避免索引偏移
    for i in range(len(replacements) - 1, -1, -1):
        start_idx, old_len, new_segment = replacements[i]

        # 删除旧行
        del result[start_idx : start_idx + old_len]

        # 插入新行
        for j in range(len(new_segment)):
            result.insert(start_idx + j, new_segment[j])

    return result


def derive_new_contents_from_chunks(file_path: str, chunks: list[dict]) -> str:
    """从 chunks 推导新内容"""
    # 读取原始文件
    try:
        with open(file_path, encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        raise ValueError(f"Failed to read file {file_path}: {e}") from e

    # 移除末尾空元素以保持一致的行计数
    original_lines = original_content.strip().split("\n")

    # 计算替换
    replacements = compute_replacements(original_lines, file_path, chunks)
    new_lines = apply_replacements(original_lines, replacements)

    # 确保末尾有换行符
    if len(new_lines) == 0 or new_lines[-1] != "":
        new_lines.append("")

    return "\n".join(new_lines)


def derive_new_contents_from_content(
    original_content: str,
    file_path: str,
    chunks: list[dict],
) -> str:
    """Derive updated content from in-memory content + parsed chunks."""
    original_lines = original_content.strip().split("\n")
    replacements = compute_replacements(original_lines, file_path, chunks)
    new_lines = apply_replacements(original_lines, replacements)
    if len(new_lines) == 0 or new_lines[-1] != "":
        new_lines.append("")
    return "\n".join(new_lines)


def _build_adapter(
    session_manager: SessionFileSystemManager | None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> UnifiedSessionFSAdapter:
    """Build unified adapter for patch operations."""
    if adapter is not None:
        return adapter
    return UnifiedSessionFSAdapter(
        session_manager=session_manager,
        store=get_store(),
        unified_enabled=True,
    )


def apply_patch_with_session(
    *,
    session_id: str | None,
    file_path: str | None,
    diff: str | None,
    session_manager: SessionFileSystemManager | None = None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> str:
    """Apply patch using session-aware unified adapter."""
    if not session_id:
        raise ValueError("session_id is required")
    if not file_path:
        raise ValueError("file_path is required")
    if not diff:
        raise ValueError("diff is required")

    active_adapter = _build_adapter(session_manager, adapter)
    current = active_adapter.read_text(session_id, file_path)
    chunks = parse_update_chunks(diff)
    if not chunks:
        raise ValueError("patch rejected: empty patch")

    new_content = derive_new_contents_from_content(
        current.content,
        file_path,
        chunks,
    )
    active_adapter.write_text(session_id, file_path, new_content)
    return f"Success. Updated file: {file_path}"


def register_apply_diff(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    @mcp.tool(
        name="patch",
        description=(
            "Use the `patch` tool to precisely update existing files with Unified diff format."
            "Within a hunk which formatted as `@@ -start,len +start,len @@`.each line starts with:\n"
            "- ' ' (space) for context lines (unchanged)\n"
            "- '-' for lines to remove\n"
            "- '+' for lines to add\n"
            "Diff format:\n\n"
            "--- <old_file>\n"
            "+++ <new_file>\n"
            "@@ -start,len +start,len @@\n"
            "-<old_line>\n"
            "+<new_line>\n"
            " <unchanged_line>\n\n"
            "Example:\n\n"
            "```\n"
            "--- report.md\n"
            "+++ report.md\n"
            "@@ -10,3 +10,2 @@\n"
            " The content of line 10.\n"
            "-The content of line 11.\n"
            "+Updated findings based on latest search results [1].\n"
            " The content of line 12\n"
            "```\n\n"
            "```\n\n"
            "Key features:\n\n"
            "- Only supports Update File operations\n"
            "- Use @@ to specify context lines for precise matching\n"
            "- Use `validate_only=true` if the context is uncertain. If a conflict occurs, re-read the file to sync line numbers and regenerate the diff."
            "STRICT REQUIREMENTS:\n"
            "1. **Header**: Must start with `--- filename` and `+++ filename` matching the `file_path`. \n"
            "2. **The Golden Rule**: Every line starting with a space (context) or minus (removal) must match the file content EXACTLY, including the number of leading spaces or tabs.\n"
            "3. ** NEVER omit empty lines (represented as '\n' or blank line in the file) in the diff **：\n"
            "- eg, add empty line:'+\n\n'\n"
            "- eg, context empty line:' \n\n'\n"
            "- eg, delete empty line:'-\n\n'\n"
        ),
    )
    async def patch(
        ctx: Context,
        file_path: Annotated[
            str | None,
            Field(description=get_path_description()),
        ],
        diff: Annotated[
            str | None,
            Field(
                description="The incremental modification content in unified diff format (UTF-8 encoded)."
            ),
        ],
        session_id: Annotated[
            str | None,
            Field(description="Session ID for session-scoped patch operations"),
        ] = None,
        expected_version: Annotated[
            int | None,
            Field(
                description="The file version number recorded by the client during the last read, used for optimistic locking to avoid overwriting modifications from other Agents."
            ),
        ] = None,
        validate_only: Annotated[
            bool,
            Field(
                description="Whether to only perform diff parsing and conflict checking without actual file writing. Defaults to False (execute actual incremental modification if verification passes)."
            ),
        ] = False,
        max_diff_lines: Annotated[
            int | None,
            Field(
                description="The maximum allowed number of lines for the incoming diff content. Defaults to 1000 lines if not provided, and returns an error if the diff exceeds this limit."
            ),
        ] = None,
    ) -> ToolResult:
        """应用简化版补丁（仅支持 Update）"""
        try:
            return apply_patch_with_session(
                session_id=session_id,
                file_path=file_path,
                diff=diff,
                session_manager=session_manager,
            )
        except Exception as e:
            raise ValueError(f"Error applying patch: {e}") from e
