from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import check_db, get_db
from app.models import (
    Property,
    RentRollChargeSummary,
    RentRollFutureResident,
    RentRollRow,
    RentRollSnapshot,
    RentRollSummaryGroup,
    WebsitePage,
)
from app.schemas import DiagnosticsOut
from app.services.vector_index import collection_status

router = APIRouter(tags=["diagnostics"])


def diagnostics_payload(db: Session) -> dict:
    """
    Build a compact operational health payload without exposing secrets.

    The response includes database counts, Chroma collection status, allowed chat
    models, and the configured embedding model. It intentionally never returns
    OPENAI_API_KEY or other credentials.
    """
    settings = get_settings()
    db_connected = check_db()
    chroma_status = collection_status()
    chroma_chunks = chroma_status.get("count") if isinstance(chroma_status, dict) else None
    if not db_connected:
        return {
            "db_connected": False,
            "property_count": 0,
            "properties_count": 0,
            "snapshot_count": 0,
            "snapshots_count": 0,
            "rent_roll_row_count": 0,
            "rent_roll_rows_count": 0,
            "summary_group_count": 0,
            "summary_groups_count": 0,
            "charge_summary_count": 0,
            "charge_summaries_count": 0,
            "future_resident_count": 0,
            "future_residents_count": 0,
            "website_page_count": 0,
            "website_pages_count": 0,
            "chroma_chunks_count": chroma_chunks,
            "chroma_collection_status": chroma_status,
            "available_models": settings.allowed_models,
            "embedding_model": settings.openai_embedding_model,
        }
    property_count = db.scalar(select(func.count(Property.id))) or 0
    snapshot_count = db.scalar(select(func.count(RentRollSnapshot.id))) or 0
    rent_roll_row_count = db.scalar(select(func.count(RentRollRow.id))) or 0
    summary_group_count = db.scalar(select(func.count(RentRollSummaryGroup.id))) or 0
    charge_summary_count = db.scalar(select(func.count(RentRollChargeSummary.id))) or 0
    future_resident_count = db.scalar(select(func.count(RentRollFutureResident.id))) or 0
    website_page_count = db.scalar(select(func.count(WebsitePage.id))) or 0
    return {
        "db_connected": True,
        "property_count": property_count,
        "properties_count": property_count,
        "snapshot_count": snapshot_count,
        "snapshots_count": snapshot_count,
        "rent_roll_row_count": rent_roll_row_count,
        "rent_roll_rows_count": rent_roll_row_count,
        "summary_group_count": summary_group_count,
        "summary_groups_count": summary_group_count,
        "charge_summary_count": charge_summary_count,
        "charge_summaries_count": charge_summary_count,
        "future_resident_count": future_resident_count,
        "future_residents_count": future_resident_count,
        "website_page_count": website_page_count,
        "website_pages_count": website_page_count,
        "chroma_chunks_count": chroma_chunks,
        "chroma_collection_status": chroma_status,
        "available_models": settings.allowed_models,
        "embedding_model": settings.openai_embedding_model,
    }


@router.get("/diagnostics", response_model=DiagnosticsOut)
def diagnostics(db: Session = Depends(get_db)) -> dict:
    """Return backend, MySQL, Chroma, and model configuration diagnostics."""
    return diagnostics_payload(db)
