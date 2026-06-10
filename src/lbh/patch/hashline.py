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
                create=edit.create,
            )
        )

    diff_parts: list[str] = []
    modified_files: list[str] = []

    for rel, file_edits in grouped.items():
        path = resolve_repo_path(repo_root, rel)
        create_diff = _materialize_create_file(rel, path, file_edits)
        if create_diff is not None:
            diff_parts.extend(create_diff)
            modified_files.append(rel)
            continue

        existing_diff = _materialize_existing_file(rel, path, file_edits)
        if existing_diff is None:
            continue

        diff_parts.extend(existing_diff)
        modified_files.append(rel)

    if not diff_parts:
        raise HashLinePatchError("hashline patch produced no file changes")

    return MaterializedHashLinePatch(diff="\n".join(diff_parts) + "\n", modified_files=modified_files)


def _validate_create_edit(edit: HashLinePatchEdit) -> None:
    if edit.start_line or edit.end_line or edit.start_hash or edit.end_hash:
        raise HashLinePatchError(f"new file creation edit for {edit.path} must not include line anchors")
    if edit.old or edit.block_hash:
        raise HashLinePatchError(f"new file creation edit for {edit.path} must not include old or block_hash")


def _materialize_create_file(
    rel: str,
    path: Path,
    file_edits: list[HashLinePatchEdit],
) -> list[str] | None:
    create_edits = [edit for edit in file_edits if edit.create]
    if not create_edits:
        return None
    if len(file_edits) != 1:
        raise HashLinePatchError(f"new file creation for {rel} must be a single edit")
    edit = create_edits[0]
    if path.exists():
        raise HashLinePatchError(f"target file already exists: {rel}")
    _validate_create_edit(edit)
    return _build_create_file_diff(rel, edit)


def _build_create_file_diff(rel: str, edit: HashLinePatchEdit) -> list[str]:
    new_lines = edit.new.splitlines()
    unified = list(
        difflib.unified_diff(
            [],
            new_lines,
            fromfile="/dev/null",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )

    diff_lines = [f"diff --git a/{rel} b/{rel}", "new file mode 100644"]
    if unified:
        diff_lines.extend(unified)
    else:
        diff_lines.extend(["--- /dev/null", f"+++ b/{rel}"])
    return diff_lines


def _materialize_existing_file(
    rel: str,
    path: Path,
    file_edits: list[HashLinePatchEdit],
) -> list[str] | None:
    if not path.exists() or not path.is_file():
        raise HashLinePatchError(f"target file not found: {rel}")

    original_text = read_text(path, max_chars=None)
    newline = _detect_newline(original_text)
    original_lines = original_text.splitlines()
    updated_lines = list(original_lines)

    for edit in sorted(file_edits, key=lambda item: item.start_line, reverse=True):
        _validate_existing_span(updated_lines, edit)
        _apply_replacement(updated_lines, edit)

    if updated_lines == original_lines:
        return None

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
        return None

    return [f"diff --git a/{rel} b/{rel}", *unified]


def _validate_existing_span(current_lines: list[str], edit: HashLinePatchEdit) -> None:
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


def _apply_replacement(current_lines: list[str], edit: HashLinePatchEdit) -> None:
    start_idx = edit.start_line - 1
    end_idx = edit.end_line
    current_lines[start_idx:end_idx] = edit.new.splitlines()


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    return "\n"
