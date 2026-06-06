from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lbh.core.config import Config
from lbh.core.fs import format_numbered_lines, read_text, redact_secrets, sha256_file
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
            numbered = format_numbered_lines(text, 1, end)
            chunks.append(f'<snippet path="{rf.path}" sha256="{sha256_file(path)}" lines="1-{end}">\n{numbered}\n</snippet>')
        return "\n\n".join(chunks)

    def build_initial_prompt(self, user_request: str, ranked: list[RankedFile]) -> str:
        prompt = f"""
# LBH SESSION

You are a senior code repair agent. You cannot access the local filesystem directly.
You must work only from the context provided by LBH.

## User Request

{user_request}

## Hard Rules

1. Do not modify any file unless its content has been provided through LBH context in this session.
2. If you need more information, output exactly one `lbh-tool` block.
3. If you are ready to patch, output exactly one `lbh-diff` block or LBH diff sentinel block.
4. Do not include prose outside the allowed block.
5. Paths must exactly match paths from the repository map or tool results.
6. Prefer minimal READ ranges over full files.
7. Do not request secrets, `.env`, credentials, build artifacts, lockfiles, or ignored files.
8. Do not invent APIs that are not shown in context.
9. Final patch must be a valid git unified diff with `diff --git` headers.
10. When uncertain, request more context instead of guessing.

## Available LBH Tools

```lbh-tool
{{
  "type": "context_request",
  "requests": [
    {{
      "op": "READ",
      "path": "relative/path/from/repo",
      "ranges": [{{"start": 1, "end": 120}}],
      "why": "brief reason"
    }}
  ]
}}
```

Supported ops: READ, GREP, FIND_SYMBOL, LIST_DIR, DEP_GRAPH, TEST_HINTS.

Legacy shorthand is also accepted: `[READ: path]` or `[READ: path#start-end]`.

## Final Patch Format

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
