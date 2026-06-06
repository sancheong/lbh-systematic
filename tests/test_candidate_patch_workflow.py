import argparse
import json
import subprocess
from pathlib import Path

from lbh.cli import cmd_respond
from lbh.core.config import init_config
from lbh.session.manager import SessionManager


VALID_DIFF = """<<<LBH_DIFF_BEGIN>>>
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a
+b
<<<LBH_DIFF_END>>>
"""


def _init_repo(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    init_config(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")
    manager = SessionManager(tmp_path)
    session = manager.create("fix a", ranked=[])
    manager.register_read_file(session.root, "src/a.py", "sha256", [{"start": 1, "end": 1}])
    return manager, session


def _run_respond(tmp_path: Path, session_root: Path, response_file: Path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(response_file=str(response_file), session=str(session_root))
    return cmd_respond(args)


def test_candidate_patch_promotes_when_validation_passes(tmp_path, monkeypatch):
    manager, session = _init_repo(tmp_path)
    response_file = tmp_path / "final.md"
    response_file.write_text(VALID_DIFF, encoding="utf-8")

    rc = _run_respond(tmp_path, session.root, response_file, monkeypatch)
    assert rc == 0

    candidate_dir = session.root / "candidates"
    diff_path = candidate_dir / "candidate_001.diff"
    validation_path = candidate_dir / "candidate_001.validation.json"
    critique_path = candidate_dir / "candidate_001.critique.md"
    repair_path = candidate_dir / "candidate_001.repair_prompt.md"

    assert diff_path.exists()
    assert validation_path.exists()
    assert critique_path.exists()
    assert repair_path.exists()
    assert session.patch.exists()

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["ok"] is True
    assert validation["promoted_to_patch"] is True
    assert validation["candidate"] == "candidates/candidate_001.diff"

    manifest = manager.load_manifest(session.root)
    assert manifest["latest_candidate"] == "candidates/candidate_001.diff"
    assert manifest["patch"]["path"] == "patch.diff"
    assert manifest["patch"]["source_candidate"] == "candidates/candidate_001.diff"
    assert manifest["candidates"][0]["ok"] is True
    assert manifest["candidates"][0]["promoted_to_patch"] is True


def test_candidate_patch_failure_generates_critique_and_no_patch(tmp_path, monkeypatch):
    manager, session = _init_repo(tmp_path)
    response_file = tmp_path / "broken.md"
    response_file.write_text("LBH_ANSWER_BEGIN\n" + VALID_DIFF + "\nLBH_ANSWER_END\n", encoding="utf-8")

    rc = _run_respond(tmp_path, session.root, response_file, monkeypatch)
    assert rc == 3

    candidate_dir = session.root / "candidates"
    validation_path = candidate_dir / "candidate_001.validation.json"
    critique_path = candidate_dir / "candidate_001.critique.md"
    repair_path = candidate_dir / "candidate_001.repair_prompt.md"

    assert validation_path.exists()
    assert critique_path.exists()
    assert repair_path.exists()
    assert not session.patch.exists()

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["ok"] is False
    assert validation["promoted_to_patch"] is False
    assert any(item["kind"] == "protocol_invention" for item in validation["errors"])

    critique = critique_path.read_text(encoding="utf-8")
    assert "LBH_ANSWER_BEGIN" in critique

    repair_prompt = repair_path.read_text(encoding="utf-8")
    assert "Do not redesign the feature." in repair_prompt
    assert "Remove unsupported protocol markers" in repair_prompt

    manifest = manager.load_manifest(session.root)
    assert manifest["patch"] is None
    assert manifest["latest_candidate"] == "candidates/candidate_001.diff"
    assert manifest["candidates"][0]["ok"] is False
    assert manifest["candidates"][0]["promoted_to_patch"] is False


def test_candidate_patch_numbering_increments(tmp_path, monkeypatch):
    _, session = _init_repo(tmp_path)
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text(VALID_DIFF, encoding="utf-8")
    second.write_text(VALID_DIFF, encoding="utf-8")

    assert _run_respond(tmp_path, session.root, first, monkeypatch) == 0
    assert _run_respond(tmp_path, session.root, second, monkeypatch) == 0

    candidate_dir = session.root / "candidates"
    assert (candidate_dir / "candidate_001.diff").exists()
    assert (candidate_dir / "candidate_002.diff").exists()
