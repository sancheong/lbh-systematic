from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelResponse:
    text: str
    metadata: dict[str, str] | None = None


class ModelTransport(Protocol):
    def start_session(self, initial_prompt: str) -> str:
        ...

    def send(self, session_id: str, message: str) -> ModelResponse:
        ...
