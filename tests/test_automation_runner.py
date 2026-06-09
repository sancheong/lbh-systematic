import argparse
import subprocess
from pathlib import Path

from lbh.automation.base import AutomationOptions, AutomationResult, BrowserChat, BrowserControllerError, BrowserResponse
from lbh.automation.runner import AutomationRunner
from lbh.cli import cmd_automate
from lbh.core.config import init_config
from lbh.session.manager import SessionManager
from lbh.workflow import AskResult


READ_REQUEST = """```lbh-tool
{"type":"context_request","requests":[{"op":"READ","path":"src/a.py","ranges":[{"start":1,"end":1}],"why":"inspect file"}]}
```"""

VALID_DIFF = """````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a
+b
<<<LBH_DIFF_END>>>
````
"""

BROKEN_DIFF = """LBH_ANSWER_BEGIN
<<<LBH_DIFF_BEGIN>>>
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a
+b
<<<LBH_DIFF_END>>>
LBH_ANSWER_END
"""


class FakeBrowserController:
    def __init__(self, responses, *, fail_wait: int = 0):
        self.responses = list(responses)
        self.fail_wait = fail_wait
        self.calls: list[tuple[str, str]] = []
        self.sent_messages: list[str] = []
        self.chat_ref = "https://chatgpt.example/c/test"

    def start_chat(self, *, profile: str) -> BrowserChat:
        self.calls.append(("start_chat", profile))
        return BrowserChat(chat_ref=self.chat_ref, metadata={"profile": profile})

    def resume_chat(self, *, profile: str, chat_ref: str) -> BrowserChat:
        self.calls.append(("resume_chat", profile))
        return BrowserChat(chat_ref=chat_ref, metadata={"profile": profile, "resumed": True})

    def send_message(self, *, profile: str, chat_ref: str, text: str) -> dict[str, str]:
        self.calls.append(("send_message", profile))
        self.sent_messages.append(text)
        return {"profile": profile}

    def wait_for_response(self, *, profile: str, chat_ref: str, timeout_seconds: int, poll_seconds: float) -> BrowserResponse:
        self.calls.append(("wait_for_response", profile))
        if self.fail_wait > 0:
            self.fail_wait -= 1
            raise BrowserControllerError("wait failed")
        if not self.responses:
            raise BrowserControllerError("no fake responses left")
        return BrowserResponse(text=self.responses.pop(0), metadata={"profile": profile})

    def capture_debug(self, *, profile: str, chat_ref: str | None, session_root: Path) -> dict[str, str]:
        self.calls.append(("capture_debug", profile))
        return {"chat_ref": chat_ref or "", "session_root": str(session_root)}


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    init_config(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")


def _ask_fn(register_read: bool = False):
    def _inner(repo: Path, request: str, *, limit: int | None = None) -> AskResult:
        manager = SessionManager(repo)
        session = manager.create(request, ranked=[])
        session.initial_prompt.write_text("initial prompt", encoding="utf-8")
        if register_read:
            manager.register_read_file(session.root, "src/a.py", "sha256", [{"start": 1, "end": 1}])
        return AskResult(session_root=session.root, initial_prompt=session.initial_prompt)

    return _inner


def test_automation_runner_handles_context_append_and_apply_yes(tmp_path):
    _init_repo(tmp_path)
    controller = FakeBrowserController([READ_REQUEST, VALID_DIFF])
    runner = AutomationRunner(
        tmp_path,
        controller,
        AutomationOptions(apply_mode="yes"),
        ask_fn=_ask_fn(register_read=False),
    )

    result = runner.start("fix a")

    assert result.state == "completed"
    assert (tmp_path / "src" / "a.py").read_text(encoding="utf-8") == "b\n"
    assert controller.sent_messages[0] == "initial prompt"
    assert "<file path=\"src/a.py\"" in controller.sent_messages[1]

    manifest = SessionManager(tmp_path).load_manifest(result.session_root)
    assert manifest["automation"]["state"] == "completed"
    assert manifest["automation"]["latest_inbound_response"] == "response_002.md"
    assert manifest["patch"]["path"] == "patch.diff"
    assert (result.session_root / "response_001.md").exists()
    assert (result.session_root / "response_002.md").exists()


def test_automation_runner_repairs_failed_candidate_then_completes(tmp_path):
    _init_repo(tmp_path)
    controller = FakeBrowserController([BROKEN_DIFF, VALID_DIFF])
    runner = AutomationRunner(
        tmp_path,
        controller,
        AutomationOptions(apply_mode="check"),
        ask_fn=_ask_fn(register_read=True),
    )

    result = runner.start("fix a")

    assert result.state == "completed"
    candidate_dir = result.session_root / "candidates"
    assert (candidate_dir / "candidate_001.diff").exists()
    assert (candidate_dir / "candidate_002.diff").exists()
    assert (result.session_root / "repair_response_001.md").exists()
    assert "You are repairing a ChatGPT-generated candidate patch." in controller.sent_messages[1]

    manifest = SessionManager(tmp_path).load_manifest(result.session_root)
    assert manifest["candidates"][0]["ok"] is False
    assert manifest["candidates"][1]["ok"] is True
    assert manifest["patch"]["source_candidate"] == "candidates/candidate_002.diff"


def test_automation_runner_retries_then_blocks(tmp_path):
    _init_repo(tmp_path)
    controller = FakeBrowserController([], fail_wait=2)
    runner = AutomationRunner(
        tmp_path,
        controller,
        AutomationOptions(apply_mode="check", max_retries=1),
        ask_fn=_ask_fn(register_read=True),
    )

    result = runner.start("fix a")

    assert result.state == "blocked"
    manifest = SessionManager(tmp_path).load_manifest(result.session_root)
    assert manifest["automation"]["awaiting_human_intervention"] is True
    assert manifest["automation"]["blocked_from_state"] == "waiting_for_response"
    assert manifest["automation"]["debug_artifacts"]["chat_ref"] == controller.chat_ref


def test_automation_runner_resumes_blocked_session_without_new_chat(tmp_path):
    _init_repo(tmp_path)
    first = FakeBrowserController([VALID_DIFF], fail_wait=1)
    runner = AutomationRunner(
        tmp_path,
        first,
        AutomationOptions(apply_mode="check", max_retries=0),
        ask_fn=_ask_fn(register_read=True),
    )
    blocked = runner.start("fix a")
    assert blocked.state == "blocked"

    second = FakeBrowserController([VALID_DIFF])
    resumed = AutomationRunner(
        tmp_path,
        second,
        AutomationOptions(apply_mode="check", max_retries=0),
        ask_fn=_ask_fn(register_read=True),
    ).resume(blocked.session_root)

    assert resumed.state == "completed"
    assert ("resume_chat", "Profile 4") in second.calls
    assert ("start_chat", "Profile 4") not in second.calls


def test_cmd_automate_passes_profile_and_skip_apply(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, repo_root, controller, options):
            captured["repo_root"] = repo_root
            captured["controller"] = controller
            captured["options"] = options

        def start(self, request, *, limit=None):
            captured["request"] = request
            captured["limit"] = limit
            return AutomationResult(session_root=tmp_path / ".lbh" / "sessions" / "fake", state="completed")

        def resume(self, session_root):
            raise AssertionError("resume should not be called")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("lbh.cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr("lbh.cli.ensure_index", lambda repo: None)
    monkeypatch.setattr("lbh.cli.build_browser_controller", lambda args: object())
    monkeypatch.setattr("lbh.cli.AutomationRunner", FakeRunner)

    args = argparse.Namespace(
        request="repair flow",
        session=None,
        limit=7,
        chrome_profile="Profile X",
        controller_command=None,
        skip_apply=True,
        max_retries=4,
        poll_seconds=1.5,
        timeout_seconds=90,
    )
    rc = cmd_automate(args)

    assert rc == 0
    assert captured["request"] == "repair flow"
    assert captured["limit"] == 7
    options = captured["options"]
    assert options.chrome_profile == "Profile X"
    assert options.apply_mode == "check"
    assert options.max_retries == 4
