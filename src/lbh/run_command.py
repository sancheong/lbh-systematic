from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from lbh.core.config import Config, init_config
from lbh.core.paths import lbh_dir
from lbh.gateway_loop import GatewayLoopResult, run_gateway_loop
from lbh.indexer.builder import RepoIndexer
from lbh.preflight import GATEWAY_API_KEY_ENV, GATEWAY_URL, PreflightResult, run_preflight


@dataclass(frozen=True)
class RunResult:
    ok: bool
    phase: str
    status: str
    target_repo: str | None
    preflight_status: str
    init_ran: bool
    index_ran: bool
    working_tree_dirty: bool | None
    session_path: str | None
    response_file: str | None
    candidate_path: str | None
    promoted_patch_path: str | None
    patch_path: str | None
    rounds: int | None
    gateway_url: str
    stop_reason: str
    exact_stop_reason: str
    failed_check: str | None
    validation_summary: dict[str, str] | None
    checks: list[dict[str, object]] | None
    next_safe_command: str
    writer_session_url: str | None = None
    reviewer_session_url: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class GatewayRunPreparation:
    repo_root: Path
    preflight: PreflightResult
    init_ran: bool
    index_ran: bool

    @property
    def api_key(self) -> str:
        return os.environ.get(GATEWAY_API_KEY_ENV, "").strip()


_PREPARABLE_PREFLIGHT_STATUSES = {"init_required", "index_required", "ok"}
_PREPARATION_ACTIONS = {
    "init_required": ("init", "index"),
    "index_required": ("index",),
    "ok": (),
}


def validate_gateway_request_source(
    request: str | None,
    request_file: str | Path | None,
    *,
    message: str = "provide exactly one of request or request_file",
) -> None:
    if bool(request) == bool(request_file):
        raise ValueError(message)


def run_gateway_request(
    repo_root: Path,
    *,
    request: str | None,
    request_file: Path | None,
    request_label: str | None,
    base_url: str,
    api_key: str,
    max_rounds: int,
    limit: int | None,
    skip_apply: bool,
) -> GatewayLoopResult:
    return run_gateway_loop(
        repo_root,
        request=request,
        request_file=request_file,
        request_label=request_label,
        base_url=base_url,
        api_key=api_key,
        max_rounds=max_rounds,
        limit=limit,
        skip_apply=skip_apply,
    )


def _repo_root_from_preflight(preflight: PreflightResult) -> Path:
    if preflight.target_repo is None:
        raise ValueError("preflight did not return a target repository")
    return Path(preflight.target_repo).resolve()


def _run_init(repo_root: Path) -> None:
    init_config(repo_root)
    (lbh_dir(repo_root) / "index").mkdir(parents=True, exist_ok=True)
    (lbh_dir(repo_root) / "sessions").mkdir(parents=True, exist_ok=True)


def _run_index(repo_root: Path) -> None:
    RepoIndexer(repo_root, Config.load(repo_root)).rebuild()


def _run_preparation_action(repo_root: Path, action: str) -> None:
    if action == "init":
        _run_init(repo_root)
        return
    if action == "index":
        _run_index(repo_root)
        return
    raise ValueError(f"unknown gateway preparation action: {action}")


def _normalize_request_file(request_file: str | Path) -> Path:
    path = Path(request_file)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _from_preflight(preflight: PreflightResult, *, init_ran: bool, index_ran: bool) -> RunResult:
    return RunResult(
        ok=False,
        phase="preflight",
        status=preflight.status,
        target_repo=preflight.target_repo,
        preflight_status=preflight.status,
        init_ran=init_ran,
        index_ran=index_ran,
        working_tree_dirty=preflight.working_tree_dirty,
        session_path=None,
        response_file=None,
        candidate_path=None,
        promoted_patch_path=None,
        patch_path=None,
        rounds=None,
        gateway_url=preflight.gateway_url,
        stop_reason=preflight.stop_reason,
        exact_stop_reason=preflight.stop_reason,
        failed_check=None,
        validation_summary=None,
        checks=None,
        next_safe_command=preflight.next_safe_command,
    )


def _gateway_failure_result(
    preparation: GatewayRunPreparation,
    *,
    phase: str,
    status: str,
    stop_reason: str,
    failed_check: str | None,
    next_safe_command: str,
) -> RunResult:
    return RunResult(
        ok=False,
        phase=phase,
        status=status,
        target_repo=str(preparation.repo_root),
        preflight_status=preparation.preflight.status,
        init_ran=preparation.init_ran,
        index_ran=preparation.index_ran,
        working_tree_dirty=preparation.preflight.working_tree_dirty,
        session_path=None,
        response_file=None,
        candidate_path=None,
        promoted_patch_path=None,
        patch_path=None,
        rounds=None,
        gateway_url=GATEWAY_URL,
        stop_reason=stop_reason,
        exact_stop_reason=stop_reason,
        failed_check=failed_check,
        validation_summary=None,
        checks=None,
        next_safe_command=next_safe_command,
    )


def _gateway_next_safe_command(gateway_result: GatewayLoopResult, *, skip_apply: bool) -> str:
    if gateway_result.status == "patch_ready" and gateway_result.patch_file is not None:
        return (
            f"Set-Location '{gateway_result.session_root}'; "
            f"python -m lbh.cli apply '{gateway_result.patch_file}' --session '{gateway_result.session_root}' --yes"
        )
    if gateway_result.status == "plan_ready":
        return f"Inspect the plan artifacts under '{gateway_result.session_root}'."
    if gateway_result.status in {"blocked", "max_rounds_exceeded", "gateway_run_failed"}:
        return f"Inspect the session under '{gateway_result.session_root}'."
    if gateway_result.status == "applied":
        return "not applicable"
    if skip_apply and gateway_result.patch_file is not None:
        return (
            f"Set-Location '{gateway_result.session_root}'; "
            f"python -m lbh.cli apply '{gateway_result.patch_file}' --session '{gateway_result.session_root}' --yes"
        )
    return "not applicable"


def _session_thread_urls(session_root: Path) -> tuple[str | None, str | None]:
    manifest_path = session_root / "manifest.json"
    if not manifest_path.exists():
        return None, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    writer_url = manifest.get("transport_session_url")
    reviewer = manifest.get("reviewer")
    reviewer_url = reviewer.get("transport_session_url") if isinstance(reviewer, dict) else None
    return (
        writer_url if isinstance(writer_url, str) and writer_url else None,
        reviewer_url if isinstance(reviewer_url, str) and reviewer_url else None,
    )


def _from_gateway_result(
    gateway_result: GatewayLoopResult,
    *,
    preflight: PreflightResult,
    init_ran: bool,
    index_ran: bool,
    skip_apply: bool,
) -> RunResult:
    ok_statuses = {"applied", "patch_ready", "plan_ready"}
    next_safe_command = _gateway_next_safe_command(gateway_result, skip_apply=skip_apply)
    stop_reason = "" if gateway_result.status in ok_statuses else (gateway_result.message or gateway_result.status)
    writer_url, reviewer_url = _session_thread_urls(gateway_result.session_root)
    return RunResult(
        ok=gateway_result.status in ok_statuses,
        phase="gateway_run",
        status=gateway_result.status,
        target_repo=preflight.target_repo,
        preflight_status=preflight.status,
        init_ran=init_ran,
        index_ran=index_ran,
        working_tree_dirty=preflight.working_tree_dirty,
        session_path=str(gateway_result.session_root),
        response_file=str(gateway_result.response_file) if gateway_result.response_file is not None else None,
        candidate_path=str(gateway_result.candidate_path) if gateway_result.candidate_path is not None else None,
        promoted_patch_path=str(gateway_result.promoted_patch_path) if gateway_result.promoted_patch_path is not None else None,
        patch_path=str(gateway_result.patch_file) if gateway_result.patch_file is not None else None,
        rounds=gateway_result.rounds,
        gateway_url=preflight.gateway_url,
        stop_reason=stop_reason,
        exact_stop_reason=stop_reason,
        failed_check=gateway_result.failed_check,
        validation_summary=gateway_result.validation_summary,
        checks=gateway_result.checks,
        next_safe_command=next_safe_command,
        writer_session_url=writer_url,
        reviewer_session_url=reviewer_url,
    )


def _prepare_gateway_run(target: str | Path | None) -> GatewayRunPreparation | RunResult:
    preflight = run_preflight(target)
    init_ran = False
    index_ran = False

    if preflight.status not in _PREPARABLE_PREFLIGHT_STATUSES:
        return _from_preflight(preflight, init_ran=init_ran, index_ran=index_ran)

    repo_root = _repo_root_from_preflight(preflight)
    for action in _PREPARATION_ACTIONS[preflight.status]:
        _run_preparation_action(repo_root, action)
        if action == "init":
            init_ran = True
        elif action == "index":
            index_ran = True

    preflight = run_preflight(repo_root)
    if preflight.status != "ok":
        return _from_preflight(preflight, init_ran=init_ran, index_ran=index_ran)

    return GatewayRunPreparation(
        repo_root=repo_root,
        preflight=preflight,
        init_ran=init_ran,
        index_ran=index_ran,
    )


def run_request(
    *,
    request: str | None = None,
    request_file: str | Path | None = None,
    request_label: str | None = None,
    target: str | Path | None = None,
    limit: int | None = None,
    max_rounds: int = 20,
    skip_apply: bool = False,
) -> RunResult:
    validate_gateway_request_source(request, request_file)

    preparation = _prepare_gateway_run(target)
    if isinstance(preparation, RunResult):
        return preparation

    api_key = preparation.api_key
    if not api_key:
        return _gateway_failure_result(
            preparation,
            phase="preflight",
            status="api_key_missing",
            stop_reason=f"{GATEWAY_API_KEY_ENV} is not set.",
            failed_check=None,
            next_safe_command=f"Set {GATEWAY_API_KEY_ENV}, then rerun `lbh run`.",
        )

    request_file_path = _normalize_request_file(request_file) if request_file is not None else None
    try:
        gateway_result = run_gateway_request(
            preparation.repo_root,
            request=request,
            request_file=request_file_path,
            request_label=request_label,
            base_url=preparation.preflight.gateway_url,
            api_key=api_key,
            max_rounds=max_rounds,
            limit=limit,
            skip_apply=skip_apply,
        )
    except Exception as exc:
        return _gateway_failure_result(
            preparation,
            phase="gateway_run",
            status="gateway_run_failed",
            stop_reason=str(exc),
            failed_check="gateway_run",
            next_safe_command="Inspect the gateway logs and rerun `lbh run` after fixing the failure.",
        )

    return _from_gateway_result(
        gateway_result,
        preflight=preparation.preflight,
        init_ran=preparation.init_ran,
        index_ran=preparation.index_ran,
        skip_apply=skip_apply,
    )
