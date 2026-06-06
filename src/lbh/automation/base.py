from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class BrowserControllerError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserChat:
    chat_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserResponse:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BrowserController(Protocol):
    def start_chat(self, *, profile: str) -> BrowserChat:
        ...

    def resume_chat(self, *, profile: str, chat_ref: str) -> BrowserChat:
        ...

    def send_message(self, *, profile: str, chat_ref: str, text: str) -> dict[str, Any]:
        ...

    def wait_for_response(
        self,
        *,
        profile: str,
        chat_ref: str,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> BrowserResponse:
        ...

    def capture_debug(self, *, profile: str, chat_ref: str | None, session_root: Path) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AutomationOptions:
    chrome_profile: str = "Profile 4"
    apply_mode: str = "yes"
    max_retries: int = 2
    poll_seconds: float = 2.0
    timeout_seconds: int = 300
    controller_kind: str = "shell_command"
    controller_command: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutomationResult:
    session_root: Path
    state: str
    chat_ref: str | None = None
    latest_outbound_artifact: str | None = None
    latest_inbound_response: str | None = None
    patch_path: Path | None = None
