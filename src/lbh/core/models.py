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
    candidates: Path


@dataclass(frozen=True)
class CandidatePaths:
    index: int
    diff: Path
    validation: Path
    critique: Path
    repair_prompt: Path


@dataclass(frozen=True)
class CandidateIssue:
    kind: str
    message: str
    severity: str = "blocking"

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message, "severity": self.severity}


@dataclass
class CandidateValidation:
    candidate: str
    ok: bool
    promoted_to_patch: bool = False
    errors: list[CandidateIssue] = field(default_factory=list)
    warnings: list[CandidateIssue] = field(default_factory=list)
    preserve: list[str] = field(default_factory=list)
    repair_instruction: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "ok": self.ok,
            "promoted_to_patch": self.promoted_to_patch,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "preserve": list(self.preserve),
            "repair_instruction": list(self.repair_instruction),
            "modified_files": list(self.modified_files),
            "new_files": list(self.new_files),
            "deleted_files": list(self.deleted_files),
        }
