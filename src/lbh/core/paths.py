from __future__ import annotations

import os
from pathlib import Path


class PathSecurityError(ValueError):
    pass


def find_repo_root(start: Path | None = None) -> Path:
    """Find the current project root.

    Preference order:
    1. nearest parent containing .git
    2. nearest parent containing .lbh
    3. current working directory
    """
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / ".git").exists():
            return parent
    for parent in [cur, *cur.parents]:
        if (parent / ".lbh").exists():
            return parent
    return cur


def lbh_dir(repo_root: Path) -> Path:
    return repo_root / ".lbh"


def index_dir(repo_root: Path) -> Path:
    return lbh_dir(repo_root) / "index"


def sessions_dir(repo_root: Path) -> Path:
    return lbh_dir(repo_root) / "sessions"


def config_path(repo_root: Path) -> Path:
    return lbh_dir(repo_root) / "config.toml"


def normalize_relpath(path: str | Path) -> str:
    s = str(path).replace("\\", "/").strip()
    if not s:
        raise PathSecurityError("empty path")
    if s.startswith("a/") or s.startswith("b/"):
        s = s[2:]
    if s.startswith("./"):
        s = s[2:]
    p = Path(s)
    if p.is_absolute():
        raise PathSecurityError(f"absolute path is not allowed: {s}")
    parts = p.parts
    if any(part == ".." for part in parts):
        raise PathSecurityError(f"path traversal is not allowed: {s}")
    if any(part == "" for part in parts):
        raise PathSecurityError(f"invalid path: {s}")
    return "/".join(parts)


def resolve_repo_path(repo_root: Path, rel_path: str | Path) -> Path:
    rel = normalize_relpath(rel_path)
    target = (repo_root / rel).resolve()
    root = repo_root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PathSecurityError(f"path escapes repository: {rel}") from exc
    return target


def to_repo_rel(repo_root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise PathSecurityError(f"path is outside repo: {path}") from exc
