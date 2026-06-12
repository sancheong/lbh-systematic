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
    patch_path: str | None
    rounds: int | None
    gateway_url: str
    stop_reason: str
    next_safe_command: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


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
    if bool(request) == bool(request_file):
        raise ValueError("provide exactly one of request or request_file")

    initial_preflight = run_preflight(target)
    init_ran = False
    index_ran = False

    if initial_preflight.status in {"init_required", "index_required", "ok"}:
        repo_root = _repo_root_from_preflight(initial_preflight)
    else:
        return _from_preflight(initial_preflight, init_ran=init_ran, index_ran=index_ran)

    if initial_preflight.status == "init_required":
        _run_init(repo_root)
        init_ran = True
        _run_index(repo_root)
        index_ran = True
    elif initial_preflight.status == "index_required":
        _run_index(repo_root)
        index_ran = True

    final_preflight = run_preflight(repo_root)
    if final_preflight.status != "ok":
        return _from_preflight(final_preflight, init_ran=init_ran, index_ran=index_ran)

    api_key = os.environ.get(GATEWAY_API_KEY_ENV, "").strip()
    if not api_key:
        return RunResult(
            ok=False,
            phase="preflight",
            status="api_key_missing",
            target_repo=str(repo_root),
            preflight_status=final_preflight.status,
            init_ran=init_ran,
            index_ran=index_ran,
            working_tree_dirty=final_preflight.working_tree_dirty,
            session_path=None,
            response_file=None,
            patch_path=None,
            rounds=None,
            gateway_url=GATEWAY_URL,
            stop_reason=f"{GATEWAY_API_KEY_ENV} is not set.",
            next_safe_command=f"Set {GATEWAY_API_KEY_ENV}, then rerun `lbh run`.",
        )

    try:
        gateway_result = run_gateway_loop(
            repo_root,
            request=request,
            request_file=_normalize_request_file(request_file) if request_file is not None else None,
            request_label=request_label,
            base_url=GATEWAY_URL,
            api_key=api_key,
            max_rounds=max_rounds,
            limit=limit,
            skip_apply=skip_apply,
        )
    except Exception as exc:
        return RunResult(
            ok=False,
            phase="gateway_run",
            status="gateway_run_failed",
            target_repo=str(repo_root),
            preflight_status=final_preflight.status,
            init_ran=init_ran,
            index_ran=index_ran,
            working_tree_dirty=final_preflight.working_tree_dirty,
            session_path=None,
            response_file=None,
            patch_path=None,
            rounds=None,
            gateway_url=GATEWAY_URL,
            stop_reason=str(exc),
            next_safe_command="Inspect the gateway logs and rerun `lbh run` after fixing the failure.",
        )

    return _from_gateway_result(
        gateway_result,
        preflight=final_preflight,
        init_ran=init_ran,
        index_ran=index_ran,
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
        patch_path=None,
        rounds=None,
        gateway_url=preflight.gateway_url,
        stop_reason=preflight.stop_reason,
        next_safe_command=preflight.next_safe_command,
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
        patch_path=str(gateway_result.patch_file) if gateway_result.patch_file is not None else None,
        rounds=gateway_result.rounds,
        gateway_url=preflight.gateway_url,
        stop_reason=stop_reason,
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
