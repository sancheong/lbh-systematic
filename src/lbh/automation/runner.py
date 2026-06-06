from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from lbh.session.manager import SessionManager
from lbh.workflow import ApplyOutcome, ask_request, apply_patch_file, process_response_file

from .base import AutomationOptions, AutomationResult, BrowserController, BrowserControllerError

AUTOMATION_STATES = {
    "created",
    "sending_initial_prompt",
    "waiting_for_response",
    "saving_response",
    "running_lbh_respond",
    "sending_context_append",
    "candidate_failed",
    "candidate_repairing",
    "patch_promoted",
    "apply_check",
    "apply_yes",
    "completed",
    "blocked",
}


class ArtifactResolver:
    def __init__(self, manager: SessionManager):
        self.manager = manager

    def next_response_path(self, session_root: Path, *, repair: bool) -> Path:
        prefix = "repair_response" if repair else "response"
        indexes: list[int] = []
        for path in session_root.glob(f"{prefix}_*.md"):
            try:
                indexes.append(int(path.stem.split("_")[-1]))
            except ValueError:
                continue
        return session_root / f"{prefix}_{max(indexes, default=0) + 1:03d}.md"

    def resolve_artifact(self, session_root: Path, rel_path: str) -> Path:
        return session_root / rel_path


class AutomationRunner:
    def __init__(
        self,
        repo_root: Path,
        controller: BrowserController,
        options: AutomationOptions,
        *,
        ask_fn: Callable[..., Any] = ask_request,
        respond_fn: Callable[..., Any] = process_response_file,
        apply_fn: Callable[..., ApplyOutcome] = apply_patch_file,
    ):
        self.repo_root = repo_root
        self.controller = controller
        self.options = options
        self.ask_fn = ask_fn
        self.respond_fn = respond_fn
        self.apply_fn = apply_fn
        self.manager = SessionManager(repo_root)
        self.artifacts = ArtifactResolver(self.manager)

    def start(self, request: str, *, limit: int | None = None) -> AutomationResult:
        ask = self.ask_fn(self.repo_root, request, limit=limit)
        manifest = self.manager.load_manifest(ask.session_root)
        manifest["automation"] = {
            "provider": "chatgpt_web",
            "controller_kind": self.options.controller_kind,
            "chrome_profile": self.options.chrome_profile,
            "apply_mode": self.options.apply_mode,
            "state": "created",
            "retry_counts": {},
            "chat_ref": None,
            "chat_metadata": {},
            "latest_outbound_artifact": None,
            "latest_outbound_kind": None,
            "latest_inbound_response": None,
            "awaiting_human_intervention": False,
            "debug_artifacts": {},
        }
        self.manager.write_manifest(ask.session_root, manifest)
        self._append_state_event(ask.session_root, "created")
        return self._drive(ask.session_root)

    def resume(self, session_root: Path) -> AutomationResult:
        manifest = self.manager.load_manifest(session_root)
        automation = manifest.get("automation")
        if not automation:
            raise ValueError("session does not contain automation metadata")
        if automation.get("state") == "blocked":
            blocked_from = automation.get("blocked_from_state") or "created"
            self._update_automation(
                session_root,
                state=str(blocked_from),
                awaiting_human_intervention=False,
            )
            manifest = self.manager.load_manifest(session_root)
            automation = manifest.get("automation") or {}
        chat_ref = automation.get("chat_ref")
        if chat_ref:
            chat = self._browser_step(
                session_root,
                "resume_chat",
                "resume_chat",
                lambda: self.controller.resume_chat(
                    profile=self.options.chrome_profile,
                    chat_ref=str(chat_ref),
                ),
            )
            if chat is None:
                return self._result(session_root)
            self._update_automation(
                session_root,
                chat_ref=chat.chat_ref,
                chat_metadata=chat.metadata,
                awaiting_human_intervention=False,
            )
        return self._drive(session_root)

    def _drive(self, session_root: Path) -> AutomationResult:
        while True:
            manifest = self.manager.load_manifest(session_root)
            automation = manifest.get("automation") or {}
            state = automation.get("state", "created")
            if state not in AUTOMATION_STATES:
                raise ValueError(f"unknown automation state: {state}")
            session_paths = self.manager.paths(session_root)

            if state == "created":
                chat = self._browser_step(
                    session_root,
                    "created",
                    "starting_chat",
                    lambda: self.controller.start_chat(profile=self.options.chrome_profile),
                )
                if chat is None:
                    return self._result(session_root)
                self._update_automation(
                    session_root,
                    state="sending_initial_prompt",
                    chat_ref=chat.chat_ref,
                    chat_metadata=chat.metadata,
                    latest_outbound_artifact=session_paths.initial_prompt.name,
                    latest_outbound_kind="initial_prompt",
                    awaiting_human_intervention=False,
                    debug_artifacts={},
                )
                continue

            if state in {"sending_initial_prompt", "sending_context_append", "candidate_repairing"}:
                artifact_rel = automation.get("latest_outbound_artifact")
                if not artifact_rel:
                    self._block(session_root, f"missing outbound artifact in state {state}", blocked_from=state)
                    return self._result(session_root)
                artifact_path = self.artifacts.resolve_artifact(session_root, artifact_rel)
                text = artifact_path.read_text(encoding="utf-8")
                ok = self._browser_step(
                    session_root,
                    state,
                    "sending_message",
                    lambda: self.controller.send_message(
                        profile=self.options.chrome_profile,
                        chat_ref=str(automation.get("chat_ref")),
                        text=text,
                    ),
                )
                if ok is None:
                    return self._result(session_root)
                self._update_automation(session_root, state="waiting_for_response", awaiting_human_intervention=False)
                continue

            if state == "waiting_for_response":
                response = self._browser_step(
                    session_root,
                    "waiting_for_response",
                    "waiting_response",
                    lambda: self.controller.wait_for_response(
                        profile=self.options.chrome_profile,
                        chat_ref=str(automation.get("chat_ref")),
                        timeout_seconds=self.options.timeout_seconds,
                        poll_seconds=self.options.poll_seconds,
                    ),
                )
                if response is None:
                    return self._result(session_root)
                repair = automation.get("latest_outbound_kind") == "repair_prompt"
                response_path = self.artifacts.next_response_path(session_root, repair=repair)
                response_path.write_text(response.text, encoding="utf-8")
                self._update_automation(
                    session_root,
                    state="saving_response",
                    latest_inbound_response=response_path.name,
                    awaiting_human_intervention=False,
                )
                self.manager.append_event(
                    session_root,
                    {
                        "type": "automation_response_saved",
                        "file": response_path.name,
                        "repair": repair,
                    },
                )
                continue

            if state == "saving_response":
                self._update_automation(session_root, state="running_lbh_respond")
                continue

            if state == "running_lbh_respond":
                response_name = automation.get("latest_inbound_response")
                if not response_name:
                    self._block(session_root, "missing inbound response file before lbh respond", blocked_from=state)
                    return self._result(session_root)
                outcome = self.respond_fn(self.repo_root, session_root, session_root / response_name)
                if outcome.kind == "context_append" and outcome.context_append is not None:
                    self._update_automation(
                        session_root,
                        state="sending_context_append",
                        latest_outbound_artifact=outcome.context_append.name,
                        latest_outbound_kind="context_append",
                        awaiting_human_intervention=False,
                    )
                    continue
                if outcome.kind == "candidate_failed" and outcome.repair_prompt_path is not None:
                    self._update_automation(session_root, state="candidate_failed", awaiting_human_intervention=False)
                    continue
                if outcome.kind == "candidate_ok" and outcome.patch_path is not None:
                    self._update_automation(
                        session_root,
                        state="patch_promoted",
                        latest_outbound_kind="patch",
                        awaiting_human_intervention=False,
                    )
                    continue
                self._block(session_root, outcome.error_message or "no actionable LBH artifact appeared", blocked_from=state)
                return self._result(session_root)

            if state == "candidate_failed":
                candidate = self._latest_candidate(manifest)
                if not candidate or not candidate.get("repair_prompt"):
                    self._block(session_root, "candidate failed but no repair prompt was recorded", blocked_from=state)
                    return self._result(session_root)
                self._update_automation(
                    session_root,
                    state="candidate_repairing",
                    latest_outbound_artifact=str(candidate["repair_prompt"]),
                    latest_outbound_kind="repair_prompt",
                    awaiting_human_intervention=False,
                )
                continue

            if state == "patch_promoted":
                self._update_automation(session_root, state="apply_check")
                continue

            if state == "apply_check":
                outcome = self.apply_fn(self.repo_root, session_paths.patch, session_root=session_root, check=True, yes=False)
                if not outcome.ok:
                    self._block(session_root, outcome.output or "; ".join(outcome.validation_errors) or "apply check failed", blocked_from=state)
                    return self._result(session_root)
                self.manager.append_event(session_root, {"type": "automation_apply_check", "ok": True})
                if self.options.apply_mode == "yes":
                    self._update_automation(session_root, state="apply_yes")
                else:
                    self._update_automation(session_root, state="completed")
                continue

            if state == "apply_yes":
                outcome = self.apply_fn(self.repo_root, session_paths.patch, session_root=session_root, check=False, yes=True)
                if not outcome.ok:
                    self._block(session_root, outcome.output or "; ".join(outcome.validation_errors) or "apply failed", blocked_from=state)
                    return self._result(session_root)
                self.manager.append_event(session_root, {"type": "automation_apply_yes", "ok": True})
                self._update_automation(session_root, state="completed")
                continue

            if state in {"completed", "blocked"}:
                return self._result(session_root)

    def _browser_step(
        self,
        session_root: Path,
        retry_key: str,
        event_type: str,
        action: Callable[[], Any],
    ) -> Any | None:
        try:
            value = action()
        except BrowserControllerError as exc:
            if not self._retry_or_block(session_root, retry_key, str(exc)):
                return None
            return self._browser_step(session_root, retry_key, event_type, action)
        self._reset_retry(session_root, retry_key)
        self.manager.append_event(session_root, {"type": event_type, "state": retry_key})
        return value

    def _retry_or_block(self, session_root: Path, retry_key: str, message: str) -> bool:
        manifest = self.manager.load_manifest(session_root)
        automation = manifest.setdefault("automation", {})
        retry_counts = dict(automation.get("retry_counts", {}))
        count = int(retry_counts.get(retry_key, 0)) + 1
        retry_counts[retry_key] = count
        automation["retry_counts"] = retry_counts
        self.manager.write_manifest(session_root, manifest)
        self.manager.append_event(
            session_root,
            {"type": "automation_retry", "state": retry_key, "attempt": count, "message": message},
        )
        if count <= self.options.max_retries:
            return True
        self._block(session_root, message, blocked_from=retry_key)
        return False

    def _reset_retry(self, session_root: Path, retry_key: str) -> None:
        manifest = self.manager.load_manifest(session_root)
        automation = manifest.setdefault("automation", {})
        retry_counts = dict(automation.get("retry_counts", {}))
        if retry_key in retry_counts:
            retry_counts[retry_key] = 0
            automation["retry_counts"] = retry_counts
            self.manager.write_manifest(session_root, manifest)

    def _block(self, session_root: Path, message: str, *, blocked_from: str) -> None:
        manifest = self.manager.load_manifest(session_root)
        automation = manifest.setdefault("automation", {})
        debug = self.controller.capture_debug(
            profile=self.options.chrome_profile,
            chat_ref=automation.get("chat_ref"),
            session_root=session_root,
        )
        automation["state"] = "blocked"
        automation["awaiting_human_intervention"] = True
        automation["blocked_from_state"] = blocked_from
        if debug:
            automation["debug_artifacts"] = debug
        manifest["automation"] = automation
        self.manager.write_manifest(session_root, manifest)
        self.manager.append_event(session_root, {"type": "automation_blocked", "message": message})

    def _update_automation(self, session_root: Path, **updates: Any) -> None:
        manifest = self.manager.load_manifest(session_root)
        automation = manifest.setdefault("automation", {})
        previous_state = automation.get("state")
        automation.update(updates)
        manifest["automation"] = automation
        self.manager.write_manifest(session_root, manifest)
        if "state" in updates and updates["state"] != previous_state:
            self._append_state_event(session_root, str(updates["state"]))

    def _append_state_event(self, session_root: Path, state: str) -> None:
        self.manager.append_event(session_root, {"type": "automation_state", "state": state})

    def _latest_candidate(self, manifest: dict[str, Any]) -> dict[str, Any] | None:
        candidates = manifest.get("candidates") or []
        if not candidates:
            return None
        return candidates[-1]

    def _result(self, session_root: Path) -> AutomationResult:
        manifest = self.manager.load_manifest(session_root)
        automation = manifest.get("automation") or {}
        patch_path = None
        if manifest.get("patch"):
            patch_path = session_root / str(manifest["patch"]["path"])
        return AutomationResult(
            session_root=session_root,
            state=str(automation.get("state", "created")),
            chat_ref=automation.get("chat_ref"),
            latest_outbound_artifact=automation.get("latest_outbound_artifact"),
            latest_inbound_response=automation.get("latest_inbound_response"),
            patch_path=patch_path,
        )
