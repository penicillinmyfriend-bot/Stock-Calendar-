"""Local model client (Ollama only).

All inference goes to a local Ollama server over its HTTP API using the Python
standard library (``urllib``) -- there is no cloud SDK and no cloud endpoint.
The client only ever contacts the host configured in ``config.yaml`` (default
``http://127.0.0.1:11434``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class LLMError(Exception):
    """Raised when the local model cannot be reached or returns an error."""


class OllamaClient:
    """Minimal chat client for a local Ollama server."""

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder",
        *,
        temperature: float = 0.2,
        timeout: int = 120,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise LLMError(
                f"could not reach Ollama at {self.host} ({exc}). "
                "Is `ollama serve` running and the model pulled?"
            ) from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise LLMError(f"invalid JSON from Ollama: {exc}") from exc

    def is_available(self) -> bool:
        """True if the local Ollama server answers."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        format: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Send a chat completion request and return the assistant's text.

        ``format='json'`` asks Ollama to constrain output to valid JSON.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature if temperature is None else temperature},
        }
        if format:
            payload["format"] = format
        data = self._post("/api/chat", payload)
        message = data.get("message") or {}
        content = message.get("content")
        if content is None:
            raise LLMError(f"unexpected Ollama response: {data!r}")
        return content
