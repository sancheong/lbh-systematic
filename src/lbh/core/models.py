from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class FileRecord:
    path: str
    lang: str
    size_bytes: int
    mtime_ns: int
    sha256: str
    is_test: bool = False
    is_config: bool = False
    is_generated: bool = False
    content_preview: str = ""


@dataclass(frozen=True)
class SymbolRecord:
    path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    exported: bool = False
    container: str = ""


@dataclass(frozen=True)
class ImportRecord:
    src_path: str
    raw: str
    resolved_path: str = ""
    line: int = 0


@dataclass(frozen=True)
class ExtractionResult:
    symbols: list[SymbolRecord] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RankedFile:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    layer: str = "other"


@dataclass(frozen=True)
class ReadRange:
    start: int
    end: int


@dataclass(frozen=True)
class ToolRequest:
    op: str
    path: str = ""
    ranges: list[ReadRange] = field(default_factory=list)
    pattern: str = ""
    query: str = ""
    globs: list[str] = field(default_factory=list)
    max_results: int = 80
    why: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiffValidationResult:
    ok: bool
    modified_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise ValueError("diff validation failed: " + "; ".join(self.errors))


@dataclass
class SessionPaths:
    root: Path
    request: Path
    initial_prompt: Path
    manifest: Path
    transcript: Path
    patch: Path
