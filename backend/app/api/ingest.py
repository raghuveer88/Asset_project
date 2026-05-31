from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.services.local_ingestion_service import reset_and_ingest_local_data

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
def ingest(db: Session = Depends(get_db)) -> dict:
    """Reset and rebuild local prototype data from backend/data."""
    settings = get_settings()
    if not settings.enable_ingest_endpoint:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ingestion is disabled for this deployment.",
        )
    return reset_and_ingest_local_data(db)
