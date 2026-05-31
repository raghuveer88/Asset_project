from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import init_db
from app.models import (
    Property,
    RentRollChargeSummary,
    RentRollFutureResident,
    RentRollRow,
    RentRollSnapshot,
    RentRollSummaryGroup,
)


MONTHS = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


@dataclass
class IngestionSummary:
    files_processed: int = 0
    properties: set[str] = field(default_factory=set)
    snapshots: int = 0
    rows_inserted: int = 0
    summary_groups_inserted: int = 0
    charge_summaries_inserted: int = 0
    future_residents_inserted: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a printable summary for CLI output and setup verification."""
        return {
            "files_processed": self.files_processed,
            "properties": len(self.properties),
            "property_codes": sorted(self.properties),
            "snapshots": self.snapshots,
            "rent_roll_rows_inserted": self.rows_inserted,
            "summary_groups_inserted": self.summary_groups_inserted,
            "charge_summaries_inserted": self.charge_summaries_inserted,
            "future_residents_inserted": self.future_residents_inserted,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def ingest_zip(db: Session, zip_path: str | Path) -> IngestionSummary:
    """
    Ingest every Excel rent-roll file from a zip archive into MySQL.

    Each file is parsed independently, duplicate snapshots for the same
    property_code/report_month/source_file are replaced, and a compact summary
    of processed files, rows, skipped files, and errors is returned.
    """
    init_db()
    summary = IngestionSummary()
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith((".xls", ".xlsx")) and not Path(m).name.startswith("~$")]
        for member in members:
            try:
                raw = archive.read(member)
                result = ingest_excel_bytes(db, raw, Path(member).name)
                inserted = (
                    result["rows"]
                    + result["summary_groups"]
                    + result["charge_summaries"]
                    + result["future_residents"]
                )
                if result["snapshot"] and inserted:
                    summary.files_processed += 1
                    summary.snapshots += 1
                    summary.rows_inserted += result["rows"]
                    summary.summary_groups_inserted += result["summary_groups"]
                    summary.charge_summaries_inserted += result["charge_summaries"]
                    summary.future_residents_inserted += result["future_residents"]
                    summary.properties.add(result["property_code"])
                else:
                    summary.skipped.append(f"{member}: no rent-roll data sections")
            except Exception as exc:
                db.rollback()
                summary.errors.append(f"{member}: {exc}")
    db.commit()
    return summary


def ingest_excel_bytes(db: Session, raw: bytes, source_file: str) -> dict[str, Any]:
    """
    Parse and ingest one rent-roll Excel file from bytes.

    The parser detects metadata/header rows, separates current detail rows
    from future applicants and source summary tables, and writes all sections
    under one scoped RentRollSnapshot.
    """
    df = pd.read_excel(BytesIO(raw), sheet_name="Report1", header=None, dtype=object)
    metadata = _extract_metadata(df, source_file)
    header_idx = _find_header_row(df)
    if header_idx is None:
        raise ValueError("Could not locate table header")

    columns = _build_columns(df.iloc[header_idx], df.iloc[header_idx + 1] if header_idx + 1 < len(df) else None)
    summary_idx = _find_section_row(df, "summary groups")
    future_idx = _find_section_row(df, "future residents applicants", start=header_idx + 2, end=summary_idx)
    charge_summary_idx = _find_section_row(
        df,
        "summary of charges by charge code",
        start=summary_idx + 1 if summary_idx is not None else header_idx + 2,
    )

    current_end = _first_index_after(header_idx, [future_idx, summary_idx, charge_summary_idx], len(df))
    current_table = df.iloc[header_idx + 2 : current_end].copy()
    row_payloads = _parse_current_detail_rows(current_table, columns)
    future_payloads = _parse_future_resident_rows(df, columns, future_idx, summary_idx)
    summary_payloads = _parse_summary_groups(df, summary_idx, charge_summary_idx)
    charge_payloads, charge_total_amount = _parse_charge_summary(df, charge_summary_idx)

    if not row_payloads and not future_payloads and not summary_payloads and not charge_payloads:
        return {
            "property_code": metadata["property_code"],
            "snapshot": False,
            "rows": 0,
            "summary_groups": 0,
            "charge_summaries": 0,
            "future_residents": 0,
            "charge_summary_total_amount": None,
        }

    _upsert_property_from_rent_roll(db, metadata)
    existing = db.scalars(
        select(RentRollSnapshot).where(
            RentRollSnapshot.property_code == metadata["property_code"],
            RentRollSnapshot.report_month == metadata["report_month"],
            RentRollSnapshot.source_file == source_file,
        )
    ).all()
    for snapshot in existing:
        db.delete(snapshot)
    db.flush()

    snapshot = RentRollSnapshot(
        property_code=metadata["property_code"],
        property_name=metadata.get("property_name"),
        report_month=metadata["report_month"],
        as_of_date=metadata.get("as_of_date"),
        source_file=source_file,
    )
    db.add(snapshot)
    db.flush()

    row_count = 0
    for payload in row_payloads:
        row = RentRollRow(
            snapshot_id=snapshot.id,
            property_code=metadata["property_code"],
            report_month=metadata["report_month"],
            **payload,
        )
        db.add(row)
        row_count += 1

    summary_group_count = 0
    for payload in summary_payloads:
        db.add(
            RentRollSummaryGroup(
                snapshot_id=snapshot.id,
                property_code=metadata["property_code"],
                report_month=metadata["report_month"],
                **payload,
            )
        )
        summary_group_count += 1

    charge_summary_count = 0
    for payload in charge_payloads:
        db.add(
            RentRollChargeSummary(
                snapshot_id=snapshot.id,
                property_code=metadata["property_code"],
                report_month=metadata["report_month"],
                **payload,
            )
        )
        charge_summary_count += 1

    future_resident_count = 0
    for payload in future_payloads:
        db.add(
            RentRollFutureResident(
                snapshot_id=snapshot.id,
                property_code=metadata["property_code"],
                report_month=metadata["report_month"],
                **payload,
            )
        )
        future_resident_count += 1

    return {
        "property_code": metadata["property_code"],
        "snapshot": True,
        "rows": row_count,
        "summary_groups": summary_group_count,
        "charge_summaries": charge_summary_count,
        "future_residents": future_resident_count,
        "charge_summary_total_amount": charge_total_amount,
    }


def _parse_current_detail_rows(table: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    """Parse only Current/Notice/Vacant Residents detail and charge rows."""
    if table.empty:
        return []
    table.columns = columns
    table = table.dropna(how="all")
    table = _normalize_dataframe(table)
    if table.empty:
        return []

    row_payloads = []
    for _, record in table.iterrows():
        unit = _clean_str(record.get("unit"))
        charge_code = _clean_str(record.get("charge_code"))
        if not unit or _looks_like_summary_row(unit):
            continue
        if charge_code and _looks_like_summary_row(charge_code):
            continue
        if _looks_like_summary_row(record.get("resident_id")) or _looks_like_summary_row(record.get("resident_name")):
            continue
        if not charge_code and pd.isna(record.get("charge_amount")):
            continue
        row_payloads.append(
            {
                "unit": unit,
                "unit_type": _clean_str(record.get("unit_type")),
                "unit_sqft": _to_float(record.get("unit_sqft")),
                "resident_id": _clean_str(record.get("resident_id")),
                "resident_name": _clean_str(record.get("resident_name")),
                "market_rent": _to_float(record.get("market_rent")),
                "charge_code": charge_code.upper() if charge_code else None,
                "charge_amount": _to_float(record.get("charge_amount")),
                "resident_deposit": _to_float(record.get("resident_deposit")),
                "other_deposit": _to_float(record.get("other_deposit")),
                "move_in": _to_date(record.get("move_in")),
                "lease_expiration": _to_date(record.get("lease_expiration")),
                "move_out": _to_date(record.get("move_out")),
                "balance": _to_float(record.get("balance")),
                "occupancy_status": _occupancy_status(record),
            }
        )
    return row_payloads


def _parse_future_resident_rows(
    df: pd.DataFrame, columns: list[str], future_idx: int | None, summary_idx: int | None
) -> list[dict[str, Any]]:
    """Parse one row per Future Residents/Applicants entry without forward-fill."""
    if future_idx is None:
        return []
    end_idx = summary_idx if summary_idx is not None and summary_idx > future_idx else len(df)
    table = df.iloc[future_idx + 1 : end_idx].copy()
    if table.empty:
        return []
    table.columns = columns
    table = table.loc[:, ~table.columns.duplicated()]
    payloads = []
    for _, record in table.iterrows():
        unit = _clean_str(record.get("unit"))
        if not unit or _looks_like_summary_row(unit):
            continue
        payloads.append(
            {
                "unit": unit,
                "unit_type": _clean_str(record.get("unit_type")),
                "unit_sqft": _to_float(record.get("unit_sqft")),
                "resident_id": _clean_str(record.get("resident_id")),
                "resident_name": _clean_str(record.get("resident_name")),
                "market_rent": _to_float(record.get("market_rent")),
                "resident_deposit": _to_float(record.get("resident_deposit")),
                "other_deposit": _to_float(record.get("other_deposit")),
                "move_in": _to_date(record.get("move_in")),
                "lease_expiration": _to_date(record.get("lease_expiration")),
                "move_out": _to_date(record.get("move_out")),
                "balance": _to_float(record.get("balance")),
            }
        )
    return payloads


def _parse_summary_groups(
    df: pd.DataFrame, summary_idx: int | None, charge_summary_idx: int | None
) -> list[dict[str, Any]]:
    """Parse the source Summary Groups footer table into canonical groups."""
    if summary_idx is None:
        return []
    end_idx = charge_summary_idx if charge_summary_idx is not None and charge_summary_idx > summary_idx else len(df)
    payloads = []
    data_started = False
    for row_idx in range(summary_idx + 1, end_idx):
        row = df.iloc[row_idx]
        if _row_is_blank(row):
            if data_started:
                break
            continue
        original_label = _clean_str(_cell(row, 0))
        group_name = _canonical_summary_group_name(original_label)
        if not group_name:
            continue
        data_started = True
        payloads.append(
            {
                "group_name": group_name,
                "original_label": original_label,
                "square_footage": _to_float(_cell(row, 5)),
                "market_rent": _to_float(_cell(row, 6)),
                "lease_charges": _to_float(_cell(row, 7)),
                "security_deposit": _to_float(_cell(row, 8)),
                "other_deposits": _to_float(_cell(row, 9)),
                "unit_count": _to_int(_cell(row, 10)),
                "unit_occupancy_pct": _to_float(_cell(row, 11)),
                "sqft_occupied_pct": _to_float(_cell(row, 12)),
                "balance": _to_float(_cell(row, 13)),
            }
        )
    return payloads


def _parse_charge_summary(df: pd.DataFrame, charge_summary_idx: int | None) -> tuple[list[dict[str, Any]], float | None]:
    """Parse Summary of Charges by Charge Code, excluding the Total row."""
    if charge_summary_idx is None:
        return [], None
    payloads = []
    total_amount = None
    data_started = False
    for row_idx in range(charge_summary_idx + 1, len(df)):
        row = df.iloc[row_idx]
        if _row_is_blank(row):
            if data_started:
                break
            continue
        raw_code = _clean_str(_cell(row, 0))
        normalized = _normalize_label(raw_code)
        if normalized in {
            "",
            "current notice residents only",
            "charge code",
            "summary of charges by charge code",
        }:
            continue
        amount = _to_float(_cell(row, 3))
        if normalized == "total":
            total_amount = amount
            break
        data_started = True
        if not raw_code:
            continue
        payloads.append(
            {
                "scope": "current_notice_residents_only",
                "charge_code": raw_code.upper(),
                "amount": amount,
            }
        )
    return payloads, total_amount


def _extract_metadata(df: pd.DataFrame, source_file: str) -> dict[str, Any]:
    """Extract property code, property name, report month, and as-of date."""
    property_code = _property_code_from_filename(source_file)
    report_month = _report_month_from_filename(source_file)
    property_name = None
    as_of_date = None

    for _, row in df.head(12).iterrows():
        text = " ".join(str(v) for v in row.dropna().tolist())
        match = re.search(r"(.+?)\s*\(([A-Za-z0-9]+)\)", text)
        if match:
            property_name = match.group(1).strip(" -:")
            property_code = property_code or match.group(2).lower()
        if "as of" in text.lower():
            parsed = _first_date(text)
            as_of_date = parsed or as_of_date
        month_match = re.search(r"\b(0?[1-9]|1[0-2])[/\-](20\d{2})\b", text)
        if month_match:
            report_month = f"{month_match.group(2)}-{int(month_match.group(1)):02d}"

    if not property_code:
        raise ValueError(f"Could not parse property code from {source_file}")
    if not report_month:
        raise ValueError(f"Could not parse report month from {source_file}")
    return {
        "property_code": property_code.lower(),
        "property_name": property_name,
        "report_month": report_month,
        "as_of_date": as_of_date,
    }


def _property_code_from_filename(name: str) -> str | None:
    """Parse a property code such as 115r from a rent-roll filename."""
    match = re.search(r"_([A-Za-z0-9]+)\.xls", name, re.IGNORECASE)
    return match.group(1).lower() if match else None


def _report_month_from_filename(name: str) -> str | None:
    """Parse YYYY-MM report month from a rent-roll filename when available."""
    lower = Path(name).name.lower()
    month = MONTHS.get(lower[:3])
    year_match = re.search(r"(20\d{2})", lower)
    year = year_match.group(1) if year_match else None
    if month and year:
        return f"{year}-{month}"
    return None


def _find_header_row(df: pd.DataFrame) -> int | None:
    """Locate the messy rent-roll table header row by scoring expected labels."""
    for idx in range(min(len(df), 80)):
        text = " ".join(str(v).lower() for v in df.iloc[idx].dropna().tolist())
        score = sum(token in text for token in ["unit", "resident", "market", "charge", "balance"])
        if score >= 3:
            return idx
    return None


def _find_section_row(
    df: pd.DataFrame, section_label: str, start: int = 0, end: int | None = None
) -> int | None:
    """Return the first row whose first cell matches a normalized section label."""
    target = _normalize_label(section_label)
    stop = len(df) if end is None else min(end, len(df))
    for idx in range(max(start, 0), stop):
        if _normalize_label(_cell(df.iloc[idx], 0)) == target:
            return idx
    return None


def _first_index_after(anchor: int, candidates: list[int | None], default: int) -> int:
    """Return the first candidate row after an anchor, or a default endpoint."""
    valid = [idx for idx in candidates if idx is not None and idx > anchor]
    return min(valid) if valid else default


def _build_columns(row1: pd.Series, row2: pd.Series | None) -> list[str]:
    """Merge two possible header rows into canonical internal column names."""
    columns = []
    for i, value in enumerate(row1.tolist()):
        parts = [str(value).strip()] if pd.notna(value) else []
        if row2 is not None and i < len(row2) and pd.notna(row2.iloc[i]):
            second = str(row2.iloc[i]).strip()
            if second and second.lower() not in [p.lower() for p in parts]:
                parts.append(second)
        raw = " ".join(parts)
        columns.append(_canonical_column(raw) or f"unused_{i}")
    return columns


def _canonical_column(raw: str) -> str | None:
    """Map a raw Excel header label to the schema column used by ingestion."""
    normalized = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    mapping = [
        ("unit type", "unit_type"),
        ("unit sq ft", "unit_sqft"),
        ("resident id", "resident_id"),
        ("resident name", "resident_name"),
        ("market rent", "market_rent"),
        ("charge code", "charge_code"),
        ("amount", "charge_amount"),
        ("resident deposit", "resident_deposit"),
        ("other deposit", "other_deposit"),
        ("move in", "move_in"),
        ("lease expiration", "lease_expiration"),
        ("move out", "move_out"),
        ("balance", "balance"),
        ("resident", "resident_id"),
        ("name", "resident_name"),
        ("unit", "unit"),
    ]
    for needle, target in mapping:
        if needle in normalized:
            return target
    return None


def _normalize_label(value: Any) -> str:
    """Normalize section and footer labels from Excel."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_summary_group_name(value: Any) -> str | None:
    """Map Summary Groups labels to stable internal names."""
    normalized = _normalize_label(value)
    mapping = {
        "current notice vacant residents": "current_notice_vacant_residents",
        "future residents applicants": "future_residents_applicants",
        "occupied units": "occupied_units",
        "non rev units": "total_non_rev_units",
        "total non rev units": "total_non_rev_units",
        "vacant units": "total_vacant_units",
        "total vacant units": "total_vacant_units",
        "totals": "totals",
        "total": "totals",
    }
    return mapping.get(normalized)


def _normalize_dataframe(table: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the extracted rent-roll table before persistence.

    Only true continuation charge rows inherit unit context. A row with a new
    unit value must not inherit resident, lease, balance, rent, or deposit
    fields from the previous unit, because that can turn vacant/sparse rows
    into occupied-looking rows.
    """
    table = table.loc[:, ~table.columns.duplicated()]
    context_cols = [
        "unit",
        "unit_type",
        "unit_sqft",
        "resident_id",
        "resident_name",
        "market_rent",
        "resident_deposit",
        "other_deposit",
        "move_in",
        "lease_expiration",
        "move_out",
        "balance",
    ]
    for col in context_cols:
        if col not in table.columns:
            table[col] = None
    for col in ["charge_code", "charge_amount"]:
        if col not in table.columns:
            table[col] = None

    table = table.replace("", pd.NA).infer_objects(copy=False)
    last_context: dict[str, Any] | None = None
    normalized_rows = []
    for _, row in table.iterrows():
        row_dict = row.to_dict()
        original_unit = row_dict.get("unit")
        has_new_unit = not _is_blank(original_unit)
        if has_new_unit:
            # A new unit starts a new context, even when some fields are blank.
            # This prevents resident/lease/balance values from leaking from the
            # previous unit into the new unit.
            last_context = {col: row_dict.get(col) for col in context_cols}
        elif last_context:
            # Blank-unit rows are continuation charge rows under the current
            # unit, so they inherit the current unit's context only.
            for col in context_cols:
                if _is_blank(row_dict.get(col)):
                    row_dict[col] = last_context.get(col)
        normalized_rows.append(row_dict)

    table = pd.DataFrame(normalized_rows, columns=table.columns)
    for col in ["market_rent", "charge_amount", "resident_deposit", "other_deposit", "balance", "unit_sqft"]:
        table[col] = table[col].apply(_to_float)
    for col in ["move_in", "lease_expiration", "move_out"]:
        table[col] = table[col].apply(_to_date)
    return table


def _upsert_property_from_rent_roll(db: Session, metadata: dict[str, Any]) -> None:
    """Create or update minimal Property metadata discovered from rent-roll files."""
    prop = db.scalar(select(Property).where(Property.property_code == metadata["property_code"]))
    if not prop:
        prop = Property(property_code=metadata["property_code"])
        db.add(prop)
    if metadata.get("property_name") and not prop.property_name:
        prop.property_name = metadata["property_name"]


def _to_float(value: Any) -> float | None:
    """Convert currency/accounting-style Excel values into floats."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[$,\s()]", "", text)
    try:
        number = float(text)
        return -number if negative else number
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    """Convert whole-number Excel values into ints."""
    number = _to_float(value)
    return int(round(number)) if number is not None else None


def _to_date(value: Any) -> date | None:
    """Convert Excel/Pandas/string date values into date objects."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _first_date(text: str) -> date | None:
    """Return the first date-like token found in a metadata string."""
    match = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text)
    return _to_date(match.group(0)) if match else None


def _clean_str(value: Any) -> str | None:
    """Normalize blank, NaN, and whitespace-only values to None."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None


def _is_blank(value: Any) -> bool:
    """Return True for empty Excel/Pandas values."""
    return value is None or pd.isna(value) or str(value).strip() == ""


def _cell(row: pd.Series, index: int) -> Any:
    """Return a cell by zero-based position, tolerating short rows."""
    return row.iloc[index] if index < len(row) else None


def _row_is_blank(row: pd.Series) -> bool:
    """Return True when every cell in an Excel row is blank."""
    return all(_is_blank(value) for value in row.tolist())


def _looks_like_summary_row(value: Any) -> bool:
    """Identify rent-roll section/footer rows that should not become detail rows."""
    if value is None or pd.isna(value):
        return False
    lower = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()
    summary_labels = {
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
        "summary of charges by charge code",
        "current notice residents only",
        "charge code",
    }
    return lower in summary_labels or lower.endswith(" total") or lower.endswith(" totals")


def _occupancy_status(record: pd.Series) -> str:
    """Infer simple occupied/vacant status from resident context."""
    resident_id = (_clean_str(record.get("resident_id")) or "").lower()
    resident_name = (_clean_str(record.get("resident_name")) or "").lower()
    if resident_id.startswith("vacant"):
        return "vacant"
    if resident_id:
        return "occupied"
    if resident_name.startswith("vacant") or resident_name in {"", "none", "[redacted]", "redacted"}:
        return "vacant"
    return "occupied"
