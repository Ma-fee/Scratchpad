from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .exceptions import ValidationError
from .utils import normalize_path

HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


@dataclass(slots=True)
class UnifiedHunk:
    """Container for a single unified diff hunk."""

    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[str]


@dataclass(slots=True)
class ChunkSummary:
    """Represents an added/removed chunk summary for structured output."""

    start_line: int
    end_line: int
    content: list[str]


@dataclass(slots=True)
class ApplyDiffOutcome:
    """Result of applying a diff to existing content."""

    new_content: str
    added_chunks: list[ChunkSummary]
    removed_chunks: list[ChunkSummary]
    lines_added: int
    lines_removed: int


def apply_unified_diff(
    diff_text: str, original_text: str, file_path: str
) -> ApplyDiffOutcome:
    """Apply a unified diff string to the given original text."""
    normalized_target = normalize_path(file_path)
    diff_target, hunks = _parse_unified_diff(diff_text)
    diff_target_normalized = normalize_path(diff_target)

    if diff_target_normalized != normalized_target:
        raise ValidationError(
            f"Diff header path '{diff_target}' does not match requested file '{file_path}'"
        )

    if not hunks:
        raise ValidationError("Diff does not contain any hunks")

    return _apply_hunks(original_text, hunks)


def _parse_unified_diff(diff_text: str) -> tuple[str, list[UnifiedHunk]]:
    if not diff_text or not diff_text.strip():
        raise ValidationError("Diff content cannot be empty")

    lines = diff_text.splitlines()
    old_path = None
    new_path = None
    hunks: list[UnifiedHunk] = []
    idx = 0
    header_seen = False

    while idx < len(lines):
        line = lines[idx]

        if line.startswith("diff --git "):
            if header_seen:
                raise ValidationError(
                    "apply_diff only supports a single file per request"
                )
            idx += 1
            continue

        if line.startswith("--- "):
            if header_seen:
                raise ValidationError("apply_diff only supports one file diff")
            old_path = _clean_header_path(line[4:].strip())
            idx += 1
            if idx >= len(lines) or not lines[idx].startswith("+++ "):
                raise ValidationError("Diff header missing matching +++ line")
            new_path = _clean_header_path(lines[idx][4:].strip())

            if old_path == "/dev/null" or new_path == "/dev/null":
                raise ValidationError(
                    "Diff cannot create or delete files via apply_diff"
                )

            header_seen = True
            idx += 1
            continue

        if line.startswith("@@ "):
            if not header_seen or not old_path or not new_path:
                raise ValidationError(
                    "Diff missing ---/+++ header before hunk definition"
                )
            match = HUNK_HEADER_RE.match(line)
            if not match:
                raise ValidationError(f"Invalid hunk header: {line}")
            old_start = int(match.group(1))
            old_len = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_len = int(match.group(4) or "1")

            idx += 1
            hunk_lines: list[str] = []
            while idx < len(lines):
                next_line = lines[idx]
                if next_line.startswith("@@ "):
                    break
                if next_line.startswith("diff --git ") or next_line.startswith("--- "):
                    raise ValidationError(
                        "apply_diff does not support multiple file hunks"
                    )
                hunk_lines.append(next_line)
                idx += 1

            hunks.append(
                UnifiedHunk(
                    old_start=old_start,
                    old_len=old_len,
                    new_start=new_start,
                    new_len=new_len,
                    lines=hunk_lines,
                )
            )
            continue

        idx += 1

    if not header_seen or not new_path:
        raise ValidationError("Diff must include ---/+++ headers for the target file")

    return new_path, hunks


def _clean_header_path(path: str) -> str:
    stripped = path.strip()
    if stripped.startswith("a/") or stripped.startswith("b/"):
        return stripped[2:]
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
        if stripped.startswith("a/") or stripped.startswith("b/"):
            stripped = stripped[2:]
    return stripped


def parse_change_line(lines: list[str]) -> dict:
    # 解析上下文行
    context_line = lines[0][1:].strip()

    old_lines = []
    new_lines = []
    is_end_of_file = False
    i = 0
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

    return {
        "old_lines": old_lines,
        "new_lines": new_lines,
        "change_context": context_line if context_line else None,
        "is_end_of_file": is_end_of_file if is_end_of_file else None,
    }


def _apply_hunks(original_text: str, hunks: Iterable[UnifiedHunk]) -> ApplyDiffOutcome:
    original_lines = original_text.splitlines()
    cursor = 0
    new_lines: list[str] = []
    added_chunks: list[ChunkSummary] = []
    removed_chunks: list[ChunkSummary] = []
    lines_added = 0
    lines_removed = 0
    new_file_has_trailing_newline = original_text.endswith("\n")

    for hunk in hunks:
        start_index = max(hunk.old_start - 1, 0)

        # chunk=parse_change_line(hunk.lines)
        # start_index=seek_sequence(original_lines,chunk[''],start_index)

        if start_index < cursor:
            raise ValidationError("Diff hunks overlap or are out of order")
        if start_index > len(original_lines):
            raise ValidationError("Diff references lines outside of file length")

        # Copy unchanged context before hunk
        new_lines.extend(original_lines[cursor:start_index])
        cursor = start_index

        add_buffer: list[str] = []
        add_start: int | None = None
        remove_buffer: list[str] = []
        remove_start: int | None = None
        last_op: str | None = None

        def flush_added() -> None:
            nonlocal add_buffer, add_start
            if add_start is not None and add_buffer:
                added_chunks.append(
                    ChunkSummary(
                        start_line=add_start,
                        end_line=add_start + len(add_buffer) - 1,
                        content=add_buffer.copy(),
                    )
                )
            add_buffer = []
            add_start = None

        def flush_removed() -> None:
            nonlocal remove_buffer, remove_start
            if remove_start is not None and remove_buffer:
                removed_chunks.append(
                    ChunkSummary(
                        start_line=remove_start,
                        end_line=remove_start + len(remove_buffer) - 1,
                        content=remove_buffer.copy(),
                    )
                )
            remove_buffer = []
            remove_start = None

        for raw_line in hunk.lines:
            if raw_line.startswith("\\ No newline at end of file"):
                if last_op == "+":
                    new_file_has_trailing_newline = False
                # if last_op == "-", it only indicates the old file lacked newline
                continue

            if not raw_line:
                raise ValidationError("Diff hunk contains empty line without prefix")

            op = raw_line[0]
            line_text = raw_line[1:]

            if op == " ":
                flush_added()
                flush_removed()
                if cursor >= len(original_lines):
                    raise ValidationError("Diff context exceeds file length")
                if original_lines[cursor] != line_text:
                    offset = max(0, cursor - 3)
                    limit = min(len(original_lines) - offset - 1, 10)
                    lines = original_lines[offset : offset + limit]
                    # 格式化输出
                    original_line_content = "\n".join(
                        f"{(i + offset + 1):05d}| {line}"
                        for i, line in enumerate(lines)
                    )
                    raise ValidationError(
                        f"Diff context mismatch at line {cursor + 1}: "
                        f"expected original line '{original_lines[cursor]}', got line '{line_text}'\n"
                        f"<suggest>The exact context from line {offset + 1} to line {offset + limit}:```\n{original_line_content}```\n\n"
                        f"you can fix the diff context by the exact context, or use `edit` to edit.</suggest>"
                    )
                new_lines.append(line_text)
                cursor += 1
                new_file_has_trailing_newline = True
            elif op == "-":
                flush_added()
                if cursor >= len(original_lines):
                    raise ValidationError("Diff removal exceeds file length")
                if original_lines[cursor] != line_text:
                    offset = max(0, cursor - 3)
                    limit = min(len(original_lines) - offset - 1, 10)
                    lines = original_lines[offset : offset + limit]
                    # 格式化输出
                    original_line_content = "\n".join(
                        f"{(i + offset + 1):05d}| {line}"
                        for i, line in enumerate(lines)
                    )

                    raise ValidationError(
                        f"Diff context mismatch at line {cursor + 1}: "
                        f"expected original line '{original_lines[cursor]}', got line '{line_text}'\n"
                        f"<suggest>The exact context from line {offset + 1} to line {offset + limit}:```\n{original_line_content}```\n\n"
                        f"you can fix the diff context by the exact context, or use `edit` to edit.</suggest>"
                    )
                if remove_start is None:
                    remove_start = cursor + 1
                remove_buffer.append(f"-{line_text}")
                cursor += 1
                lines_removed += 1
            elif op == "+":
                flush_removed()
                insertion_line_number = len(new_lines) + 1
                if add_start is None:
                    add_start = insertion_line_number
                new_lines.append(line_text)
                add_buffer.append(f"+{line_text}")
                lines_added += 1
                new_file_has_trailing_newline = True
            else:
                raise ValidationError(f"Unsupported diff line prefix '{op}'")

            last_op = op

        flush_added()
        flush_removed()

    # Append the rest of the original content after final hunk
    new_lines.extend(original_lines[cursor:])

    new_text = "\n".join(new_lines)
    if new_file_has_trailing_newline and new_lines:
        new_text = new_text + "\n"

    return ApplyDiffOutcome(
        new_content=new_text,
        added_chunks=added_chunks,
        removed_chunks=removed_chunks,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )
