from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lbh.context.packer import ContextPacker
from lbh.core.config import Config
from lbh.core.models import CandidateIssue
from lbh.core.request_classification import RequestClassification, classify_patch_request
from lbh.core.fs import write_text_exact
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
from lbh.patch.hashline import HashLinePatchError, materialize_hashline_patch
from lbh.protocol.parser import (
    extract_diff,
    extract_hashline_patch,
    parse_tool_requests,
    strip_diff_payloads,
    strip_hashline_patch_payloads,
)
from lbh.protocol.tools import ToolExecutor
from lbh.search.ranker import SearchRanker
from lbh.session.manager import SessionManager
from lbh.validation.promotion import promote_candidate, write_promotion_result


@dataclass(frozen=True)
class AskResult:
    session_root: Path
    initial_prompt: Path
    request_classification: RequestClassification = field(default_factory=RequestClassification.small)


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
    request_classification = classify_patch_request(request, config)
    ranked = SearchRanker(repo).rank(request, limit=limit or config.initial_file_limit)
    manager = SessionManager(repo)
    session = manager.create(request, ranked=[item.__dict__ for item in ranked])
    packer = ContextPacker(repo, config)
    prompt = packer.build_initial_prompt(request, ranked)
    session.initial_prompt.write_text(prompt, encoding="utf-8")
    manager.register_read_files(session.root, packer.initial_read_files(ranked))
    if request_classification.is_broad_or_multi_component:
        manager.create_plan_artifacts(session.root, {"task_prompt.md": prompt})
    return AskResult(
        session_root=session.root,
        initial_prompt=session.initial_prompt,
        request_classification=request_classification,
    )


def create_session_for_request(
    repo: Path,
    request: str,
    *,
    config: Config | None = None,
    limit: int | None = None,
) -> tuple[Path, Path]:
    if config is not None:
        request_classification = classify_patch_request(request, config)
        ranked = SearchRanker(repo).rank(request, limit=limit or config.initial_file_limit)
        manager = SessionManager(repo)
        session = manager.create(request, ranked=[item.__dict__ for item in ranked])
        packer = ContextPacker(repo, config)
        prompt = packer.build_initial_prompt(request, ranked)
        session.initial_prompt.write_text(prompt, encoding="utf-8")
        manager.register_read_files(session.root, packer.initial_read_files(ranked))
        if request_classification.is_broad_or_multi_component:
            manager.create_plan_artifacts(session.root, {"task_prompt.md": prompt})
        return session.root, session.initial_prompt
    result = ask_request(repo, request, limit=limit)
    return result.session_root, result.initial_prompt


def create_session_for_prompt(
    repo: Path,
    prompt_text: str,
    *,
    request_label: str = "prompt file execution",
) -> tuple[Path, Path]:
    manager = SessionManager(repo)
    session = manager.create(request_label, ranked=[])
    session.initial_prompt.write_text(prompt_text, encoding="utf-8")
    return session.root, session.initial_prompt


def process_response_file(repo: Path, session_root: Path, response_file: Path) -> ResponseOutcome:
    config = Config.load(repo)
    manager = SessionManager(repo)
    raw = response_file.read_text(encoding="utf-8")
    manager.append_event(session_root, {"type": "model_response", "file": str(response_file)})

    diff = extract_diff(raw)
    hashline_patch = extract_hashline_patch(raw)
    source_mode = "diff"
    non_diff_raw = strip_hashline_patch_payloads(strip_diff_payloads(raw))
    requests = parse_tool_requests(non_diff_raw)

    kinds = sum(1 for item in (requests, diff, hashline_patch) if item)
    if kinds > 1:
        return ResponseOutcome(
            kind="error",
            return_code=2,
            error_message="Response contains multiple output modes. Please provide only one of lbh-tool, lbh-hashline-patch, or diff.",
        )

    if requests:
        executor = ToolExecutor(repo, config, session_root)
        append_text = executor.execute(requests)
        out = manager.next_context_append_path(session_root)
        out.write_text(append_text, encoding="utf-8")
        manager.append_event(session_root, {"type": "context_append", "file": out.name, "request_count": len(requests)})
        return ResponseOutcome(kind="context_append", return_code=0, context_append=out)

    if hashline_patch:
        try:
            materialized = materialize_hashline_patch(repo, hashline_patch)
            diff = materialized.diff
            source_mode = "hashline"
        except HashLinePatchError as exc:
            return ResponseOutcome(kind="error", return_code=2, error_message=str(exc))

    if diff:
        manifest = manager.load_manifest(session_root)
        session_paths = manager.paths(session_root)
        candidate_index = next_candidate_index(session_root)
        paths = candidate_paths(session_root, candidate_index)
        write_text_exact(paths.diff, diff)

        candidate_rel = paths.diff.relative_to(session_root).as_posix()
        validation = validate_candidate(
            diff=diff,
            raw_response=raw,
            candidate=candidate_rel,
            candidate_path=paths.diff,
            repo_root=repo,
            config=config,
            read_files=manifest.get("read_files", {}),
            source_mode=source_mode,
        )

        manifest["latest_candidate"] = candidate_rel
        promotion = promote_candidate(
            repo_root=repo,
            session_root=session_root,
            candidate_path=paths.diff,
            validation=validation,
            patch_path=session_paths.patch,
        )
        promotion_path = write_promotion_result(session_root, promotion)
        promotion_rel = promotion_path.relative_to(session_root).as_posix()
        if promotion.ok:
            validation.promoted_to_patch = True
        elif validation.structural_ok:
            validation.ok = False
            validation.errors.append(
                CandidateIssue(
                    kind=promotion.failed_check or "promotion_failed",
                    message=promotion.exact_stop_reason or promotion.status,
                )
            )
            validation.repair_instruction.append("Produce a complete replacement candidate against the original session repository state.")
            validation.repair_instruction.append("Fix only the failed promotion gate.")

        if promotion.ok:
            manifest["patch"] = {
                "path": session_paths.patch.name,
                "source_candidate": candidate_rel,
                "validation": validation.to_dict(),
                "promotion": promotion.to_dict(session_root),
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
                "promotion": promotion_rel,
                "ok": validation.ok,
                "structural_ok": validation.structural_ok,
                "status": promotion.status,
                "failed_check": promotion.failed_check,
                "promoted_to_patch": validation.promoted_to_patch,
            }
        )
        manifest["latest_promotion"] = promotion_rel
        manager.write_manifest(session_root, manifest)
        manager.append_event(
            session_root,
            {
                "type": "candidate_patch",
                "file": candidate_rel,
                "ok": validation.ok,
                "structural_ok": validation.structural_ok,
                "promotion_status": promotion.status,
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
        error_message="No lbh-tool request, lbh-hashline-patch, or diff found in response.",
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


def apply_patch_ready(
    repo: Path,
    patch_path: Path,
    *,
    session_root: Path | None = None,
    skip_apply: bool = False,
) -> ApplyOutcome:
    check_outcome = apply_patch_file(repo, patch_path, session_root=session_root, check=True, yes=False)
    if not check_outcome.ok or skip_apply:
        return check_outcome
    return apply_patch_file(repo, patch_path, session_root=session_root, check=False, yes=True)
