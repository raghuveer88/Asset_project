from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from typing import Any

from openai import OpenAI


class NoopTrace(AbstractContextManager["NoopTrace"]):
    """No-op trace context with the same small surface used by llm_service."""

    def __enter__(self) -> "NoopTrace":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def end(self, outputs: dict[str, Any] | None = None) -> None:
        return None

    def set_outputs(self, outputs: dict[str, Any] | None = None) -> None:
        self.end(outputs)


class LangSmithTrace(AbstractContextManager["LangSmithTrace"]):
    """Small fail-open wrapper around langsmith.trace."""

    def __init__(self, context: AbstractContextManager[Any]) -> None:
        self.context = context
        self.run: Any = None
        self.disabled = False

    def __enter__(self) -> "LangSmithTrace":
        try:
            self.run = self.context.__enter__()
        except Exception:
            self.disabled = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self.disabled:
            return False
        try:
            self.context.__exit__(exc_type, exc, tb)
        except Exception:
            return False
        return False

    def end(self, outputs: dict[str, Any] | None = None) -> None:
        if self.disabled or not self.run:
            return
        try:
            self.run.end(outputs=_safe_payload(outputs or {}))
        except Exception:
            pass

    def set_outputs(self, outputs: dict[str, Any] | None = None) -> None:
        self.end(outputs)


def is_langsmith_enabled(settings: Any) -> bool:
    """Return True only when tracing is explicitly enabled and a key exists."""
    return bool(getattr(settings, "langsmith_tracing", False) and getattr(settings, "langsmith_api_key", ""))


def create_openai_client(settings: Any) -> OpenAI:
    """Create the OpenAI client, optionally wrapped for LangSmith tracing."""
    client = OpenAI(api_key=settings.openai_api_key)
    if not is_langsmith_enabled(settings):
        return client
    _configure_langsmith_env(settings)
    try:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(client)
    except Exception:
        return client


def noop_trace(name: str, inputs: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> NoopTrace:
    """Return an inert trace context."""
    return NoopTrace()


def trace_context(name: str, inputs: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> AbstractContextManager[Any]:
    """Return a LangSmith trace context or a no-op context when unavailable."""
    try:
        from app.config import get_settings

        settings = get_settings()
        if not is_langsmith_enabled(settings):
            return noop_trace(name, inputs, metadata)
        _configure_langsmith_env(settings)
        from langsmith import trace

        context = trace(
            name,
            run_type="chain",
            inputs=_safe_payload(inputs or {}),
            metadata=_safe_payload(metadata or {}),
            project_name=settings.langsmith_project,
        )
        return LangSmithTrace(context)
    except Exception:
        return noop_trace(name, inputs, metadata)


def summarize_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Summarize a tool result without logging large rows or retrieval chunks."""
    data = result.get("data")
    rows = data if isinstance(data, list) else []
    retrieved = result.get("results")
    output = {
        "tool_name": tool_name,
        "result_keys": sorted(str(key) for key in result.keys()),
        "property_code": result.get("property_code"),
        "report_month": result.get("report_month"),
        "as_of_date": result.get("as_of_date"),
        "category": result.get("category"),
        "row_count": len(rows),
        "source_count": len(retrieved) if isinstance(retrieved, list) else 0,
        "total_amount": _sum_amounts(rows),
        "error": result.get("error"),
        "warning": result.get("warning"),
    }
    return {key: value for key, value in output.items() if value not in (None, [], {})}


def summarize_tool_call(tool_call: Any) -> dict[str, Any]:
    """Return selected tool name and parsed model arguments."""
    function = getattr(tool_call, "function", None)
    raw_arguments = getattr(function, "arguments", None)
    return {
        "tool_name": getattr(function, "name", None),
        "arguments": _parse_json_object(raw_arguments),
    }


def summarize_chat_response(response: Any) -> dict[str, Any]:
    """Return a compact response summary for tracing."""
    return {
        "route": response.metadata.route,
        "tools_used": response.metadata.tools_used,
        "retrieval_called": "retrieve_property_context" in response.metadata.tools_used,
        "component_types": get_component_types(response),
        "source_count": len(response.sources),
        "source_urls": get_source_urls(response),
        "answer_preview": (response.answer_markdown or "")[:500],
        "property_code": response.metadata.property_code,
        "selected_model": response.metadata.model,
    }


def get_component_types(response_or_components: Any) -> list[str]:
    """Return component type names from a response or component list."""
    components = getattr(response_or_components, "components", response_or_components)
    return [str(getattr(component, "type", "")) for component in components or [] if getattr(component, "type", None)]


def get_source_urls(response_or_sources: Any) -> list[str]:
    """Return source URLs from a response or source list."""
    sources = getattr(response_or_sources, "sources", response_or_sources)
    return [str(getattr(source, "url", "")) for source in sources or [] if getattr(source, "url", None)]


def _configure_langsmith_env(settings: Any) -> None:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _sum_amounts(rows: list[dict[str, Any]]) -> float | None:
    total = 0.0
    seen = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("amount", "charge_amount", "total_amount"):
            if key in row and isinstance(row.get(key), (int, float)):
                total += float(row[key])
                seen = True
                break
    return round(total, 2) if seen else None


def _safe_payload(value: Any, depth: int = 0) -> Any:
    """Make trace payloads JSON-safe and bounded."""
    if depth > 4:
        return str(type(value).__name__)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_payload(item, depth + 1) for key, item in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set)):
        return [_safe_payload(item, depth + 1) for item in list(value)[:25]]
    return str(value)
