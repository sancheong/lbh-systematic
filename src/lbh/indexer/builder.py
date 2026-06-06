from __future__ import annotations

import json
from pathlib import Path
from time import time

from lbh.core.config import Config
from lbh.core.fs import classify_layer, detect_lang, is_config_path, is_test_path, read_text, sha256_file
from lbh.core.models import FileRecord, ImportRecord
from lbh.core.paths import index_dir
from lbh.indexer.extractors import LightweightExtractor
from lbh.indexer.scanner import FileScanner
from lbh.indexer.store import IndexStore


def resolve_import(repo_root: Path, src_rel: str, raw: str, all_files: set[str]) -> str:
    """Best-effort resolver for local imports.

    Handles both relative imports such as ``../notifications/bus`` and dotted
    Python-style imports such as ``src.notifications.bus``. The resolver is not
    meant to be a full language server; it only creates useful graph edges for
    context ranking.
    """
    suffixes = ["", ".py", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts", "/index.tsx", "/__init__.py"]
    candidates: list[str] = []
    if raw.startswith("."):
        base = Path(src_rel).parent
        candidates.append((base / raw).as_posix())
        stripped = raw.lstrip(".")
        if stripped:
            candidates.append((base / stripped.replace(".", "/")).as_posix())
    else:
        candidates.append(raw.replace(".", "/"))

    for candidate in candidates:
        for suf in suffixes:
            p = (candidate + suf).replace("//", "/")
            if p in all_files:
                return p
    return ""


class RepoIndexer:
    def __init__(self, repo_root: Path, config: Config):
        self.repo_root = repo_root
        self.config = config
        self.store = IndexStore(index_dir(repo_root) / "files.sqlite")
        self.extractor = LightweightExtractor()

    def rebuild(self) -> dict[str, int]:
        started = time()
        self.store.init_schema()
        self.store.clear()
        scanner = FileScanner(self.repo_root, self.config)
        files = scanner.scan()
        all_files = set(files)

        for rel in files:
            path = self.repo_root / rel
            stat = path.stat()
            text = read_text(path, max_chars=None)
            preview = text[: self.config.content_preview_chars]
            record = FileRecord(
                path=rel,
                lang=detect_lang(rel),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                sha256=sha256_file(path),
                is_test=is_test_path(rel),
                is_config=is_config_path(rel),
                is_generated=False,
                content_preview=preview,
            )
            self.store.insert_file(record)
            extraction = self.extractor.extract(rel, text)
            resolved_imports: list[ImportRecord] = []
            for imp in extraction.imports:
                resolved_imports.append(
                    ImportRecord(
                        src_path=imp.src_path,
                        raw=imp.raw,
                        resolved_path=resolve_import(self.repo_root, rel, imp.raw, all_files),
                        line=imp.line,
                    )
                )
            self.store.insert_symbols(extraction.symbols)
            self.store.insert_imports(resolved_imports)

        self.store.build_edges()
        self.store.rebuild_fts()
        stats = self.store.stats()
        stats["elapsed_ms"] = int((time() - started) * 1000)
        meta = {
            "schema": "lbh.index.v1",
            "stats": stats,
            "note": "Lightweight extractor. Tree-sitter adapter can be added later.",
        }
        index_dir(self.repo_root).mkdir(parents=True, exist_ok=True)
        (index_dir(self.repo_root) / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return stats
