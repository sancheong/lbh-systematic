from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lbh.core.paths import index_dir

LBH_CHECKOUT = Path(r"C:\developer\lbh-systematic")
GATEWAY_URL = "http://localhost:8000"
GATEWAY_API_KEY_ENV = "LBH_GATEWAY_API_KEY"


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    status: str
    target_path: str
    target_repo: str | None
    lbh_checkout: str
    working_tree_dirty: bool | None
    docker_running: bool
    docker_detail: str | None
    lbh_exists: bool | None
    index_exists: bool | None
    api_key_source: str
    gateway_url: str
    http_status: int | None
    stop_reason: str
    next_safe_command: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def run_preflight(target: str | Path | None = None) -> PreflightResult:
    target_path = (Path(target) if target is not None else Path.cwd()).resolve()
    if not target_path.exists():
        return _result(
            ok=False,
            status="target_missing",
            target_path=target_path,
            target_repo=None,
            working_tree_dirty=None,
            docker_running=False,
            docker_detail=None,
            lbh_exists=None,
            index_exists=None,
            api_key_source="missing",
            http_status=None,
            stop_reason=f"Target path does not exist: {target_path}",
            next_safe_command="Provide a valid --target path.",
        )

    repo_root = _resolve_repo_root(target_path)
    if repo_root is None:
        return _result(
            ok=False,
            status="not_git_repo",
            target_path=target_path,
            target_repo=None,
            working_tree_dirty=None,
            docker_running=False,
            docker_detail=None,
            lbh_exists=None,
            index_exists=None,
            api_key_source="missing",
            http_status=None,
            stop_reason=f"Target is not inside a Git repository: {target_path}",
            next_safe_command="Choose a target path inside an existing Git repository.",
        )

    if not LBH_CHECKOUT.exists():
        return _result(
            ok=False,
            status="lbh_checkout_missing",
            target_path=target_path,
            target_repo=repo_root,
            working_tree_dirty=_git_is_dirty(repo_root),
            docker_running=False,
            docker_detail=None,
            lbh_exists=(repo_root / ".lbh").exists(),
            index_exists=(index_dir(repo_root) / "files.sqlite").exists(),
            api_key_source="missing",
            http_status=None,
            stop_reason=f"LBH checkout is missing: {LBH_CHECKOUT}",
            next_safe_command=f"Restore the LBH checkout at {LBH_CHECKOUT}.",
        )

    working_tree_dirty = _git_is_dirty(repo_root)
    lbh_exists = (repo_root / ".lbh").exists()
    index_exists = (index_dir(repo_root) / "files.sqlite").exists()

    docker_running, docker_detail = _check_docker()
    if not docker_running:
        return _result(
            ok=False,
            status="docker_not_running",
            target_path=target_path,
            target_repo=repo_root,
            working_tree_dirty=working_tree_dirty,
            docker_running=False,
            docker_detail=docker_detail,
            lbh_exists=lbh_exists,
            index_exists=index_exists,
            api_key_source="missing",
            http_status=None,
            stop_reason=docker_detail or "Docker is not running.",
            next_safe_command="Start Docker Desktop or the Docker daemon, then rerun `lbh preflight`.",
        )

    if not lbh_exists:
        return _result(
            ok=True,
            status="init_required",
            target_path=target_path,
            target_repo=repo_root,
            working_tree_dirty=working_tree_dirty,
            docker_running=True,
            docker_detail=docker_detail,
            lbh_exists=False,
            index_exists=False,
            api_key_source="missing",
            http_status=None,
            stop_reason="LBH workspace is missing.",
            next_safe_command=_command_in_repo(repo_root, "python -m lbh.cli init"),
        )

    if not index_exists:
        return _result(
            ok=True,
            status="index_required",
            target_path=target_path,
            target_repo=repo_root,
            working_tree_dirty=working_tree_dirty,
            docker_running=True,
            docker_detail=docker_detail,
            lbh_exists=True,
            index_exists=False,
            api_key_source="missing",
            http_status=None,
            stop_reason="LBH index is missing.",
            next_safe_command=_command_in_repo(repo_root, "python -m lbh.cli index"),
        )

    api_key = os.environ.get(GATEWAY_API_KEY_ENV, "").strip()
    if not api_key:
        return _result(
            ok=False,
            status="api_key_missing",
            target_path=target_path,
            target_repo=repo_root,
            working_tree_dirty=working_tree_dirty,
            docker_running=True,
            docker_detail=docker_detail,
            lbh_exists=True,
            index_exists=True,
            api_key_source="missing",
            http_status=None,
            stop_reason=f"{GATEWAY_API_KEY_ENV} is not set.",
            next_safe_command=f"Set {GATEWAY_API_KEY_ENV}, then rerun `lbh preflight`.",
        )

    gateway_status, http_status, gateway_reason = _check_gateway_status(api_key)
    if gateway_status != "ok":
        return _result(
            ok=False,
            status=gateway_status,
            target_path=target_path,
            target_repo=repo_root,
            working_tree_dirty=working_tree_dirty,
            docker_running=True,
            docker_detail=docker_detail,
            lbh_exists=True,
            index_exists=True,
            api_key_source="env",
            http_status=http_status,
            stop_reason=gateway_reason,
            next_safe_command="Fix the gateway issue, then rerun `lbh preflight`.",
        )

    return _result(
        ok=True,
        status="ok",
        target_path=target_path,
        target_repo=repo_root,
        working_tree_dirty=working_tree_dirty,
        docker_running=True,
        docker_detail=docker_detail,
        lbh_exists=True,
        index_exists=True,
        api_key_source="env",
        http_status=http_status,
        stop_reason="Preflight checks passed.",
        next_safe_command=_command_in_repo(
            repo_root,
            "python -m lbh.cli gateway-run \"<rough request>\" --base-url http://localhost:8000 --api-key $env:LBH_GATEWAY_API_KEY --max-rounds 20",
        ),
    )


def _result(
    *,
    ok: bool,
    status: str,
    target_path: Path,
    target_repo: Path | None,
    working_tree_dirty: bool | None,
    docker_running: bool,
    docker_detail: str | None,
    lbh_exists: bool | None,
    index_exists: bool | None,
    api_key_source: str,
    http_status: int | None,
    stop_reason: str,
    next_safe_command: str,
) -> PreflightResult:
    return PreflightResult(
        ok=ok,
        status=status,
        target_path=str(target_path),
        target_repo=str(target_repo) if target_repo is not None else None,
        lbh_checkout=str(LBH_CHECKOUT),
        working_tree_dirty=working_tree_dirty,
        docker_running=docker_running,
        docker_detail=docker_detail,
        lbh_exists=lbh_exists,
        index_exists=index_exists,
        api_key_source=api_key_source,
        gateway_url=GATEWAY_URL,
        http_status=http_status,
        stop_reason=stop_reason,
        next_safe_command=next_safe_command,
    )


def _resolve_repo_root(target_path: Path) -> Path | None:
    probe = target_path if target_path.is_dir() else target_path.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=probe,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    if not root:
        return None
    return Path(root).resolve()


def _git_is_dirty(repo_root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _check_docker() -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "Docker CLI is not installed or not on PATH."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "Docker daemon is not running."
        return False, detail
    return True, None


def _check_gateway_status(api_key: str) -> tuple[str, int | None, str]:
    request = Request(
        f"{GATEWAY_URL.rstrip('/')}/status",
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urlopen(request, timeout=15.0) as response:
            body = response.read().decode("utf-8")
            status = getattr(response, "status", response.getcode())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        reason = detail or exc.reason or "HTTP error"
        if exc.code in (401, 403):
            return "gateway_auth_failed", exc.code, f"Gateway status check returned {exc.code}: {reason}"
        return "gateway_http_error", exc.code, f"Gateway status check returned {exc.code}: {reason}"
    except URLError as exc:
        return "gateway_unreachable", None, f"Gateway status check failed: {exc.reason}"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "gateway_invalid_json", status, "Gateway status check returned invalid JSON."
    if not isinstance(payload, dict):
        return "gateway_schema_error", status, "Gateway status check did not return a JSON object."
    return "ok", status, "Gateway status check passed."


def _command_in_repo(repo_root: Path, command: str) -> str:
    return f"Set-Location '{repo_root}'; {command}"
