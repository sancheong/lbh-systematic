from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_DIFF_CHARS = 50000
MAX_REVIEW_CHARS = 30000


@dataclass(frozen=True)
class ReviewArtifacts:
    index: int
    root: Path
    prompt: Path
    response: Path
    writer_feedback: Path


def next_review_index(session_root: Path) -> int:
    root = session_root / "reviewers"
    indexes: list[int] = []
    if root.exists():
        for path in root.glob("review_*.prompt.md"):
            try:
                indexes.append(int(path.stem.split("_")[1].split(".")[0]))
            except (IndexError, ValueError):
                continue
    return max(indexes, default=0) + 1


def review_artifacts(session_root: Path, index: int) -> ReviewArtifacts:
    root = session_root / "reviewers"
    root.mkdir(parents=True, exist_ok=True)
    stem = f"review_{index:03d}"
    return ReviewArtifacts(
        index=index,
        root=root,
        prompt=root / f"{stem}.prompt.md",
        response=root / f"{stem}.response.md",
        writer_feedback=root / f"{stem}.writer_feedback.md",
    )


def build_reviewer_prompt(
    *,
    session_root: Path,
    manifest: dict[str, Any],
    candidate_entry: dict[str, Any],
) -> str:
    candidate_rel = str(candidate_entry.get("path") or "")
    validation_rel = str(candidate_entry.get("validation") or "")
    promotion_rel = str(candidate_entry.get("promotion") or "")
    candidate_text = _read_rel(session_root, candidate_rel)
    validation = _read_json_rel(session_root, validation_rel)
    promotion = _read_json_rel(session_root, promotion_rel)

    return "\n".join(
        [
            "# LBH Reviewer Task",
            "",
            "You are the reviewer ChatGPT session. A separate writer ChatGPT session produced the candidate patch below.",
            "Your job is to diagnose why the candidate is unsafe or invalid and produce focused feedback for the writer.",
            "",
            "Do not write a replacement patch.",
            "Do not broaden the requested change.",
            "Treat the candidate as a complete patch against the original session base.",
            "Focus on the failed gate and any directly related defects that would block promotion.",
            "",
            "Return concise Markdown with this exact shape:",
            "",
            "```text",
            "VERDICT: revise",
            "BLOCKING ISSUES:",
            "- <file>: <specific issue>",
            "REQUIRED WRITER CHANGES:",
            "- <specific change the writer must make>",
            "TESTS TO RUN:",
            "- <test command or test path>",
            "```",
            "",
            "## Original User Request",
            "",
            str(manifest.get("user_request") or ""),
            "",
            "## Candidate Metadata",
            "",
            "```json",
            json.dumps(
                {
                    "candidate": candidate_rel,
                    "status": candidate_entry.get("status"),
                    "failed_check": candidate_entry.get("failed_check"),
                    "modified_files": promotion.get("modified_files"),
                    "selected_tests": promotion.get("selected_tests"),
                    "validation_summary": promotion.get("validation_summary"),
                    "exact_stop_reason": promotion.get("exact_stop_reason"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Candidate Validation",
            "",
            "```json",
            json.dumps(_compact_validation(validation), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Promotion Checks",
            "",
            "```json",
            json.dumps(promotion.get("checks") or [], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Candidate Diff",
            "",
            "```diff",
            _truncate(candidate_text, MAX_DIFF_CHARS),
            "```",
            "",
        ]
    )


def build_writer_feedback_prompt(
    *,
    base_repair_prompt: str,
    reviewer_response: str,
    candidate_rel: str,
    reviewer_response_rel: str,
) -> str:
    return "\n".join(
        [
            base_repair_prompt.rstrip(),
            "",
            "# Reviewer Feedback",
            "",
            "A separate reviewer ChatGPT session inspected the failed candidate.",
            "Use the feedback below to produce a complete replacement candidate against the original session repository state.",
            "Do not produce an incremental patch against the previous failed candidate.",
            "Fix only the failed gate and directly related blocking issues.",
            "",
            f"Candidate reviewed: `{candidate_rel}`",
            f"Reviewer artifact: `{reviewer_response_rel}`",
            "",
            "```text",
            _truncate(reviewer_response, MAX_REVIEW_CHARS),
            "```",
            "",
        ]
    )


def _read_rel(session_root: Path, rel: str) -> str:
    if not rel:
        return ""
    path = session_root / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json_rel(session_root: Path, rel: str) -> dict[str, Any]:
    text = _read_rel(session_root, rel)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _compact_validation(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": validation.get("ok"),
        "structural_ok": validation.get("structural_ok"),
        "source_mode": validation.get("source_mode"),
        "promoted_to_patch": validation.get("promoted_to_patch"),
        "errors": validation.get("errors") or [],
        "warnings": validation.get("warnings") or [],
        "modified_files": validation.get("modified_files") or [],
    }


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated {len(text) - limit} chars]"
