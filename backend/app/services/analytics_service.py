from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    Property,
    RentRollChargeSummary,
    RentRollFutureResident,
    RentRollRow,
    RentRollSnapshot,
    RentRollSummaryGroup,
)


def _latest_month(db: Session, property_code: str) -> str | None:
    """Return the latest report month for one property, scoped by property_code."""
    return db.scalar(
        select(RentRollSnapshot.report_month)
        .where(RentRollSnapshot.property_code == property_code)
        .order_by(desc(RentRollSnapshot.report_month))
        .limit(1)
    )


def _available_months(db: Session, property_code: str, ascending: bool = True) -> list[str]:
    """Return report months for one active property."""
    order_by = RentRollSnapshot.report_month if ascending else desc(RentRollSnapshot.report_month)
    return list(
        db.scalars(
            select(RentRollSnapshot.report_month)
            .where(RentRollSnapshot.property_code == property_code)
            .distinct()
            .order_by(order_by)
        ).all()
    )


def _resolve_month(db: Session, property_code: str, month: str | None) -> str | None:
    """
    Validate an optional month for one property or fall back to the latest month.

    A requested month is only accepted if a snapshot exists for the same
    property_code, preventing accidental cross-property month lookups.
    """
    if month:
        exists = db.scalar(
            select(RentRollSnapshot.id)
            .where(
                RentRollSnapshot.property_code == property_code,
                RentRollSnapshot.report_month == month,
            )
            .limit(1)
        )
        return month if exists else None
    return _latest_month(db, property_code)


def _snapshot_for_month(db: Session, property_code: str, report_month: str) -> RentRollSnapshot | None:
    """Return the newest snapshot row for one property/month pair."""
    return db.scalar(
        select(RentRollSnapshot)
        .where(RentRollSnapshot.property_code == property_code, RentRollSnapshot.report_month == report_month)
        .order_by(desc(RentRollSnapshot.created_at), desc(RentRollSnapshot.id))
        .limit(1)
    )


def _summary_group_for_month(
    db: Session, property_code: str, month: str, group_name: str
) -> RentRollSummaryGroup | None:
    """Return one canonical Summary Groups row for the latest snapshot in a month."""
    snapshot = _snapshot_for_month(db, property_code, month)
    if not snapshot:
        return None
    return db.scalar(
        select(RentRollSummaryGroup)
        .where(
            RentRollSummaryGroup.snapshot_id == snapshot.id,
            RentRollSummaryGroup.property_code == property_code,
            RentRollSummaryGroup.group_name == group_name,
        )
        .limit(1)
    )


def _summary_groups_for_month(db: Session, property_code: str, month: str) -> list[RentRollSummaryGroup]:
    """Return all Summary Groups rows for the latest snapshot in a month."""
    snapshot = _snapshot_for_month(db, property_code, month)
    if not snapshot:
        return []
    return list(
        db.scalars(
            select(RentRollSummaryGroup)
            .where(RentRollSummaryGroup.snapshot_id == snapshot.id, RentRollSummaryGroup.property_code == property_code)
            .order_by(RentRollSummaryGroup.id)
        ).all()
    )


def _charge_summaries_for_month(db: Session, property_code: str, month: str) -> list[RentRollChargeSummary]:
    """Return source charge-code summaries for the latest snapshot in a month."""
    snapshot = _snapshot_for_month(db, property_code, month)
    if not snapshot:
        return []
    return list(
        db.scalars(
            select(RentRollChargeSummary)
            .where(RentRollChargeSummary.snapshot_id == snapshot.id, RentRollChargeSummary.property_code == property_code)
            .order_by(RentRollChargeSummary.charge_code)
        ).all()
    )


def _future_residents_for_month(db: Session, property_code: str, month: str) -> list[RentRollFutureResident]:
    """Return Future Residents/Applicants rows for the latest snapshot in a month."""
    snapshot = _snapshot_for_month(db, property_code, month)
    if not snapshot:
        return []
    return list(
        db.scalars(
            select(RentRollFutureResident)
            .where(RentRollFutureResident.snapshot_id == snapshot.id, RentRollFutureResident.property_code == property_code)
            .order_by(RentRollFutureResident.move_in, RentRollFutureResident.unit, RentRollFutureResident.id)
        ).all()
    )


def _summary_groups_by_name(db: Session, property_code: str, month: str) -> dict[str, RentRollSummaryGroup]:
    """Return Summary Groups keyed by canonical group_name."""
    return {group.group_name: group for group in _summary_groups_for_month(db, property_code, month)}


def _normalize_label(value: Any) -> str:
    """Normalize rent-roll labels without treating numbers as special."""
    text = str(value or "").strip().lower()
    return " ".join(text.replace("_", " ").replace("-", " ").replace(":", " ").split())


SUMMARY_LABELS = {
    "total",
    "totals",
    "subtotal",
    "grand total",
    "page total",
    "property total",
    "current notice vacant residents",
    "future residents applicants",
    "occupied units",
    "non rev units",
    "vacant units",
    "total non rev units",
    "total vacant units",
    "summary groups",
}


def _looks_like_summary_unit(value: Any) -> bool:
    """
    Identify obvious non-unit labels without dropping numeric unit IDs.

    Many properties use units like 305, 1101, or 1202. Numeric-looking values
    are therefore valid unit identifiers and must not be filtered here.
    """
    normalized = _normalize_label(value)
    if not normalized:
        return True
    return normalized in SUMMARY_LABELS or normalized.endswith(" total") or normalized.endswith(" totals")


def _looks_like_summary_code(value: Any) -> bool:
    """Identify total/subtotal or numeric footer values in charge-code fields."""
    text = str(value or "").strip()
    normalized = _normalize_label(text)
    if not normalized:
        return False
    numeric_like = all(char.isdigit() or char in "$,.() -+" for char in text)
    return normalized in SUMMARY_LABELS or normalized.endswith(" total") or normalized.endswith(" totals") or numeric_like


def _normalize_charge_code(value: Any) -> str:
    """Normalize charge codes for allowlist matching."""
    return "".join(char for char in str(value or "").upper().strip() if char.isalnum())


# RENT_CHARGE_CODES = {"RENT", "MARKET", "BASERENT", "RENTAFF", "RENTRETL", "CONRENT","RNTPROF"}

RENT_CHARGE_CODES = {
    "RENT",      # standard residential rent
    "RENTAFF",   # affordable-program rent
    "RENTRETL",  # retail/commercial rent
    "CONRENT",   # rent concession / adjustment
    "RNTPROF",   # professional/retail rent variant
    "CONRETL",   # retail rent concession / adjustment
}

CHARGE_CODE_DICTIONARY = {
    "RENT": "Standard apartment rent.",
    "MARKET": "Market rent when supplied as a charge code.",
    "BASERENT": "Base rent.",
    "RENTAFF": "Affordable-program rent.",
    "RENTRETL": "Retail/commercial rent.",
    "CONRENT": "Rent concession or rent-related adjustment.",
    "PARKING": "Parking charge.",
    "AMENITY": "Amenity fee.",
    "TRASH": "Trash or waste fee.",
    "PETFEEM": "Monthly pet fee.",
    "GARAGE": "Garage charge.",
    "STORAGE": "Storage charge.",
    "SUBSIDY": "Subsidy amount.",
    "MTM": "Month-to-month charge.",
    "RNTPROF": "Professional/retail rent variant seen in source data.",
    "RETXEST": "Estimated retail tax/expense charge seen in source data.",
    "CONRETL": "Retail rent concession or rent-related adjustment.",
}


def _is_rent_charge_code(value: Any) -> bool:
    """
    Return True only for explicit rent-like charge codes.

    This is allowlist-based because substring checks such as "RENT" in code
    incorrectly classify charge codes like CURRENT as rent.
    """
    code = _normalize_charge_code(value)
    return code in RENT_CHARGE_CODES


def _charge_allowed(charge_code: Any, category: str = "all") -> bool:
    """Apply supported charge-code category filters."""
    if _looks_like_summary_code(charge_code):
        return False
    if category == "rent":
        return _is_rent_charge_code(charge_code)
    if category == "non_rent":
        return not _is_rent_charge_code(charge_code)
    return True


def _unit_rollup(db: Session, property_code: str, month: str, snapshot_id: int | None = None) -> list[dict[str, Any]]:
    """
    Collapse rent-roll charge rows into one compact row per unit.

    Rent-roll files can contain multiple charge rows per unit. This function
    uses the latest snapshot for property_code/month, then rolls rows up into
    unit-level context used by all analytics tools.
    """
    if snapshot_id is None:
        snapshot = _snapshot_for_month(db, property_code, month)
        if not snapshot:
            return []
        snapshot_id = snapshot.id
    rows = db.scalars(
        select(RentRollRow)
        .where(RentRollRow.snapshot_id == snapshot_id, RentRollRow.property_code == property_code)
        .order_by(RentRollRow.unit, RentRollRow.id)
    ).all()
    units: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (
            _looks_like_summary_unit(row.unit)
            or (row.resident_id is not None and _looks_like_summary_unit(row.resident_id))
            or (row.resident_name is not None and _looks_like_summary_unit(row.resident_name))
        ):
            continue
        unit_key = row.unit or f"row-{row.id}"
        if unit_key not in units:
            units[unit_key] = {
                "unit": row.unit,
                "unit_type": row.unit_type,
                "unit_sqft": row.unit_sqft,
                "resident_id": row.resident_id,
                "resident_name": row.resident_name,
                "market_rent": row.market_rent or 0.0,
                "resident_deposit": row.resident_deposit or 0.0,
                "other_deposit": row.other_deposit or 0.0,
                "move_in": row.move_in,
                "lease_expiration": row.lease_expiration,
                "move_out": row.move_out,
                "balance": row.balance if row.balance is not None else 0.0,
                "_balance_seen": row.balance is not None,
                "occupancy_status": row.occupancy_status,
                "rent_charges": 0.0,
                "all_charges": 0.0,
                "charge_codes": set(),
            }
        unit = units[unit_key]
        amount = row.charge_amount or 0.0
        code = (row.charge_code or "").upper()
        if code and not _looks_like_summary_code(code):
            unit["charge_codes"].add(code)
        if _charge_allowed(code):
            unit["all_charges"] += amount
        if _charge_allowed(code, "rent"):
            unit["rent_charges"] += amount
        if row.balance is not None and not unit["_balance_seen"]:
            unit["balance"] = row.balance
            unit["_balance_seen"] = True
    for unit in units.values():
        unit["charge_codes"] = sorted(unit["charge_codes"])
        unit.pop("_balance_seen", None)
    return list(units.values())


def _is_occupied(unit: dict[str, Any]) -> bool:
    """
    Infer whether a unit is occupied from resident context.

    Historical report months are evaluated from the rent-roll values, not the
    current date, so older move-out fields do not distort occupancy.
    """
    resident_id = str(unit.get("resident_id") or "").strip().lower()
    resident_name = str(unit.get("resident_name") or "").strip().lower()
    status = (unit.get("occupancy_status") or "").lower()
    vacant_markers = {"vacant", "vacant unit", "vacant/notice", "vacant notice", "notice/vacant", "vacant resident"}
    if resident_id:
        normalized_id = _normalize_label(resident_id)
        if normalized_id in vacant_markers or normalized_id.startswith("vacant"):
            return False
        return True
    if resident_name and resident_name not in {"[redacted]", "redacted", "none", "nan"}:
        normalized_name = _normalize_label(resident_name)
        if normalized_name in vacant_markers or normalized_name.startswith("vacant"):
            return False
        return True
    if status:
        return status == "occupied" and bool(resident_id)
    return False


def _money_value(value: Any) -> str:
    """Format dollar values for deterministic executive summary text."""
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "$0"


def _num(value: Any, default: float = 0.0) -> float:
    """Return a numeric value while preserving explicit zeros."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int = 0) -> int:
    """Return an int value while preserving explicit zeros."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _summary_group_to_dict(group: RentRollSummaryGroup) -> dict[str, Any]:
    """Serialize a Summary Groups row for tool output."""
    return {
        "group_name": group.group_name,
        "original_label": group.original_label,
        "square_footage": round(_num(group.square_footage), 2) if group.square_footage is not None else None,
        "market_rent": round(_num(group.market_rent), 2) if group.market_rent is not None else None,
        "lease_charges": round(_num(group.lease_charges), 2) if group.lease_charges is not None else None,
        "security_deposit": round(_num(group.security_deposit), 2) if group.security_deposit is not None else None,
        "other_deposits": round(_num(group.other_deposits), 2) if group.other_deposits is not None else None,
        "unit_count": group.unit_count,
        "unit_occupancy_pct": round(_num(group.unit_occupancy_pct), 2) if group.unit_occupancy_pct is not None else None,
        "sqft_occupied_pct": round(_num(group.sqft_occupied_pct), 2) if group.sqft_occupied_pct is not None else None,
        "balance": round(_num(group.balance), 2) if group.balance is not None else None,
    }


def _future_resident_to_dict(row: RentRollFutureResident, report_month: str) -> dict[str, Any]:
    """Serialize a Future Residents/Applicants row for tool output."""
    return {
        "report_month": report_month,
        "unit": row.unit,
        "unit_type": row.unit_type,
        "unit_sqft": row.unit_sqft,
        "resident_id": row.resident_id or row.resident_name,
        "resident_name": row.resident_name,
        "market_rent": round(_num(row.market_rent), 2),
        "resident_deposit": round(_num(row.resident_deposit), 2),
        "other_deposit": round(_num(row.other_deposit), 2),
        "move_in": row.move_in.isoformat() if row.move_in else None,
        "lease_expiration": row.lease_expiration.isoformat() if row.lease_expiration else None,
        "move_out": row.move_out.isoformat() if row.move_out else None,
        "balance": round(_num(row.balance), 2),
    }


def get_available_months(db: Session, property_code: str) -> dict[str, Any]:
    """Return all rent-roll report months available for one property."""
    return {"property_code": property_code, "months": _available_months(db, property_code, ascending=False)}


def get_property_metadata(db: Session, property_code: str) -> dict[str, Any]:
    """Return stored property metadata for the active property."""
    prop = db.scalar(select(Property).where(Property.property_code == property_code))
    if not prop:
        return {"property_code": property_code, "found": False}
    return {
        "property_code": prop.property_code,
        "property_name": prop.property_name,
        "official_property_name": prop.official_property_name,
        "address": prop.address,
        "website_url": prop.website_url,
        "match_confidence": prop.match_confidence,
        "found": True,
    }


def get_property_overview(db: Session, property_code: str, month: str | None = None) -> dict[str, Any]:
    """Build a compact overview for one property and reporting month."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}

    snapshot = _snapshot_for_month(db, property_code, report_month)
    units = _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None)
    occupied = [u for u in units if _is_occupied(u)]
    vacant = [u for u in units if not _is_occupied(u)]
    groups = _summary_groups_by_name(db, property_code, report_month)
    current_group = groups.get("current_notice_vacant_residents")
    occupied_group = groups.get("occupied_units")
    vacant_group = groups.get("total_vacant_units")
    non_rev_group = groups.get("total_non_rev_units")
    future_group = groups.get("future_residents_applicants")
    totals_group = groups.get("totals")
    summary_source = current_group is not None

    detail_total_units = len(units)
    detail_total_market_rent = sum(u["market_rent"] or 0 for u in units)
    detail_rent_charges = sum(u["rent_charges"] or 0 for u in units)
    detail_all_units_net_balance = sum(u["balance"] or 0 for u in units)
    occupied_units_net_balance = sum(u["balance"] or 0 for u in occupied)

    total_units = _int_value(current_group.unit_count, detail_total_units) if current_group else detail_total_units
    occupied_units = _int_value(occupied_group.unit_count, len(occupied)) if occupied_group else len(occupied)
    vacant_units = _int_value(vacant_group.unit_count, len(vacant)) if vacant_group else len(vacant)
    total_market_rent = _num(current_group.market_rent, detail_total_market_rent) if current_group else detail_total_market_rent
    total_charge_rent = _num(current_group.lease_charges, detail_rent_charges) if current_group else detail_rent_charges
    current_net_balance = _num(current_group.balance, detail_all_units_net_balance) if current_group else detail_all_units_net_balance
    all_units_net_balance = current_net_balance
    occupancy_rate = (
        _num(current_group.unit_occupancy_pct)
        if current_group and current_group.unit_occupancy_pct is not None
        else round((occupied_units / total_units) * 100, 2)
        if total_units
        else 0
    )

    anchor_date = snapshot.as_of_date if snapshot and snapshot.as_of_date else date.today()
    upcoming = [
        u
        for u in occupied
        if u.get("lease_expiration")
        and anchor_date <= u["lease_expiration"] <= anchor_date + timedelta(days=90)
    ]
    return {
        "property_code": property_code,
        "property_name": snapshot.property_name if snapshot else None,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "total_units": total_units,
        "occupied_units": occupied_units,
        "vacant_units": vacant_units,
        "occupancy_rate": round(occupancy_rate, 2),
        "total_market_rent": round(total_market_rent, 2),
        "total_charge_rent": round(total_charge_rent, 2),
        "average_market_rent": round(total_market_rent / total_units, 2) if total_units else 0,
        "all_units_net_balance": round(all_units_net_balance, 2),
        "occupied_units_net_balance": round(occupied_units_net_balance, 2),
        "net_balance": round(current_net_balance, 2),
        "total_balance": round(all_units_net_balance, 2),
        "balance_note": "Negative net balances usually indicate credits or prepayments." if current_net_balance < 0 else None,
        "high_balance_count": len([u for u in occupied if (u["balance"] or 0) > 0]),
        "positive_balance_count": len([u for u in occupied if (u["balance"] or 0) > 0]),
        "upcoming_lease_expirations_count": len(upcoming),
        "current_net_balance": round(current_net_balance, 2),
        "source_total_balance": round(_num(totals_group.balance), 2) if totals_group and totals_group.balance is not None else None,
        "future_resident_count": _int_value(future_group.unit_count, 0) if future_group else 0,
        "future_market_rent": round(_num(future_group.market_rent), 2) if future_group else 0,
        "future_security_deposit": round(_num(future_group.security_deposit), 2) if future_group else 0,
        "future_balance": round(_num(future_group.balance), 2) if future_group else 0,
        "non_revenue_units": _int_value(non_rev_group.unit_count, 0) if non_rev_group else 0,
        "vacancy_market_rent": round(_num(vacant_group.market_rent), 2) if vacant_group else round(sum(u["market_rent"] or 0 for u in vacant), 2),
        "summary_source": summary_source,
    }


def get_occupancy_trend(db: Session, property_code: str) -> dict[str, Any]:
    """Return a month-by-month occupancy trend for one property."""
    trend = []
    for month in _available_months(db, property_code):
        overview = get_property_overview(db, property_code, month)
        if "error" not in overview:
            trend.append(
                {
                    "month": month,
                    "total_units": overview["total_units"],
                    "occupied_units": overview["occupied_units"],
                    "vacant_units": overview["vacant_units"],
                    "occupancy_rate": overview["occupancy_rate"],
                }
            )
    return {
        "property_code": property_code,
        "start_month": trend[0]["month"] if trend else None,
        "end_month": trend[-1]["month"] if trend else None,
        "data": trend,
    }


def get_unit_type_mix(db: Session, property_code: str, month: str | None = None) -> dict[str, Any]:
    """Summarize unit count, occupancy, rent, and size by unit type."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None):
        groups[unit.get("unit_type") or "Unknown"].append(unit)

    data = []
    for unit_type, units in sorted(groups.items()):
        total_units = len(units)
        occupied_units = len([u for u in units if _is_occupied(u)])
        vacant_units = total_units - occupied_units
        sqft_values = [u["unit_sqft"] for u in units if u.get("unit_sqft")]
        total_market_rent = sum(u.get("market_rent") or 0 for u in units)
        average_sqft = sum(sqft_values) / len(sqft_values) if sqft_values else 0
        average_market_rent = total_market_rent / total_units if total_units else 0
        data.append(
            {
                "unit_type": unit_type,
                "total_units": total_units,
                "occupied_units": occupied_units,
                "vacant_units": vacant_units,
                "occupancy_rate": round((occupied_units / total_units) * 100, 2) if total_units else 0,
                "average_market_rent": round(average_market_rent, 2),
                "total_market_rent": round(total_market_rent, 2),
                "average_sqft": round(average_sqft, 2) if average_sqft else None,
                "rent_per_sqft": round(average_market_rent / average_sqft, 2) if average_sqft else None,
            }
        )
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "data": data,
    }


def get_charge_breakdown(
    db: Session, property_code: str, month: str | None = None, category: str = "all", limit: int = 20
) -> dict[str, Any]:
    """Return top charge-code totals for one property and month."""
    category = category if category in {"all", "rent", "non_rent"} else "all"
    limit = min(max(int(limit or 20), 1), 50)
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    grouped: dict[str, dict[str, Any]] = {}
    charge_summaries = _charge_summaries_for_month(db, property_code, report_month)
    if charge_summaries:
        for row in charge_summaries:
            code = (row.charge_code or "UNKNOWN").upper()
            if not _charge_allowed(code, category):
                continue
            grouped.setdefault(code, {"charge_code": code, "amount": 0.0, "rows": 0})
            grouped[code]["amount"] += row.amount or 0.0
            grouped[code]["rows"] += 1
    else:
        rows = (
            db.scalars(
                select(RentRollRow).where(RentRollRow.snapshot_id == snapshot.id, RentRollRow.property_code == property_code)
            ).all()
            if snapshot
            else []
        )
        for row in rows:
            code = (row.charge_code or "UNKNOWN").upper()
            if not _charge_allowed(code, category):
                continue
            grouped.setdefault(code, {"charge_code": code, "amount": 0.0, "rows": 0})
            grouped[code]["amount"] += row.charge_amount or 0.0
            grouped[code]["rows"] += 1
    data = sorted(grouped.values(), key=lambda item: item["amount"], reverse=True)[:limit]
    for item in data:
        item["amount"] = round(float(item["amount"] or 0), 2)
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "category": category,
        "limit": limit,
        "summary_source": bool(charge_summaries),
        "data": data,
    }


def get_lease_expiration_risk(
    db: Session, property_code: str, window_days: int = 90, month: str | None = None
) -> dict[str, Any]:
    """List occupied units with leases expiring inside a bounded window."""
    window_days = min(max(int(window_days or 90), 1), 365)
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    anchor_date = snapshot.as_of_date if snapshot and snapshot.as_of_date else date.today()
    end = anchor_date + timedelta(days=window_days)
    units = [
        u
        for u in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None)
        if _is_occupied(u) and u.get("lease_expiration") and anchor_date <= u["lease_expiration"] <= end
    ]
    units.sort(key=lambda u: u["lease_expiration"])
    data = [
        {
            "unit": u["unit"],
            "resident_id": u["resident_id"] or u["resident_name"],
            "lease_expiration": u["lease_expiration"].isoformat(),
            "market_rent": round(u["market_rent"] or 0, 2),
            "balance": round(u["balance"] or 0, 2),
        }
        for u in units[:50]
    ]
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": anchor_date.isoformat(),
        "window_start": anchor_date.isoformat(),
        "window_end": end.isoformat(),
        "window_days": window_days,
        "total_expiring_leases": len(units),
        "returned_rows": len(data),
        "data": data,
    }


def get_expiration_summary_by_month(
    db: Session, property_code: str, window_days: int = 180, month: str | None = None
) -> dict[str, Any]:
    """Group lease expirations by expiration month inside a snapshot-anchored window."""
    window_days = min(max(int(window_days or 180), 1), 365)
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    anchor_date = snapshot.as_of_date if snapshot and snapshot.as_of_date else date.today()
    end = anchor_date + timedelta(days=window_days)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None):
        expiration = unit.get("lease_expiration")
        if _is_occupied(unit) and expiration and anchor_date <= expiration <= end:
            grouped[expiration.strftime("%Y-%m")].append(unit)
    data = []
    for expiration_month, units in sorted(grouped.items()):
        total_market_rent = sum(u.get("market_rent") or 0 for u in units)
        data.append(
            {
                "expiration_month": expiration_month,
                "expiring_leases": len(units),
                "total_market_rent": round(total_market_rent, 2),
                "average_market_rent": round(total_market_rent / len(units), 2) if units else 0,
                "total_balance": round(sum(u.get("balance") or 0 for u in units), 2),
            }
        )
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": anchor_date.isoformat(),
        "window_start": anchor_date.isoformat(),
        "window_end": end.isoformat(),
        "window_days": window_days,
        "data": data,
    }


def get_high_balance_residents(
    db: Session, property_code: str, limit: int = 10, month: str | None = None
) -> dict[str, Any]:
    """Return the highest outstanding balances for occupied units in one property."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    units = [
        u
        for u in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None)
        if _is_occupied(u) and (u["balance"] or 0) > 0
    ]
    units.sort(key=lambda u: u["balance"] or 0, reverse=True)
    data = [
        {
            "unit": u["unit"],
            "resident_id": u["resident_id"] or u["resident_name"],
            "balance": round(u["balance"] or 0, 2),
            "market_rent": round(u["market_rent"] or 0, 2),
            "lease_expiration": u["lease_expiration"].isoformat() if u.get("lease_expiration") else None,
        }
        for u in units[: min(max(int(limit or 10), 1), 50)]
    ]
    total_positive_balance = sum(u["balance"] or 0 for u in units)
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "minimum_balance": 0,
        "limit": min(max(int(limit or 10), 1), 50),
        "total_positive_balance_count": len(units),
        "total_positive_balance": round(total_positive_balance, 2),
        "returned_rows": len(data),
        "data": data,
    }


def get_balance_summary(
    db: Session, property_code: str, month: str | None = None, include_top: bool = True
) -> dict[str, Any]:
    """Separate positive outstanding balances from negative credits/prepayments."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    occupied = [u for u in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None) if _is_occupied(u)]
    positives = [u for u in occupied if (u.get("balance") or 0) > 0]
    credits = [u for u in occupied if (u.get("balance") or 0) < 0]
    positives.sort(key=lambda u: u.get("balance") or 0, reverse=True)
    credits.sort(key=lambda u: u.get("balance") or 0)
    total_positive = sum(u.get("balance") or 0 for u in positives)
    total_credit = sum(abs(u.get("balance") or 0) for u in credits)
    current_group = _summary_group_for_month(db, property_code, report_month, "current_notice_vacant_residents")
    occupied_group = _summary_group_for_month(db, property_code, report_month, "occupied_units")
    detail_net_balance = sum(u.get("balance") or 0 for u in occupied)
    net_balance = _num(current_group.balance, detail_net_balance) if current_group else detail_net_balance
    summary = {
        "occupied_units": _int_value(occupied_group.unit_count, len(occupied)) if occupied_group else len(occupied),
        "residents_with_positive_balance": len(positives),
        "residents_with_credit_balance": len(credits),
        "total_positive_balance": round(total_positive, 2),
        "total_credit_balance": round(total_credit, 2),
        "net_balance": round(net_balance, 2),
        "average_positive_balance": round(total_positive / len(positives), 2) if positives else 0,
        "largest_positive_balance": round(positives[0].get("balance") or 0, 2) if positives else 0,
        "largest_credit_balance": round(abs(credits[0].get("balance") or 0), 2) if credits else 0,
        "net_balance_source": "summary_groups" if current_group else "detail_rows",
        "split_source": "detail_rows",
    }

    def balance_row(unit: dict[str, Any], credit: bool = False) -> dict[str, Any]:
        value = unit.get("balance") or 0
        return {
            "unit": unit.get("unit"),
            "resident_id": unit.get("resident_id") or unit.get("resident_name"),
            "balance": round(abs(value) if credit else value, 2),
            "market_rent": round(unit.get("market_rent") or 0, 2),
            "lease_expiration": unit["lease_expiration"].isoformat() if unit.get("lease_expiration") else None,
        }

    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "summary": summary,
        "top_positive_balances": [balance_row(u) for u in positives[:10]] if include_top else [],
        "top_credits": [balance_row(u, credit=True) for u in credits[:10]] if include_top else [],
        "note": "Net balance uses the source Summary Groups current/notice/vacant total when available; positive and credit splits use unit-level detail rows.",
    }


def get_balance_trend(db: Session, property_code: str) -> dict[str, Any]:
    """Return signed rent-roll balance trend by month."""
    data = []
    for month in _available_months(db, property_code):
        snapshot = _snapshot_for_month(db, property_code, month)
        occupied = [u for u in _unit_rollup(db, property_code, month, snapshot.id if snapshot else None) if _is_occupied(u)]
        positives = [u for u in occupied if (u.get("balance") or 0) > 0]
        credits = [u for u in occupied if (u.get("balance") or 0) < 0]
        current_group = _summary_group_for_month(db, property_code, month, "current_notice_vacant_residents")
        detail_net_balance = sum(u.get("balance") or 0 for u in occupied)
        data.append(
            {
                "month": month,
                "net_balance": round(_num(current_group.balance, detail_net_balance) if current_group else detail_net_balance, 2),
                "total_positive_balance": round(sum(u.get("balance") or 0 for u in positives), 2),
                "total_credit_balance": round(sum(abs(u.get("balance") or 0) for u in credits), 2),
                "residents_with_positive_balance": len(positives),
                "residents_with_credit_balance": len(credits),
                "net_balance_source": "summary_groups" if current_group else "detail_rows",
            }
        )
    return {
        "property_code": property_code,
        "start_month": data[0]["month"] if data else None,
        "end_month": data[-1]["month"] if data else None,
        "data": data,
        "note": "This is a rent-roll balance trend, not accounting delinquency aging.",
    }


def get_vacant_units(db: Session, property_code: str, month: str | None = None) -> dict[str, Any]:
    """Return vacant units and estimated monthly rent loss for one property."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    vacant = [u for u in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None) if not _is_occupied(u)]
    vacant.sort(key=lambda u: u["market_rent"] or 0, reverse=True)
    vacant_group = _summary_group_for_month(db, property_code, report_month, "total_vacant_units")
    summary_source = vacant_group is not None
    data = [
        {
            "unit": u["unit"],
            "unit_type": u["unit_type"],
            "market_rent": round(u["market_rent"] or 0, 2),
            "estimated_monthly_rent_loss": round(u["market_rent"] or 0, 2),
        }
        for u in vacant[:50]
    ]
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "vacant_units": _int_value(vacant_group.unit_count, len(vacant)) if vacant_group else len(vacant),
        "estimated_monthly_rent_loss": round(
            _num(vacant_group.market_rent, sum(u["market_rent"] or 0 for u in vacant)) if vacant_group else sum(u["market_rent"] or 0 for u in vacant),
            2,
        ),
        "summary_source": summary_source,
        "detail_list_count": len(vacant),
        "data": data,
    }


def get_vacancy_loss_by_unit_type(db: Session, property_code: str, month: str | None = None) -> dict[str, Any]:
    """Group vacant units and estimated monthly rent loss by unit type."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None):
        if not _is_occupied(unit):
            grouped[unit.get("unit_type") or "Unknown"].append(unit)
    data = []
    for unit_type, units in sorted(grouped.items()):
        total_loss = sum(u.get("market_rent") or 0 for u in units)
        sqft_values = [u["unit_sqft"] for u in units if u.get("unit_sqft")]
        data.append(
            {
                "unit_type": unit_type,
                "vacant_units": len(units),
                "estimated_monthly_rent_loss": round(total_loss, 2),
                "average_market_rent": round(total_loss / len(units), 2) if units else 0,
                "average_sqft": round(sum(sqft_values) / len(sqft_values), 2) if sqft_values else None,
            }
        )
    data.sort(key=lambda row: row["estimated_monthly_rent_loss"], reverse=True)
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "data": data,
    }


def get_charge_trend(
    db: Session, property_code: str, charge_code: str | None = None, category: str = "all"
) -> dict[str, Any]:
    """Trend rent-roll charge amounts across available months."""
    category = category if category in {"all", "rent", "non_rent"} else "all"
    requested_code = charge_code.strip().upper() if charge_code else None
    data = []
    for month in _available_months(db, property_code):
        snapshot = _snapshot_for_month(db, property_code, month)
        amount = 0.0
        row_count = 0
        charge_summaries = _charge_summaries_for_month(db, property_code, month)
        if charge_summaries:
            for row in charge_summaries:
                code = (row.charge_code or "UNKNOWN").upper()
                if requested_code and code != requested_code:
                    continue
                if not _charge_allowed(code, category):
                    continue
                amount += row.amount or 0.0
                row_count += 1
            source = "charge_summaries"
        else:
            rows = (
                db.scalars(
                    select(RentRollRow).where(RentRollRow.snapshot_id == snapshot.id, RentRollRow.property_code == property_code)
                ).all()
                if snapshot
                else []
            )
            for row in rows:
                code = (row.charge_code or "UNKNOWN").upper()
                if requested_code and code != requested_code:
                    continue
                if not _charge_allowed(code, category):
                    continue
                amount += row.charge_amount or 0.0
                row_count += 1
            source = "detail_rows"
        data.append({"month": month, "amount": round(amount, 2), "row_count": row_count, "source": source})
    return {
        "property_code": property_code,
        "charge_code": requested_code,
        "category": category,
        "start_month": data[0]["month"] if data else None,
        "end_month": data[-1]["month"] if data else None,
        "data": data,
    }


def get_rent_roll_summary_groups(db: Session, property_code: str, month: str | None = None) -> dict[str, Any]:
    """Return the source Summary Groups table for one property and reporting month."""
    report_month = _resolve_month(db, property_code, month)
    if not report_month:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}
    snapshot = _snapshot_for_month(db, property_code, report_month)
    groups = _summary_groups_for_month(db, property_code, report_month)
    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
        "summary_source": bool(groups),
        "data": [_summary_group_to_dict(group) for group in groups],
    }


def get_future_residents(
    db: Session, property_code: str, month: str | None = None, include_history: bool = False, limit: int = 50
) -> dict[str, Any]:
    """Return Future Residents/Applicants details and source summary totals."""
    limit = min(max(int(limit or 50), 1), 200)
    months = _available_months(db, property_code) if include_history else [_resolve_month(db, property_code, month)]
    months = [item for item in months if item]
    if not months:
        return {"property_code": property_code, "report_month": month, "error": "No rent-roll data found."}

    data: list[dict[str, Any]] = []
    summary_by_month: list[dict[str, Any]] = []
    total_rows = 0
    for report_month in months:
        future_group = _summary_group_for_month(db, property_code, report_month, "future_residents_applicants")
        future_rows = _future_residents_for_month(db, property_code, report_month)
        total_rows += len(future_rows)
        summary_by_month.append(
            {
                "report_month": report_month,
                "future_resident_count": _int_value(future_group.unit_count, len(future_rows)) if future_group else len(future_rows),
                "future_market_rent": round(_num(future_group.market_rent), 2) if future_group else round(sum(_num(row.market_rent) for row in future_rows), 2),
                "future_security_deposit": round(_num(future_group.security_deposit), 2) if future_group else round(sum(_num(row.resident_deposit) for row in future_rows), 2),
                "future_other_deposits": round(_num(future_group.other_deposits), 2) if future_group else round(sum(_num(row.other_deposit) for row in future_rows), 2),
                "future_balance": round(_num(future_group.balance), 2) if future_group else round(sum(_num(row.balance) for row in future_rows), 2),
                "summary_source": future_group is not None,
                "detail_count": len(future_rows),
            }
        )
        for row in future_rows:
            if len(data) < limit:
                data.append(_future_resident_to_dict(row, report_month))

    active_summary = summary_by_month[-1] if include_history else summary_by_month[0]
    return {
        "property_code": property_code,
        "report_month": None if include_history else months[0],
        "include_history": bool(include_history),
        "limit": limit,
        "returned_rows": len(data),
        "total_rows": total_rows,
        "future_resident_count": active_summary.get("future_resident_count", 0),
        "future_market_rent": active_summary.get("future_market_rent", 0),
        "future_security_deposit": active_summary.get("future_security_deposit", 0),
        "future_other_deposits": active_summary.get("future_other_deposits", 0),
        "future_deposits": round(
            _num(active_summary.get("future_security_deposit", 0)) + _num(active_summary.get("future_other_deposits", 0)),
            2,
        ),
        "future_balance": active_summary.get("future_balance", 0),
        "summary_by_month": summary_by_month,
        "data": data,
    }


def get_unit_lookup(
    db: Session, property_code: str, unit: str, include_history: bool = False, month: str | None = None
) -> dict[str, Any]:
    """Return unit details for one snapshot or all available months."""
    unit_query = str(unit or "").strip()
    if not unit_query:
        return {"property_code": property_code, "error": "A unit is required."}
    months = _available_months(db, property_code) if include_history else [_resolve_month(db, property_code, month)]
    data = []
    unit_type_candidates = []
    for report_month in [m for m in months if m]:
        snapshot = _snapshot_for_month(db, property_code, report_month)
        for item in _unit_rollup(db, property_code, report_month, snapshot.id if snapshot else None):
            row = {
                "report_month": report_month,
                "as_of_date": snapshot.as_of_date.isoformat() if snapshot and snapshot.as_of_date else None,
                "unit": item.get("unit"),
                "unit_type": item.get("unit_type"),
                "unit_sqft": item.get("unit_sqft"),
                "occupancy_status": "occupied" if _is_occupied(item) else "vacant",
                "resident_id": item.get("resident_id") or item.get("resident_name"),
                "market_rent": round(item.get("market_rent") or 0, 2),
                "rent_charges": round(item.get("rent_charges") or 0, 2),
                "all_charges": round(item.get("all_charges") or 0, 2),
                "balance": round(item.get("balance") or 0, 2),
                "move_in": item["move_in"].isoformat() if item.get("move_in") else None,
                "lease_expiration": item["lease_expiration"].isoformat() if item.get("lease_expiration") else None,
                "move_out": item["move_out"].isoformat() if item.get("move_out") else None,
                "charge_codes": ", ".join(item.get("charge_codes") or []),
            }
            if str(item.get("unit") or "").strip().lower() == unit_query.lower():
                data.append({**row, "matched_as": "unit"})
            elif str(item.get("unit_type") or "").strip().lower() == unit_query.lower():
                unit_type_candidates.append({**row, "matched_as": "unit_type"})
    matched_as = "unit" if data else None
    if not data and unit_type_candidates:
        data = unit_type_candidates[:50]
        matched_as = "unit_type"
    return {
        "property_code": property_code,
        "unit": unit_query,
        "include_history": bool(include_history),
        "report_month": None if include_history else (months[0] if months else None),
        "matched_as": matched_as,
        "returned_rows": len(data),
        "note": "No exact unit match was found; results matched unit_type instead." if matched_as == "unit_type" else None,
        "data": data,
    }


def get_property_health_summary(db: Session, property_code: str, month: str | None = None) -> dict[str, Any]:
    """Build a deterministic executive summary from implemented rent-roll metrics."""
    overview = get_property_overview(db, property_code, month)
    if "error" in overview:
        return overview
    report_month = overview.get("report_month")
    balance = get_balance_summary(db, property_code, report_month, include_top=False)
    vacant = get_vacant_units(db, property_code, report_month)
    vacancy_by_type = get_vacancy_loss_by_unit_type(db, property_code, report_month)
    expirations = get_expiration_summary_by_month(db, property_code, 180, report_month)

    risks = []
    if overview.get("vacant_units", 0):
        risks.append(
            {
                "focus_area": "Vacancy",
                "metric": f"{overview.get('vacant_units')} vacant units",
                "detail": f"Estimated monthly rent loss is {_money_value(vacant.get('estimated_monthly_rent_loss', 0))}.",
            }
        )
    if balance.get("summary", {}).get("residents_with_positive_balance", 0):
        risks.append(
            {
                "focus_area": "Outstanding balances",
                "metric": _money_value(balance["summary"].get("total_positive_balance", 0)),
                "detail": f"{balance['summary'].get('residents_with_positive_balance')} occupied units have positive balances.",
            }
        )
    expiring_count = sum(row.get("expiring_leases", 0) for row in expirations.get("data", []))
    if expiring_count:
        risks.append(
            {
                "focus_area": "Lease expirations",
                "metric": f"{expiring_count} leases in {expirations.get('window_days')} days",
                "detail": "Grouped expiration exposure is shown from the current rent-roll snapshot.",
            }
        )

    opportunities = []
    future_count = overview.get("future_resident_count", 0)
    if future_count:
        future_deposits = _num(overview.get("future_security_deposit", 0))
        opportunities.append(
            {
                "focus_area": "Future residents/applicants",
                "metric": f"{future_count} future applicants",
                "detail": (
                    f"Represents {_money_value(overview.get('future_market_rent', 0))} of future market rent "
                    f"and {_money_value(future_deposits)} of deposits based on the rent-roll future section."
                ),
            }
        )
    if vacancy_by_type.get("data"):
        top = vacancy_by_type["data"][0]
        opportunities.append(
            {
                "focus_area": "Vacancy concentration",
                "metric": top.get("unit_type"),
                "detail": f"{top.get('vacant_units')} vacant units drive {_money_value(top.get('estimated_monthly_rent_loss', 0))} of estimated monthly rent loss.",
            }
        )
    opportunities.append(
        {
            "focus_area": "Balance follow-up",
            "metric": "Credits separated from outstanding balances",
            "detail": "Use the balance summary to avoid mixing prepayments into high-balance outreach.",
        }
    )

    return {
        "property_code": property_code,
        "report_month": report_month,
        "as_of_date": overview.get("as_of_date"),
        "key_metrics": {
            "occupancy_rate": overview.get("occupancy_rate", 0),
            "occupied_units": overview.get("occupied_units", 0),
            "total_units": overview.get("total_units", 0),
            "vacant_units": overview.get("vacant_units", 0),
            "estimated_monthly_vacancy_loss": vacant.get("estimated_monthly_rent_loss", 0),
            "total_positive_balance": balance.get("summary", {}).get("total_positive_balance", 0),
            "total_credit_balance": balance.get("summary", {}).get("total_credit_balance", 0),
            "net_balance": balance.get("summary", {}).get("net_balance", 0),
            "leases_expiring_180_days": expiring_count,
            "future_resident_count": future_count,
            "future_market_rent": overview.get("future_market_rent", 0),
        },
        "risks": risks,
        "opportunities": opportunities,
        "supporting_tables": {"vacancy_loss_by_unit_type": vacancy_by_type.get("data", [])[:10]},
    }
