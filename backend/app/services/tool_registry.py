from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services import analytics_service
from app.services.retrieval_service import retrieve_property_context


CHARGE_CATEGORY_SCHEMA = {
    "type": "string",
    "enum": ["all", "rent", "non_rent"],
    "default": "all",
    "description": "Use rent for rent charges only, non_rent for fees/other charges, or all.",
}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_property_overview",
            "description": "Get latest or selected month property KPIs such as occupancy, rent, balances, and lease risk counts.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_property_health_summary",
            "description": "Get an executive property health summary using rent-roll metrics only.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rent_roll_summary_groups",
            "description": "Return the source Summary Groups table from the rent-roll snapshot, including current residents, future applicants, occupied units, vacant units, non-revenue units, and totals.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_future_residents",
            "description": "Return Future Residents/Applicants from the rent-roll snapshot, including upcoming move-ins, assigned units, market rent, deposits, lease dates, and balance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Optional report month in YYYY-MM."},
                    "include_history": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_occupancy_trend",
            "description": "Get monthly occupancy trend for the active property.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_type_mix",
            "description": "Get unit mix, occupancy, vacancy, average rent, and rent per square foot by unit type.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_charge_breakdown",
            "description": "Get top charge-code totals for latest or selected month, optionally filtered to rent or non-rent charges.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Optional report month in YYYY-MM."},
                    "category": CHARGE_CATEGORY_SCHEMA,
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_charge_trend",
            "description": "Trend charge amounts across months, optionally for a charge code or rent/non-rent category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "charge_code": {"type": "string", "description": "Optional exact charge code to trend."},
                    "category": CHARGE_CATEGORY_SCHEMA,
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lease_expiration_risk",
            "description": "List occupied units with leases expiring within a window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_days": {"type": "integer", "default": 90},
                    "month": {"type": "string", "description": "Optional report month in YYYY-MM."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expiration_summary_by_month",
            "description": "Group lease expirations by month within a snapshot-anchored window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_days": {"type": "integer", "default": 180},
                    "month": {"type": "string", "description": "Optional report month in YYYY-MM."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_high_balance_residents",
            "description": "List top occupied units with positive outstanding balances only; credits are excluded.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "month": {"type": "string", "description": "Optional report month in YYYY-MM."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_balance_summary",
            "description": "Separate positive outstanding balances from negative credits/prepayments.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_balance_trend",
            "description": "Trend net balance, positive balances, and credits across available rent-roll months.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vacant_units",
            "description": "List vacant units and estimated monthly rent loss.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vacancy_loss_by_unit_type",
            "description": "Group vacant units and estimated monthly rent loss by unit type.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "Optional report month in YYYY-MM."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_lookup",
            "description": "Look up one unit's rent, charges, balance, lease dates, and optional history across months.",
            "parameters": {
                "type": "object",
                "required": ["unit"],
                "properties": {
                    "unit": {"type": "string"},
                    "include_history": {"type": "boolean", "default": False},
                    "month": {"type": "string", "description": "Optional report month in YYYY-MM."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_property_context",
            "description": "Retrieve property website facts such as amenities, neighborhood, leasing, floor plans, or contact details.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_months",
            "description": "Get available rent-roll months for the active property.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_property_metadata",
            "description": "Get active property name, address, website URL, and metadata.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def tool_names() -> list[str]:
    """Return the allow-listed tool names exposed to the LLM."""
    return [tool["function"]["name"] for tool in TOOL_SCHEMAS]


def _safe_args(raw: str | None) -> dict[str, Any]:
    """Parse LLM tool arguments defensively and fall back to an empty object."""
    if not raw:
        return {}
    try:
        args = json.loads(raw)
        return args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return {}


def execute_tool(db: Session, property_code: str, tool_name: str, raw_arguments: str | None = None) -> dict[str, Any]:
    """
    Execute one allow-listed tool with backend-enforced property scope.

    The LLM is never trusted to choose property_code. Any property_code-like
    argument is removed, and the active property_code from the API request is
    injected into every analytics and retrieval call.
    """
    args = _safe_args(raw_arguments)
    args.pop("property_code", None)
    args.pop("propertyCode", None)

    dispatch: dict[str, Callable[..., dict[str, Any]]] = {
        "get_property_overview": lambda **kw: analytics_service.get_property_overview(db, property_code, kw.get("month")),
        "get_property_health_summary": lambda **kw: analytics_service.get_property_health_summary(db, property_code, kw.get("month")),
        "get_rent_roll_summary_groups": lambda **kw: analytics_service.get_rent_roll_summary_groups(
            db, property_code, kw.get("month")
        ),
        "get_future_residents": lambda **kw: analytics_service.get_future_residents(
            db, property_code, kw.get("month"), kw.get("include_history", False), kw.get("limit", 50)
        ),
        "get_occupancy_trend": lambda **kw: analytics_service.get_occupancy_trend(db, property_code),
        "get_unit_type_mix": lambda **kw: analytics_service.get_unit_type_mix(db, property_code, kw.get("month")),
        "get_charge_breakdown": lambda **kw: analytics_service.get_charge_breakdown(
            db, property_code, kw.get("month"), kw.get("category", "all"), kw.get("limit", 20)
        ),
        "get_charge_trend": lambda **kw: analytics_service.get_charge_trend(
            db, property_code, kw.get("charge_code"), kw.get("category", "all")
        ),
        "get_lease_expiration_risk": lambda **kw: analytics_service.get_lease_expiration_risk(
            db, property_code, kw.get("window_days", 90), kw.get("month")
        ),
        "get_expiration_summary_by_month": lambda **kw: analytics_service.get_expiration_summary_by_month(
            db, property_code, kw.get("window_days", 180), kw.get("month")
        ),
        "get_high_balance_residents": lambda **kw: analytics_service.get_high_balance_residents(
            db, property_code, kw.get("limit", 10), kw.get("month")
        ),
        "get_balance_summary": lambda **kw: analytics_service.get_balance_summary(db, property_code, kw.get("month")),
        "get_balance_trend": lambda **kw: analytics_service.get_balance_trend(db, property_code),
        "get_vacant_units": lambda **kw: analytics_service.get_vacant_units(db, property_code, kw.get("month")),
        "get_vacancy_loss_by_unit_type": lambda **kw: analytics_service.get_vacancy_loss_by_unit_type(
            db, property_code, kw.get("month")
        ),
        "get_unit_lookup": lambda **kw: analytics_service.get_unit_lookup(
            db, property_code, kw.get("unit", ""), kw.get("include_history", False), kw.get("month")
        ),
        "retrieve_property_context": lambda **kw: retrieve_property_context(
            property_code, kw.get("query", ""), kw.get("top_k", 5)
        ),
        "get_available_months": lambda **kw: analytics_service.get_available_months(db, property_code),
        "get_property_metadata": lambda **kw: analytics_service.get_property_metadata(db, property_code),
    }
    if tool_name not in dispatch:
        return {"error": f"Tool {tool_name} is not allowed.", "property_code": property_code}
    return dispatch[tool_name](**args)
