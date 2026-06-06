from __future__ import annotations

from .base import ModelResponse


class ManualPasteTransport:
    """Manual transport placeholder.

    LBH core does not depend on any browser automation. This adapter documents
    the manual copy/paste workflow and can be replaced by a permitted API
    adapter later.
    """

    def start_session(self, initial_prompt: str) -> str:
        return "manual"

    def send(self, session_id: str, message: str) -> ModelResponse:
        return ModelResponse(text=message, metadata={"transport": "manual"})
