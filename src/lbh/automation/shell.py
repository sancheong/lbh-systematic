from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .base import BrowserChat, BrowserControllerError, BrowserResponse


class ShellBrowserController:
    """Bridge to an external Chrome/ChatGPT controller executable.

    The external command receives a single JSON payload on stdin and must reply
    with a JSON object on stdout.
    """

    def __init__(self, command: tuple[str, ...], *, timeout_seconds: int = 60):
        if not command:
            raise BrowserControllerError(
                "browser controller command is required; set --controller-command or LBH_BROWSER_CONTROLLER_COMMAND"
            )
        self.command = command
        self.timeout_seconds = timeout_seconds

    def start_chat(self, *, profile: str) -> BrowserChat:
        data = self._invoke("start_chat", {"profile": profile})
        return BrowserChat(chat_ref=str(data["chat_ref"]), metadata=dict(data.get("metadata", {})))

    def resume_chat(self, *, profile: str, chat_ref: str) -> BrowserChat:
        data = self._invoke("resume_chat", {"profile": profile, "chat_ref": chat_ref})
        return BrowserChat(chat_ref=str(data.get("chat_ref", chat_ref)), metadata=dict(data.get("metadata", {})))

    def send_message(self, *, profile: str, chat_ref: str, text: str) -> dict[str, Any]:
        data = self._invoke(
            "send_message",
            {"profile": profile, "chat_ref": chat_ref, "text": text},
        )
        return dict(data.get("metadata", {}))

    def wait_for_response(
        self,
        *,
        profile: str,
        chat_ref: str,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> BrowserResponse:
        data = self._invoke(
            "wait_for_response",
            {
                "profile": profile,
                "chat_ref": chat_ref,
                "timeout_seconds": timeout_seconds,
                "poll_seconds": poll_seconds,
            },
            timeout_seconds=max(self.timeout_seconds, timeout_seconds + 10),
        )
        return BrowserResponse(text=str(data["text"]), metadata=dict(data.get("metadata", {})))

    def capture_debug(self, *, profile: str, chat_ref: str | None, session_root: Path) -> dict[str, Any]:
        try:
            data = self._invoke(
                "capture_debug",
                {
                    "profile": profile,
                    "chat_ref": chat_ref,
                    "session_root": str(session_root),
                },
                timeout_seconds=self.timeout_seconds,
            )
        except BrowserControllerError:
            return {}
        return dict(data.get("metadata", data))

    def _invoke(self, action: str, payload: dict[str, Any], *, timeout_seconds: int | None = None) -> dict[str, Any]:
        request = json.dumps({"action": action, **payload}, ensure_ascii=False)
        proc = subprocess.run(
            list(self.command),
            input=request,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds or self.timeout_seconds,
        )
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or f"controller action failed: {action}"
            raise BrowserControllerError(message)
        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise BrowserControllerError(f"controller returned invalid JSON for {action}: {exc}") from exc
        if data.get("ok", True) is False:
            raise BrowserControllerError(str(data.get("error", f"controller action failed: {action}")))
        return data
