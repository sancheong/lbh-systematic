from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lbh.core.config import Config
from lbh.session.manager import SessionManager
from lbh.transport.catgpt_gateway import CatGptGatewayTransport
from lbh.workflow import (
    ResponseOutcome,
    apply_patch_ready,
    create_session_for_prompt,
    create_session_for_request,
    process_response_file,
)


@dataclass(frozen=True)
class GatewayLoopResult:
    session_root: Path
    status: str
    rounds: int
    response_file: Path | None = None
    patch_file: Path | None = None
    message: str = ""
    failed_check: str | None = None
    candidate_path: Path | None = None
    promoted_patch_path: Path | None = None
    validation_summary: dict[str, str] | None = None
    checks: list[dict[str, Any]] | None = None


def run_gateway_loop(
    repo: Path,
    *,
    request: str | None = None,
    request_file: Path | None = None,
    request_label: str | None = None,
    base_url: str,
    api_key: str = "dummy123",
    max_rounds: int = 20,
    limit: int | None = None,
    skip_apply: bool = False,
    transport: CatGptGatewayTransport | None = None,
) -> GatewayLoopResult:
    if (request is None) == (request_file is None):
        raise ValueError("provide exactly one of request or request_file")

    config = Config.load(repo)
    manager = SessionManager(repo)
    if request_file is not None:
        prompt_path = request_file if request_file.is_absolute() else (Path.cwd() / request_file).resolve()
        prompt_text = prompt_path.read_text(encoding="utf-8")
        session_root, initial_prompt = create_session_for_prompt(
            repo,
            prompt_text,
            request_label=request_label or f"prompt-file:{prompt_path.name}",
        )
    else:
        session_root, initial_prompt = create_session_for_request(repo, request or "", config=config, limit=limit)
        manifest = manager.load_manifest(session_root)
        plan = manifest.get("plan")
        if plan:
            prompt_files = plan.get("prompt_files") or []
            return GatewayLoopResult(
                session_root=session_root,
                status="plan_ready",
                rounds=0,
                message=f"Plan mode ready with {len(prompt_files)} task prompt file(s).",
            )

    transport = transport or CatGptGatewayTransport(base_url=base_url, api_key=api_key)
    started = transport.start_session(initial_prompt.read_text(encoding="utf-8"))
    _record_transport_session(manager, session_root, base_url, started.session_id)
    response_file = _write_response_file(manager, session_root, 1, started.response.text, started.response.metadata)
    outcome = process_response_file(repo, session_root, response_file)
    if outcome.return_code == 1:
        return GatewayLoopResult(session_root=session_root, status="blocked", rounds=1, response_file=response_file, message="No tool request or diff found in first response.")
    if not _is_expected_outcome(outcome):
        return GatewayLoopResult(
            session_root=session_root,
            status="blocked",
            rounds=1,
            response_file=response_file,
            message=outcome.error_message or f"Unexpected processing outcome: {outcome.kind}",
        )

    for round_num in range(2, max_rounds + 1):
        patch_file = _promoted_patch_file(manager, session_root)
        if patch_file is not None:
            return _finish_patch_ready(
                repo,
                session_root,
                patch_file,
                rounds=round_num - 1,
                response_file=response_file,
                skip_apply=skip_apply,
            )

        outbound = _next_outbound_artifact(manager, session_root)
        if outbound is None:
            return GatewayLoopResult(session_root=session_root, status="blocked", rounds=round_num - 1, response_file=response_file, message="No pending context append or repair prompt found.")

        reply = transport.send(started.session_id, outbound.read_text(encoding="utf-8"))
        response_file = _write_response_file(manager, session_root, round_num, reply.text, reply.metadata)
        outcome = process_response_file(repo, session_root, response_file)
        if outcome.return_code == 1:
            return GatewayLoopResult(session_root=session_root, status="blocked", rounds=round_num, response_file=response_file, message="No tool request or diff found in response.")
        if not _is_expected_outcome(outcome):
            return GatewayLoopResult(
                session_root=session_root,
                status="blocked",
                rounds=round_num,
                response_file=response_file,
                message=outcome.error_message or f"Unexpected processing outcome: {outcome.kind}",
            )

    patch_file = _promoted_patch_file(manager, session_root)
    if patch_file is not None:
        return _finish_patch_ready(
            repo,
            session_root,
            patch_file,
            rounds=max_rounds,
            response_file=response_file,
            skip_apply=skip_apply,
        )
    return GatewayLoopResult(session_root=session_root, status="max_rounds_exceeded", rounds=max_rounds, response_file=response_file, message="Maximum gateway rounds exceeded.")


def _finish_patch_ready(
    repo: Path,
    session_root: Path,
    patch_file: Path,
    *,
    rounds: int,
    response_file: Path,
    skip_apply: bool,
) -> GatewayLoopResult:
    promotion = _promotion_from_manifest(SessionManager(repo), session_root)
    outcome = apply_patch_ready(repo, patch_file, session_root=session_root, skip_apply=skip_apply)
    if not outcome.ok:
        message = outcome.output or "; ".join(outcome.validation_errors) or "patch apply failed"
        return GatewayLoopResult(
            session_root=session_root,
            status="blocked",
            rounds=rounds,
            response_file=response_file,
            patch_file=patch_file,
            message=message,
            failed_check="apply",
            candidate_path=_candidate_path_from_promotion(session_root, promotion),
            promoted_patch_path=patch_file,
            validation_summary=_validation_summary_from_promotion(promotion),
            checks=_checks_from_promotion(promotion),
        )
    status = "patch_ready" if skip_apply else "applied"
    return GatewayLoopResult(
        session_root=session_root,
        status=status,
        rounds=rounds,
        response_file=response_file,
        patch_file=patch_file,
        message=outcome.output,
        candidate_path=_candidate_path_from_promotion(session_root, promotion),
        promoted_patch_path=patch_file,
        validation_summary=_validation_summary_from_promotion(promotion),
        checks=_checks_from_promotion(promotion),
    )


def _record_transport_session(manager: SessionManager, session_root: Path, base_url: str, session_id: str) -> None:
    manifest = manager.load_manifest(session_root)
    manifest["transport"] = "catgpt-gateway"
    manifest["transport_base_url"] = base_url
    manifest["transport_session_id"] = session_id
    manifest.setdefault("responses", [])
    manager.write_manifest(session_root, manifest)
    manager.append_event(
        session_root,
        {
            "type": "transport_session_started",
            "transport": "catgpt-gateway",
            "base_url": base_url,
            "transport_session_id": session_id,
        },
    )


def _write_response_file(
    manager: SessionManager,
    session_root: Path,
    index: int,
    text: str,
    metadata: dict[str, str] | None,
) -> Path:
    path = session_root / f"response_{index:03d}.md"
    path.write_text(text, encoding="utf-8")
    manifest = manager.load_manifest(session_root)
    manifest.setdefault("responses", []).append(path.name)
    manager.write_manifest(session_root, manifest)
    manager.append_event(
        session_root,
        {
            "type": "transport_response",
            "file": path.name,
            "metadata": metadata or {},
        },
    )
    return path


def _promoted_patch_file(manager: SessionManager, session_root: Path) -> Path | None:
    manifest = manager.load_manifest(session_root)
    patch = manifest.get("patch")
    if not isinstance(patch, dict):
        return None
    promotion = patch.get("promotion")
    if not isinstance(promotion, dict) or promotion.get("ok") is not True:
        return None
    patch_name = patch.get("path")
    promoted_path = promotion.get("promoted_patch_path")
    if patch_name != "patch.diff" or promoted_path != "patch.diff":
        return None
    patch_file = session_root / "patch.diff"
    return patch_file if patch_file.exists() else None


def _promotion_from_manifest(manager: SessionManager, session_root: Path) -> dict[str, Any] | None:
    manifest = manager.load_manifest(session_root)
    patch = manifest.get("patch")
    if isinstance(patch, dict) and isinstance(patch.get("promotion"), dict):
        return patch["promotion"]
    return None


def _candidate_path_from_promotion(session_root: Path, promotion: dict[str, Any] | None) -> Path | None:
    if not promotion:
        return None
    candidate = promotion.get("candidate_path")
    if isinstance(candidate, str):
        return session_root / candidate
    return None


def _validation_summary_from_promotion(promotion: dict[str, Any] | None) -> dict[str, str] | None:
    if not promotion:
        return None
    checks = promotion.get("checks")
    if not isinstance(checks, list):
        return None
    summary = {
        "protocol": "passed",
        "diff": "passed",
        "sandbox_apply": "not_run",
        "static": "not_run",
        "targeted_tests": "not_run",
        "cli_smoke": "not_run",
    }
    for check in checks:
        if isinstance(check, dict) and isinstance(check.get("kind"), str) and isinstance(check.get("status"), str):
            summary[check["kind"]] = check["status"]
    return summary


def _checks_from_promotion(promotion: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not promotion or not isinstance(promotion.get("checks"), list):
        return None
    return [item for item in promotion["checks"] if isinstance(item, dict)]


def _is_expected_outcome(outcome: ResponseOutcome) -> bool:
    return outcome.return_code in (0, 3) and outcome.kind in {"context_append", "candidate_ok", "candidate_failed"}


def _next_outbound_artifact(manager: SessionManager, session_root: Path) -> Path | None:
    manifest = manager.load_manifest(session_root)
    sent = {item["artifact"] for item in manifest.get("gateway_sent", []) if isinstance(item, dict) and "artifact" in item}

    candidates: list[Path] = []
    for name in manifest.get("context_appends", []):
        if isinstance(name, str):
            candidates.append(session_root / name)
    last_candidate = manifest.get("candidates", [])
    if isinstance(last_candidate, list) and last_candidate:
        repair_prompt = last_candidate[-1].get("repair_prompt")
        if isinstance(repair_prompt, str):
            candidates.append(session_root / repair_prompt)

    for path in candidates:
        rel = path.relative_to(session_root).as_posix()
        if path.exists() and rel not in sent:
            manifest.setdefault("gateway_sent", []).append({"artifact": rel})
            manager.write_manifest(session_root, manifest)
            manager.append_event(session_root, {"type": "transport_send", "file": rel})
            return path
    return None
