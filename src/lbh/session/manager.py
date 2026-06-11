from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lbh.core.models import PlanArtifactPaths, SessionPaths
from lbh.core.paths import lbh_dir, sessions_dir


def slugify(text: str, limit: int = 40) -> str:
    text = re.sub(r"[^A-Za-z0-9가-힣_-]+", "-", text).strip("-")
    if not text:
        text = "session"
    return text[:limit]


class SessionManager:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        sessions_dir(repo_root).mkdir(parents=True, exist_ok=True)
        self.plans_root.mkdir(parents=True, exist_ok=True)

    @property
    def plans_root(self) -> Path:
        return lbh_dir(self.repo_root) / "plans"

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
            "plan": None,
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
        self.register_read_files(session_root, {path: {"sha256": sha256, "ranges": ranges}})

    def register_read_files(self, session_root: str | Path, read_files: dict[str, Any]) -> None:
        manifest = self.load_manifest(session_root)
        entries = manifest.setdefault("read_files", {})
        for path, read_entry in read_files.items():
            entry = entries.setdefault(path, {"sha256": read_entry.get("sha256", ""), "ranges": []})
            if "sha256" in read_entry:
                entry["sha256"] = read_entry["sha256"]
            entry.setdefault("ranges", []).extend(read_entry.get("ranges", []))
        self.write_manifest(session_root, manifest)

    def next_context_append_path(self, session_root: str | Path) -> Path:
        manifest = self.load_manifest(session_root)
        round_num = int(manifest.get("tool_round", 0)) + 1
        manifest["tool_round"] = round_num
        out = Path(session_root) / f"context_append_{round_num:03d}.md"
        manifest.setdefault("context_appends", []).append(out.name)
        self.write_manifest(session_root, manifest)
        return out

    def plan_artifact_paths(self, plan_id: str) -> PlanArtifactPaths:
        root = self.plans_root / plan_id
        return PlanArtifactPaths(
            root=root,
            immutable_prompts=root / "prompts",
            mutable_state=root / "state.json",
            summary=root / "summary.md",
            bootstrap_source=self.repo_root / "refactoring.md",
        )

    def create_plan_artifacts(self, session_root: str | Path, prompt_files: dict[str, str]) -> PlanArtifactPaths:
        manifest = self.load_manifest(session_root)
        plan_id = str(manifest["session_id"])
        paths = self.plan_artifact_paths(plan_id)
        existing_plan = manifest.get("plan")

        if existing_plan and paths.immutable_prompts.exists():
            paths.mutable_state.parent.mkdir(parents=True, exist_ok=True)
            if not paths.mutable_state.exists():
                paths.mutable_state.write_text(
                    json.dumps({"schema": "lbh.plan.state.v1", "status": "planned"}, indent=2),
                    encoding="utf-8",
                )
            if not paths.summary.exists():
                paths.summary.write_text("", encoding="utf-8")
            return paths

        paths.immutable_prompts.mkdir(parents=True, exist_ok=False)
        split_prompt_files: dict[str, str] = {}
        for name, text in prompt_files.items():
            if Path(name).name != name:
                raise ValueError(f"plan prompt file name must be relative and flat: {name}")
            split_prompt_files.update(self._split_plan_prompt(name, text))
        for name, text in split_prompt_files.items():
            (paths.immutable_prompts / name).write_text(text, encoding="utf-8")
        paths.mutable_state.write_text(json.dumps({"schema": "lbh.plan.state.v1", "status": "planned"}, indent=2), encoding="utf-8")
        paths.summary.write_text("", encoding="utf-8")
        plan_entry: dict[str, Any] = {
            "schema": "lbh.plan.v1",
            "plan_id": plan_id,
            "root": paths.root.relative_to(self.repo_root).as_posix(),
            "immutable_prompts_dir": paths.immutable_prompts.relative_to(self.repo_root).as_posix(),
            "state": paths.mutable_state.relative_to(self.repo_root).as_posix(),
            "summary": paths.summary.relative_to(self.repo_root).as_posix(),
            "prompt_files": [
                (paths.immutable_prompts / name).relative_to(self.repo_root).as_posix()
                for name in split_prompt_files
            ],
        }
        if paths.bootstrap_source and paths.bootstrap_source.exists():
            plan_entry["bootstrap_source"] = paths.bootstrap_source.relative_to(self.repo_root).as_posix()
            plan_entry["bootstrap_temporary"] = True
        manifest["plan"] = plan_entry
        self.write_manifest(session_root, manifest)
        return paths

    def _split_plan_prompt(self, name: str, text: str) -> dict[str, str]:
        stem = Path(name).stem or "task_prompt"
        chunks = [chunk.strip() for chunk in text.split("\n---\n") if chunk.strip()]
        if not chunks:
            chunks = [text]
        if len(chunks) == 1:
            return {f"{stem}_001.md": chunks[0]}
        return {f"{stem}_{index:03d}.md": chunk for index, chunk in enumerate(chunks, start=1)}
