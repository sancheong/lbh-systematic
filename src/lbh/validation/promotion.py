from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lbh.core.fs import write_text_exact
from lbh.core.models import CandidateValidation
from lbh.validation.checks import (
    CheckResult,
    run_cli_smoke,
    run_compile_check,
    run_targeted_tests,
    run_undefined_name_check,
)
from lbh.validation.test_selector import select_tests


@dataclass
class PromotionResult:
    ok: bool
    status: str
    failed_check: str | None
    exact_stop_reason: str
    candidate_path: Path
    promoted_patch_path: Path | None = None
    checks: list[CheckResult] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    selected_tests: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_dir: Path | None = None

    def to_dict(self, session_root: Path | None = None) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "failed_check": self.failed_check,
            "exact_stop_reason": self.exact_stop_reason,
            "candidate_path": _rel_or_str(self.candidate_path, session_root),
            "promoted_patch_path": _rel_or_str(self.promoted_patch_path, session_root) if self.promoted_patch_path else None,
            "checks": [check.to_dict() for check in self.checks],
            "validation_summary": self.validation_summary,
            "modified_files": list(self.modified_files),
            "selected_tests": list(self.selected_tests),
            "warnings": list(self.warnings),
            "artifact_dir": _rel_or_str(self.artifact_dir, session_root) if self.artifact_dir else None,
        }

    @property
    def validation_summary(self) -> dict[str, str]:
        summary = {
            "protocol": "passed",
            "diff": "passed",
            "sandbox_apply": "not_run",
            "static": "not_run",
            "targeted_tests": "not_run",
            "cli_smoke": "not_run",
        }
        for check in self.checks:
            summary[check.kind] = check.status
        return summary


def promote_candidate(
    *,
    repo_root: Path,
    session_root: Path,
    candidate_path: Path,
    validation: CandidateValidation,
    patch_path: Path,
) -> PromotionResult:
    artifact_dir = session_root / "promotion" / candidate_path.stem
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if not validation.structural_ok:
        return PromotionResult(
            ok=False,
            status=_candidate_rejected_status(validation),
            failed_check="candidate_structural",
            exact_stop_reason=_first_validation_error(validation),
            candidate_path=candidate_path,
            modified_files=list(validation.modified_files),
            artifact_dir=artifact_dir,
        )

    sandbox_result = _prepare_sandbox(repo_root, artifact_dir)
    if not sandbox_result.ok:
        return sandbox_result._replace_candidate(candidate_path, validation.modified_files)

    sandbox_root = artifact_dir / "sandbox"
    apply_check = _apply_in_sandbox(sandbox_root, candidate_path, artifact_dir)
    checks: list[CheckResult] = [apply_check]
    if apply_check.status != "passed":
        return _failed_result(
            status="promotion_failed_sandbox_apply",
            failed_check="sandbox_apply",
            exact_stop_reason=apply_check.summary,
            candidate_path=candidate_path,
            modified_files=validation.modified_files,
            checks=checks,
            artifact_dir=artifact_dir,
        )

    compile_check = run_compile_check(sandbox_root, validation.modified_files, artifact_dir)
    checks.append(compile_check)
    if compile_check.status == "failed":
        return _failed_result(
            status="promotion_failed_static",
            failed_check="static",
            exact_stop_reason=compile_check.summary,
            candidate_path=candidate_path,
            modified_files=validation.modified_files,
            checks=checks,
            artifact_dir=artifact_dir,
        )

    undefined_check = run_undefined_name_check(sandbox_root, validation.modified_files, artifact_dir)
    checks.append(undefined_check)
    if undefined_check.status == "failed":
        return _failed_result(
            status="promotion_failed_static",
            failed_check="static",
            exact_stop_reason=undefined_check.summary,
            candidate_path=candidate_path,
            modified_files=validation.modified_files,
            checks=checks,
            artifact_dir=artifact_dir,
        )

    selected_tests, selector_warnings = select_tests(repo_root, validation.modified_files)
    test_check = run_targeted_tests(sandbox_root, selected_tests, artifact_dir)
    test_check.warnings.extend(selector_warnings)
    checks.append(test_check)
    if test_check.status == "failed":
        return _failed_result(
            status="promotion_failed_tests",
            failed_check="targeted_tests",
            exact_stop_reason=test_check.summary,
            candidate_path=candidate_path,
            modified_files=validation.modified_files,
            checks=checks,
            selected_tests=selected_tests,
            warnings=selector_warnings,
            artifact_dir=artifact_dir,
        )

    cli_check = run_cli_smoke(sandbox_root, artifact_dir)
    checks.append(cli_check)
    if cli_check.status == "failed":
        return _failed_result(
            status="promotion_failed_cli_smoke",
            failed_check="cli_smoke",
            exact_stop_reason=cli_check.summary,
            candidate_path=candidate_path,
            modified_files=validation.modified_files,
            checks=checks,
            selected_tests=selected_tests,
            warnings=selector_warnings,
            artifact_dir=artifact_dir,
        )

    write_text_exact(patch_path, candidate_path.read_text(encoding="utf-8"))
    return PromotionResult(
        ok=True,
        status="patch_ready",
        failed_check=None,
        exact_stop_reason="",
        candidate_path=candidate_path,
        promoted_patch_path=patch_path,
        checks=checks,
        modified_files=list(validation.modified_files),
        selected_tests=selected_tests,
        warnings=selector_warnings,
        artifact_dir=artifact_dir,
    )


@dataclass
class _SandboxPrepareResult:
    ok: bool
    status: str = "passed"
    summary: str = ""

    def _replace_candidate(self, candidate_path: Path, modified_files: list[str]) -> PromotionResult:
        return PromotionResult(
            ok=False,
            status=self.status,
            failed_check="sandbox_prepare",
            exact_stop_reason=self.summary,
            candidate_path=candidate_path,
            modified_files=list(modified_files),
        )


def _prepare_sandbox(repo_root: Path, artifact_dir: Path) -> _SandboxPrepareResult:
    sandbox_root = artifact_dir / "sandbox"
    try:
        shutil.copytree(repo_root, sandbox_root, ignore=_copy_ignore)
    except OSError as exc:
        return _SandboxPrepareResult(
            ok=False,
            status="promotion_failed_sandbox_prepare",
            summary=f"sandbox prepare failed: {exc}",
        )
    return _SandboxPrepareResult(ok=True)


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {
        ".git",
        ".lbh",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
        "coverage",
        ".venv",
        "venv",
    }
    return {name for name in names if name in ignored}


def _apply_in_sandbox(sandbox_root: Path, candidate_path: Path, artifact_dir: Path) -> CheckResult:
    command = ["git", "apply", "--whitespace=fix", str(candidate_path)]
    env = os.environ.copy()
    env["GIT_CEILING_DIRECTORIES"] = str(artifact_dir)
    proc = subprocess.run(
        command,
        cwd=sandbox_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    artifact = artifact_dir / "sandbox_apply.log"
    artifact.write_text(proc.stdout, encoding="utf-8")
    return CheckResult(
        name="git_apply",
        kind="sandbox_apply",
        status="passed" if proc.returncode == 0 else "failed",
        command=command,
        artifact=artifact.name,
        summary="sandbox apply passed" if proc.returncode == 0 else _first_line(proc.stdout, "sandbox apply failed"),
    )


def _failed_result(
    *,
    status: str,
    failed_check: str,
    exact_stop_reason: str,
    candidate_path: Path,
    modified_files: list[str],
    checks: list[CheckResult],
    selected_tests: list[str] | None = None,
    warnings: list[str] | None = None,
    artifact_dir: Path,
) -> PromotionResult:
    return PromotionResult(
        ok=False,
        status=status,
        failed_check=failed_check,
        exact_stop_reason=exact_stop_reason,
        candidate_path=candidate_path,
        checks=checks,
        modified_files=list(modified_files),
        selected_tests=list(selected_tests or []),
        warnings=list(warnings or []),
        artifact_dir=artifact_dir,
    )


def write_promotion_result(session_root: Path, result: PromotionResult) -> Path:
    artifact_dir = result.artifact_dir or (session_root / "promotion" / result.candidate_path.stem)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "promotion.json"
    path.write_text(json.dumps(result.to_dict(session_root), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _candidate_rejected_status(validation: CandidateValidation) -> str:
    kinds = {issue.kind for issue in validation.errors}
    if "protocol_invention" in kinds:
        return "candidate_rejected_protocol"
    if "apply_check_failed" in kinds:
        return "candidate_rejected_apply_check"
    return "candidate_rejected_diff"


def _first_validation_error(validation: CandidateValidation) -> str:
    if validation.errors:
        return validation.errors[0].message
    return "candidate structural validation failed"


def _first_line(text: str, fallback: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return fallback


def _rel_or_str(path: Path | None, root: Path | None) -> str | None:
    if path is None:
        return None
    if root is not None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return str(path)
