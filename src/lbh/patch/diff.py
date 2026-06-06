from __future__ import annotations

import re
from pathlib import Path

from lbh.core.config import Config
from lbh.core.models import DiffValidationResult
from lbh.core.paths import PathSecurityError, normalize_relpath, resolve_repo_path

DIFF_GIT_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)$", re.M)
FILE_HEADER_RE = re.compile(r"^(---|\+\+\+)\s+(.*)$", re.M)


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
            if not is_new and path not in read_files:
                result.ok = False
                result.errors.append(f"diff modifies file that was not READ in this session: {path}")

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
