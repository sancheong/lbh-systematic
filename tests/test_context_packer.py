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
    assert "inspect the prompt generator, parser, CLI, tests, and docs together" in prompt
    assert "prefer the LBH sentinel diff format" in prompt
    assert '<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>' in prompt
