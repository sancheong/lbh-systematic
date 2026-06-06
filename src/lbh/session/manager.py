from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lbh.core.models import SessionPaths
from lbh.core.paths import sessions_dir


def slugify(text: str, limit: int = 40) -> str:
    text = re.sub(r"[^A-Za-z0-9가-힣_-]+", "-", text).strip("-")
    if not text:
        text = "session"
    return text[:limit]


class SessionManager:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        sessions_dir(repo_root).mkdir(parents=True, exist_ok=True)

    def create(self, user_request: str, ranked: list[dict[str, Any]] | None = None) -> SessionPaths:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        sid = f"{ts}-{slugify(user_request)}"
        root = sessions_dir(self.repo_root) / sid
        root.mkdir(parents=True, exist_ok=False)
        paths = self.paths(root)
        paths.request.write_text(user_request, encoding="utf-8")
        manifest = {
            "schema": "lbh.session.v1",
            "session_id": sid,
            "created_at": ts,
            "repo_root": str(self.repo_root),
            "user_request": user_request,
            "ranked_files": ranked or [],
            "read_files": {},
            "tool_round": 0,
            "context_appends": [],
            "latest_candidate": None,
            "candidates": [],
            "patch": None,
            "automation": None,
            "events": [],
        }
        self.write_manifest(paths.root, manifest)
        paths.transcript.write_text("", encoding="utf-8")
        return paths

    def paths(self, session_root: str | Path) -> SessionPaths:
        root = Path(session_root)
        return SessionPaths(
            root=root,
            request=root / "request.txt",
            initial_prompt=root / "initial_prompt.md",
            manifest=root / "manifest.json",
            transcript=root / "transcript.jsonl",
            patch=root / "patch.diff",
            candidates=root / "candidates",
        )

    def load_manifest(self, session_root: str | Path) -> dict[str, Any]:
        path = Path(session_root) / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def write_manifest(self, session_root: str | Path, manifest: dict[str, Any]) -> None:
        path = Path(session_root) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def append_event(self, session_root: str | Path, event: dict[str, Any]) -> None:
        manifest = self.load_manifest(session_root)
        manifest.setdefault("events", []).append(event)
        self.write_manifest(session_root, manifest)
        transcript = Path(session_root) / "transcript.jsonl"
        with transcript.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def register_read_file(self, session_root: str | Path, path: str, sha256: str, ranges: list[dict[str, int]]) -> None:
        manifest = self.load_manifest(session_root)
        entry = manifest.setdefault("read_files", {}).setdefault(path, {"sha256": sha256, "ranges": []})
        entry["sha256"] = sha256
        entry.setdefault("ranges", []).extend(ranges)
        self.write_manifest(session_root, manifest)

    def next_context_append_path(self, session_root: str | Path) -> Path:
        manifest = self.load_manifest(session_root)
        round_num = int(manifest.get("tool_round", 0)) + 1
        manifest["tool_round"] = round_num
        out = Path(session_root) / f"context_append_{round_num:03d}.md"
        manifest.setdefault("context_appends", []).append(out.name)
        self.write_manifest(session_root, manifest)
        return out
