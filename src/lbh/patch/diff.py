from __future__ import annotations

import re
from pathlib import Path

from lbh.core.config import Config
from lbh.core.models import DiffValidationResult
from lbh.core.paths import PathSecurityError, normalize_relpath, resolve_repo_path

DIFF_GIT_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)$", re.M)
FILE_HEADER_RE = re.compile(r"^(---|\+\+\+)\s+(.*)$", re.M)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def modified_paths(diff: str) -> tuple[list[str], list[str], list[str]]:
    modified: list[str] = []
    new_files: list[str] = []
    deleted_files: list[str] = []
    current: tuple[str, str] | None = None
    for line in diff.splitlines():
        m = DIFF_GIT_RE.match(line)
        if m:
            a = normalize_relpath(m.group(1))
            b = normalize_relpath(m.group(2))
            current = (a, b)
            if b not in modified:
                modified.append(b)
            continue
        if line.startswith("new file mode") and current:
            if current[1] not in new_files:
                new_files.append(current[1])
        if line.startswith("deleted file mode") and current:
            if current[0] not in deleted_files:
                deleted_files.append(current[0])
    return modified, new_files, deleted_files



def _changed_old_line_ranges(diff: str) -> dict[str, list[tuple[int, int]]]:
    ranges_by_path: dict[str, list[tuple[int, int]]] = {}
    current_path: str | None = None
    old_line: int | None = None
    changed_start: int | None = None
    changed_end: int | None = None

    def flush_changed_range() -> None:
        nonlocal changed_start, changed_end
        if current_path is not None and changed_start is not None and changed_end is not None:
            ranges_by_path.setdefault(current_path, []).append((changed_start, changed_end))
        changed_start = None
        changed_end = None

    for line in diff.splitlines():
        m = DIFF_GIT_RE.match(line)
        if m:
            flush_changed_range()
            current_path = normalize_relpath(m.group(2))
            old_line = None
            continue
        if current_path is None:
            continue
        hunk = HUNK_RE.match(line)
        if hunk:
            flush_changed_range()
            old_line = int(hunk.group(1))
            continue
        if old_line is None:
            continue
        if line.startswith("-") and not line.startswith("---"):
            if changed_start is None:
                changed_start = old_line
            changed_end = old_line
            old_line += 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if changed_start is None:
                anchor = old_line - 1 if old_line > 1 else old_line
                changed_start = anchor
                changed_end = anchor
            continue
        flush_changed_range()
        if line.startswith(" "):
            old_line += 1
    flush_changed_range()
    return ranges_by_path


def _read_ranges(read_entry: object) -> list[tuple[int, int]]:
    if not isinstance(read_entry, dict):
        return []
    ranges: list[tuple[int, int]] = []
    for item in read_entry.get("ranges", []):
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        if isinstance(start, int) and isinstance(end, int) and start >= 1 and end >= start:
            ranges.append((start, end))
    return ranges


def _range_is_read(start: int, end: int, read_ranges: list[tuple[int, int]]) -> bool:
    return any(read_start <= start and end <= read_end for read_start, read_end in read_ranges)


def validate_diff(diff: str, repo_root: Path, config: Config, read_files: dict[str, object] | None = None) -> DiffValidationResult:
    result = DiffValidationResult(ok=True)
    if not diff.strip():
        result.ok = False
        result.errors.append("empty diff")
        return result
    if "diff --git " not in diff:
        result.ok = False
        result.errors.append("missing diff --git header")
        return result
    if "GIT binary patch" in diff or "Binary files " in diff:
        result.ok = False
        result.errors.append("binary patch is not allowed")
        return result

    read_files = read_files or {}
    try:
        modified, new_files, deleted_files = modified_paths(diff)
        changed_ranges = _changed_old_line_ranges(diff)
    except PathSecurityError as exc:
        result.ok = False
        result.errors.append(str(exc))
        return result

    result.modified_files = modified
    result.new_files = new_files
    result.deleted_files = deleted_files

    for path in modified:
        try:
            resolve_repo_path(repo_root, path)
        except PathSecurityError as exc:
            result.ok = False
            result.errors.append(str(exc))
            continue
        if config.is_excluded(path):
            result.ok = False
            result.errors.append(f"diff modifies excluded path: {path}")
        if config.require_read_before_modify:
            is_new = path in new_files and config.allow_new_files_without_read
            if is_new:
                continue
            if path not in read_files:
                result.ok = False
                result.errors.append(f"diff modifies file that was not READ in this session: {path}")
                continue
            read_ranges = _read_ranges(read_files[path])
            if not read_ranges:
                result.ok = False
                result.errors.append(f"diff modifies file with no READ ranges in this session: {path}")
                continue
            for start, end in changed_ranges.get(path, []):
                if not _range_is_read(start, end, read_ranges):
                    result.ok = False
                    result.errors.append(f"diff modifies unread lines in this session: {path}:{start}-{end}")

    # Validate ---/+++ headers too. /dev/null is allowed for create/delete.
    for prefix, raw_path in FILE_HEADER_RE.findall(diff):
        raw_path = raw_path.strip()
        if raw_path == "/dev/null":
            continue
        try:
            normalize_relpath(raw_path)
        except PathSecurityError as exc:
            result.ok = False
            result.errors.append(f"invalid {prefix} header path: {raw_path}: {exc}")

    return result
