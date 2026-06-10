from types import SimpleNamespace

from lbh.context.packer import ContextPacker
from lbh.core.config import Config
from lbh.session.manager import SessionManager
from lbh.workflow import create_session_for_request


def test_build_initial_prompt_includes_strict_protocol_guidance(tmp_path):
    prompt = ContextPacker(tmp_path, Config({})).build_initial_prompt("설명형 요청", [])

    assert "output exactly one fenced `lbh-tool` block" in prompt
    assert "Do not output raw JSON" in prompt
    assert "A `json` fenced block is invalid." in prompt
    assert "`READ`: `op`, `path`, `ranges`, `why`" in prompt
    assert "`GREP`: `op`, `pattern` (preferred; current implementation also accepts `query`), `globs`, `max_results`, `why`" in prompt
    assert "`FIND_SYMBOL`: `op`, `query` (preferred; current implementation also accepts `pattern`), `max_results`, `why`" in prompt
    assert "for `FIND_SYMBOL`, do not use `symbol`" in prompt
    assert "Repository map, directory tree, grep results, symbol search results, and import paths do not count as file body reads." in prompt
    assert "Document and Markdown files follow the same read-before-modify rule for existing files." in prompt
    assert "Do not derive READ paths from imports, module names, comments, documentation mentions, or conventional package layouts." in prompt
    assert "If you infer that an unlisted file may be relevant, use `GREP`, `FIND_SYMBOL`, `LIST_DIR`, or `DEP_GRAPH` first to discover an exact path." in prompt
    assert "The LBH sentinel only wraps the diff; it does not relax git unified diff syntax." in prompt
    assert "never use Markdown bullets, fenced code blocks, explanatory prose, numbered lists, or pseudo-code formatting." in prompt
    assert "Every file patch must start at column 1 with `diff --git a/... b/...`." in prompt
    assert "Every hunk line must begin with a space, `+`, or `-`." in prompt
    assert "four-backtick-or-longer `text` fence" in prompt
    assert "transport wrapper" in prompt
    assert "does not rewrite `+`, `-`, indentation, or backticks inside the diff" in prompt
    assert "inspect the prompt generator, parser, CLI, tests, and docs together" in prompt
    assert "promoted patch automatically by default" in prompt
    assert "explicit skip-apply flag" in prompt
    assert "prefer the LBH sentinel diff format" in prompt
    assert '<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>' in prompt
    assert "inside it you must still produce a pure git unified diff" in prompt


def test_initial_prompt_snippet_files_are_registered_as_read_files(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "a.py"
    source.write_text("a\nb\nc\n", encoding="utf-8")
    ranked = [SimpleNamespace(path="src/a.py", score=1.0, layer="test", reasons=[])]

    class FakeRanker:
        def __init__(self, repo):
            self.repo = repo

        def rank(self, request, *, limit=None):
            return ranked

    monkeypatch.setattr("lbh.workflow.SearchRanker", FakeRanker)
    monkeypatch.setattr(ContextPacker, "repo_map", lambda self, ranked: "")

    session_root, initial_prompt = create_session_for_request(
        tmp_path,
        "fix a",
        config=Config({"context": {"snippet_lines": 2}}),
    )

    prompt = initial_prompt.read_text(encoding="utf-8")
    assert '<snippet path="src/a.py"' in prompt
    assert 'lines="1-2"' in prompt

    manifest = SessionManager(tmp_path).load_manifest(session_root)
    entry = manifest["read_files"]["src/a.py"]
    assert entry["sha256"]
    assert entry["ranges"] == [{"start": 1, "end": 2}]


def test_initial_prompt_empty_snippet_files_do_not_register_empty_ranges(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "empty.py"
    source.write_text("", encoding="utf-8")
    ranked = [SimpleNamespace(path="src/empty.py", score=1.0, layer="test", reasons=[])]

    class FakeRanker:
        def __init__(self, repo):
            self.repo = repo

        def rank(self, request, *, limit=None):
            return ranked

    monkeypatch.setattr("lbh.workflow.SearchRanker", FakeRanker)
    monkeypatch.setattr(ContextPacker, "repo_map", lambda self, ranked: "")

    session_root, initial_prompt = create_session_for_request(
        tmp_path,
        "fix empty",
        config=Config({"context": {"snippet_lines": 2}}),
    )

    prompt = initial_prompt.read_text(encoding="utf-8")
    assert '<snippet path="src/empty.py"' in prompt
    assert 'lines="1-0"' in prompt

    manifest = SessionManager(tmp_path).load_manifest(session_root)
    entry = manifest["read_files"]["src/empty.py"]
    assert entry["sha256"]
    assert entry["ranges"] == []
