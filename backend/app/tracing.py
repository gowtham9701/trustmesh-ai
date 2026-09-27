"""Optional metadata-only Langfuse/LangSmith trace adapters."""
from __future__ import annotations

import os
from typing import Any


class NoOpTracer:
    enabled = False
    name = "disabled"
    failure: str | None = None

    def trace(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        return None

    def close(self) -> None:
        return None


class LangfuseTracer(NoOpTracer):
    enabled = True
    name = "langfuse"

    def __init__(self, client: Any):
        self.client = client

    def trace(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        trace = self.client.trace(name=name, metadata=metadata or {})
        trace.span(name=name, metadata=metadata or {})

    def close(self) -> None:
        self.client.flush()


class LangSmithTracer(NoOpTracer):
    enabled = True
    name = "langsmith"

    def __init__(self, client: Any):
        self.client = client

    def trace(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        run_id = self.client.create_run(
            name=name,
            run_type="chain",
            inputs={},
            project_name=os.getenv("LANGCHAIN_PROJECT", "trustmesh"),
            extra={"metadata": metadata or {}},
        )
        self.client.update_run(run_id, outputs={"status": "completed"})


def get_tracer() -> NoOpTracer:
    provider = os.getenv("TRACING_PROVIDER", "disabled").lower()
    if provider in {"", "disabled", "none", "off"}:
        return NoOpTracer()
    try:
        if provider == "langfuse":
            if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
                tracer = NoOpTracer()
                tracer.failure = "Langfuse keys are not configured"
                return tracer
            from langfuse import Langfuse
            return LangfuseTracer(Langfuse())
        if provider == "langsmith":
            if not os.getenv("LANGCHAIN_API_KEY"):
                tracer = NoOpTracer()
                tracer.failure = "LANGCHAIN_API_KEY is not configured"
                return tracer
            from langsmith import Client
            return LangSmithTracer(Client())
        tracer = NoOpTracer()
        tracer.failure = f"Unknown tracing provider: {provider}"
        return tracer
    except ImportError as exc:
        tracer = NoOpTracer()
        tracer.failure = f"Tracing dependency unavailable: {exc.name}"
        return tracer


def tracing_metadata() -> dict[str, Any]:
    tracer = get_tracer()
    return {"provider": tracer.name, "enabled": tracer.enabled, "failure": tracer.failure}
