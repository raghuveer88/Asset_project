from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.schemas import ChatMetadata, ChatResponse, Followup, ResponseComponent, Source


SUPPORTED_COMPONENT_TYPES = {"kpi_cards", "table", "bar_chart", "line_chart"}


def safe_parse_response(raw: str, property_code: str, model: str, tools_used: list[str], route: str) -> ChatResponse:
    """
    Validate the LLM's final JSON response and apply safe fallbacks.

    The backend overwrites metadata.property_code, model, and tools_used so the
    client receives trusted request-scoped metadata even if the model omits or
    changes those fields.
    """
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("LLM returned non-object JSON")
        payload.setdefault("components", [])
        payload["components"] = _normalize_components(payload["components"])
        payload.setdefault("sources", [])
        payload["sources"] = _normalize_sources(payload["sources"])
        payload.setdefault("followups", [])
        payload["followups"] = _normalize_followups(payload["followups"])
        payload["metadata"] = {
            **payload.get("metadata", {}),
            "property_code": property_code,
            "model": model,
            "tools_used": tools_used,
            "route": route,
        }
        response = ChatResponse.model_validate(payload)
        return clean_component_markdown(response)
    except (json.JSONDecodeError, ValidationError, ValueError):
        response = ChatResponse(
            answer_markdown=raw.strip() or "I could not produce a complete response. Please try again.",
            components=[],
            sources=[],
            followups=default_followups(route),
            metadata=ChatMetadata(property_code=property_code, model=model, tools_used=tools_used, route=route),
        )
        return clean_component_markdown(response)


def clean_component_markdown(response: ChatResponse) -> ChatResponse:
    """Remove duplicated Markdown tables when structured components already exist."""
    component_types = {component.type for component in response.components}
    if {"table", "bar_chart", "line_chart", "kpi_cards"} & component_types:
        response.answer_markdown = _strip_markdown_tables(response.answer_markdown)
    response.answer_markdown = _trim_empty_sections(response.answer_markdown)
    return response


def _strip_markdown_tables(markdown: str) -> str:
    """Remove GitHub-style Markdown table blocks from answer text."""
    lines = markdown.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        is_table_start = line.lstrip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}:?\s*\|", next_line)
        if is_table_start:
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                index += 1
            continue
        kept.append(line)
        index += 1
    return "\n".join(kept).strip()


def _trim_empty_sections(markdown: str) -> str:
    """Collapse extra blank lines left after removing duplicate tables."""
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown or "I prepared the relevant property view below."


def _normalize_sources(raw_sources: Any) -> list[dict[str, Any]]:
    """Coerce model source variants into Source-compatible dictionaries."""
    if not isinstance(raw_sources, list):
        return []
    normalized: list[dict[str, Any]] = []
    for source in raw_sources:
        if isinstance(source, str):
            normalized.append({"title": "Property website", "url": source, "snippet": None})
        elif isinstance(source, dict):
            normalized.append(source)
    return normalized


def _normalize_followups(raw_followups: Any) -> list[dict[str, Any]]:
    """Coerce follow-up variants into Followup-compatible dictionaries."""
    if not isinstance(raw_followups, list):
        return []
    normalized: list[dict[str, Any]] = []
    for followup in raw_followups:
        if isinstance(followup, str):
            normalized.append({"label": followup[:32], "question": followup, "route_hint": None})
        elif isinstance(followup, dict) and followup.get("question"):
            normalized.append(
                {
                    "label": followup.get("label") or str(followup["question"])[:32],
                    "question": followup["question"],
                    "route_hint": followup.get("route_hint"),
                }
            )
    return normalized


def default_followups(route: str) -> list[Followup]:
    """Return scoped fallback follow-up chips that map to real tools."""
    if route == "RETRIEVAL":
        return [
            Followup(label="Amenities", question="What amenities does this property advertise?", route_hint="RETRIEVAL"),
            Followup(label="Neighborhood", question="What does the website say about the neighborhood?", route_hint="RETRIEVAL"),
            Followup(label="Floor Plans", question="What floor plans does this property advertise?", route_hint="RETRIEVAL"),
        ]
    return [
        Followup(label="Occupancy", question="What is the current occupancy?", route_hint="PROPERTY_ANALYTICS"),
        Followup(label="Unit Mix", question="Show unit type mix.", route_hint="PROPERTY_ANALYTICS"),
        Followup(label="Balances", question="Separate outstanding balances from credits.", route_hint="PROPERTY_ANALYTICS"),
        Followup(label="Expirations", question="Group lease expirations by month.", route_hint="PROPERTY_ANALYTICS"),
    ]


def contextual_followups(question: str, route: str, tools_used: list[str], tool_results: list[dict[str, Any]]) -> list[Followup]:
    """Build useful follow-up chips from the current question and actual tools used."""
    tool_set = set(tools_used)
    question_lower = question.lower()
    followups: list[Followup]
    if "get_occupancy_trend" in tool_set:
        followups = [
            Followup(label="Unit Mix", question="Show unit type mix.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Vacancy Loss", question="Show vacancy loss by unit type.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Vacant Units", question="Show vacant units.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_unit_type_mix" in tool_set:
        followups = [
            Followup(label="Vacancy Loss", question="Show vacancy loss by unit type.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Occupancy Trend", question="Show occupancy trend across months.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Charge Breakdown", question="Show charge breakdown.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_lease_expiration_risk" in tool_set or "get_expiration_summary_by_month" in tool_set:
        followups = [
            Followup(label="90 Days", question="Which leases expire in the next 90 days?", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="By Month", question="Group lease expirations by month.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Balances", question="Separate outstanding balances from credits.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_balance_summary" in tool_set or "get_high_balance_residents" in tool_set:
        followups = [
            Followup(label="Balance Trend", question="Show balance trend across months.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="High Balances", question="Show high balance residents.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Expirations", question="Which leases expire in the next 90 days?", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_balance_trend" in tool_set:
        followups = [
            Followup(label="Balance Split", question="Separate outstanding balances from credits.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="High Balances", question="Show high balance residents.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Executive Summary", question="Give me an executive summary for this property.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_vacant_units" in tool_set or "get_vacancy_loss_by_unit_type" in tool_set:
        followups = [
            Followup(label="Occupancy", question="What is the current occupancy?", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Unit Mix", question="Show unit type mix.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Trend", question="Show occupancy trend across months.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_charge_breakdown" in tool_set or "get_charge_trend" in tool_set:
        followups = [
            Followup(label="Non-Rent Fees", question="Show non-rent fees.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Rent Trend", question="Show rent charge trend.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Balances", question="Separate outstanding balances from credits.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_rent_roll_summary_groups" in tool_set:
        followups = [
            Followup(label="Future Applicants", question="Show future residents and applicants.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Overview", question="Show the property overview from source totals.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Charge Summary", question="Show charge breakdown.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_future_residents" in tool_set:
        followups = [
            Followup(label="Summary Groups", question="Show the rent-roll summary groups.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Vacant Units", question="Show vacant units.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Overview", question="Show the property overview.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "get_unit_lookup" in tool_set:
        followups = [
            Followup(label="Unit History", question="Has this unit changed across months?", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Vacant Units", question="Show vacant units.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Unit Mix", question="Show unit type mix.", route_hint="PROPERTY_ANALYTICS"),
        ]
    elif "retrieve_property_context" in tool_set:
        followups = [
            Followup(label="Floor Plans", question="What floor plans does this property advertise?", route_hint="RETRIEVAL"),
            Followup(label="Neighborhood", question="What does the website say about the neighborhood?", route_hint="RETRIEVAL"),
            Followup(label="Amenities", question="What amenities does this property advertise?", route_hint="RETRIEVAL"),
        ]
    elif "get_property_health_summary" in tool_set or "executive" in question_lower or "summary" in question_lower:
        followups = [
            Followup(label="Vacancy Loss", question="Show vacancy loss by unit type.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Balances", question="Separate outstanding balances from credits.", route_hint="PROPERTY_ANALYTICS"),
            Followup(label="Expirations", question="Group lease expirations by month.", route_hint="PROPERTY_ANALYTICS"),
        ]
    else:
        followups = default_followups(route)

    seen: set[str] = set()
    unique = []
    for followup in followups:
        if followup.question.lower() == question_lower or followup.question in seen:
            continue
        seen.add(followup.question)
        unique.append(followup)
    return unique[:4]


def concise_answer_from_tool_results(question: str, tool_results: list[dict[str, Any]]) -> str | None:
    """Build concise prose for component-backed answers."""
    results = {item.get("tool_name"): item.get("result", {}) for item in tool_results}
    question_lower = question.lower()

    if "get_property_health_summary" in results:
        result = results["get_property_health_summary"]
        metrics = result.get("key_metrics", {})
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"occupancy is {metrics.get('occupancy_rate', 0)}% with {metrics.get('vacant_units', 0)} vacant units, "
            f"{_money(metrics.get('estimated_monthly_vacancy_loss', 0))} of estimated monthly vacancy loss, and "
            f"{_money(metrics.get('total_positive_balance', 0))} in positive outstanding balances."
        )

    if "get_balance_summary" in results:
        result = results["get_balance_summary"]
        summary = result.get("summary", {})
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"{summary.get('residents_with_positive_balance', 0)} occupied units have positive outstanding balances totaling "
            f"{_money(summary.get('total_positive_balance', 0))}. "
            f"Separately, {summary.get('residents_with_credit_balance', 0)} occupied units have credits/prepayments totaling "
            f"{_money(summary.get('total_credit_balance', 0))}."
        )

    if "get_balance_trend" in results:
        result = results["get_balance_trend"]
        return (
            f"Balance trend is shown from {result.get('start_month')} to {result.get('end_month')}. "
            "This is a rent-roll balance trend, not true accounting delinquency aging."
        )

    if "get_unit_type_mix" in results:
        result = results["get_unit_type_mix"]
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            "the table below breaks out units, occupancy, vacancy, rent, and size by unit type."
        )

    if "get_vacancy_loss_by_unit_type" in results:
        result = results["get_vacancy_loss_by_unit_type"]
        total_loss = sum(row.get("estimated_monthly_rent_loss", 0) for row in result.get("data", []))
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"estimated monthly vacancy loss by unit type totals {_money(total_loss)}."
        )

    if "get_expiration_summary_by_month" in results:
        result = results["get_expiration_summary_by_month"]
        count = sum(row.get("expiring_leases", 0) for row in result.get("data", []))
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"I found {count} leases expiring from {result.get('window_start')} to {result.get('window_end')}, grouped by month."
        )

    if "get_charge_trend" in results:
        result = results["get_charge_trend"]
        label = result.get("charge_code") or result.get("category", "all").replace("_", "-")
        return f"Charge trend for {label} is shown from {result.get('start_month')} to {result.get('end_month')}."

    if "get_rent_roll_summary_groups" in results:
        result = results["get_rent_roll_summary_groups"]
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            "the table below shows the source Summary Groups totals for current residents, future applicants, occupied units, vacant units, and totals."
        )

    if "get_future_residents" in results:
        result = results["get_future_residents"]
        return (
            f"Using the {result.get('report_month') or 'available'} rent roll, "
            f"I found {result.get('future_resident_count', 0)} future residents/applicants with "
            f"{_money(result.get('future_market_rent', 0))} of future market rent and "
            f"{_money(result.get('future_deposits', 0))} of deposits."
        )

    if "get_unit_lookup" in results:
        result = results["get_unit_lookup"]
        count = len(result.get("data", []))
        if count:
            if result.get("matched_as") == "unit_type":
                return (
                    f"I did not find an exact unit named {result.get('unit')}, but I found {count} rent-roll rows "
                    f"where {result.get('unit')} is the unit type."
                )
            return f"I found {count} scoped rent-roll record{'s' if count != 1 else ''} for unit {result.get('unit')}."
        return f"I did not find unit {result.get('unit')} in the active property's rent-roll snapshots."

    if "get_lease_expiration_risk" in results and "get_high_balance_residents" in results:
        lease_result = results["get_lease_expiration_risk"]
        balance_result = results["get_high_balance_residents"]
        lease_count = lease_result.get("total_expiring_leases", len(lease_result.get("data", [])))
        balance_count = balance_result.get("total_positive_balance_count", len(balance_result.get("data", [])))
        return (
            f"Using the {lease_result.get('report_month')} rent roll as of {lease_result.get('as_of_date')}, "
            f"management should focus on {lease_count} leases expiring from {lease_result.get('window_start')} "
            f"to {lease_result.get('window_end')} and {balance_count} residents with positive outstanding balances."
        )

    if "get_lease_expiration_risk" in results:
        result = results["get_lease_expiration_risk"]
        count = result.get("total_expiring_leases", len(result.get("data", [])))
        returned = result.get("returned_rows", len(result.get("data", [])))
        limit_note = f" The table shows the first {returned} rows." if returned and returned < count else ""
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"I found {count} leases expiring from {result.get('window_start')} to {result.get('window_end')}.{limit_note}"
        )

    if "get_high_balance_residents" in results:
        result = results["get_high_balance_residents"]
        count = result.get("total_positive_balance_count", len(result.get("data", [])))
        returned = result.get("returned_rows", len(result.get("data", [])))
        limit_note = f" The table shows the top {returned} rows." if returned and returned < count else ""
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"I found {count} occupied units with positive outstanding balances totaling "
            f"{_money(result.get('total_positive_balance', 0))}. Credits/prepayments are excluded.{limit_note}"
        )

    if "get_occupancy_trend" in results:
        result = results["get_occupancy_trend"]
        data = result.get("data", [])
        if data:
            low = min(data, key=lambda row: row.get("occupancy_rate", 0))
            high = max(data, key=lambda row: row.get("occupancy_rate", 0))
            return (
                f"Occupancy is shown across {result.get('start_month')} to {result.get('end_month')}. "
                f"The low point was {low.get('occupancy_rate')}% in {low.get('month')}, "
                f"and the high point was {high.get('occupancy_rate')}% in {high.get('month')}."
            )
        return "I prepared the occupancy trend chart below for the available report months."

    if "get_charge_breakdown" in results:
        result = results["get_charge_breakdown"]
        category = result.get("category", "all").replace("_", "-")
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"the chart below shows the largest {category} charge categories for this property."
        )

    if "get_vacant_units" in results:
        result = results["get_vacant_units"]
        return (
            f"Using the {result.get('report_month')} rent roll as of {result.get('as_of_date')}, "
            f"I found {result.get('vacant_units', 0)} vacant units with estimated monthly rent loss of "
            f"{_money(result.get('estimated_monthly_rent_loss', 0))}."
        )

    if "get_property_overview" in results:
        overview = results["get_property_overview"]
        if "occupancy" in question_lower:
            return (
                f"As of {overview.get('as_of_date')} ({overview.get('report_month')}), occupancy is "
                f"{overview.get('occupancy_rate')}% with {overview.get('occupied_units')} occupied units out of "
                f"{overview.get('total_units')}."
            )
        balance_note = " Negative net balance generally indicates credits or prepayments." if overview.get("net_balance", 0) < 0 else ""
        return (
            f"Using the latest rent roll ({overview.get('report_month')}, as of {overview.get('as_of_date')}), "
            f"the property is {overview.get('occupancy_rate')}% occupied with {overview.get('vacant_units')} vacant units "
            f"and an occupied-unit net balance of {_money(overview.get('occupied_units_net_balance', overview.get('net_balance', 0)))}."
            f" All-unit net balance is {_money(overview.get('all_units_net_balance', overview.get('total_balance', 0)))}.{balance_note}"
        )

    return None


def _normalize_components(raw_components: Any) -> list[dict[str, Any]]:
    """Drop unsupported or malformed model-provided components."""
    if not isinstance(raw_components, list):
        return []
    normalized: list[dict[str, Any]] = []
    for component in raw_components:
        item = _valid_component_dict(component)
        if item:
            normalized.append(item)
    return normalized


def _valid_component_dict(component: Any) -> dict[str, Any] | None:
    """Return a schema-safe component dict or None."""
    if not isinstance(component, dict):
        return None
    component_type = component.get("type")
    if component_type not in SUPPORTED_COMPONENT_TYPES:
        return None
    item = dict(component)
    item["title"] = str(item.get("title") or _title_for_component(component_type))

    if component_type == "kpi_cards":
        data = item.get("data")
        if not isinstance(data, list) or not data:
            return None
        cards = []
        for card in data:
            if isinstance(card, dict) and {"label", "value"}.issubset(card.keys()):
                cards.append(
                    {
                        "label": str(card.get("label") or ""),
                        "value": str(card.get("value") or ""),
                        "description": str(card.get("description") or ""),
                    }
                )
        if not cards:
            return None
        return {"type": "kpi_cards", "title": item["title"], "data": cards}

    if component_type == "table":
        data = item.get("data")
        if isinstance(data, dict):
            item["columns"] = data.get("headers") or data.get("columns") or item.get("columns")
            item["rows"] = data.get("rows") or item.get("rows")
        columns = [str(col) for col in item.get("columns") or []]
        rows = _rows_to_dicts(columns, item.get("rows") or [])
        if not columns or not rows:
            return None
        return {"type": "table", "title": item["title"], "columns": columns, "rows": rows}

    data = item.get("data")
    x_key = item.get("x_key")
    y_key = item.get("y_key")
    if not isinstance(data, list) or not data or not x_key or not y_key:
        return None
    chart_rows = [row for row in data if isinstance(row, dict) and x_key in row and y_key in row]
    if not chart_rows:
        return None
    return {"type": component_type, "title": item["title"], "data": chart_rows, "x_key": x_key, "y_key": y_key}


def _title_for_component(component_type: Any) -> str:
    """Return a readable fallback title for model-provided components."""
    if component_type == "line_chart":
        return "Trend"
    if component_type == "bar_chart":
        return "Breakdown"
    if component_type == "kpi_cards":
        return "Key Metrics"
    if component_type == "table":
        return "Details"
    return "Insight"


def _rows_to_dicts(columns: list[str], rows: Any) -> list[dict[str, Any]]:
    """Convert table rows from list form into dictionaries keyed by columns."""
    if not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            output.append(row)
        elif isinstance(row, list):
            output.append({columns[index]: value for index, value in enumerate(row) if index < len(columns)})
    return output


def components_from_tool_results(tool_results: list[dict[str, Any]]) -> list[ResponseComponent]:
    """Build deterministic UI components from tool results."""
    components: list[ResponseComponent] = []
    for item in tool_results:
        name = item.get("tool_name")
        result = item.get("result", {})
        if "error" in result:
            continue
        if name == "get_property_overview":
            components.append(
                ResponseComponent(
                    type="kpi_cards",
                    title="Property Overview",
                    data=[
                        {"label": "Occupancy", "value": f"{result.get('occupancy_rate', 0)}%", "description": result.get("report_month")},
                        {"label": "Occupied Units", "value": str(result.get("occupied_units", 0)), "description": f"{result.get('total_units', 0)} total"},
                        {"label": "Occupied Net Balance", "value": _money(result.get("occupied_units_net_balance", result.get("net_balance", 0))), "description": "Credits can be negative"},
                        {"label": "Vacant Units", "value": str(result.get("vacant_units", 0)), "description": result.get("as_of_date") or "Latest month"},
                    ],
                )
            )
        elif name == "get_property_health_summary":
            metrics = result.get("key_metrics", {})
            components.append(
                ResponseComponent(
                    type="kpi_cards",
                    title="Executive Summary",
                    data=[
                        {"label": "Occupancy", "value": f"{metrics.get('occupancy_rate', 0)}%", "description": f"{metrics.get('occupied_units', 0)} of {metrics.get('total_units', 0)}"},
                        {"label": "Vacant Units", "value": str(metrics.get("vacant_units", 0)), "description": "Current snapshot"},
                        {"label": "Vacancy Loss", "value": _money(metrics.get("estimated_monthly_vacancy_loss", 0)), "description": "Estimated monthly"},
                        {"label": "Positive Balances", "value": _money(metrics.get("total_positive_balance", 0)), "description": "Credits excluded"},
                    ],
                )
            )
            _append_table(components, "Management Focus", ["focus_area", "metric", "detail"], result.get("risks", []))
            _append_table(components, "Opportunities", ["focus_area", "metric", "detail"], result.get("opportunities", []))
        elif name == "get_occupancy_trend":
            _append_line(components, "Occupancy Trend", "month", "occupancy_rate", result.get("data", []))
        elif name == "get_unit_type_mix":
            _append_table(
                components,
                "Unit Type Mix",
                [
                    "unit_type",
                    "total_units",
                    "occupied_units",
                    "vacant_units",
                    "occupancy_rate",
                    "average_market_rent",
                    "average_sqft",
                    "rent_per_sqft",
                ],
                result.get("data", []),
            )
        elif name == "get_charge_breakdown":
            category = str(result.get("category") or "all").replace("_", "-").title()
            _append_bar(components, f"{category} Charge Breakdown", "charge_code", "amount", result.get("data", []))
        elif name == "get_charge_trend":
            label = result.get("charge_code") or str(result.get("category") or "all").replace("_", "-").title()
            _append_line(components, f"{label} Charge Trend", "month", "amount", result.get("data", []))
        elif name == "get_lease_expiration_risk":
            _append_table(
                components,
                f"Lease Expirations: {result.get('window_start')} to {result.get('window_end')}",
                ["unit", "resident_id", "lease_expiration", "market_rent", "balance"],
                result.get("data", []),
            )
        elif name == "get_expiration_summary_by_month":
            _append_bar(components, "Lease Expirations by Month", "expiration_month", "expiring_leases", result.get("data", []))
            _append_table(
                components,
                "Lease Expiration Exposure",
                ["expiration_month", "expiring_leases", "total_market_rent", "average_market_rent", "total_balance"],
                result.get("data", []),
            )
        elif name == "get_high_balance_residents":
            _append_table(
                components,
                "High Balance Residents",
                ["unit", "resident_id", "balance", "market_rent", "lease_expiration"],
                result.get("data", []),
            )
        elif name == "get_balance_summary":
            summary = result.get("summary", {})
            components.append(
                ResponseComponent(
                    type="kpi_cards",
                    title="Balance Summary",
                    data=[
                        {"label": "Outstanding", "value": _money(summary.get("total_positive_balance", 0)), "description": f"{summary.get('residents_with_positive_balance', 0)} residents"},
                        {"label": "Credits", "value": _money(summary.get("total_credit_balance", 0)), "description": f"{summary.get('residents_with_credit_balance', 0)} residents"},
                        {"label": "Net Balance", "value": _money(summary.get("net_balance", 0)), "description": "Outstanding minus credits"},
                        {"label": "Avg Outstanding", "value": _money(summary.get("average_positive_balance", 0)), "description": "Positive balances only"},
                    ],
                )
            )
            _append_table(
                components,
                "Top Positive Balances",
                ["unit", "resident_id", "balance", "market_rent", "lease_expiration"],
                result.get("top_positive_balances", []),
            )
            _append_table(
                components,
                "Top Credits",
                ["unit", "resident_id", "balance", "market_rent", "lease_expiration"],
                result.get("top_credits", []),
            )
        elif name == "get_balance_trend":
            _append_line(components, "Net Balance Trend", "month", "net_balance", result.get("data", []))
            _append_table(
                components,
                "Balance Trend Detail",
                ["month", "net_balance", "total_positive_balance", "total_credit_balance", "residents_with_positive_balance", "residents_with_credit_balance"],
                result.get("data", []),
            )
        elif name == "get_vacant_units":
            _append_table(
                components,
                "Vacant Units",
                ["unit", "unit_type", "market_rent", "estimated_monthly_rent_loss"],
                result.get("data", []),
            )
        elif name == "get_vacancy_loss_by_unit_type":
            _append_bar(components, "Vacancy Loss by Unit Type", "unit_type", "estimated_monthly_rent_loss", result.get("data", []))
            _append_table(
                components,
                "Vacancy Loss by Unit Type",
                ["unit_type", "vacant_units", "estimated_monthly_rent_loss", "average_market_rent", "average_sqft"],
                result.get("data", []),
            )
        elif name == "get_rent_roll_summary_groups":
            _append_table(
                components,
                "Rent-Roll Summary Groups",
                [
                    "group_name",
                    "square_footage",
                    "market_rent",
                    "lease_charges",
                    "security_deposit",
                    "other_deposits",
                    "unit_count",
                    "unit_occupancy_pct",
                    "sqft_occupied_pct",
                    "balance",
                ],
                result.get("data", []),
            )
        elif name == "get_future_residents":
            components.append(
                ResponseComponent(
                    type="kpi_cards",
                    title="Future Residents/Applicants",
                    data=[
                        {"label": "Future Applicants", "value": str(result.get("future_resident_count", 0)), "description": result.get("report_month") or "History"},
                        {"label": "Future Market Rent", "value": _money(result.get("future_market_rent", 0)), "description": "Source future section"},
                        {"label": "Future Deposits", "value": _money(result.get("future_deposits", 0)), "description": "Security and other deposits"},
                        {"label": "Future Balance", "value": _money(result.get("future_balance", 0)), "description": "Source future section"},
                    ],
                )
            )
            _append_table(
                components,
                "Future Residents/Applicants",
                [
                    "report_month",
                    "unit",
                    "unit_type",
                    "resident_id",
                    "market_rent",
                    "resident_deposit",
                    "move_in",
                    "lease_expiration",
                    "balance",
                ],
                result.get("data", []),
            )
        elif name == "get_unit_lookup":
            columns = [
                "report_month",
                "unit",
                "unit_type",
                "unit_sqft",
                "occupancy_status",
                "resident_id",
                "market_rent",
                "rent_charges",
                "all_charges",
                "balance",
                "move_in",
                "lease_expiration",
                "move_out",
                "charge_codes",
            ]
            title = f"Unit {result.get('unit')}"
            if result.get("matched_as") == "unit_type":
                columns = ["matched_as", *columns]
                title = f"Unit Type {result.get('unit')}"
            _append_table(
                components,
                title,
                columns,
                result.get("data", []),
            )
    return components


def _append_table(components: list[ResponseComponent], title: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    """Append a table component, letting the frontend render an empty state."""
    components.append(ResponseComponent(type="table", title=title, columns=columns, rows=rows or []))


def _append_bar(
    components: list[ResponseComponent], title: str, x_key: str, y_key: str, rows: list[dict[str, Any]]
) -> None:
    """Append a bar chart component, letting the frontend render an empty state."""
    components.append(ResponseComponent(type="bar_chart", title=title, x_key=x_key, y_key=y_key, data=rows or []))


def _append_line(
    components: list[ResponseComponent], title: str, x_key: str, y_key: str, rows: list[dict[str, Any]]
) -> None:
    """Append a line chart component, letting the frontend render an empty state."""
    components.append(ResponseComponent(type="line_chart", title=title, x_key=x_key, y_key=y_key, data=rows or []))


def sources_from_tool_results(tool_results: list[dict[str, Any]]) -> list[Source]:
    """Convert retrieval tool chunks into compact, de-duplicated citations."""
    sources: list[Source] = []
    seen: set[tuple[str | None, str | None]] = set()
    for item in tool_results:
        if item.get("tool_name") != "retrieve_property_context":
            continue
        for result in item.get("result", {}).get("results", []):
            key = (result.get("page_title"), result.get("url"))
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                Source(title=result.get("page_title") or "Property website", url=result.get("url"), snippet=result.get("snippet", "")[:240])
            )
    return sources[:8]


def _money(value: Any) -> str:
    """Format a numeric value as a whole-dollar string for KPI cards."""
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "$0"
