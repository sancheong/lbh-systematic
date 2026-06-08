from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lbh.context.packer import ContextPacker
from lbh.core.config import Config
from lbh.indexer.builder import RepoIndexer
from lbh.patch.apply import git_apply, git_apply_check
from lbh.patch.candidate import (
    candidate_paths,
    next_candidate_index,
    render_candidate_critique,
    render_repair_prompt,
    validate_candidate,
)
from lbh.patch.diff import validate_diff
from lbh.protocol.parser import extract_diff, parse_tool_requests, strip_diff_payloads
from lbh.protocol.tools import ToolExecutor
from lbh.search.ranker import SearchRanker
from lbh.session.manager import SessionManager


@dataclass(frozen=True)
class AskResult:
    session_root: Path
    initial_prompt: Path


@dataclass
class ResponseOutcome:
    kind: str
    return_code: int
    context_append: Path | None = None
    candidate: Path | None = None
    validation_path: Path | None = None
    critique_path: Path | None = None
    repair_prompt_path: Path | None = None
    patch_path: Path | None = None
    modified_files: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class ApplyOutcome:
    ok: bool
    return_code: int
    output: str = ""
    validation_errors: list[str] = field(default_factory=list)


def rebuild_index(repo: Path, *, json_mode: bool = False) -> dict[str, int]:
    stats = RepoIndexer(repo, Config.load(repo)).rebuild()
    if json_mode:
        return stats
    return stats


def ask_request(repo: Path, request: str, *, limit: int | None = None) -> AskResult:
    config = Config.load(repo)
    ranked = SearchRanker(repo).rank(request, limit=limit or config.initial_file_limit)
    manager = SessionManager(repo)
    session = manager.create(request, ranked=[item.__dict__ for item in ranked])
    prompt = ContextPacker(repo, config).build_initial_prompt(request, ranked)
    session.initial_prompt.write_text(prompt, encoding="utf-8")
    return AskResult(session_root=session.root, initial_prompt=session.initial_prompt)


def create_session_for_request(
    repo: Path,
    request: str,
    *,
    config: Config | None = None,
    limit: int | None = None,
) -> tuple[Path, Path]:
    if config is not None:
        ranked = SearchRanker(repo).rank(request, limit=limit or config.initial_file_limit)
        manager = SessionManager(repo)
        session = manager.create(request, ranked=[item.__dict__ for item in ranked])
        prompt = ContextPacker(repo, config).build_initial_prompt(request, ranked)
        session.initial_prompt.write_text(prompt, encoding="utf-8")
        return session.root, session.initial_prompt
    result = ask_request(repo, request, limit=limit)
    return result.session_root, result.initial_prompt


def process_response_file(repo: Path, session_root: Path, response_file: Path) -> ResponseOutcome:
    config = Config.load(repo)
    manager = SessionManager(repo)
    raw = response_file.read_text(encoding="utf-8")
    manager.append_event(session_root, {"type": "model_response", "file": str(response_file)})

    diff = extract_diff(raw)
    non_diff_raw = strip_diff_payloads(raw)
    requests = parse_tool_requests(non_diff_raw)

    if requests and diff:
        return ResponseOutcome(
            kind="error",
            return_code=2,
            error_message="Response contains both tool requests and diff. Please provide only one kind of response.",
        )

    if requests:
        executor = ToolExecutor(repo, config, session_root)
        append_text = executor.execute(requests)
        out = manager.next_context_append_path(session_root)
        out.write_text(append_text, encoding="utf-8")
        manager.append_event(session_root, {"type": "context_append", "file": out.name, "request_count": len(requests)})
        return ResponseOutcome(kind="context_append", return_code=0, context_append=out)

    if diff:
        manifest = manager.load_manifest(session_root)
        session_paths = manager.paths(session_root)
        candidate_index = next_candidate_index(session_root)
        paths = candidate_paths(session_root, candidate_index)
        paths.diff.write_text(diff, encoding="utf-8")

        candidate_rel = paths.diff.relative_to(session_root).as_posix()
        validation = validate_candidate(
            diff=diff,
            raw_response=raw,
            candidate=candidate_rel,
            candidate_path=paths.diff,
            repo_root=repo,
            config=config,
            read_files=manifest.get("read_files", {}),
        )

        manifest["latest_candidate"] = candidate_rel
        if validation.ok:
            validation.promoted_to_patch = True
            session_paths.patch.write_text(diff, encoding="utf-8")
            manifest["patch"] = {
                "path": session_paths.patch.name,
                "source_candidate": candidate_rel,
                "validation": validation.to_dict(),
            }
        paths.validation.write_text(json.dumps(validation.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        paths.critique.write_text(render_candidate_critique(validation), encoding="utf-8")
        paths.repair_prompt.write_text(render_repair_prompt(validation), encoding="utf-8")
        manifest.setdefault("candidates", []).append(
            {
                "path": candidate_rel,
                "validation": paths.validation.relative_to(session_root).as_posix(),
                "critique": paths.critique.relative_to(session_root).as_posix(),
                "repair_prompt": paths.repair_prompt.relative_to(session_root).as_posix(),
                "ok": validation.ok,
                "promoted_to_patch": validation.promoted_to_patch,
            }
        )
        manager.write_manifest(session_root, manifest)
        manager.append_event(
            session_root,
            {
                "type": "candidate_patch",
                "file": candidate_rel,
                "ok": validation.ok,
                "promoted_to_patch": validation.promoted_to_patch,
            },
        )
        return ResponseOutcome(
            kind="candidate_ok" if validation.ok else "candidate_failed",
            return_code=0 if validation.ok else 3,
            candidate=paths.diff,
            validation_path=paths.validation,
            critique_path=paths.critique,
            repair_prompt_path=paths.repair_prompt,
            patch_path=session_paths.patch if validation.ok else None,
            modified_files=list(validation.modified_files),
        )

    return ResponseOutcome(
        kind="none",
        return_code=1,
        error_message="No lbh-tool request or diff found in response.",
    )


def apply_patch_file(
    repo: Path,
    patch_path: Path,
    *,
    session_root: Path | None = None,
    check: bool = False,
    yes: bool = False,
) -> ApplyOutcome:
    config = Config.load(repo)
    read_files = {}
    if session_root is not None:
        read_files = SessionManager(repo).load_manifest(session_root).get("read_files", {})
    validation = validate_diff(patch_path.read_text(encoding="utf-8"), repo, config, read_files=read_files)
    if not validation.ok:
        return ApplyOutcome(ok=False, return_code=2, validation_errors=list(validation.errors))

    ok, output = git_apply_check(repo, patch_path)
    if not ok:
        return ApplyOutcome(ok=False, return_code=3, output=output)
    if check:
        return ApplyOutcome(ok=True, return_code=0, output="git apply --check passed")
    if not yes:
        return ApplyOutcome(ok=True, return_code=0, output="Not applying because --yes was not provided.")
    output = git_apply(repo, patch_path)
    return ApplyOutcome(ok=True, return_code=0, output=output.strip() or "Patch applied")
