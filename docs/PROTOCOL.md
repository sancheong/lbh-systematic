# LBH Protocol

## Overview

LBH assumes the model cannot directly read local files. The model must work only from context provided through LBH prompts and context append artifacts.

Under `lbh automate` or `gateway-run`, the output modes remain explicit:

- tool requests use exactly one fenced `lbh-tool` block
- final patches may use exactly one fenced `lbh-hashline-patch` block
- final patches may still use a valid LBH diff form as fallback

The operating flow is:

1. the model requests more context with `lbh-tool`
2. LBH returns file bodies and discovery results
3. the model emits a final patch plan
4. LBH validates and materializes a candidate diff
5. candidate validation must pass before `patch.diff` exists

## Hard Rules

```text
1. Use only context that LBH already provided in this session.
2. If more context is needed, output exactly one fenced `lbh-tool` block.
3. Do not output raw JSON by itself or a `json` fenced block for tool requests.
4. Do not modify an existing file unless its body was provided as `<file>` or `<snippet>` context.
5. New files may be created without READ only when the patch explicitly uses the supported new-file form and the path is allowed.
6. Repository map, grep results, symbol search results, and import paths do not satisfy read-before-modify.
7. Prefer `lbh-hashline-patch` for final patches. Use diff only as fallback.
8. If uncertain, request more context instead of guessing.
```

## Tool Request Format

```lbh-tool
{
  "type": "context_request",
  "requests": [
    {
      "op": "READ",
      "path": "src/payments/checkout.ts",
      "ranges": [{"start": 1, "end": 160}],
      "why": "Need to inspect checkout flow."
    }
  ]
}
```

Supported ops:

- `READ`: `op`, `path`, `ranges`, `why`
- `GREP`: `op`, `pattern` or `query`, `globs`, `max_results`, `why`
- `FIND_SYMBOL`: `op`, `query` or `pattern`, `max_results`, `why`
- `LIST_DIR`: `op`, `path`, `why`
- `DEP_GRAPH`: `op`, `path`, `why`
- `TEST_HINTS`: `op`, `path`, `why`

Legacy shorthand is still accepted in manual flows:

```text
[READ: src/foo.py]
[READ: src/foo.py#1-120]
```

## Hashline Context Format

When LBH provides file bodies or snippets for editable context, it emits hashline-formatted lines:

```markdown
<file path="src/foo.py" sha256="..." lines="17-19" line_format="hashline">
@@LINE[17,a1b2c3]@@ def foo():
@@LINE[18,d4e5f6]@@     pass
@@LINE[19,9a8b7c]@@
</file>
```

Each visible line contains:

- a `@@LINE[num,hash]@@` anchor
- the source line number inside that anchor
- a short content hash for that exact line inside that anchor
- the line text after the anchor

Each `@@LINE[num,hash]@@` anchor is a single source of truth for both the displayed line number and its content hash. For a hashline patch, `start_line` and `start_hash` must be copied from the same starting anchor, and `end_line` and `end_hash` must be copied from the same ending anchor. Preserve the full anchor text exactly when referring to context. Never split, reformat, renumber, recompute, translate, or rewrite anchors into legacy forms such as `12#a1b2c3 | code`.

## Preferred Final Patch Format

Preferred final patch mode:

```lbh-hashline-patch
{
  "type": "hashline_patch",
  "edits": [
    {
      "path": "src/foo.py",
      "start_line": 1,
      "start_hash": "a1b2c3",
      "end_line": 2,
      "end_hash": "d4e5f6",
      "new": "def foo():\n    return 1"
    }
  ]
}
```

Rules:

- Output exactly one fenced `lbh-hashline-patch` block and nothing else.
- For existing-file edits, `new` must be the full replacement block text.
- For existing-file edits, use the anchored span (`start_line`, `start_hash`, `end_line`, `end_hash`) as the primary source locator.
- Copy `start_line` and `start_hash` from the same starting `@@LINE[num,hash]@@` anchor, and copy `end_line` and `end_hash` from the same ending anchor.
- Treat each `@@LINE[...]@@` marker as an indivisible context anchor and a single source of truth for its line number and hash. Do not split, reformat, renumber, recompute, translate, or rewrite it into any other notation.
- Never rewrite anchors into legacy forms such as `12#a1b2c3 | code`.
- For new files, use an edit with `create: true`, `path`, and `new`; omit line anchors, `old`, and `block_hash`.
- New-file edits must target paths that do not already exist.
- Do not retype the full `old` source block unless LBH explicitly asks for it.
- `block_hash` is optional extra verification when LBH context explicitly provides it.
- Prefer a small number of precise block replacements over whole-file rewrites.
- Do not emit overlapping `edits` for the same file.
- If one conceptual change renumbers or rewrites adjacent lines, emit one larger replacement block instead of multiple overlapping edits.
- Do not invent line numbers or hashes.
- If an existing target file was not provided as body context, request it first with `lbh-tool`.

LBH validates anchors against current file content for existing files, validates new-file creation targets, applies the edits deterministically in memory, and materializes a real unified diff for existing validation and apply steps.

## Diff Fallback

Fallback diff mode is still supported:

````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,2 +1,2 @@
-def foo():
+def foo():
+    return 1
<<<LBH_DIFF_END>>>
````

Use diff fallback only when the requested change cannot be expressed cleanly as anchored block replacements.

## Validation

LBH enforces:

- target paths must stay inside the repo root
- excluded files such as secrets and ignored artifacts are blocked
- existing file modifications must satisfy read-before-modify
- hashline new-file edits must materialize as real new-file diffs so validation can apply `allow_new_files_without_read`
- final candidates must still pass deterministic validation
- materialized diffs must pass `git apply --check` before promotion to `patch.diff`
