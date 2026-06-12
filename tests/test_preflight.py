from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError

from lbh.preflight import run_preflight


class _FakeResponse:
    def __init__(self, payload: object, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_repo(tmp_path: Path, *, with_lbh: bool, with_index: bool) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    if with_lbh:
        (repo / ".lbh").mkdir()
    if with_index:
        (repo / ".lbh" / "index").mkdir(parents=True, exist_ok=True)
        (repo / ".lbh" / "index" / "files.sqlite").write_text("", encoding="utf-8")
    return repo


def _fake_run_factory(repo: Path, *, dirty: bool = False, docker_ok: bool = True, docker_detail: str = ""):
    def fake_run(cmd, cwd=None, capture_output=None, text=None, check=None):
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, str(repo) + "\n", "")
        if cmd[:3] == ["git", "status", "--short"]:
            stdout = " M src/a.py\n" if dirty else ""
            return subprocess.CompletedProcess(cmd, 0, stdout, "")
        if cmd[:2] == ["docker", "info"]:
            if docker_ok:
                return subprocess.CompletedProcess(cmd, 0, '{"ServerVersion":"27.0"}', "")
            return subprocess.CompletedProcess(cmd, 1, "", docker_detail or "Cannot connect to the Docker daemon")
        raise AssertionError(f"unexpected command: {cmd}")

    return fake_run


def test_preflight_reports_missing_target(tmp_path):
    result = run_preflight(tmp_path / "missing-repo")

    assert result.ok is False
    assert result.status == "target_missing"
    assert result.target_repo is None


def test_preflight_reports_init_required_before_gateway(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, with_lbh=False, with_index=False)
    checkout = tmp_path / "lbh-checkout"
    checkout.mkdir()
    monkeypatch.setattr("lbh.preflight.LBH_CHECKOUT", checkout)
    monkeypatch.setattr("lbh.preflight.subprocess.run", _fake_run_factory(repo))

    result = run_preflight(repo)

    assert result.ok is True
    assert result.status == "init_required"
    assert result.lbh_exists is False
    assert result.index_exists is False
    assert result.docker_running is True
    assert "python -m lbh.cli init" in result.next_safe_command


def test_preflight_reports_docker_not_running(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, with_lbh=True, with_index=True)
    checkout = tmp_path / "lbh-checkout"
    checkout.mkdir()
    monkeypatch.setattr("lbh.preflight.LBH_CHECKOUT", checkout)
    monkeypatch.setattr(
        "lbh.preflight.subprocess.run",
        _fake_run_factory(repo, docker_ok=False, docker_detail="Docker Desktop is stopped."),
    )

    result = run_preflight(repo)

    assert result.ok is False
    assert result.status == "docker_not_running"
    assert result.docker_running is False
    assert result.stop_reason == "Docker Desktop is stopped."


def test_preflight_maps_gateway_auth_failure(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, with_lbh=True, with_index=True)
    checkout = tmp_path / "lbh-checkout"
    checkout.mkdir()
    monkeypatch.setattr("lbh.preflight.LBH_CHECKOUT", checkout)
    monkeypatch.setattr("lbh.preflight.subprocess.run", _fake_run_factory(repo, dirty=True))
    monkeypatch.setenv("LBH_GATEWAY_API_KEY", "secret")

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"unauthorized"),
        )

    monkeypatch.setattr("lbh.preflight.urlopen", fake_urlopen)

    result = run_preflight(repo)

    assert result.ok is False
    assert result.status == "gateway_auth_failed"
    assert result.http_status == 401
    assert result.working_tree_dirty is True
    assert result.api_key_source == "env"


def test_preflight_reports_ok_when_everything_is_ready(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, with_lbh=True, with_index=True)
    checkout = tmp_path / "lbh-checkout"
    checkout.mkdir()
    monkeypatch.setattr("lbh.preflight.LBH_CHECKOUT", checkout)
    monkeypatch.setattr("lbh.preflight.subprocess.run", _fake_run_factory(repo))
    monkeypatch.setenv("LBH_GATEWAY_API_KEY", "secret")
    monkeypatch.setattr("lbh.preflight.urlopen", lambda request, timeout: _FakeResponse({"status": "ok"}, status=200))

    result = run_preflight(repo)

    assert result.ok is True
    assert result.status == "ok"
    assert result.http_status == 200
    assert result.api_key_source == "env"
    assert "python -m lbh.cli gateway-run" in result.next_safe_command
