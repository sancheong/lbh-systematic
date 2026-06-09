from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lbh.core.config import Config
from lbh.core.fs import format_hashline_lines, read_text, redact_secrets, sha256_file
from lbh.core.models import RankedFile
from lbh.core.paths import index_dir
from lbh.indexer.store import IndexStore


class ContextPacker:
    def __init__(self, repo_root: Path, config: Config):
        self.repo_root = repo_root
        self.config = config
        self.store = IndexStore(index_dir(repo_root) / "files.sqlite")

    def repo_head(self) -> str:
        try:
            proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=self.repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
            if proc.returncode == 0:
                return proc.stdout.strip()
        except FileNotFoundError:
            pass
        return "unknown"

    def package_manager_hint(self) -> str:
        checks = [
            ("pnpm-lock.yaml", "pnpm"),
            ("yarn.lock", "yarn"),
            ("package-lock.json", "npm"),
            ("pyproject.toml", "python"),
            ("requirements.txt", "python"),
            ("go.mod", "go"),
            ("Cargo.toml", "rust"),
        ]
        found = [name for file, name in checks if (self.repo_root / file).exists()]
        return ", ".join(dict.fromkeys(found)) or "unknown"

    def relevant_tree(self, ranked: list[RankedFile]) -> str:
        paths = [r.path for r in ranked]
        return "\n".join(f"- {p}" for p in paths)

    def repo_map(self, ranked: list[RankedFile]) -> str:
        lines: list[str] = []
        with self.store.connect() as conn:
            for rf in ranked:
                row = conn.execute("SELECT id, lang FROM files WHERE path = ?", (rf.path,)).fetchone()
                if not row:
                    continue
                fid = int(row["id"])
                lines.append(f"{rf.path}  score={rf.score:.2f} layer={rf.layer}")
                syms = conn.execute("SELECT kind, name, signature, start_line, end_line FROM symbols WHERE file_id = ? ORDER BY start_line LIMIT 20", (fid,)).fetchall()
                for sym in syms:
                    sig = sym["signature"] or sym["name"]
                    lines.append(f"  - {sym['kind']} {sig}  lines={sym['start_line']}-{sym['end_line']}")
                imps = conn.execute("SELECT raw, resolved_path FROM imports WHERE src_file_id = ? LIMIT 15", (fid,)).fetchall()
                if imps:
                    lines.append("  imports:")
                    for imp in imps:
                        resolved = f" -> {imp['resolved_path']}" if imp["resolved_path"] else ""
                        lines.append(f"    - {imp['raw']}{resolved}")
                reasons = "; ".join(rf.reasons[:5])
                if reasons:
                    lines.append(f"  reasons: {reasons}")
                lines.append("")
        return "\n".join(lines).strip()

    def snippets(self, ranked: list[RankedFile]) -> str:
        chunks: list[str] = []
        for rf in ranked[: self.config.initial_file_limit]:
            path = self.repo_root / rf.path
            if not path.exists():
                continue
            text = read_text(path, max_chars=None)
            if self.config.redact_secrets:
                text = redact_secrets(text)
            lines = text.splitlines()
            end = min(len(lines), self.config.snippet_lines)
            numbered = format_hashline_lines(text, 1, end)
            chunks.append(
                f'<snippet path="{rf.path}" sha256="{sha256_file(path)}" lines="1-{end}" line_format="hashline">'
                f"\n{numbered}\n</snippet>"
            )
        return "\n\n".join(chunks)

    def build_initial_prompt(self, user_request: str, ranked: list[RankedFile]) -> str:
        prompt = f"""
# LBH SESSION

You are a senior code repair agent. You cannot access the local filesystem directly.
You must work only from the context provided by LBH.

## User Request

{user_request}

## Hard Rules

1. Do not modify any existing file unless its content has been provided through LBH context in this session.
2. New files may be created without prior READ only with a supported new-file patch form; prefer `lbh-hashline-patch` with `create: true`.
3. If you need more information, output exactly one fenced `lbh-tool` block.
4. The very first non-whitespace characters of a tool request must be three U+0060 backtick characters immediately followed by `lbh-tool`.
5. The block must end with a line that contains exactly three U+0060 backtick characters and nothing else.
6. Do not output raw JSON, a `json` fenced block, or prose outside the `lbh-tool` block when requesting context.
7. Do not prepend commentary such as "Thought for 5s", "Here is the request", or any text before the opening `lbh-tool` fence.
8. If you are ready to patch, prefer exactly one `lbh-hashline-patch` block. Use `lbh-diff` only as fallback when a hashline patch cannot express the change.
9. Before any final diff, verify that every existing file you modify was actually provided in this session through a `<file>` or `<snippet>` block.
10. Repository map, directory tree, grep results, symbol search results, and import paths do not count as file body reads.
11. If any existing file you want to modify has not been provided as file body context yet, do not emit a diff; request it with `lbh-tool` READ first.
12. Document and Markdown files follow the same read-before-modify rule for existing files.
13. A READ path must appear exactly in the Repository Map, Relevant Directory Tree, Evidence Snippets, or prior LBH tool results.
14. Do not derive READ paths from imports, module names, comments, documentation mentions, or conventional package layouts.
15. If you infer that an unlisted file may be relevant, use `GREP`, `FIND_SYMBOL`, `LIST_DIR`, or `DEP_GRAPH` first to discover an exact path.
16. `GREP`, `FIND_SYMBOL`, `LIST_DIR`, `DEP_GRAPH`, and `TEST_HINTS` help you discover or inspect paths, but they do not replace a final file body READ before modification.
17. Prefer minimal READ ranges over full files.
18. Do not request secrets, `.env`, credentials, build artifacts, lockfiles, or ignored files.
19. Do not invent APIs or tool schema fields that are not shown in this prompt.
20. For protocol or output-format changes, inspect the prompt generator, parser, CLI, tests, and docs together. For session or manifest changes, inspect the session manager too.
21. When patching Markdown files that contain fenced code blocks, prefer the LBH sentinel diff format instead of a fenced `lbh-diff` block.
22. The LBH sentinel only wraps the diff; inside it you must still produce a pure git unified diff.
23. Final patch must be a valid git unified diff with `diff --git` headers.
24. LBH automation applies a promoted patch automatically by default; only an explicit skip-apply flag should stop at patch-ready.
25. When uncertain, request more context instead of guessing.

## Available LBH Tools

Tool requests must be exactly one fenced `lbh-tool` block. Raw JSON by itself is invalid. A `json` fenced block is invalid. Do not write explanation text before or after the block.
The request must start with a line consisting of three U+0060 backtick characters followed immediately by `lbh-tool`.
The request must end with a line consisting of exactly three U+0060 backtick characters.
Do not emit commentary, thought summaries, or partial JSON outside the fence.

Allowed request shapes:

- `READ`: `op`, `path`, `ranges`, `why`
- `GREP`: `op`, `pattern` (preferred; current implementation also accepts `query`), `globs`, `max_results`, `why`
- `FIND_SYMBOL`: `op`, `query` (preferred; current implementation also accepts `pattern`), `max_results`, `why`
- `LIST_DIR`: `op`, `path`, `why`
- `DEP_GRAPH`: `op`, `path`, `why`
- `TEST_HINTS`: `op`, `path`, `why`

Do not invent fields that are not listed above. In particular, for `FIND_SYMBOL`, do not use `symbol`.
Do not invent READ paths from imports or documentation mentions; first use discovery tools to confirm an exact path that appears in LBH context.

Example tool request structure:

- Opening line: three U+0060 backtick characters immediately followed by `lbh-tool`
- Body: a single JSON object
- Closing line: exactly three U+0060 backtick characters

Example JSON body:

{{
  "type": "context_request",
  "requests": [
    {{
      "op": "READ",
      "path": "relative/path/from/repo",
      "ranges": [{{"start": 1, "end": 120}}],
      "why": "brief reason"
    }},
    {{
      "op": "GREP",
      "pattern": "notification_bus",
      "globs": ["src/**"],
      "max_results": 20,
      "why": "find call sites"
    }},
    {{
      "op": "FIND_SYMBOL",
      "query": "NotificationBus",
      "max_results": 20,
      "why": "find symbol definitions"
    }},
    {{
      "op": "LIST_DIR",
      "path": "src/notifications",
      "why": "inspect nearby files"
    }},
    {{
      "op": "DEP_GRAPH",
      "path": "src/notifications/bus.py",
      "why": "inspect import neighbors"
    }},
    {{
      "op": "TEST_HINTS",
      "path": "src/notifications/bus.py",
      "why": "find relevant tests"
    }}
  ]
}}

Supported ops: READ, GREP, FIND_SYMBOL, LIST_DIR, DEP_GRAPH, TEST_HINTS.

Legacy shorthand is also accepted: `[READ: path]` or `[READ: path#start-end]`.

## Final Patch Format

Preferred final patch mode is a fenced `lbh-hashline-patch` block.

When LBH provides `<file ... line_format="hashline">` or `<snippet ... line_format="hashline">`, each line is formatted as:

- `<line-number>#<6-hex-content-hash> | <line text>`

Use those anchors in the final patch.

Preferred hashline patch structure:

```lbh-hashline-patch
{{
  "type": "hashline_patch",
  "edits": [
    {{
      "path": "relative/path/from/repo",
      "start_line": 10,
      "start_hash": "a1b2c3",
      "end_line": 12,
      "end_hash": "d4e5f6",
      "new": "replacement block text"
    }}
  ]
}}
```

Rules for `lbh-hashline-patch`:

- Output exactly one fenced `lbh-hashline-patch` block and nothing else.
- For existing-file edits, `new` must be the full replacement block text.
- For existing-file edits, use the anchored span (`start_line`, `start_hash`, `end_line`, `end_hash`) as the primary source locator.
- For new files, use `create: true` with `path` and `new`; omit `start_line`, `start_hash`, `end_line`, `end_hash`, `old`, and `block_hash`.
- New-file edits must target paths that do not already exist.
- Do not retype the full `old` source block unless LBH explicitly asks for it.
- `block_hash` is optional extra verification when LBH context explicitly provides it.
- Prefer a small number of precise block replacements over whole-file rewrites.
- Do not emit overlapping `edits` for the same file.
- If a renumbering or paragraph/list rewrite affects adjacent lines, emit one larger replacement block instead of multiple overlapping edits.
- Do not invent hashes or line numbers; copy them exactly from LBH context.
- If an existing file has not been provided as `<file>` or `<snippet>` body context yet, request it with `lbh-tool` READ instead of emitting a patch.
Preflight before emitting any final diff:

- Check that every existing modified file body was already provided in LBH context in this session.
- New files do not have prior body context, but must use the explicit new-file protocol form and must not already exist.
- Repo map, directory tree, grep results, symbol search results, and import paths are not enough to satisfy read-before-modify.
- If any existing target file has not been provided yet, request it with `lbh-tool` READ instead of emitting a diff.
- This rule applies to documentation files too.
- The LBH sentinel only wraps the diff; it does not relax git unified diff syntax.
- Inside the final diff, never use Markdown bullets, fenced code blocks, explanatory prose, numbered lists, or pseudo-code formatting.
- Every file patch must start at column 1 with `diff --git a/... b/...`.
- Every hunk line must begin with a space, `+`, or `-`.
- When adding code or text, write real added lines prefixed with `+`; do not wrap them in Markdown fences.
- If the diff would likely fail `git apply --check`, do not emit it; request more context instead.

Preferred format when modifying Markdown fenced code blocks:

Use an outer four-backtick-or-longer `text` fence as a transport wrapper so ChatGPT Markdown rendering does not rewrite `+`, `-`, indentation, or backticks inside the diff.
Prefer this wrapped sentinel format over raw sentinel text, especially for Markdown fence edits.

````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/path b/path
--- a/path
+++ b/path
@@ ...
 +real added line
 -removed line
<<<LBH_DIFF_END>>>
````

Transport wrapper rules:

- The outer four-backtick `text` fence is only a transport wrapper.
- The LBH sentinel still wraps a pure git unified diff inside that transport wrapper.
- Inside the final diff, never use Markdown bullets, fenced code blocks, explanatory prose, numbered lists, or pseudo-code formatting.
- Every file patch must start at column 1 with `diff --git a/... b/...`.
- Every hunk line must begin with a space, `+`, or `-`.
- When adding code or text, write real added lines prefixed with `+`; do not wrap them in Markdown fences.
- If the diff would likely fail `git apply --check`, do not emit it; request more context instead.

Alternative fenced format:

```lbh-diff
diff --git a/path b/path
--- a/path
+++ b/path
@@ ...
```

## Repository Header

<repo>
root_name: {self.repo_root.name}
head: {self.repo_head()}
package_manager_hint: {self.package_manager_hint()}
</repo>

## Relevant Directory Tree

<tree>
{self.relevant_tree(ranked)}
</tree>

## Repo Map

<repomap>
{self.repo_map(ranked)}
</repomap>

## Evidence Snippets

{self.snippets(ranked)}
""".strip() + "\n"
        if len(prompt) > self.config.max_prompt_chars:
            prompt = prompt[: self.config.max_prompt_chars] + "\n\n[LBH_TRUNCATED: prompt exceeded max_prompt_chars]\n"
        return prompt
