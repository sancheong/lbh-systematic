from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelResponse:
    text: str
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class StartedSession:
    session_id: str
    response: ModelResponse


class ModelTransport(Protocol):
    def start_session(self, initial_prompt: str) -> StartedSession:
        ...

    def send(self, session_id: str, message: str) -> ModelResponse:
        ...
