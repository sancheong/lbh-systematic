from lbh.protocol.parser import extract_diff, parse_tool_requests


def test_parse_legacy_read():
    reqs = parse_tool_requests("[READ: src/foo.py#2-5]")
    assert len(reqs) == 1
    assert reqs[0].op == "READ"
    assert reqs[0].path == "src/foo.py"
    assert reqs[0].ranges[0].start == 2
    assert reqs[0].ranges[0].end == 5


def test_parse_lbh_tool_json():
    raw = """```lbh-tool
{"type":"context_request","requests":[{"op":"GREP","pattern":"hello","globs":["src/**"]}]}
```"""
    reqs = parse_tool_requests(raw)
    assert reqs[0].op == "GREP"
    assert reqs[0].pattern == "hello"


def test_extract_sentinel_diff():
    raw = "<<<LBH_DIFF_BEGIN>>>\ndiff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n<<<LBH_DIFF_END>>>"
    diff = extract_diff(raw)
    assert diff is not None
    assert diff.startswith("diff --git")
