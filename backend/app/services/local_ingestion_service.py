from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import init_db
from app.models import (
    ChatMessage,
    ChatSession,
    Property,
    RentRollChargeSummary,
    RentRollFutureResident,
    RentRollRow,
    RentRollSnapshot,
    RentRollSummaryGroup,
    WebsitePage,
)
from app.services.rent_roll_ingestion import IngestionSummary, ingest_excel_bytes, ingest_zip
from app.services.vector_index import rebuild_index
from app.services.website_scraper import safe_page_name, upsert_property_metadata, upsert_website_page


RENT_ROLL_ZIP_NAME = "RentRoll_LeaseCharges_NamesRedacted.zip"
WEBSITE_JSON_NAME = "property_websites.json"


def reset_and_ingest_local_data(db: Session) -> dict[str, Any]:
    """
    Rebuild local prototype data from backend/data and local scraped text files.

    This intentionally clears only this application's tables and Chroma
    collection. It reuses the existing rent-roll parser and vector builder so
    the API and scripts stay on the same ingestion path.
    """
    init_db()
    settings = get_settings()
    data_dir = settings.backend_root / "data"
    warnings: list[str] = []
    errors: list[str] = []

    _clear_project_tables(db)
    db.commit()

    rent_summary = _ingest_rent_roll_from_data_dir(db, data_dir)
    warnings.extend(rent_summary.skipped)
    errors.extend(rent_summary.errors)
    db.commit()

    website_summary = _ingest_website_metadata_and_local_pages(db, data_dir / WEBSITE_JSON_NAME)
    warnings.extend(website_summary["warnings"])
    errors.extend(website_summary["errors"])
    db.commit()

    chroma_summary: dict[str, Any] = {}
    try:
        chroma_summary = rebuild_index(db)
    except Exception as exc:
        errors.append(f"chroma rebuild failed: {exc}")

    per_property_summary = _per_property_summary(db)
    result = {
        "success": not errors,
        "properties_ingested": db.scalar(select(func.count(Property.id))) or 0,
        "snapshots_ingested": db.scalar(select(func.count(RentRollSnapshot.id))) or 0,
        "rent_roll_rows_ingested": db.scalar(select(func.count(RentRollRow.id))) or 0,
        "summary_groups_ingested": db.scalar(select(func.count(RentRollSummaryGroup.id))) or 0,
        "charge_summaries_ingested": db.scalar(select(func.count(RentRollChargeSummary.id))) or 0,
        "future_residents_ingested": db.scalar(select(func.count(RentRollFutureResident.id))) or 0,
        "website_pages_ingested": db.scalar(select(func.count(WebsitePage.id))) or 0,
        "chroma_chunks_ingested": chroma_summary.get("chunks_indexed", 0),
        "warnings": warnings,
        "errors": errors,
        "per_property_summary": per_property_summary,
    }
    return result


def _clear_project_tables(db: Session) -> None:
    """Delete app-owned data in foreign-key-safe order."""
    for model in [
        ChatMessage,
        ChatSession,
        WebsitePage,
        RentRollFutureResident,
        RentRollChargeSummary,
        RentRollSummaryGroup,
        RentRollRow,
        RentRollSnapshot,
        Property,
    ]:
        db.execute(delete(model))


def _ingest_rent_roll_from_data_dir(db: Session, data_dir: Path) -> IngestionSummary:
    """Ingest rent-roll Excel files from backend/data zip or rent_roll folder."""
    summary = IngestionSummary()
    zip_path = data_dir / RENT_ROLL_ZIP_NAME
    rent_roll_dir = data_dir / "rent_roll"
    if zip_path.exists():
        return ingest_zip(db, zip_path)
    if not rent_roll_dir.exists():
        summary.errors.append(f"Missing rent-roll input: {zip_path} or {rent_roll_dir}")
        return summary
    files = sorted(
        path
        for path in rent_roll_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".xls", ".xlsx"} and not path.name.startswith("~$")
    )
    if not files:
        summary.errors.append(f"No rent-roll Excel files found under {rent_roll_dir}")
        return summary
    for path in files:
        try:
            result = ingest_excel_bytes(db, path.read_bytes(), path.name)
            inserted = result["rows"] + result["summary_groups"] + result["charge_summaries"] + result["future_residents"]
            if result["snapshot"] and inserted:
                summary.files_processed += 1
                summary.snapshots += 1
                summary.rows_inserted += result["rows"]
                summary.summary_groups_inserted += result["summary_groups"]
                summary.charge_summaries_inserted += result["charge_summaries"]
                summary.future_residents_inserted += result["future_residents"]
                summary.properties.add(result["property_code"])
            else:
                summary.skipped.append(f"{path}: no rent-roll data sections")
        except Exception as exc:
            db.rollback()
            summary.errors.append(f"{path}: {exc}")
    return summary


def _ingest_website_metadata_and_local_pages(db: Session, json_path: Path) -> dict[str, Any]:
    """Load property metadata and website_pages from local scraped text files."""
    settings = get_settings()
    warnings: list[str] = []
    errors: list[str] = []
    pages_ingested = 0
    if not json_path.exists():
        return {"pages_ingested": 0, "warnings": warnings, "errors": [f"Missing website JSON: {json_path}"]}

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"pages_ingested": 0, "warnings": warnings, "errors": [f"Could not read website JSON: {exc}"]}

    records = data.get("properties", data) if isinstance(data, dict) else data
    scraped_root = settings.resolve_backend_path(settings.scraped_content_dir)
    for record in records:
        code = str(record.get("property_code", "")).strip().lower()
        if not code:
            warnings.append("website JSON record missing property_code")
            continue
        upsert_property_metadata(db, record)
        if not record.get("scrape_enabled"):
            warnings.append(f"{code}: scrape disabled")
            continue
        urls = record.get("scrape_urls") or []
        if isinstance(urls, str):
            urls = [urls]
        if not urls and record.get("website_url"):
            urls = [record["website_url"]]
        for url in urls:
            local_path = scraped_root / code / f"{safe_page_name(url)}.txt"
            if not local_path.exists():
                warnings.append(f"{code}: missing scraped content for {url}")
                continue
            content = local_path.read_text(encoding="utf-8", errors="ignore")
            title = _title_from_scraped_content(content, url)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            upsert_website_page(db, code, url, title, local_path, content_hash)
            pages_ingested += 1
    return {"pages_ingested": pages_ingested, "warnings": warnings, "errors": errors}


def _title_from_scraped_content(content: str, fallback_url: str) -> str:
    """Extract the Title line from local scraped text content."""
    for line in content.splitlines()[:5]:
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            return title[:500] or fallback_url
    return fallback_url


def _per_property_summary(db: Session) -> list[dict[str, Any]]:
    """Return compact per-property ingestion counts."""
    rows = db.execute(
        select(
            Property.property_code,
            func.count(func.distinct(RentRollSnapshot.id)),
            func.count(func.distinct(RentRollRow.id)),
            func.count(func.distinct(WebsitePage.id)),
        )
        .outerjoin(RentRollSnapshot, RentRollSnapshot.property_code == Property.property_code)
        .outerjoin(RentRollRow, RentRollRow.snapshot_id == RentRollSnapshot.id)
        .outerjoin(WebsitePage, WebsitePage.property_code == Property.property_code)
        .group_by(Property.property_code)
        .order_by(Property.property_code)
    ).all()
    return [
        {
            "property_code": code,
            "snapshots": int(snapshots or 0),
            "rent_roll_rows": int(rent_rows or 0),
            "website_pages": int(website_pages or 0),
        }
        for code, snapshots, rent_rows, website_pages in rows
    ]
