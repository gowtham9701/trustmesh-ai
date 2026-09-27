"""Local-only provider seam. Mock is default; Ollama is opt-in via configuration."""
from __future__ import annotations

import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """A configured local model could not return a valid response."""


class Provider(Protocol):
    name: str

    def propose_claims(self, question: str, evidence: list[str]) -> list[str]: ...


class MockLocalProvider:
    name = "mock/local"

    def propose_claims(self, question: str, evidence: list[str]) -> list[str]:
        return []


class OllamaProvider:
    name = "ollama-local"

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def propose_claims(self, question: str, evidence: list[str]) -> list[str]:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer using only the provided evidence. Return JSON {\"claims\": [string]}. "
                        "Each claim must be directly supported by evidence. Return an empty claims array "
                        "if the evidence is insufficient. Never include advice that is not in evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False),
                },
            ],
            "options": {"temperature": 0},
        }
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))) as response:
                body = json.load(response)
            content = body["message"]["content"]
            decoded = json.loads(content)
            claims = decoded.get("claims")
            if not isinstance(claims, list) or any(not isinstance(claim, str) for claim in claims):
                raise ProviderError("Local model returned an invalid claims shape")
            return [claim.strip() for claim in claims if claim.strip()][:5]
        except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("Local Ollama model request failed") from exc


def get_provider() -> Provider:
    provider = os.getenv("LLM_PROVIDER", "mock/local").lower()
    if provider in {"mock", "mock/local", "none"}:
        return MockLocalProvider()
    if provider == "ollama":
        return OllamaProvider(
            os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        )
    raise ProviderError(f"Unsupported LLM_PROVIDER: {provider}")
