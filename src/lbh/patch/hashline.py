from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from lbh.core.fs import read_text, short_block_hash, short_line_hash
from lbh.core.models import HashLinePatchEdit
from lbh.core.paths import normalize_relpath, resolve_repo_path


class HashLinePatchError(ValueError):
    pass


@dataclass(frozen=True)
class MaterializedHashLinePatch:
    diff: str
    modified_files: list[str]


def materialize_hashline_patch(repo_root: Path, edits: list[HashLinePatchEdit]) -> MaterializedHashLinePatch:
    if not edits:
        raise HashLinePatchError("hashline patch contained no edits")

    grouped: dict[str, list[HashLinePatchEdit]] = {}
    for edit in edits:
        rel = normalize_relpath(edit.path)
        grouped.setdefault(rel, []).append(
            HashLinePatchEdit(
                path=rel,
                start_line=edit.start_line,
                start_hash=edit.start_hash,
                end_line=edit.end_line,
                end_hash=edit.end_hash,
                new=edit.new,
                block_hash=edit.block_hash,
                old=edit.old,
            )
        )

    diff_parts: list[str] = []
    modified_files: list[str] = []

    for rel, file_edits in grouped.items():
        path = resolve_repo_path(repo_root, rel)
        if not path.exists() or not path.is_file():
            raise HashLinePatchError(f"target file not found: {rel}")

        original_text = read_text(path, max_chars=None)
        newline = _detect_newline(original_text)
        original_lines = original_text.splitlines()
        updated_lines = list(original_lines)

        for edit in sorted(file_edits, key=lambda item: item.start_line, reverse=True):
            _validate_edit(updated_lines, edit)
            start_idx = edit.start_line - 1
            end_idx = edit.end_line
            replacement_lines = edit.new.splitlines()
            updated_lines[start_idx:end_idx] = replacement_lines

        if updated_lines == original_lines:
            continue

        updated_text = newline.join(updated_lines)
        if original_text.endswith(("\n", "\r\n")) and not updated_text.endswith(newline):
            updated_text += newline

        unified = list(
            difflib.unified_diff(
                original_lines,
                updated_lines,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
            )
        )
        if not unified:
            continue

        diff_parts.append(f"diff --git a/{rel} b/{rel}")
        diff_parts.extend(unified)
        modified_files.append(rel)

    if not diff_parts:
        raise HashLinePatchError("hashline patch produced no file changes")

    return MaterializedHashLinePatch(diff="\n".join(diff_parts) + "\n", modified_files=modified_files)


def _validate_edit(current_lines: list[str], edit: HashLinePatchEdit) -> None:
    if edit.start_line < 1 or edit.end_line < edit.start_line:
        raise HashLinePatchError(f"invalid line span for {edit.path}: {edit.start_line}-{edit.end_line}")
    if edit.end_line > len(current_lines):
        raise HashLinePatchError(f"line span out of range for {edit.path}: {edit.start_line}-{edit.end_line}")

    start_line = current_lines[edit.start_line - 1]
    end_line = current_lines[edit.end_line - 1]
    if short_line_hash(start_line) != edit.start_hash:
        raise HashLinePatchError(
            f"start hash mismatch for {edit.path}:{edit.start_line} expected {edit.start_hash}"
        )
    if short_line_hash(end_line) != edit.end_hash:
        raise HashLinePatchError(
            f"end hash mismatch for {edit.path}:{edit.end_line} expected {edit.end_hash}"
        )

    current_block = "\n".join(current_lines[edit.start_line - 1 : edit.end_line])
    if edit.block_hash and short_block_hash(current_block) != edit.block_hash:
        raise HashLinePatchError(
            f"block hash mismatch for {edit.path}:{edit.start_line}-{edit.end_line} expected {edit.block_hash}"
        )

    if edit.old and current_block != edit.old:
        raise HashLinePatchError(
            f"old text mismatch for {edit.path}:{edit.start_line}-{edit.end_line}"
        )


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    return "\n"
