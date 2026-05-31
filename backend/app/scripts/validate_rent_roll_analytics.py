from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings
from sqlalchemy import desc, func, select

from app.config import get_settings
from app.database import session_scope
from app.models import (
    Property,
    RentRollChargeSummary,
    RentRollFutureResident,
    RentRollRow,
    RentRollSnapshot,
    RentRollSummaryGroup,
    WebsitePage,
)
from app.services import analytics_service as analytics
from app.services.retrieval_service import COLLECTION_NAME


def main() -> None:
    """Print data availability and latest-month rent-roll validation by property."""
    with session_scope() as db:
        failures: list[str] = []
        codes = db.scalars(select(Property.property_code).order_by(Property.property_code)).all()
        property_count = db.scalar(select(func.count(Property.id))) or 0
        snapshot_count = db.scalar(select(func.count(RentRollSnapshot.id))) or 0
        row_count = db.scalar(select(func.count(RentRollRow.id))) or 0
        summary_group_count = db.scalar(select(func.count(RentRollSummaryGroup.id))) or 0
        charge_summary_count = db.scalar(select(func.count(RentRollChargeSummary.id))) or 0
        future_resident_count = db.scalar(select(func.count(RentRollFutureResident.id))) or 0
        website_page_count = db.scalar(select(func.count(WebsitePage.id))) or 0
        chroma_count = _chroma_count()
        print("dataset_summary")
        print(f"  properties: {property_count}")
        print(f"  rent_roll_snapshots: {snapshot_count}")
        print(f"  rent_roll_rows: {row_count}")
        print(f"  rent_roll_summary_groups: {summary_group_count}")
        print(f"  rent_roll_charge_summaries: {charge_summary_count}")
        print(f"  rent_roll_future_residents: {future_resident_count}")
        print(f"  website_pages: {website_page_count}")
        print(f"  chroma_chunks: {chroma_count}")
        print("")
        print(
            "property_code\treport_month\tlatest_snapshot_id\twebsite_pages\traw_distinct_units\tanalytics_total_units\t"
            "occupied_units\tvacant_units\toccupancy_rate\tsummary_groups\tcharge_summaries\tfuture_residents\twarnings"
        )
        for code in codes:
            website_pages = db.scalar(select(func.count(WebsitePage.id)).where(WebsitePage.property_code == code)) or 0
            snapshot = db.scalar(
                select(RentRollSnapshot)
                .where(RentRollSnapshot.property_code == code)
                .order_by(desc(RentRollSnapshot.report_month), desc(RentRollSnapshot.created_at), desc(RentRollSnapshot.id))
                .limit(1)
            )
            if not snapshot:
                warnings = ["no rent-roll snapshots"]
                if website_pages == 0:
                    warnings.append("no website pages")
                print(f"{code}\t-\t-\t{website_pages}\t0\t0\t0\t0\t0\t0\t0\t0\t{'; '.join(warnings)}")
                continue

            rows = db.scalars(
                select(RentRollRow).where(RentRollRow.snapshot_id == snapshot.id, RentRollRow.property_code == code)
            ).all()
            summary_groups = db.scalars(
                select(RentRollSummaryGroup).where(
                    RentRollSummaryGroup.snapshot_id == snapshot.id,
                    RentRollSummaryGroup.property_code == code,
                )
            ).all()
            charge_summaries = db.scalars(
                select(RentRollChargeSummary).where(
                    RentRollChargeSummary.snapshot_id == snapshot.id,
                    RentRollChargeSummary.property_code == code,
                )
            ).all()
            future_residents = db.scalars(
                select(RentRollFutureResident).where(
                    RentRollFutureResident.snapshot_id == snapshot.id,
                    RentRollFutureResident.property_code == code,
                )
            ).all()
            raw_units = {
                str(row.unit).strip()
                for row in rows
                if row.unit and not analytics._looks_like_summary_unit(row.unit)
            }
            overview = analytics.get_property_overview(db, code, snapshot.report_month)
            top_charges = _top_charge_codes(db, snapshot.id, code)
            warnings = []
            if overview.get("total_units", 0) == 0 and raw_units:
                warnings.append("analytics_total_units_zero_but_raw_units_exist")
            if not overview.get("summary_source") and overview.get("total_units") != len(raw_units):
                warnings.append(f"unit_count_mismatch raw={len(raw_units)} analytics={overview.get('total_units')}")
            if not summary_groups:
                warnings.append("missing_summary_groups")
                failures.append(f"{code} {snapshot.report_month}: missing Summary Groups")
            if website_pages == 0:
                warnings.append("no website pages")
            duplicate_count = db.scalar(
                select(func.count(RentRollSnapshot.id)).where(
                    RentRollSnapshot.property_code == code,
                    RentRollSnapshot.report_month == snapshot.report_month,
                )
            )
            if duplicate_count and duplicate_count > 1:
                warnings.append(f"duplicate_snapshots_for_month={duplicate_count}; analytics uses latest snapshot_id")
            if analytics._is_rent_charge_code("CURRENT"):
                warnings.append("CURRENT incorrectly classified as rent")
            if any(str(row.resident_id or "").strip().lower().startswith("vacant") for row in rows):
                vacant_units = [unit for unit in analytics._unit_rollup(db, code, snapshot.report_month, snapshot.id) if not analytics._is_occupied(unit)]
                if not vacant_units:
                    warnings.append("resident_id_vacant_rows_exist_but_no_vacancy_detected")
            future_group = next((group for group in summary_groups if group.group_name == "future_residents_applicants"), None)
            if future_group and future_group.unit_count is not None and int(future_group.unit_count) != len(future_residents):
                message = (
                    f"{code} {snapshot.report_month}: future detail count {len(future_residents)} "
                    f"!= Summary Groups unit_count {future_group.unit_count}"
                )
                warnings.append("future_count_mismatch")
                failures.append(message)

            print(
                f"{code}\t{snapshot.report_month}\t{snapshot.id}\t{website_pages}\t{len(raw_units)}\t{overview.get('total_units', 0)}\t"
                f"{overview.get('occupied_units', 0)}\t{overview.get('vacant_units', 0)}\t{overview.get('occupancy_rate', 0)}\t"
                f"{len(summary_groups)}\t{len(charge_summaries)}\t{len(future_residents)}\t"
                f"{'; '.join(warnings) if warnings else '-'}"
            )
            print(f"  top_charge_codes: {top_charges}")

        _validate_jan_2025_115r(db, failures)
        if analytics._is_rent_charge_code("CURRENT"):
            failures.append("_is_rent_charge_code('CURRENT') returned True")

        if failures:
            print("")
            print("validation_failures")
            for failure in failures:
                print(f"  - {failure}")
            raise SystemExit(1)
        print("")
        print("validation_passed")


def _chroma_count() -> int | str:
    settings = get_settings()
    try:
        client = chromadb.PersistentClient(
            path=str(settings.resolve_backend_path(settings.chroma_persist_dir)),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        return int(client.get_or_create_collection(COLLECTION_NAME).count())
    except Exception as exc:
        return f"unavailable ({exc})"


def _validate_jan_2025_115r(db, failures: list[str]) -> None:
    """Validate the known January 2025 115r source totals."""
    overview = analytics.get_property_overview(db, "115r", "2025-01")
    if overview.get("error"):
        failures.append(f"115r 2025-01 overview unavailable: {overview.get('error')}")
        return
    _require_equal(failures, "115r Jan total_units", overview.get("total_units"), 293)
    _require_equal(failures, "115r Jan occupied_units", overview.get("occupied_units"), 285)
    _require_equal(failures, "115r Jan vacant_units", overview.get("vacant_units"), 8)
    _require_approx(failures, "115r Jan occupancy_rate", overview.get("occupancy_rate"), 97.26)
    _require_approx(failures, "115r Jan total_market_rent", overview.get("total_market_rent"), 735583.36)
    _require_approx(failures, "115r Jan total_charge_rent", overview.get("total_charge_rent"), 770726.45)
    _require_approx(failures, "115r Jan current_net_balance", overview.get("current_net_balance"), -62525.24)
    _require_equal(failures, "115r Jan future_resident_count", overview.get("future_resident_count"), 2)

    future = analytics.get_future_residents(db, "115r", "2025-01")
    _require_equal(failures, "115r Jan future detail rows", len(future.get("data", [])), 2)

    charges = analytics.get_charge_breakdown(db, "115r", "2025-01", "all", 20)
    charge_map = {row.get("charge_code"): row.get("amount") for row in charges.get("data", [])}
    _require_approx(failures, "115r Jan TRASH charge summary", charge_map.get("TRASH"), 6975)
    _require_approx(failures, "115r Jan AMENITY charge summary", charge_map.get("AMENITY"), 10060)
    _require_approx(failures, "115r Jan RENT charge summary", charge_map.get("RENT"), 730966.45)
    _require_approx(failures, "115r Jan PARKING charge summary", charge_map.get("PARKING"), 19600)
    if not charges.get("summary_source"):
        failures.append("115r Jan charge breakdown did not use charge summary rows")


def _require_equal(failures: list[str], label: str, actual: object, expected: object) -> None:
    if actual != expected:
        failures.append(f"{label}: expected {expected}, got {actual}")


def _require_approx(failures: list[str], label: str, actual: object, expected: float, tolerance: float = 0.05) -> None:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        failures.append(f"{label}: expected approximately {expected}, got {actual}")
        return
    if abs(value - expected) > tolerance:
        failures.append(f"{label}: expected approximately {expected}, got {actual}")


def _top_charge_codes(db, snapshot_id: int, property_code: str) -> list[dict[str, object]]:
    rows = db.execute(
        select(RentRollRow.charge_code, func.count(RentRollRow.id), func.sum(RentRollRow.charge_amount))
        .where(RentRollRow.snapshot_id == snapshot_id, RentRollRow.property_code == property_code)
        .group_by(RentRollRow.charge_code)
        .order_by(desc(func.count(RentRollRow.id)))
        .limit(5)
    ).all()
    return [
        {"charge_code": code or "UNKNOWN", "count": int(count or 0), "amount": round(float(amount or 0), 2)}
        for code, count, amount in rows
    ]


if __name__ == "__main__":
    main()
