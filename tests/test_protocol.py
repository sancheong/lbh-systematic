from lbh.protocol.parser import extract_diff, parse_tool_requests, strip_diff_payloads


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


def test_parse_lbh_tool_with_info_string_attributes():
    raw = """```lbh-tool id="tmr4cn"
{"type":"context_request","requests":[{"op":"LIST_DIR","path":"src"}]}
```"""
    reqs = parse_tool_requests(raw)
    assert len(reqs) == 1
    assert reqs[0].op == "LIST_DIR"
    assert reqs[0].path == "src"


def test_extract_sentinel_diff():
    raw = "<<<LBH_DIFF_BEGIN>>>\ndiff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n<<<LBH_DIFF_END>>>"
    diff = extract_diff(raw)
    assert diff is not None
    assert diff.startswith("diff --git")


def test_extract_sentinel_diff_inside_text_fence():
    raw = """````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/a.md b/a.md
--- a/a.md
+++ b/a.md
@@ -1 +1 @@
-old
+new
<<<LBH_DIFF_END>>>
````"""
    diff = extract_diff(raw)
    assert diff is not None
    assert diff.startswith("diff --git")
    assert "+new" in diff


def test_extract_sentinel_diff_with_markdown_fence_content():
    raw = """````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/docs/example.md b/docs/example.md
--- a/docs/example.md
+++ b/docs/example.md
@@ -1 +1,4 @@
 title
+```python
+print("hello")
+```
<<<LBH_DIFF_END>>>
````"""
    diff = extract_diff(raw)
    assert diff is not None
    assert "```python" in diff
    assert '+print("hello")' in diff


def test_extract_sentinel_diff_with_literal_sentinel_text_inside_hunk():
    raw = """````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/docs/example.md b/docs/example.md
--- a/docs/example.md
+++ b/docs/example.md
@@ -1 +1,3 @@
+<<<LBH_DIFF_BEGIN>>>
+example only
+<<<LBH_DIFF_END>>>
<<<LBH_DIFF_END>>>
````"""
    diff = extract_diff(raw)
    assert diff is not None
    assert "+<<<LBH_DIFF_BEGIN>>>" in diff
    assert "+<<<LBH_DIFF_END>>>" in diff


def test_parse_tool_requests_ignores_fences_inside_diff_hunks():
    raw = """````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/docs/protocol.md b/docs/protocol.md
--- a/docs/protocol.md
+++ b/docs/protocol.md
@@ -1 +1,6 @@
+```lbh-answer
+Example explanatory answer.
+```
<<<LBH_DIFF_END>>>
````"""
    reqs = parse_tool_requests(raw)
    assert reqs == []


def test_strip_diff_payloads_removes_legacy_read_examples_inside_diff():
    raw = """````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/docs/example.md b/docs/example.md
--- a/docs/example.md
+++ b/docs/example.md
@@ -1 +1,4 @@
 [READ: src/example.py#1-2]
<<<LBH_DIFF_END>>>
````"""
    stripped = strip_diff_payloads(raw)
    assert stripped.strip() == "````text\n\n````"


def test_parse_tool_requests_does_not_treat_five_backticks_as_triple_fence():
    raw = """`````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/docs/example.md b/docs/example.md
--- a/docs/example.md
+++ b/docs/example.md
@@ -1 +1,6 @@
+```lbh-tool
+{"type":"context_request","requests":[{"op":"LIST_DIR","path":"src"}]}
+```
+[READ: src/example.py#1-2]
<<<LBH_DIFF_END>>>
`````"""
    stripped = strip_diff_payloads(raw)
    reqs = parse_tool_requests(stripped)
    assert reqs == []


def test_extract_diff_from_five_backtick_text_wrapper():
    raw = """`````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-old
+new
<<<LBH_DIFF_END>>>
`````"""
    diff = extract_diff(raw)
    assert diff is not None
    assert diff.startswith("diff --git")
    assert "+new" in diff


def test_strip_diff_payloads_with_literal_sentinel_text_inside_hunk():
    raw = """`````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/docs/example.md b/docs/example.md
--- a/docs/example.md
+++ b/docs/example.md
@@ -1 +1,4 @@
+```lbh-tool
+{"type":"context_request","requests":[{"op":"LIST_DIR","path":"src"}]}
+```
+<<<LBH_DIFF_END>>>
<<<LBH_DIFF_END>>>
`````"""
    stripped = strip_diff_payloads(raw)
    reqs = parse_tool_requests(stripped)
    assert reqs == []
