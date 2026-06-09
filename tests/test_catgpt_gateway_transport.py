from __future__ import annotations

import json
from pathlib import Path
import subprocess

from lbh.core.config import init_config
from lbh.gateway_loop import run_gateway_loop
from lbh.session.manager import SessionManager
from lbh.transport.catgpt_gateway import CatGptGatewayError, CatGptGatewayTransport


class _FakeHttpResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_gateway_transport_start_session_and_send(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(
            {
                "url": req.full_url,
                "body": json.loads(req.data.decode("utf-8")),
                "auth": req.headers["Authorization"],
                "timeout": timeout,
            }
        )
        if req.full_url.endswith("/thread/new"):
            return _FakeHttpResponse({"thread_id": "thr_123", "message": "hello"})
        return _FakeHttpResponse({"message": "next reply", "provider": "chatgpt"})

    monkeypatch.setattr("lbh.transport.catgpt_gateway.urlopen", fake_urlopen)
    transport = CatGptGatewayTransport(base_url="http://localhost:8000", api_key="secret", timeout_seconds=9)

    started = transport.start_session("first prompt")
    reply = transport.send("thr_123", "follow up")

    assert started.session_id == "thr_123"
    assert started.response.text == "hello"
    assert reply.text == "next reply"
    assert calls[0]["url"] == "http://localhost:8000/thread/new"
    assert calls[0]["body"] == {"message": "first prompt"}
    assert calls[0]["auth"] == "Bearer secret"
    assert calls[1]["url"] == "http://localhost:8000/thread/thr_123/chat"
    assert calls[1]["body"] == {"message": "follow up"}


def test_gateway_transport_rejects_missing_thread_id(monkeypatch):
    monkeypatch.setattr("lbh.transport.catgpt_gateway.urlopen", lambda req, timeout: _FakeHttpResponse({"message": "ok"}))
    transport = CatGptGatewayTransport(base_url="http://localhost:8000")
    try:
        transport.start_session("first prompt")
    except CatGptGatewayError as exc:
        assert "thread id" in str(exc)
    else:
        raise AssertionError("expected CatGptGatewayError")


class _FakeTransport:
    def __init__(self):
        self.calls = []

    def start_session(self, initial_prompt: str):
        self.calls.append(("start", initial_prompt))
        return type("Started", (), {"session_id": "thr_1", "response": type("Resp", (), {"text": "[READ: src/a.py]", "metadata": {"transport": "fake"}})()})()

    def send(self, session_id: str, message: str):
        self.calls.append(("send", session_id, message))
        return type("Resp", (), {"text": "```diff\ndiff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n```", "metadata": {"transport": "fake"}})()


def _init_gateway_repo(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")
    init_config(tmp_path)
    manager = SessionManager(tmp_path)

    class Ranked:
        def __init__(self):
            self.path = "src/a.py"
            self.score = 1.0
            self.reasons = ["x"]
            self.layer = "code"

    monkeypatch.setattr("lbh.workflow.SearchRanker.rank", lambda self, request, limit: [Ranked()])
    monkeypatch.setattr(
        "lbh.workflow.ContextPacker.build_initial_prompt",
        lambda self, request, ranked: "initial prompt",
    )
    monkeypatch.setattr(
        "lbh.workflow.ToolExecutor.execute",
        lambda self, requests: "follow-up prompt",
    )
    original_create = SessionManager.create

    def create_with_read_file(self, user_request, ranked=None):
        session = original_create(self, user_request, ranked=ranked)
        self.register_read_file(session.root, "src/a.py", "sha256", [{"start": 1, "end": 1}])
        return session

    monkeypatch.setattr("lbh.workflow.SessionManager.create", create_with_read_file)
    return manager


def test_gateway_loop_applies_patch_by_default_after_patch_ready(tmp_path, monkeypatch):
    manager = _init_gateway_repo(tmp_path, monkeypatch)

    transport = _FakeTransport()
    result = run_gateway_loop(
        tmp_path,
        request="fix a",
        base_url="http://localhost:8000",
        transport=transport,
        max_rounds=3,
    )

    assert result.status == "applied"
    assert (tmp_path / "src" / "a.py").read_text(encoding="utf-8") == "b\n"
    manifest = manager.load_manifest(result.session_root)
    assert manifest["transport"] == "catgpt-gateway"
    assert manifest["transport_session_id"] == "thr_1"
    assert manifest["responses"] == ["response_001.md", "response_002.md"]
    assert transport.calls[1][1] == "thr_1"


def test_gateway_loop_can_skip_apply_after_patch_ready(tmp_path, monkeypatch):
    _init_gateway_repo(tmp_path, monkeypatch)

    transport = _FakeTransport()
    result = run_gateway_loop(
        tmp_path,
        request="fix a",
        base_url="http://localhost:8000",
        transport=transport,
        max_rounds=3,
        skip_apply=True,
    )

    assert result.status == "patch_ready"
    assert result.patch_file == result.session_root / "patch.diff"
    assert result.message == "git apply --check passed"
    assert (tmp_path / "src" / "a.py").read_text(encoding="utf-8") == "a\n"
