from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lbh.core.config import Config
from lbh.patch.apply import git_apply_check
from lbh.session.manager import SessionManager
from lbh.transport.catgpt_gateway import CatGptGatewayTransport
from lbh.workflow import ResponseOutcome, create_session_for_request, process_response_file


@dataclass(frozen=True)
class GatewayLoopResult:
    session_root: Path
    status: str
    rounds: int
    response_file: Path | None = None
    patch_file: Path | None = None
    message: str = ""


def run_gateway_loop(
    repo: Path,
    *,
    request: str,
    base_url: str,
    api_key: str = "dummy123",
    max_rounds: int = 20,
    limit: int | None = None,
    apply_check: bool = False,
    transport: CatGptGatewayTransport | None = None,
) -> GatewayLoopResult:
    config = Config.load(repo)
    manager = SessionManager(repo)
    session_root, initial_prompt = create_session_for_request(repo, request, config=config, limit=limit)
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
        if _patch_exists(session_root):
            patch_file = session_root / "patch.diff"
            if apply_check:
                ok, output = git_apply_check(repo, patch_file)
                message = "git apply --check passed" if ok else output
                return GatewayLoopResult(session_root=session_root, status="patch_ready", rounds=round_num - 1, response_file=response_file, patch_file=patch_file, message=message)
            return GatewayLoopResult(session_root=session_root, status="patch_ready", rounds=round_num - 1, response_file=response_file, patch_file=patch_file)

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

    patch_file = session_root / "patch.diff"
    if patch_file.exists():
        return GatewayLoopResult(session_root=session_root, status="patch_ready", rounds=max_rounds, response_file=response_file, patch_file=patch_file)
    return GatewayLoopResult(session_root=session_root, status="max_rounds_exceeded", rounds=max_rounds, response_file=response_file, message="Maximum gateway rounds exceeded.")


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


def _patch_exists(session_root: Path) -> bool:
    return (session_root / "patch.diff").exists()


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
