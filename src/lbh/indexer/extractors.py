from __future__ import annotations

import ast
import re
from pathlib import Path

from lbh.core.fs import detect_lang
from lbh.core.models import ExtractionResult, ImportRecord, SymbolRecord

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


class LightweightExtractor:
    """Extract symbols/imports without mandatory third-party dependencies.

    This is intentionally conservative. It is good enough for MVP indexing and
    provides a stable boundary where a Tree-sitter adapter can later be added.
    """

    def extract(self, rel_path: str, text: str) -> ExtractionResult:
        lang = detect_lang(rel_path)
        if lang == "python":
            return self._python(rel_path, text)
        if lang in {"javascript", "jsx", "typescript", "tsx"}:
            return self._js_ts(rel_path, text)
        if lang == "go":
            return self._go(rel_path, text)
        if lang == "rust":
            return self._rust(rel_path, text)
        return self._generic(rel_path, text)

    def _terms(self, text: str, limit: int = 500) -> list[str]:
        seen: set[str] = set()
        terms: list[str] = []
        for m in WORD_RE.finditer(text):
            term = m.group(0)
            low = term.lower()
            if low not in seen:
                seen.add(low)
                terms.append(term)
            if len(terms) >= limit:
                break
        return terms

    def _python(self, rel_path: str, text: str) -> ExtractionResult:
        symbols: list[SymbolRecord] = []
        imports: list[ImportRecord] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._generic(rel_path, text)
        lines = text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno)
                sig = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else node.name
                symbols.append(SymbolRecord(rel_path, node.name, "function", node.lineno, end, sig))
            elif isinstance(node, ast.ClassDef):
                end = getattr(node, "end_lineno", node.lineno)
                sig = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else node.name
                symbols.append(SymbolRecord(rel_path, node.name, "class", node.lineno, end, sig))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportRecord(rel_path, alias.name, line=getattr(node, "lineno", 0)))
            elif isinstance(node, ast.ImportFrom):
                raw = "." * node.level + (node.module or "")
                imports.append(ImportRecord(rel_path, raw, line=getattr(node, "lineno", 0)))
        return ExtractionResult(symbols, imports, self._terms(text))

    def _js_ts(self, rel_path: str, text: str) -> ExtractionResult:
        symbols: list[SymbolRecord] = []
        imports: list[ImportRecord] = []
        lines = text.splitlines()

        import_patterns = [
            re.compile(r"import\s+.*?from\s+[\"']([^\"']+)[\"']"),
            re.compile(r"import\s+[\"']([^\"']+)[\"']"),
            re.compile(r"require\([\"']([^\"']+)[\"']\)"),
            re.compile(r"export\s+.*?from\s+[\"']([^\"']+)[\"']"),
        ]
        symbol_patterns = [
            ("class", re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
            ("function", re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
            ("function", re.compile(r"^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")),
            ("function", re.compile(r"^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function")),
            ("type", re.compile(r"^(?:export\s+)?(?:interface|type)\s+([A-Za-z_$][\w$]*)")),
        ]
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            for pat in import_patterns:
                m = pat.search(stripped)
                if m:
                    imports.append(ImportRecord(rel_path, m.group(1), line=i))
            for kind, pat in symbol_patterns:
                m = pat.search(stripped)
                if m:
                    name = m.group(1)
                    exported = stripped.startswith("export")
                    end = min(len(lines), i + 80)
                    symbols.append(SymbolRecord(rel_path, name, kind, i, end, stripped, exported))
        return ExtractionResult(symbols, imports, self._terms(text))

    def _go(self, rel_path: str, text: str) -> ExtractionResult:
        symbols: list[SymbolRecord] = []
        imports: list[ImportRecord] = []
        lines = text.splitlines()
        func_re = re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
        type_re = re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)\s+")
        import_re = re.compile(r"^[\s\w.]*[\"`]([^\"`]+)[\"`]")
        in_import = False
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("import ("):
                in_import = True
                continue
            if in_import and stripped == ")":
                in_import = False
                continue
            if in_import or stripped.startswith("import "):
                m = import_re.search(stripped.replace("import", "", 1).strip())
                if m:
                    imports.append(ImportRecord(rel_path, m.group(1), line=i))
            m = func_re.search(stripped)
            if m:
                symbols.append(SymbolRecord(rel_path, m.group(1), "function", i, min(len(lines), i + 80), stripped, m.group(1)[0].isupper()))
            m = type_re.search(stripped)
            if m:
                symbols.append(SymbolRecord(rel_path, m.group(1), "type", i, min(len(lines), i + 80), stripped, m.group(1)[0].isupper()))
        return ExtractionResult(symbols, imports, self._terms(text))

    def _rust(self, rel_path: str, text: str) -> ExtractionResult:
        symbols: list[SymbolRecord] = []
        imports: list[ImportRecord] = []
        lines = text.splitlines()
        sym_re = re.compile(r"^(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait|impl)\s+([A-Za-z_][A-Za-z0-9_]*)?")
        use_re = re.compile(r"^use\s+([^;]+);")
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            m = use_re.search(stripped)
            if m:
                imports.append(ImportRecord(rel_path, m.group(1), line=i))
            m = sym_re.search(stripped)
            if m and m.group(1):
                kind = stripped.split()[0].replace("pub", "").strip() or "symbol"
                symbols.append(SymbolRecord(rel_path, m.group(1), kind, i, min(len(lines), i + 80), stripped, stripped.startswith("pub")))
        return ExtractionResult(symbols, imports, self._terms(text))

    def _generic(self, rel_path: str, text: str) -> ExtractionResult:
        symbols: list[SymbolRecord] = []
        lines = text.splitlines()
        heading_re = re.compile(r"^#{1,6}\s+(.+)$")
        for i, line in enumerate(lines[:2000], start=1):
            m = heading_re.search(line.strip())
            if m:
                name = m.group(1).strip()[:80]
                symbols.append(SymbolRecord(rel_path, name, "heading", i, i, line.strip()))
        return ExtractionResult(symbols, [], self._terms(text))
