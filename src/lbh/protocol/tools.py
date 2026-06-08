from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from lbh.core.config import Config
from lbh.core.fs import format_hashline_lines, read_text, redact_secrets, sha256_file
from lbh.core.models import ReadRange, ToolRequest
from lbh.core.paths import resolve_repo_path, to_repo_rel
from lbh.indexer.store import IndexStore
from lbh.core.paths import index_dir
from lbh.session.manager import SessionManager


class ToolExecutor:
    def __init__(self, repo_root: Path, config: Config, session_root: Path):
        self.repo_root = repo_root
        self.config = config
        self.session_root = session_root
        self.sessions = SessionManager(repo_root)
        self.store = IndexStore(index_dir(repo_root) / "files.sqlite")

    def execute(self, requests: list[ToolRequest]) -> str:
        if len(requests) > self.config.max_tool_requests_per_round:
            requests = requests[: self.config.max_tool_requests_per_round]
        blocks: list[str] = ["# LBH CONTEXT APPEND", "", f"session: {self.session_root.name}", ""]
        for req in requests:
            if req.op == "READ":
                blocks.append(self._read(req))
            elif req.op == "GREP":
                blocks.append(self._grep(req))
            elif req.op == "FIND_SYMBOL":
                blocks.append(self._find_symbol(req))
            elif req.op == "LIST_DIR":
                blocks.append(self._list_dir(req))
            elif req.op == "DEP_GRAPH":
                blocks.append(self._dep_graph(req))
            elif req.op == "TEST_HINTS":
                blocks.append(self._test_hints(req))
            else:
                blocks.append(f"<tool-error op=\"{req.op}\">unsupported op</tool-error>")
        return "\n\n".join(blocks).strip() + "\n"

    def _validate_path(self, path: str) -> Path:
        rel = path.replace("\\", "/")
        if self.config.is_excluded(rel):
            raise ValueError(f"path is excluded by config: {rel}")
        return resolve_repo_path(self.repo_root, rel)

    def _read(self, req: ToolRequest) -> str:
        path = self._validate_path(req.path)
        if not path.exists() or not path.is_file():
            return f'<tool-error op="READ" path="{req.path}">file not found</tool-error>'
        text = read_text(path)
        if self.config.redact_secrets:
            text = redact_secrets(text)
        total = len(text.splitlines())
        ranges = req.ranges or [ReadRange(1, min(total, self.config.max_lazy_read_lines))]
        blocks: list[str] = []
        registered_ranges: list[dict[str, int]] = []
        for rr in ranges:
            start = max(1, rr.start)
            end = min(total, rr.end)
            if end - start + 1 > self.config.max_lazy_read_lines:
                end = start + self.config.max_lazy_read_lines - 1
            numbered = format_hashline_lines(text, start, end)
            blocks.append(
                f'<file path="{req.path}" sha256="{sha256_file(path)}" lines="{start}-{end}" line_format="hashline">'
                f"\n{numbered}\n</file>"
            )
            registered_ranges.append({"start": start, "end": end})
        self.sessions.register_read_file(self.session_root, req.path, sha256_file(path), registered_ranges)
        return "\n\n".join(blocks)

    def _grep(self, req: ToolRequest) -> str:
        pattern = req.pattern or req.query
        if not pattern:
            return '<tool-error op="GREP">missing pattern</tool-error>'
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern), re.I)
        globs = req.globs or ["**/*"]
        matches: list[str] = []
        with self.store.connect() as conn:
            rows = conn.execute("SELECT path FROM files ORDER BY path").fetchall()
        for row in rows:
            rel = row["path"]
            if self.config.is_excluded(rel):
                continue
            if not any(fnmatch.fnmatch(rel, g) or g == "**/*" for g in globs):
                continue
            path = self.repo_root / rel
            try:
                for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    if regex.search(line):
                        matches.append(f"{rel}:{i}: {line.strip()[:240]}")
                        if len(matches) >= req.max_results:
                            break
            except OSError:
                continue
            if len(matches) >= req.max_results:
                break
        body = "\n".join(matches) if matches else "no matches"
        return f'<grep pattern="{pattern}">\n{body}\n</grep>'

    def _find_symbol(self, req: ToolRequest) -> str:
        query = req.query or req.pattern
        if not query:
            return '<tool-error op="FIND_SYMBOL">missing query</tool-error>'
        q = f"%{query.lower()}%"
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT f.path, s.kind, s.name, s.signature, s.start_line, s.end_line
                FROM symbols s JOIN files f ON s.file_id = f.id
                WHERE lower(s.name) LIKE ? OR lower(s.signature) LIKE ?
                ORDER BY f.path, s.start_line
                LIMIT ?
                """,
                (q, q, req.max_results),
            ).fetchall()
        lines = [f"{r['path']}:{r['start_line']}-{r['end_line']} {r['kind']} {r['signature'] or r['name']}" for r in rows]
        return f'<symbols query="{query}">\n' + ("\n".join(lines) if lines else "no symbols") + "\n</symbols>"

    def _list_dir(self, req: ToolRequest) -> str:
        rel = req.path or "."
        path = self._validate_path(rel) if rel != "." else self.repo_root
        if not path.exists() or not path.is_dir():
            return f'<tool-error op="LIST_DIR" path="{rel}">directory not found</tool-error>'
        entries: list[str] = []
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            child_rel = to_repo_rel(self.repo_root, child)
            if self.config.is_excluded(child_rel):
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(child_rel + suffix)
        return f'<dir path="{rel}">\n' + "\n".join(entries[:200]) + "\n</dir>"

    def _dep_graph(self, req: ToolRequest) -> str:
        if not req.path:
            return '<tool-error op="DEP_GRAPH">missing path</tool-error>'
        rel = req.path
        with self.store.connect() as conn:
            row = conn.execute("SELECT id FROM files WHERE path = ?", (rel,)).fetchone()
            if not row:
                return f'<tool-error op="DEP_GRAPH" path="{rel}">file not indexed</tool-error>'
            fid = int(row["id"])
            outgoing = conn.execute(
                "SELECT f2.path, e.edge_kind, e.evidence FROM edges e JOIN files f2 ON e.dst_file_id = f2.id WHERE e.src_file_id = ?",
                (fid,),
            ).fetchall()
            incoming = conn.execute(
                "SELECT f1.path, e.edge_kind, e.evidence FROM edges e JOIN files f1 ON e.src_file_id = f1.id WHERE e.dst_file_id = ?",
                (fid,),
            ).fetchall()
        lines = ["outgoing:"] + [f"  -> {r['path']} ({r['edge_kind']}: {r['evidence']})" for r in outgoing]
        lines += ["incoming:"] + [f"  <- {r['path']} ({r['edge_kind']}: {r['evidence']})" for r in incoming]
        return f'<dep-graph path="{rel}">\n' + "\n".join(lines) + "\n</dep-graph>"

    def _test_hints(self, req: ToolRequest) -> str:
        paths = []
        if req.path:
            paths.append(req.path)
        raw_paths = req.raw.get("paths") if isinstance(req.raw, dict) else None
        if isinstance(raw_paths, list):
            paths.extend(str(p) for p in raw_paths)
        stems = {Path(p).stem.lower().replace(".test", "").replace(".spec", "") for p in paths if p}
        hints: list[str] = []
        with self.store.connect() as conn:
            rows = conn.execute("SELECT path FROM files WHERE is_test = 1 ORDER BY path").fetchall()
        for row in rows:
            rel = row["path"]
            low = rel.lower()
            if any(stem and stem in low for stem in stems) or any(x in low for x in ["payment", "notification", "checkout"]):
                hints.append(rel)
        return "<test-hints>\n" + ("\n".join(hints[:80]) if hints else "no obvious test hints") + "\n</test-hints>"
