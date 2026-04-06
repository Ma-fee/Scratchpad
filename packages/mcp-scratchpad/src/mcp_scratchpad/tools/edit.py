"""Edit tool - 编辑文件（字符串替换）"""

from __future__ import annotations

import re
from collections.abc import Generator
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from pydantic import Field

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..path_resolver import get_path_description
from ..storage import get_store

if TYPE_CHECKING:
    from ..fs.session_manager import SessionFileSystemManager


def normalize_line_endings(text: str) -> str:
    """标准化行尾符"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def levenshtein(a: str, b: str) -> int:
    """计算 Levenshtein 距离"""
    if a == "" or b == "":
        return max(len(a), len(b))

    matrix = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]

    for i in range(len(a) + 1):
        matrix[i][0] = i
    for j in range(len(b) + 1):
        matrix[0][j] = j

    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1, matrix[i][j - 1] + 1, matrix[i - 1][j - 1] + cost
            )

    return matrix[len(a)][len(b)]


def simple_replacer(content: str, find: str) -> Generator[str, None, None]:
    """简单替换器"""
    if find in content:
        yield find


def line_trimmed_replacer(content: str, find: str) -> Generator[str, None, None]:
    """行修剪替换器"""
    original_lines = content.split("\n")
    search_lines = find.split("\n")

    if search_lines and search_lines[-1] == "":
        search_lines.pop()

    for i in range(len(original_lines) - len(search_lines) + 1):
        matches = True

        for j in range(len(search_lines)):
            if original_lines[i + j].strip() != search_lines[j].strip():
                matches = False
                break

        if matches:
            match_start_index = sum(len(original_lines[k]) + 1 for k in range(i))
            match_end_index = match_start_index
            for k in range(i, i + len(search_lines)):
                match_end_index += len(original_lines[k])
                if k < i + len(search_lines) - 1:
                    match_end_index += 1

            yield content[match_start_index:match_end_index]


def block_anchor_replacer(content: str, find: str) -> Generator[str, None, None]:
    """块锚点替换器"""
    original_lines = content.split("\n")
    search_lines = find.split("\n")

    if len(search_lines) < 3:
        return

    if search_lines and search_lines[-1] == "":
        search_lines.pop()

    first_line_search = search_lines[0].strip()
    last_line_search = search_lines[-1].strip()
    search_block_size = len(search_lines)

    candidates = []
    for i in range(len(original_lines)):
        if original_lines[i].strip() != first_line_search:
            continue

        for j in range(i + 2, len(original_lines)):
            if original_lines[j].strip() == last_line_search:
                candidates.append((i, j))
                break

    if not candidates:
        return

    if len(candidates) == 1:
        start_line, end_line = candidates[0]
        actual_block_size = end_line - start_line + 1

        similarity = 0.0
        lines_to_check = min(search_block_size - 2, actual_block_size - 2)

        if lines_to_check > 0:
            for j in range(1, min(search_block_size - 1, actual_block_size - 1)):
                original_line = original_lines[start_line + j].strip()
                search_line = search_lines[j].strip()
                max_len = max(len(original_line), len(search_line))

                if max_len == 0:
                    continue

                distance = levenshtein(original_line, search_line)
                similarity += (1 - distance / max_len) / lines_to_check

                if similarity >= 0.0:
                    break
        else:
            similarity = 1.0

        if similarity >= 0.0:
            match_start_index = sum(
                len(original_lines[k]) + 1 for k in range(start_line)
            )
            match_end_index = match_start_index
            for k in range(start_line, end_line + 1):
                match_end_index += len(original_lines[k])
                if k < end_line:
                    match_end_index += 1

            yield content[match_start_index:match_end_index]
        return

    best_match = None
    max_similarity = -1

    for start_line, end_line in candidates:
        actual_block_size = end_line - start_line + 1
        similarity = 0.0
        lines_to_check = min(search_block_size - 2, actual_block_size - 2)

        if lines_to_check > 0:
            for j in range(1, min(search_block_size - 1, actual_block_size - 1)):
                original_line = original_lines[start_line + j].strip()
                search_line = search_lines[j].strip()
                max_len = max(len(original_line), len(search_line))

                if max_len == 0:
                    continue

                distance = levenshtein(original_line, search_line)
                similarity += 1 - distance / max_len

            similarity /= lines_to_check
        else:
            similarity = 1.0

        if similarity > max_similarity:
            max_similarity = similarity
            best_match = (start_line, end_line)

    if max_similarity >= 0.3 and best_match:
        start_line, end_line = best_match
        match_start_index = sum(len(original_lines[k]) + 1 for k in range(start_line))
        match_end_index = match_start_index
        for k in range(start_line, end_line + 1):
            match_end_index += len(original_lines[k])
            if k < end_line:
                match_end_index += 1

        yield content[match_start_index:match_end_index]


def whitespace_normalized_replacer(
    content: str, find: str
) -> Generator[str, None, None]:
    """空白标准化替换器"""

    def normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    normalized_find = normalize_whitespace(find)

    lines = content.split("\n")
    for line in lines:
        if normalize_whitespace(line) == normalized_find:
            yield line
        else:
            normalized_line = normalize_whitespace(line)
            if normalized_find in normalized_line:
                words = find.strip().split()
                if words:
                    pattern = r"\s+".join(re.escape(word) for word in words)
                    try:
                        match = re.search(pattern, line)
                        if match:
                            yield match.group(0)
                    except re.error:
                        pass

    find_lines = find.split("\n")
    if len(find_lines) > 1:
        for i in range(len(lines) - len(find_lines) + 1):
            block = "\n".join(lines[i : i + len(find_lines)])
            if normalize_whitespace(block) == normalized_find:
                yield block


def indentation_flexible_replacer(
    content: str, find: str
) -> Generator[str, None, None]:
    """缩进灵活替换器"""

    def remove_indentation(text: str) -> str:
        lines = text.split("\n")
        non_empty_lines = [line for line in lines if line.strip()]

        if not non_empty_lines:
            return text

        min_indent = min(
            len(match.group(1))
            for line in non_empty_lines
            if (match := re.match(r"^(\s*)", line))
        )

        return "\n".join(
            line if not line.strip() else line[min_indent:] for line in lines
        )

    normalized_find = remove_indentation(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")

    for i in range(len(content_lines) - len(find_lines) + 1):
        block = "\n".join(content_lines[i : i + len(find_lines)])
        if remove_indentation(block) == normalized_find:
            yield block


def escape_normalized_replacer(content: str, find: str) -> Generator[str, None, None]:
    """转义标准化替换器"""

    def unescape_string(s: str) -> str:
        return re.sub(
            r"\\(n|t|r|'\"|`|\\|\n|\$)",
            lambda m: {
                "n": "\n",
                "t": "\t",
                "r": "\r",
                "'": "'",
                '"': '"',
                "`": "`",
                "\\": "\\",
                "\n": "\n",
                "$": "$",
            }.get(m.group(1), m.group(0)),
            s,
        )

    unescaped_find = unescape_string(find)

    if unescaped_find in content:
        yield unescaped_find

    lines = content.split("\n")
    find_lines = unescaped_find.split("\n")

    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i : i + len(find_lines)])
        if unescape_string(block) == unescaped_find:
            yield block


def multi_occurrence_replacer(content: str, find: str) -> Generator[str, None, None]:
    """多出现替换器"""
    start_index = 0
    while True:
        index = content.find(find, start_index)
        if index == -1:
            break
        yield find
        start_index = index + len(find)


def trimmed_boundary_replacer(content: str, find: str) -> Generator[str, None, None]:
    """修剪边界替换器"""
    trimmed_find = find.strip()

    if trimmed_find == find:
        return

    if trimmed_find in content:
        yield trimmed_find

    lines = content.split("\n")
    find_lines = find.split("\n")

    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i : i + len(find_lines)])
        if block.strip() == trimmed_find:
            yield block


def context_aware_replacer(content: str, find: str) -> Generator[str, None, None]:
    """上下文感知替换器"""
    find_lines = find.split("\n")
    if len(find_lines) < 3:
        return

    if find_lines and find_lines[-1] == "":
        find_lines.pop()

    content_lines = content.split("\n")

    first_line = find_lines[0].strip()
    last_line = find_lines[-1].strip()

    for i in range(len(content_lines)):
        if content_lines[i].strip() != first_line:
            continue

        for j in range(i + 2, len(content_lines)):
            if content_lines[j].strip() == last_line:
                block_lines = content_lines[i : j + 1]
                block = "\n".join(block_lines)

                if len(block_lines) == len(find_lines):
                    matching_lines = 0
                    total_non_empty_lines = 0

                    for k in range(1, len(block_lines) - 1):
                        block_line = block_lines[k].strip()
                        find_line = find_lines[k].strip()

                        if block_line or find_line:
                            total_non_empty_lines += 1
                            if block_line == find_line:
                                matching_lines += 1

                    if (
                        total_non_empty_lines == 0
                        or matching_lines / total_non_empty_lines >= 0.5
                    ):
                        yield block
                        break
                break


def replace_content(
    content: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    """替换内容"""
    if old_string == new_string:
        raise ValueError("old_string and new_string must be different")

    not_found = True

    replacers = [
        simple_replacer,
        line_trimmed_replacer,
        block_anchor_replacer,
        whitespace_normalized_replacer,
        indentation_flexible_replacer,
        escape_normalized_replacer,
        trimmed_boundary_replacer,
        context_aware_replacer,
        multi_occurrence_replacer,
    ]

    for replacer in replacers:
        for search in replacer(content, old_string):
            index = content.find(search)
            if index == -1:
                continue
            not_found = False

            if replace_all:
                return content.replace(search, new_string)

            last_index = content.rfind(search)
            if index != last_index:
                continue

            return content[:index] + new_string + content[index + len(search) :]

    if not_found:
        raise ValueError("old_string not found in content")

    raise ValueError(
        "Found multiple matches for old_string. Provide more surrounding lines in old_string to identify the correct match."
    )


def _build_adapter(
    session_manager: SessionFileSystemManager | None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> UnifiedSessionFSAdapter:
    """Build unified adapter for edit operations."""
    if adapter is not None:
        return adapter
    return UnifiedSessionFSAdapter(
        session_manager=session_manager,
        store=get_store(),
        unified_enabled=True,
    )


def apply_edit_with_session(
    *,
    session_id: str | None,
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    session_manager: SessionFileSystemManager | None = None,
    adapter: UnifiedSessionFSAdapter | None = None,
) -> str:
    """Apply text edit using session-aware unified adapter."""
    if not session_id:
        raise ValueError("session_id is required")

    active_adapter = _build_adapter(session_manager, adapter)
    read_result = active_adapter.read_text(session_id, file_path)
    new_content = replace_content(
        read_result.content,
        old_string,
        new_string,
        replace_all,
    )
    active_adapter.write_text(session_id, file_path, new_content)
    return "Edit applied successfully."


def register_edit(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    @mcp.tool(
        name="edit",
        description=(
            "Performs exact string replacements in files.\n\n"
            "Usage:\n"
            "- You must use your `read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.\n"
            "- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.\n"
            "- ALWAYS prefer editing existing files. NEVER write new files unless explicitly required.\n"
            '- The edit will FAIL if `old_string` is not found in the file with an error "old_string not found in content".\n'
            '- The edit will FAIL if `old_string` is found multiple times in the file with an error "old_string found multiple times and requires more code context to uniquely identify the intended match". Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.\n'
            "- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."
        ),
    )
    async def edit(
        session_id: str | None = Field(
            default=None,
            description="Session ID for session-scoped edit operations",
        ),
        file_path: str = Field(description=get_path_description()),
        old_string: str = Field(description="The text to replace"),
        new_string: str = Field(
            description="The text to replace it with (must be different from old_string)"
        ),
        replace_all: bool | None = Field(
            default=False,
            description="Replace all occurrences of old_string (default false)",
        ),
    ) -> str:
        """编辑文件内容"""
        try:
            return apply_edit_with_session(
                session_id=session_id,
                file_path=file_path,
                old_string=old_string,
                new_string=new_string,
                replace_all=replace_all or False,
                session_manager=session_manager,
            )
        except Exception as e:
            raise ValueError(f"Error editing file: {e}") from e
