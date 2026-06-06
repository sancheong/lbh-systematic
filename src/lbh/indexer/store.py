from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from lbh.core.models import FileRecord, ImportRecord, SymbolRecord

SCHEMA_VERSION = 1

SCHEMA = f"""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  lang TEXT,
  size_bytes INTEGER,
  mtime_ns INTEGER,
  sha256 TEXT,
  is_test INTEGER DEFAULT 0,
  is_config INTEGER DEFAULT 0,
  is_generated INTEGER DEFAULT 0,
  content_preview TEXT
);
CREATE TABLE IF NOT EXISTS symbols (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  signature TEXT,
  exported INTEGER DEFAULT 0,
  container TEXT,
  FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY,
  src_file_id INTEGER NOT NULL,
  raw TEXT NOT NULL,
  resolved_path TEXT,
  line INTEGER,
  FOREIGN KEY(src_file_id) REFERENCES files(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS edges (
  src_file_id INTEGER NOT NULL,
  dst_file_id INTEGER NOT NULL,
  edge_kind TEXT NOT NULL,
  weight REAL NOT NULL,
  evidence TEXT,
  PRIMARY KEY(src_file_id, dst_file_id, edge_kind)
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(
  path,
  symbols,
  imports,
  content_preview,
  content=''
);
"""


class IndexStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("schema_version", str(SCHEMA_VERSION)))
            try:
                conn.executescript(FTS_SCHEMA)
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("fts5", "1"))
            except sqlite3.OperationalError:
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("fts5", "0"))

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM imports")
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM files")
            try:
                conn.execute("DELETE FROM fts_files")
            except sqlite3.OperationalError:
                pass

    def insert_file(self, record: FileRecord) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO files(path, lang, size_bytes, mtime_ns, sha256, is_test, is_config, is_generated, content_preview)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                  lang=excluded.lang,
                  size_bytes=excluded.size_bytes,
                  mtime_ns=excluded.mtime_ns,
                  sha256=excluded.sha256,
                  is_test=excluded.is_test,
                  is_config=excluded.is_config,
                  is_generated=excluded.is_generated,
                  content_preview=excluded.content_preview
                """,
                (
                    record.path,
                    record.lang,
                    record.size_bytes,
                    record.mtime_ns,
                    record.sha256,
                    int(record.is_test),
                    int(record.is_config),
                    int(record.is_generated),
                    record.content_preview,
                ),
            )
            row = conn.execute("SELECT id FROM files WHERE path = ?", (record.path,)).fetchone()
            assert row is not None
            return int(row["id"])

    def insert_symbols(self, symbols: list[SymbolRecord]) -> None:
        if not symbols:
            return
        with self.connect() as conn:
            for sym in symbols:
                row = conn.execute("SELECT id FROM files WHERE path = ?", (sym.path,)).fetchone()
                if not row:
                    continue
                conn.execute(
                    """
                    INSERT INTO symbols(file_id, name, kind, start_line, end_line, signature, exported, container)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (int(row["id"]), sym.name, sym.kind, sym.start_line, sym.end_line, sym.signature, int(sym.exported), sym.container),
                )

    def insert_imports(self, imports: list[ImportRecord]) -> None:
        if not imports:
            return
        with self.connect() as conn:
            for imp in imports:
                row = conn.execute("SELECT id FROM files WHERE path = ?", (imp.src_path,)).fetchone()
                if not row:
                    continue
                conn.execute(
                    "INSERT INTO imports(src_file_id, raw, resolved_path, line) VALUES (?, ?, ?, ?)",
                    (int(row["id"]), imp.raw, imp.resolved_path, imp.line),
                )

    def rebuild_fts(self) -> None:
        with self.connect() as conn:
            try:
                conn.execute("DELETE FROM fts_files")
            except sqlite3.OperationalError:
                return
            rows = conn.execute("SELECT id, path, content_preview FROM files ORDER BY path").fetchall()
            for row in rows:
                file_id = int(row["id"])
                syms = " ".join(s["name"] for s in conn.execute("SELECT name FROM symbols WHERE file_id = ?", (file_id,)).fetchall())
                imps = " ".join(i["raw"] for i in conn.execute("SELECT raw FROM imports WHERE src_file_id = ?", (file_id,)).fetchall())
                conn.execute(
                    "INSERT INTO fts_files(rowid, path, symbols, imports, content_preview) VALUES (?, ?, ?, ?, ?)",
                    (file_id, row["path"], syms, imps, row["content_preview"] or ""),
                )

    def build_edges(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM edges")
            files = {row["path"]: int(row["id"]) for row in conn.execute("SELECT id, path FROM files")}
            imports = conn.execute(
                """
                SELECT i.raw, i.resolved_path, i.line, f.id AS src_id, f.path AS src_path
                FROM imports i JOIN files f ON i.src_file_id = f.id
                """
            ).fetchall()
            for imp in imports:
                dst = imp["resolved_path"]
                if dst and dst in files:
                    conn.execute(
                        "INSERT OR REPLACE INTO edges(src_file_id, dst_file_id, edge_kind, weight, evidence) VALUES (?, ?, ?, ?, ?)",
                        (int(imp["src_id"]), files[dst], "import", 1.0, imp["raw"]),
                    )

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                "files": int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
                "symbols": int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]),
                "imports": int(conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]),
                "edges": int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]),
            }

    def get_file(self, path: str):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
