from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CORE_SMOKE_TESTS = [
    "tests/test_run_command.py",
    "tests/test_preflight.py",
    "tests/test_catgpt_gateway_transport.py",
]


DEFAULT_TEST_MAP = {
    "src/lbh/run_command.py": [
        "tests/test_run_command.py",
        "tests/test_preflight.py",
    ],
    "src/lbh/preflight.py": [
        "tests/test_preflight.py",
        "tests/test_run_command.py",
    ],
    "src/lbh/gateway_loop.py": [
        "tests/test_catgpt_gateway_transport.py",
        "tests/test_candidate_patch_workflow.py",
    ],
    "src/lbh/workflow.py": [
        "tests/test_candidate_patch_workflow.py",
        "tests/test_automation_runner.py",
    ],
    "src/lbh/patch/candidate.py": [
        "tests/test_candidate_patch_workflow.py",
        "tests/test_candidate_repair.py",
    ],
    "src/lbh/core/request_classification.py": [
        "tests/test_request_classification.py",
        "tests/test_catgpt_gateway_transport.py",
    ],
}


def select_tests(repo_root: Path, modified_files: list[str]) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    warnings: list[str] = []
    test_map = _load_test_map(repo_root)

    for rel_path in modified_files:
        _extend(selected, test_map.get(rel_path, []))
        _extend(selected, _naming_fallbacks(rel_path))

    existing = [path for path in selected if (repo_root / path).exists()]
    missing = [path for path in selected if not (repo_root / path).exists()]
    for path in missing:
        warnings.append(f"selected test path does not exist: {path}")

    if not existing:
        core_existing = [path for path in CORE_SMOKE_TESTS if (repo_root / path).exists()]
        if core_existing:
            warnings.append("no targeted tests found; using core smoke fallback")
            existing = core_existing
        else:
            warnings.append("no targeted tests found; no test files exist for fallback")

    return _unique(existing), warnings


def _load_test_map(repo_root: Path) -> dict[str, list[str]]:
    merged = {key: list(value) for key, value in DEFAULT_TEST_MAP.items()}
    path = repo_root / ".vibe" / "knowledge" / "test_map.json"
    if not path.exists():
        return merged
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return merged
    if not isinstance(raw, dict):
        return merged
    for source, tests in raw.items():
        if not isinstance(source, str) or not isinstance(tests, list):
            continue
        clean_tests = [item for item in tests if isinstance(item, str)]
        if clean_tests:
            merged.setdefault(source.replace("\\", "/"), [])
            _extend(merged[source.replace("\\", "/")], clean_tests)
    return merged


def _naming_fallbacks(rel_path: str) -> list[str]:
    rel = rel_path.replace("\\", "/")
    if not rel.endswith(".py") or rel.startswith("tests/"):
        return []
    path = Path(rel)
    stem = path.stem
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    candidates = [f"tests/test_{stem}.py"]
    if len(parts) >= 2:
        candidates.append(f"tests/test_{'_'.join(parts[1:])}.py")
    return candidates


def _extend(target: list[str], values: list[str] | tuple[str, ...]) -> None:
    for value in values:
        clean = value.replace("\\", "/")
        if clean not in target:
            target.append(clean)


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
