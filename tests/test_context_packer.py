from lbh.context.packer import ContextPacker
from lbh.core.config import Config


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
    assert "Document and Markdown files follow the same read-before-modify rule." in prompt
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
    assert "prefer the LBH sentinel diff format" in prompt
    assert '<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>' in prompt
    assert "inside it you must still produce a pure git unified diff" in prompt
