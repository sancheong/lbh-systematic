from __future__ import annotations

import re
from pathlib import Path

from lbh.core.config import Config
from lbh.core.models import CandidateIssue, CandidatePaths, CandidateValidation
from lbh.patch.apply import git_apply_check
from lbh.patch.diff import validate_diff

UNSUPPORTED_BLOCKING_MARKERS = {
    "LBH_ANSWER_BEGIN",
    "LBH_ANSWER_END",
}
ALLOWED_SENTINEL_MARKERS = {
    "LBH_DIFF_BEGIN",
    "LBH_DIFF_END",
}
ALL_LBH_MARKERS_RE = re.compile(r"(?:<<<)?(LBH_[A-Z_]+)(?:[^A-Z_]|$)")


def next_candidate_index(session_root: Path) -> int:
    candidate_dir = session_root / "candidates"
    indexes: list[int] = []
    if candidate_dir.exists():
        for path in candidate_dir.glob("candidate_*.diff"):
            try:
                indexes.append(int(path.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
    return max(indexes, default=0) + 1


def candidate_paths(session_root: Path, index: int) -> CandidatePaths:
    candidate_dir = session_root / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    stem = f"candidate_{index:03d}"
    return CandidatePaths(
        index=index,
        diff=candidate_dir / f"{stem}.diff",
        validation=candidate_dir / f"{stem}.validation.json",
        critique=candidate_dir / f"{stem}.critique.md",
        repair_prompt=candidate_dir / f"{stem}.repair_prompt.md",
    )


def validate_candidate(
    *,
    diff: str,
    raw_response: str,
    candidate: str,
    candidate_path: Path,
    repo_root: Path,
    config: Config,
    read_files: dict[str, object],
    source_mode: str = "diff",
) -> CandidateValidation:
    diff_validation = validate_diff(diff, repo_root, config, read_files=read_files)
    validation = CandidateValidation(
        candidate=candidate,
        ok=False,
        source_mode=source_mode,
        modified_files=list(diff_validation.modified_files),
        new_files=list(diff_validation.new_files),
        deleted_files=list(diff_validation.deleted_files),
    )

    for marker in sorted(set(_find_markers(raw_response))):
        if marker in UNSUPPORTED_BLOCKING_MARKERS:
            validation.errors.append(
                CandidateIssue(
                    kind="protocol_invention",
                    message=f"Unsupported marker {marker} was introduced.",
                )
            )
        elif marker not in ALLOWED_SENTINEL_MARKERS:
            validation.warnings.append(
                CandidateIssue(
                    kind="protocol_marker_warning",
                    message=f"Unknown LBH marker {marker} appeared in the candidate response.",
                    severity="warning",
                )
            )

    for error in diff_validation.errors:
        validation.errors.append(
            CandidateIssue(kind="diff_validation_failed", message=error)
        )
    for warning in diff_validation.warnings:
        validation.warnings.append(
            CandidateIssue(kind="diff_validation_warning", message=warning, severity="warning")
        )

    validation.warnings.extend(_detect_markdown_corruption(diff))

    if diff_validation.ok:
        ok, output = git_apply_check(repo_root, candidate_path)
        if not ok:
            message = "git apply --check failed."
            if output.strip():
                message += f" {output.strip()}"
            validation.errors.append(
                CandidateIssue(kind="apply_check_failed", message=message)
            )

    validation.preserve.extend(_preserve_notes(raw_response))
    validation.repair_instruction.extend(_repair_instructions(validation))
    validation.ok = not validation.errors
    return validation


def render_candidate_critique(validation: CandidateValidation) -> str:
    lines = ["# Candidate Patch Critique", ""]
    if validation.errors:
        lines.extend(["## Blocking issues", ""])
        for i, issue in enumerate(validation.errors, start=1):
            lines.append(f"{i}. {issue.message}")
        lines.append("")
    if validation.warnings:
        lines.extend(["## Warnings", ""])
        for i, issue in enumerate(validation.warnings, start=1):
            lines.append(f"{i}. {issue.message}")
        lines.append("")
    if validation.preserve:
        lines.extend(["## Preserve", ""])
        for item in validation.preserve:
            lines.append(f"- {item}")
        lines.append("")
    lines.extend(["## Repair instruction", ""])
    for item in validation.repair_instruction:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def render_repair_prompt(validation: CandidateValidation) -> str:
    lines = [
        "You are repairing a ChatGPT-generated candidate patch.",
        "",
        "Do not redesign the feature.",
        "Use the candidate patch as the starting point.",
        "Fix only the validation failures listed below.",
        "",
        "Candidate:",
        f"`{validation.candidate}`",
        "",
    ]
    if validation.source_mode == "hashline":
        lines.extend(
            [
                "Original source mode:",
                "`lbh-hashline-patch`",
                "",
                "Keep the repaired output in `lbh-hashline-patch` mode. Do not fall back to a unified diff response.",
                "Use `create: true` for new files instead of switching to diff fallback.",
                "",
            ]
        )
    if validation.errors:
        lines.append("Blocking failures:")
        for i, issue in enumerate(validation.errors, start=1):
            lines.append(f"{i}. {issue.message}")
        lines.append("")
    if validation.warnings:
        lines.append("Warnings to respect:")
        for i, issue in enumerate(validation.warnings, start=1):
            lines.append(f"{i}. {issue.message}")
        lines.append("")
    lines.append("Required repair:")
    for item in validation.repair_instruction:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _find_markers(raw_response: str) -> list[str]:
    return [match.group(1) for match in ALL_LBH_MARKERS_RE.finditer(raw_response)]


def _detect_markdown_corruption(diff: str) -> list[CandidateIssue]:
    warnings: list[CandidateIssue] = []
    if re.search(r"(?m)^ +diff --git ", diff):
        warnings.append(
            CandidateIssue(
                kind="indented_diff_header",
                message="Indented `diff --git` header detected; file patch boundary may be corrupted.",
                severity="warning",
            )
        )
    if len(re.findall(r"(?m)^\* ", diff)) >= 2:
        warnings.append(
            CandidateIssue(
                kind="markdown_bullet_suspected",
                message="Markdown bullet lines were detected inside the candidate diff.",
                severity="warning",
            )
        )
    if re.search(r"(?m)^```", diff):
        warnings.append(
            CandidateIssue(
                kind="raw_markdown_fence",
                message="Prefix-free Markdown fence detected inside the diff body.",
                severity="warning",
            )
        )
    return warnings


def _preserve_notes(raw_response: str) -> list[str]:
    notes: list[str] = []
    if "<<<LBH_DIFF_BEGIN" in raw_response:
        notes.append("Keep the candidate's use of the LBH diff sentinel wrapper where valid.")
    if "````text" in raw_response or "`````text" in raw_response:
        notes.append("Keep the code-fenced diff transport wrapper where valid.")
    if "lbh-hashline-patch" in raw_response:
        notes.append("Preserve the `lbh-hashline-patch` output mode where valid.")
    notes.append("Preserve any hunks that already satisfy unified diff syntax and read-before-modify rules.")
    return notes


def _repair_instructions(validation: CandidateValidation) -> list[str]:
    instructions = ["Revise the candidate patch only. Do not redesign the feature."]
    seen = set(instructions)

    for issue in validation.errors:
        if issue.kind == "protocol_invention":
            _push(instructions, seen, "Remove unsupported protocol markers and keep only supported LBH diff output.")
        elif issue.kind == "diff_validation_failed":
            _push(instructions, seen, issue.message)
        elif issue.kind == "apply_check_failed":
            if validation.source_mode == "hashline":
                _push(
                    instructions,
                    seen,
                    "Make the deterministic materialized diff pass `git apply --check`.",
                )
            else:
                _push(instructions, seen, "Make the patch pass `git apply --check`.")

    for issue in validation.warnings:
        if issue.kind == "markdown_bullet_suspected":
            _push(instructions, seen, "Replace Markdown bullets inside hunks with valid unified diff lines.")
        elif issue.kind == "raw_markdown_fence":
            _push(instructions, seen, "Do not place prefix-free Markdown fences inside the diff body.")
        elif issue.kind == "indented_diff_header":
            _push(instructions, seen, "`diff --git` headers must start at column 1.")

    _push(instructions, seen, "Preserve correct parts of the candidate.")
    if validation.source_mode == "hashline":
        _push(instructions, seen, "Produce exactly one fenced `lbh-hashline-patch` block.")
    else:
        _push(instructions, seen, "Produce a valid git unified diff.")
    return instructions


def _push(items: list[str], seen: set[str], value: str) -> None:
    if value not in seen:
        seen.add(value)
        items.append(value)
