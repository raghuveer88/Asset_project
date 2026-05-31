from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ChatMessage, ChatSession, Property
from app.schemas import ChatMetadata, ChatRequest, ChatResponse
from app.services.response_builder import (
    clean_component_markdown,
    concise_answer_from_tool_results,
    components_from_tool_results,
    contextual_followups,
    default_followups,
    safe_parse_response,
    sources_from_tool_results,
)
from app.services.tracing_service import (
    create_openai_client,
    summarize_chat_response,
    summarize_tool_call,
    summarize_tool_result,
    trace_context,
)
from app.services.tool_registry import TOOL_SCHEMAS, execute_tool


SYSTEM_PROMPT = """You are Asset AI, a property-scoped real-estate intelligence assistant.

You answer only for the ACTIVE_PROPERTY_CODE. If the user asks about a different property by code, name, official name, or website identity, tell them to switch the active property first. Never provide cross-property answers.

Use tools for factual property metrics. Do not invent numbers. The backend is the source of truth for property scoping, analytics, SQL queries, retrieval filters, and UI component payloads. Use retrieval for website facts such as amenities, neighborhood, floor plans, leasing, or contact information. Normal greetings and general capability questions do not require tools.

The request payload includes ACTIVE_PROPERTY_NAME and ACTIVE_PROPERTY_ALIASES. If a named property in CURRENT_USER_QUESTION appears in ACTIVE_PROPERTY_ALIASES, treat it as the active property and answer normally. If the user asks about a named property that is not the active property, do not answer from active-property context and do not call retrieval for the active property. The assistant must not rename active-property source content as another property. Source URLs and answer content must describe the active property only.

The CURRENT_USER_QUESTION is the primary task. RECENT_HISTORY is only for resolving references like "that", "those", "previous", "make it shorter", or "show that as a chart". Do not call tools based only on older history. Only call tools needed for the current user question.

Supported analytics tools cover: property overview KPIs; source Summary Groups; Future Residents/Applicants; occupancy and vacancy; occupancy trend; unit type mix; average rent by unit type; vacancy loss; vacancy loss by unit type; charge breakdown; rent/non-rent charge breakdown; charge trend; lease expirations within a window; lease expirations grouped by month; high positive balances; balance summary separating credits and outstanding balances; balance trend; unit lookup; available report months; property metadata; executive property health summary based on available rent-roll fields; and website facts from retrieved website content.

Unsupported examples include: renewal conversion rate; probability that a tenant renews; renovation ROI; leasing velocity by lead source; traffic source performance; work orders; amenity causal impact on rent; demographic segmentation; and true accounting delinquency aging beyond current rent-roll balances.

If the user asks for a metric that is not supported by the available tools or data, do not guess. Return this kind of clean limitation response: "I don't currently have a reliable tool or data source for that metric. I can answer occupancy, vacancy, unit mix, balances, charges, lease expirations, vacant units, unit lookup, executive summaries, or website-based questions for the active property."

Tool guidance:
- Use get_property_health_summary for executive summaries or management focus.
- Use get_rent_roll_summary_groups when the user asks for source summary, summary groups, source totals, or how the rent roll groups current/future/occupied/vacant units.
- Use get_future_residents when the user asks about future residents, applicants, upcoming move-ins, pre-leased vacant units, or future deposits.
- Use get_unit_type_mix for unit mix, floor-plan occupancy, average rent by unit type, or unit-type vacancy.
- Use get_balance_summary to separate outstanding balances from credits, and get_high_balance_residents only for positive balances.
- Use get_balance_trend for balance trend questions, making clear it is rent-roll balance trend rather than accounting delinquency aging.
- Use get_expiration_summary_by_month for grouped lease expirations.
- Use get_vacancy_loss_by_unit_type for vacancy concentration or vacancy loss by floor plan/unit type.
- Use get_charge_breakdown with category rent or non_rent for rent-only or non-rent fee questions.
- Use get_charge_trend for charge changes over time.
- Use get_unit_lookup for a specific unit, and include history only when the user asks for changes over time.
- Do not count future residents/applicants as current occupancy.

For analytics answers, the backend will generate KPI/table/chart components. Keep answer_markdown concise and explanatory. Do not include Markdown tables or full chart data in answer_markdown when the same data belongs in table, KPI, bar_chart, or line_chart components. Mention report_month/as_of_date for current metrics and window_start/window_end for lease-expiration windows. If retrieval returns no confident results, say the information was not found in the scraped website sample instead of guessing.

Return final answers as strict JSON with this shape:
{
  "answer_markdown": "Markdown answer",
  "components": [],
  "sources": [],
  "followups": [{"label": "Short label", "question": "Scoped follow-up question", "route_hint": "PROPERTY_ANALYTICS|RETRIEVAL|HYBRID|CHAT"}],
  "metadata": {"route": "PROPERTY_ANALYTICS|RETRIEVAL|HYBRID|CHAT"}
}

Components may only be kpi_cards, table, bar_chart, or line_chart. Keep responses concise, executive-friendly, and useful for multifamily operations.
"""


def handle_chat(db: Session, request: ChatRequest) -> ChatResponse:
    """
    Orchestrate one property-scoped chat turn with OpenAI tool calling.

    The selected chat model is validated against the allow-list. Recent history
    is loaded only for the same session_id and property_code, and every tool
    call is executed by the backend with the active property_code injected.
    """
    settings = get_settings()
    model = request.selected_model if request.selected_model in settings.allowed_models else settings.openai_default_model
    model = model if model in settings.allowed_models else "gpt-4o-mini"
    property_code = request.property_code.lower().strip()
    _store_user_message(db, request, model, property_code)
    recent_history = _recent_history(db, request.session_id, property_code)
    active_context = _active_property_context(db, property_code)
    chat_inputs = {
        "question": request.message,
        "property_code": property_code,
        "property_name": active_context["name"],
        "selected_model": model,
        "session_id": request.session_id,
        "recent_history_count": len(recent_history),
    }
    chat_metadata = {
        "property_code": property_code,
        "selected_model": model,
        "project": settings.langsmith_project,
    }

    with trace_context("api.chat", inputs=chat_inputs, metadata=chat_metadata) as chat_trace:
        scope_issue = _cross_property_scope_issue(db, property_code, request.message)
        if scope_issue:
            response = _cross_property_response(db, property_code, scope_issue, model)
            _store_assistant_message(db, request.session_id, property_code, response)
            db.commit()
            chat_trace.end(outputs=_fallback_trace_output(response, "cross_property_scope"))
            return response

        if not settings.openai_api_key:
            response = _local_fallback_response(property_code, model)
            _store_assistant_message(db, request.session_id, property_code, response)
            db.commit()
            chat_trace.end(outputs=_fallback_trace_output(response, "missing_openai_api_key"))
            return response

        client = create_openai_client(settings)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "ACTIVE_PROPERTY_CODE": property_code,
                        "ACTIVE_PROPERTY_NAME": active_context["name"],
                        "ACTIVE_PROPERTY_ALIASES": active_context["aliases"],
                        "RECENT_HISTORY": recent_history,
                        "CURRENT_USER_QUESTION": request.message,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        tools_used: list[str] = []
        tool_results: list[dict[str, Any]] = []
        available_tools = [tool["function"]["name"] for tool in TOOL_SCHEMAS]
        for _ in range(3):
            stage_name = "generate_grounded_response" if tool_results else "plan_tool_calls"
            llm_inputs = (
                {
                    "question": request.message,
                    "property_code": property_code,
                    "property_name": active_context["name"],
                    "selected_model": model,
                    "tool_results_summary": [
                        summarize_tool_result(item["tool_name"], item["result"]) for item in tool_results
                    ],
                    "tools_used_so_far": tools_used,
                }
                if tool_results
                else {
                    "question": request.message,
                    "property_code": property_code,
                    "property_name": active_context["name"],
                    "selected_model": model,
                    "available_tools": available_tools,
                }
            )
            with trace_context(stage_name, inputs=llm_inputs, metadata=chat_metadata) as llm_trace:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                assistant_message = completion.choices[0].message
                tool_calls = assistant_message.tool_calls or []
                finish_reason = completion.choices[0].finish_reason
                llm_trace.end(
                    outputs={
                        "finish_reason": finish_reason,
                        "tool_calls": [summarize_tool_call(call) for call in tool_calls],
                        "has_tool_calls": bool(tool_calls),
                        "answer_preview": (assistant_message.content or "")[:500],
                    }
                )
            messages.append(assistant_message.model_dump(exclude_none=True))
            if not tool_calls:
                raw = assistant_message.content or ""
                route = _route_from_tools(tools_used)
                response = safe_parse_response(raw, property_code, model, tools_used, route)
                deterministic_components = components_from_tool_results(tool_results)
                has_analytics_tools = any(tool != "retrieve_property_context" for tool in tools_used)
                if has_analytics_tools:
                    response.components = deterministic_components
                elif deterministic_components:
                    response.components = deterministic_components
                else:
                    response.components = []
                response = clean_component_markdown(response)
                concise_answer = concise_answer_from_tool_results(request.message, tool_results)
                if concise_answer and response.components and response.metadata.route == "PROPERTY_ANALYTICS":
                    response.answer_markdown = concise_answer
                availability_answer = _availability_limitation_answer(tool_results)
                if availability_answer:
                    response.answer_markdown = availability_answer
                tool_sources = sources_from_tool_results(tool_results)
                if tool_sources:
                    response.sources = tool_sources
                response.followups = contextual_followups(request.message, response.metadata.route, tools_used, tool_results)
                response.metadata.tools_used = tools_used
                response.metadata.property_code = property_code
                response.metadata.model = model
                _store_assistant_message(db, request.session_id, property_code, response)
                db.commit()
                chat_trace.end(outputs=summarize_chat_response(response))
                return response

            for call in tool_calls:
                tool_name = call.function.name
                tool_summary = summarize_tool_call(call)
                tool_inputs = {
                    "tool_name": tool_name,
                    "model_arguments": tool_summary.get("arguments", {}),
                    "backend_injected_property_code": property_code,
                }
                with trace_context(f"Tool: {tool_name}", inputs=tool_inputs, metadata=chat_metadata) as tool_trace:
                    # execute_tool strips any model-supplied property code and injects
                    # the request-scoped property_code, which is the core anti-leakage guard.
                    result = execute_tool(db, property_code, tool_name, call.function.arguments)
                    tool_trace.end(outputs=summarize_tool_result(tool_name, result))
                tools_used.append(tool_name)
                tool_results.append({"tool_name": tool_name, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": tool_name,
                        "content": json.dumps(result, default=str, ensure_ascii=False),
                    }
                )

        response = ChatResponse(
            answer_markdown=concise_answer_from_tool_results(request.message, tool_results)
            or "I gathered the relevant property data, but I could not complete a clean final response. Try asking the question more directly.",
            components=components_from_tool_results(tool_results),
            sources=sources_from_tool_results(tool_results),
            followups=contextual_followups(request.message, _route_from_tools(tools_used), tools_used, tool_results),
            metadata={"property_code": property_code, "model": model, "tools_used": tools_used, "route": _route_from_tools(tools_used)},
        )
        response = clean_component_markdown(response)
        _store_assistant_message(db, request.session_id, property_code, response)
        db.commit()
        output = summarize_chat_response(response)
        output.update({"fallback": True, "fallback_reason": "max_tool_loop"})
        chat_trace.end(outputs=output)
        return response


def _fallback_trace_output(response: ChatResponse, reason: str) -> dict[str, Any]:
    """Build compact trace output for deterministic fallback paths."""
    return {
        "fallback": True,
        "fallback_reason": reason,
        "answer_preview": (response.answer_markdown or "")[:500],
        "property_code": response.metadata.property_code,
        "selected_model": response.metadata.model,
    }


def _availability_limitation_answer(tool_results: list[dict[str, Any]]) -> str | None:
    """Return deterministic no-data wording for missing scoped data sources."""
    if not tool_results:
        return None
    analytics_results = [
        item.get("result", {})
        for item in tool_results
        if item.get("tool_name") != "retrieve_property_context"
    ]
    retrieval_results = [
        item.get("result", {})
        for item in tool_results
        if item.get("tool_name") == "retrieve_property_context"
    ]
    if analytics_results and all(result.get("error") == "No rent-roll data found." for result in analytics_results):
        return "I don't have rent-roll snapshots for this active property, so I can't calculate analytics for it yet."
    if retrieval_results and all(not result.get("results") for result in retrieval_results) and not analytics_results:
        warning = retrieval_results[-1].get("warning")
        if warning == "Vector index is empty.":
            return "I don't have a built website vector index yet, so I can't answer website questions from scraped context."
        return "I did not find that information in the scraped website sample for this active property."
    return None


def _store_user_message(db: Session, request: ChatRequest, model: str, property_code: str) -> None:
    """Persist the user message under the active session and property scope."""
    session = db.scalar(select(ChatSession).where(ChatSession.session_id == request.session_id))
    if not session:
        session = ChatSession(session_id=request.session_id, property_code=property_code, selected_model=model)
        db.add(session)
    else:
        session.property_code = property_code
        session.selected_model = model
    db.add(ChatMessage(session_id=request.session_id, property_code=property_code, role="user", content=request.message))
    db.flush()


def _store_assistant_message(db: Session, session_id: str, property_code: str, response: ChatResponse) -> None:
    """Persist the validated assistant response for same-property history lookup."""
    db.add(
        ChatMessage(
            session_id=session_id,
            property_code=property_code,
            role="assistant",
            content=response.answer_markdown,
            route=response.metadata.route,
            tools_used_json=json.dumps(response.metadata.tools_used),
            response_json=response.model_dump_json(),
        )
    )


def _recent_history(db: Session, session_id: str, property_code: str, limit: int = 8) -> list[dict[str, str]]:
    """
    Load recent chat history only for the same session_id and property_code.

    This prevents context from one property from being used to answer another
    property's question while still supporting references like "that" or
    "show the previous result as a table."
    """
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.property_code == property_code)
        .order_by(desc(ChatMessage.created_at), desc(ChatMessage.id))
        .limit(limit)
    ).all()
    history = [{"role": row.role, "content": row.content[:1800]} for row in reversed(rows)]
    if history and history[-1]["role"] == "user":
        history = history[:-1]
    return history[-6:]


def _route_from_tools(tools_used: list[str]) -> str:
    """Classify a response route from the tools used during the turn."""
    has_retrieval = "retrieve_property_context" in tools_used
    has_analytics = any(tool != "retrieve_property_context" for tool in tools_used)
    if has_retrieval and has_analytics:
        return "HYBRID"
    if has_retrieval:
        return "RETRIEVAL"
    if has_analytics:
        return "PROPERTY_ANALYTICS"
    return "CHAT"


GENERIC_ALIAS_WORDS = {
    "a",
    "an",
    "the",
    "at",
    "and",
    "apartments",
    "apartment",
    "community",
    "homes",
    "home",
    "park",
    "place",
    "property",
    "residences",
    "river",
    "run",
}


def _cross_property_scope_issue(db: Session, property_code: str, message: str) -> dict[str, Any] | None:
    """
    Detect known property codes or aliases that do not include the active code.

    This deterministic guard runs before the LLM or retrieval. It prevents
    active-property website chunks from being used to answer a question about a
    different named property.
    """
    normalized_message = f" {_normalize_property_text(message)} "
    if not normalized_message.strip():
        return None
    alias_map = _property_alias_map(db)
    matches: list[dict[str, Any]] = []
    for alias, info in alias_map.items():
        if f" {alias} " in normalized_message:
            matches.append(info)
    matches.sort(key=lambda item: len(item["alias"]), reverse=True)

    for match in matches:
        codes = set(match["codes"])
        if property_code not in codes:
            return match
    return None


def _property_alias_map(db: Session) -> dict[str, dict[str, Any]]:
    """Build normalized property aliases from stored metadata."""
    alias_map: dict[str, dict[str, Any]] = {}
    properties = db.scalars(select(Property).order_by(Property.property_code)).all()
    for prop in properties:
        code = prop.property_code.lower().strip()
        display_name = _property_display_name(prop)
        _add_alias(alias_map, code, code, code, display_name)
        for raw in [prop.property_name, prop.official_property_name]:
            for alias in _alias_variants(raw):
                _add_alias(alias_map, alias, code, raw or display_name, display_name)
        for alias in _url_alias_variants(prop.website_url):
            _add_alias(alias_map, alias, code, prop.website_url or display_name, display_name)
    return alias_map


def _active_property_context(db: Session, property_code: str) -> dict[str, Any]:
    """Return active property name and a compact alias list for the LLM."""
    prop = db.scalar(select(Property).where(Property.property_code == property_code))
    if not prop:
        return {"name": property_code, "aliases": [property_code]}
    aliases = {property_code, _property_display_name(prop)}
    for raw in [prop.property_name, prop.official_property_name]:
        if raw:
            aliases.add(raw)
            aliases.update(_alias_variants(raw))
    aliases = {str(alias) for alias in aliases if alias}
    return {"name": _property_display_name(prop), "aliases": sorted(aliases, key=lambda item: (len(item), item))[:12]}


def _add_alias(alias_map: dict[str, dict[str, Any]], alias: str, code: str, matched_label: str, display_name: str) -> None:
    """Add a safe alias mapping, merging duplicate property variants."""
    normalized = _normalize_property_text(alias)
    if not _is_meaningful_alias(normalized):
        return
    entry = alias_map.setdefault(
        normalized,
        {"alias": normalized, "matched_label": matched_label, "codes": set(), "display_names": set()},
    )
    entry["codes"].add(code)
    entry["display_names"].add(display_name)
    if len(str(matched_label)) < len(str(entry.get("matched_label", ""))) or entry.get("matched_label") == normalized:
        entry["matched_label"] = matched_label


def _alias_variants(value: str | None) -> set[str]:
    """Return conservative name variants such as dropping leading 'the'."""
    normalized = _normalize_property_text(value)
    if not normalized:
        return set()
    variants = {normalized}
    without_the = _drop_leading_the(normalized)
    variants.add(without_the)
    for base in list(variants):
        variants.update(_drop_generic_suffixes(base))
    return {alias for alias in variants if _is_meaningful_alias(alias)}


def _url_alias_variants(value: str | None) -> set[str]:
    """Derive a small set of safe aliases from a property website domain."""
    if not value:
        return set()
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if not host:
        return set()
    stem = host.split(".")[0]
    spaced = _normalize_property_text(stem.replace("-", " "))
    compact = _normalize_property_text(stem)
    return {alias for alias in {spaced, compact} if _is_meaningful_alias(alias)}


def _drop_leading_the(value: str) -> str:
    """Drop leading 'the' only for alias matching."""
    return value[4:] if value.startswith("the ") else value


def _drop_generic_suffixes(value: str) -> set[str]:
    """Drop common trailing real-estate suffixes while keeping meaningful names."""
    variants: set[str] = set()
    tokens = value.split()
    suffixes = {"apartments", "apartment", "residences", "residence", "homes", "home"}
    while len(tokens) > 1 and tokens[-1] in suffixes:
        tokens = tokens[:-1]
        candidate = " ".join(tokens)
        variants.add(candidate)
        variants.add(_drop_leading_the(candidate))
    return variants


def _is_meaningful_alias(value: str) -> bool:
    """Avoid matching tiny or generic aliases by themselves."""
    if not value or len(value) < 4:
        return False
    tokens = value.split()
    if len(tokens) == 1:
        token = tokens[0]
        if any(char.isdigit() for char in token) and len(token) >= 3:
            return True
        return token not in GENERIC_ALIAS_WORDS and len(token) >= 5
    return any(token not in GENERIC_ALIAS_WORDS and len(token) >= 3 for token in tokens)


def _normalize_property_text(value: str | None) -> str:
    """Normalize user text and property aliases for safe phrase matching."""
    if not value:
        return ""
    text = value.lower()
    text = re.sub(r"([a-z0-9])['’]s\b", r"\1s", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _property_display_name(prop: Property) -> str:
    """Return the best user-facing label for a property."""
    return prop.official_property_name or prop.property_name or prop.property_code


def _current_property_label(db: Session, property_code: str) -> str:
    """Return active property name and code for scope-block messages."""
    prop = db.scalar(select(Property).where(Property.property_code == property_code))
    if not prop:
        return property_code
    return f"{_property_display_name(prop)} ({property_code})"


def _cross_property_response(db: Session, property_code: str, scope_issue: dict[str, Any], model: str) -> ChatResponse:
    """Return a safe refusal when the user asks about a property outside the active scope."""
    codes = sorted(scope_issue.get("codes", []))
    code_text = " / ".join(codes)
    requested_name = str(scope_issue.get("matched_label") or scope_issue.get("alias") or "that property")
    return ChatResponse(
        answer_markdown=(
            f"You're currently viewing {_current_property_label(db, property_code)}. "
            f"{requested_name} appears to be a different property"
            f"{f', associated with property code(s) {code_text}' if code_text else ''}. "
            "Please switch the active property before asking this question."
        ),
        components=[],
        sources=[],
        followups=default_followups("CHAT"),
        metadata=ChatMetadata(property_code=property_code, model=model, tools_used=[], route="CHAT"),
    )


def _local_fallback_response(property_code: str, model: str) -> ChatResponse:
    """Return a safe response when OPENAI_API_KEY is missing."""
    return ChatResponse(
        answer_markdown=(
            "Asset AI is ready, but `OPENAI_API_KEY` is not configured in `backend/.env`. "
            "Add the key, restart the backend, then ask property-scoped analytics or website questions."
        ),
        components=[],
        sources=[],
        followups=default_followups("CHAT"),
        metadata={"property_code": property_code, "model": model, "tools_used": [], "route": "CHAT"},
    )
