from __future__ import annotations

import subprocess
from pathlib import Path


class GitApplyError(RuntimeError):
    pass


def git_apply_check(repo_root: Path, diff_path: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", "apply", "--check", str(diff_path)],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return proc.returncode == 0, proc.stdout


def git_apply(repo_root: Path, diff_path: Path) -> str:
    proc = subprocess.run(
        ["git", "apply", "--whitespace=fix", str(diff_path)],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise GitApplyError(proc.stdout)
    return proc.stdout
