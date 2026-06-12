from __future__ import annotations

from pathlib import Path

from lbh.gateway_loop import GatewayLoopResult
from lbh.preflight import PreflightResult
from lbh.run_command import run_request


def _preflight(
    *,
    status: str,
    ok: bool,
    repo: Path | None,
    working_tree_dirty: bool | None = False,
    lbh_exists: bool | None = True,
    index_exists: bool | None = True,
    stop_reason: str = "",
    next_safe_command: str = "not applicable",
) -> PreflightResult:
    return PreflightResult(
        ok=ok,
        status=status,
        target_path=str(repo or Path("C:/missing")),
        target_repo=str(repo) if repo is not None else None,
        lbh_checkout=r"C:\developer\lbh-systematic",
        working_tree_dirty=working_tree_dirty,
        docker_running=True,
        docker_detail=None,
        lbh_exists=lbh_exists,
        index_exists=index_exists,
        api_key_source="env",
        gateway_url="http://localhost:8000",
        http_status=200 if ok else None,
        stop_reason=stop_reason,
        next_safe_command=next_safe_command,
    )


def test_run_returns_preflight_failure_without_gateway(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preflight_result = _preflight(
        status="gateway_auth_failed",
        ok=False,
        repo=repo,
        stop_reason="auth failed",
        next_safe_command="set env",
    )
    monkeypatch.setattr("lbh.run_command.run_preflight", lambda target=None: preflight_result)

    result = run_request(request="fix bug")

    assert result.ok is False
    assert result.phase == "preflight"
    assert result.status == "gateway_auth_failed"
    assert result.stop_reason == "auth failed"
    assert result.next_safe_command == "set env"


def test_run_auto_inits_and_indexes_before_gateway(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preflight_results = iter(
        [
            _preflight(status="init_required", ok=True, repo=repo, lbh_exists=False, index_exists=False, stop_reason="init needed"),
            _preflight(status="ok", ok=True, repo=repo, lbh_exists=True, index_exists=True, stop_reason="ready"),
        ]
    )
    monkeypatch.setattr("lbh.run_command.run_preflight", lambda target=None: next(preflight_results))

    calls: list[tuple[str, object]] = []

    def fake_init(repo_root: Path) -> Path:
        calls.append(("init", repo_root))
        return repo_root / ".lbh" / "config.toml"

    class _FakeIndexer:
        def __init__(self, repo_root: Path, config):
            calls.append(("indexer", repo_root))

        def rebuild(self):
            calls.append(("rebuild", None))
            return {"files": 1}

    def fake_gateway_run(repo_root: Path, **kwargs):
        calls.append(("gateway", repo_root))
        return GatewayLoopResult(
            session_root=repo_root / ".lbh" / "sessions" / "s1",
            status="applied",
            rounds=2,
            response_file=repo_root / ".lbh" / "sessions" / "s1" / "response_002.md",
            patch_file=repo_root / ".lbh" / "sessions" / "s1" / "patch.diff",
            message="applied",
        )

    monkeypatch.setattr("lbh.run_command.init_config", fake_init)
    monkeypatch.setattr("lbh.run_command.RepoIndexer", _FakeIndexer)
    monkeypatch.setattr("lbh.run_command.run_gateway_loop", fake_gateway_run)
    monkeypatch.setattr("lbh.run_command.os.environ", {"LBH_GATEWAY_API_KEY": "dummy123"})

    result = run_request(request="fix bug", target=repo)

    assert result.ok is True
    assert result.phase == "gateway_run"
    assert result.status == "applied"
    assert result.init_ran is True
    assert result.index_ran is True
    assert ("gateway", repo) in calls


def test_run_surfaces_gateway_blocked_state(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("lbh.run_command.run_preflight", lambda target=None: _preflight(status="ok", ok=True, repo=repo))
    monkeypatch.setattr("lbh.run_command.os.environ", {"LBH_GATEWAY_API_KEY": "dummy123"})
    monkeypatch.setattr(
        "lbh.run_command.run_gateway_loop",
        lambda repo_root, **kwargs: GatewayLoopResult(
            session_root=repo_root / ".lbh" / "sessions" / "s2",
            status="blocked",
            rounds=3,
            response_file=repo_root / ".lbh" / "sessions" / "s2" / "response_003.md",
            patch_file=None,
            message="No pending context append or repair prompt found.",
        ),
    )

    result = run_request(request="fix bug", target=repo)

    assert result.ok is False
    assert result.phase == "gateway_run"
    assert result.status == "blocked"
    assert result.stop_reason == "No pending context append or repair prompt found."
