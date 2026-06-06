from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

from lbh.core.config import Config
from lbh.core.fs import looks_binary
from lbh.core.paths import to_repo_rel


def _git_files(repo_root: Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _walk_files(repo_root: Path) -> list[str]:
    out: list[str] = []
    for path in repo_root.rglob("*"):
        if path.is_file():
            try:
                out.append(to_repo_rel(repo_root, path))
            except ValueError:
                continue
    return out


class FileScanner:
    def __init__(self, repo_root: Path, config: Config):
        self.repo_root = repo_root
        self.config = config

    def scan(self) -> list[str]:
        candidates = _git_files(self.repo_root) or _walk_files(self.repo_root)
        files: list[str] = []
        for rel in sorted(set(candidates)):
            rel = rel.replace("\\", "/")
            if self.config.is_excluded(rel):
                continue
            if not self.config.is_included(rel):
                continue
            path = self.repo_root / rel
            if not path.exists() or not path.is_file():
                continue
            try:
                if path.stat().st_size > self.config.max_file_bytes:
                    continue
                if looks_binary(path):
                    continue
            except OSError:
                continue
            files.append(rel)
        return files
