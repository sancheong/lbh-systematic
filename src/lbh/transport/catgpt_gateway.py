from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ModelResponse, StartedSession


class CatGptGatewayError(RuntimeError):
    pass


@dataclass
class CatGptGatewayTransport:
    base_url: str
    api_key: str = "dummy123"
    timeout_seconds: float = 120.0

    def start_session(self, initial_prompt: str) -> StartedSession:
        data = self._request_json("/thread/new", {"message": initial_prompt})
        session_id = self._extract_session_id(data)
        response = self._extract_response(data)
        return StartedSession(session_id=session_id, response=response)

    def send(self, session_id: str, message: str) -> ModelResponse:
        data = self._request_json(f"/thread/{session_id}/chat", {"message": message})
        return self._extract_response(data)

    def _request_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self.base_url.rstrip("/")
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{base}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CatGptGatewayError(f"Gateway request failed: {exc.code} {detail}") from exc
        except URLError as exc:
            raise CatGptGatewayError(f"Gateway request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise CatGptGatewayError("Gateway returned invalid JSON") from exc

    def _extract_session_id(self, data: dict[str, Any]) -> str:
        for candidate in (
            data.get("thread_id"),
            data.get("session_id"),
            data.get("id"),
            (data.get("thread") or {}).get("id") if isinstance(data.get("thread"), dict) else None,
        ):
            if isinstance(candidate, str) and candidate:
                return candidate
        raise CatGptGatewayError("Gateway response did not include a thread id")

    def _extract_response(self, data: dict[str, Any]) -> ModelResponse:
        text = self._extract_text(data)
        metadata = {
            "transport": "catgpt-gateway",
        }
        for key in ("provider", "model", "thread_id", "id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                metadata[key] = value
        return ModelResponse(text=text, metadata=metadata)

    def _extract_text(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, list):
            parts = [self._extract_text(item) for item in data]
            text = "\n".join(part for part in parts if part)
            if text:
                return text
        if isinstance(data, dict):
            for key in ("message", "content", "text", "assistant_response"):
                value = data.get(key)
                if value is None:
                    continue
                try:
                    text = self._extract_text(value)
                except CatGptGatewayError:
                    continue
                if text:
                    return text
            choice_text = self._extract_openai_choice_text(data)
            if choice_text:
                return choice_text
        raise CatGptGatewayError("Gateway response did not include assistant text")

    def _extract_openai_choice_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
        return ""
