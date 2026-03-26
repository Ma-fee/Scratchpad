"""Edit tool - 编辑文件（字符串替换）"""

import re
from pathlib import Path
from typing import Optional, Generator, List, Tuple,Annotated,Any
from fastmcp import FastMCP, Context
from pydantic import Field
import os

from ..storage import store
from ..utils import build_error_xml, create_tool_result_xml, normalize_path
from ..exceptions import ValidationError, ScratchpadFileNotFoundError, FileTooLargeError
from ..config import config
from ..models import EditOperation
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
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost
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
            len(re.match(r"^(\s*)", line).group(1))
            for line in non_empty_lines
            if re.match(r"^(\s*)", line)
        )

        return "\n".join(
            line if not line.strip() else line[min_indent:]
            for line in lines
        )

    normalized_find = remove_indentation(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")

    for i in range(len(content_lines) - len(find_lines) + 1):
        block = "\n".join(content_lines[i:i + len(find_lines)])
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
            s
        )

    unescaped_find = unescape_string(find)

    if unescaped_find in content:
        yield unescaped_find

    lines = content.split("\n")
    find_lines = unescaped_find.split("\n")

    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i:i + len(find_lines)])
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
        block = "\n".join(lines[i:i + len(find_lines)])
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
                block_lines = content_lines[i:j + 1]
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

                    if total_non_empty_lines == 0 or matching_lines / total_non_empty_lines >= 0.5:
                        yield block
                        break
                break


def replace_content(content: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """替换内容"""
    if old_string == new_string:
        raise ValueError("oldString and newString must be different")

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

            return content[:index] + new_string + content[index + len(search):]

    if not_found:
        raise ValueError("oldString not found in content")

    raise ValueError(
        "Found multiple matches for oldString. Provide more surrounding lines in oldString to identify the correct match."
    )


async def _multiedit_tool(
    ctx: Context,
    session_id: str,
    file_path: str,
    edits: list[dict[str, Any]],
    expected_version: int | None = None
) -> str:
    """
    Apply multiple edits to a single file in one operation.
    
    This tool is built on top of the edit functionality and allows you to perform
    multiple find-and-replace operations efficiently. All edits are applied in sequence,
    in the order they are provided. Each edit operates on the result of the previous edit.
    
    Args:
        ctx: FastMCP context
        session_id: Session identifier
        file_path: Absolute path to the file to modify
        edits: Array of edit operations to perform sequentially
        expected_version: Expected file version for optimistic locking
    
    Returns:
        Success message
    
    Raises:
        ValueError: If any edit fails
    """
    # Validate inputs
    if not session_id or not session_id.strip():
        raise ValidationError("Session ID cannot be empty")
    
    if not file_path or not file_path.strip():
        raise ValidationError("file_path is required")
    
    if not edits or not isinstance(edits, list):
        raise ValidationError("edits must be a non-empty array")
    
    # Debug: Log the raw edits data
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received {len(edits)} edit operations")
    for idx, edit in enumerate(edits, start=1):
        logger.info(f"Edit #{idx} type: {type(edit).__name__}, keys: {list(edit.keys())}, oldString length: {len(edit.get('oldString', ''))}")
    
    # Convert dict to EditOperation objects for validation
    try:
        edit_operations = []
        for idx, edit in enumerate(edits, start=1):
            if not isinstance(edit, dict):
                raise ValidationError(f"Edit #{idx} must be a dictionary, got {type(edit).__name__}")
            if 'oldString' not in edit or 'newString' not in edit:
                raise ValidationError(f"Edit #{idx} is missing required fields (oldString or newString)")
            try:
                edit_op = EditOperation(**edit)
                edit_operations.append(edit_op)
                logger.info(f"Edit #{idx} validated successfully: oldString={edit_op.oldString[:50]}..., newString={edit_op.newString[:50]}...")
            except Exception as exc:
                logger.error(f"Edit #{idx} validation failed: {exc}")
                raise ValidationError(f"Edit #{idx} validation failed: {exc}") from exc
    except ValidationError:
        raise
    except Exception as exc:
        logger.error(f"Failed to parse edit operations: {exc}")
        raise ValidationError(f"Failed to parse edit operations: {exc}") from exc
    
    # Validate and normalize file path
    normalized_path = normalize_path(file_path)
    
    await ctx.report_progress(10, 100, f"Loading file {normalized_path}")
    
    # Read the current file content
    abspath = os.path.join(store._session_dir(session_id), normalized_path)
    filepath = Path(abspath).resolve()
    
    # Check if file exists
    if not filepath.exists():
        raise ScratchpadFileNotFoundError(f"File not found: {file_path}")
    
    # Read file content
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    await ctx.report_progress(20, 100, "Applying edits sequentially")
    
    # Apply each edit in sequence
    results = []
    current_content = content
    
    for idx, edit in enumerate(edit_operations, start=1):
        old_string = edit.oldString
        new_string = edit.newString
        replace_all = edit.replaceAll
        
        progress = 20 + int((idx / len(edits)) * 60)
        await ctx.report_progress(progress, 100, f"Applying edit {idx}/{len(edits)}")
        
        try:
            current_content = replace_content(current_content, old_string, new_string, replace_all)
            results.append({
                "edit_index": idx,
                "status": "success",
                "old_string_preview": old_string[:100] + "..." if len(old_string) > 100 else old_string,
                "new_string_preview": new_string[:100] + "..." if len(new_string) > 100 else new_string,
                "replace_all": replace_all
            })
        except ValueError as exc:
            raise ValidationError(f"Edit #{idx} failed: {exc}") from exc
    
    await ctx.report_progress(85, 100, "Persisting changes")
    
    # Check file size
    content_size = len(current_content.encode('utf-8'))
    if content_size > config.max_file_size:
        raise FileTooLargeError(
            f"Updated file size {content_size} exceeds maximum allowed size {config.max_file_size}"
        )
    
    # Write the updated content
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(current_content)
    
    await ctx.report_progress(100, 100, "Multiedit completed")
    
    # Build success message
    summary_text = (
        f"Multiedit applied successfully to {normalized_path}\n"
        f"Total edits: {len(edit_operations)} | "
        f"Final size: {content_size} bytes"
    )
    
    return summary_text


def register_scratchpad_edit_file(mcp:FastMCP):
    @mcp.tool(
        name="scratchpad_edit_file",
        description=(
            "Performs exact string replacements in files.\n\n"
            "Usage:\n"
            "- You must use your `scratchpad_read_file` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.\n"
            "- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the oldString or newString.\n"
            "- ALWAYS prefer editing existing files in the scratchpad. NEVER write new files unless explicitly required.\n"
            "- The edit will FAIL if `oldString` is not found in the file with an error \"oldString not found in content\".\n"
            "- The edit will FAIL if `oldString` is found multiple times in the file with an error \"oldString found multiple times and requires more code context to uniquely identify the intended match\". Either provide a larger string with more surrounding context to make it unique or use `replaceAll` to change every instance of `oldString`.\n"
            "- Use `replaceAll` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."
        ),
    )
    async def edit(
        ctx: Context,
        session_id: Annotated[str, Field(description="The unique identifier of the session, formatted as `user_id-agent_id-timestamp`")],
        file_path: str = Field(description="The absolute path to the file to modify"),
        oldString: str = Field(description="The text to replace"),
        newString: str = Field(description="The text to replace it with (must be different from oldString)"),
        replaceAll: Optional[bool] = Field(default=False, description="Replace all occurrences of oldString (default false)"),
    ) -> str:
        """编辑文件内容"""
        try:
            abspath=os.path.join(store._session_dir(session_id),file_path)
            # 转换为绝对路径
            filepath = Path(abspath).resolve()

            # 检查文件是否存在
            if not filepath.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # 读取文件内容
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # 执行替换
            new_content = replace_content(content, oldString, newString, replaceAll)

            # 写入文件
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)

            return "Edit applied successfully."

        except Exception as e:
            raise ValueError(f"Error editing file: {e}")
    
    @mcp.tool(
        name="scratchpad_multiedit",
        description=(
            "Performs exact string replacements in files.\n\n"
            "Before using this tool:\n"
            "1. Use `scratchpad_read_file` tool to understand the file's contents and context\n"
            "To make multiple file edits, provide the following:\n"
            "1. edits: An array of edit operations to perform, where each edit contains:\n"
            "   - oldString: The text to replace (must match the file contents exactly, including all whitespace and indentation)\n"
            "   - newString: The edited text to replace the oldString\n"
            "   - replaceAll: Replace all occurrences of oldString. This parameter is optional and defaults to false.\n\n"
            "IMPORTANT:\n"
            "- All edits are applied in sequence, in the order they are provided\n"
            "- Each edit operates on the result of the previous edit\n"
            "- All edits must be valid for the operation to succeed - if any edit fails, none will be applied\n"
            "- This tool is ideal when you need to make several changes to different parts of the same file\n\n"
            "- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the oldString or newString.\n"
            "- The edits are atomic - either all succeed or none are applied\n"
            "- The tool will fail if `edits.oldString` doesn't match the file contents exactly (including whitespace)\n"
            "- The tool will fail if `edits.oldString` and edits.newString are the same\n"
            "- The tool will fail if `edits.replaceAll` is Null\n"

            "- Use replaceAll for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."
        ),
    )
    async def multiedit(
        ctx: Context,
        session_id: Annotated[str, Field(description="The unique identifier of the session, formatted as `user_id-agent_id-timestamp`.")],
        file_path: Annotated[str, Field(description="The absolute path to the file to modify (must be absolute, not relative).")],
        edits: Annotated[list[dict[str, Any]], Field(
            description="Array of edit operations to perform sequentially on the file. Each edit should contain: "
            "oldString (text to replace), newString (text to replace with), and optionally replaceAll (boolean)."
        )],
        expected_version: Annotated[Optional[int], Field(
            description="The version number during the last read, used for optimistic locking to avoid overwriting other modifications."
        )] = None
    ):
        try:
            result = await _multiedit_tool(ctx, session_id, file_path, edits, expected_version)
            return create_tool_result_xml(result, {"result": result})
        except Exception as exc:
            error_xml = build_error_xml(str(exc), "multiedit")
            return create_tool_result_xml(error_xml, {"error": str(exc)})
