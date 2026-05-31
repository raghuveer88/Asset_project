from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Property, RentRollSnapshot, WebsitePage
from app.schemas import PropertyOut
from app.services.analytics_service import get_available_months, get_property_overview

router = APIRouter(tags=["properties"])


@router.get("/properties", response_model=list[PropertyOut])
def list_properties(db: Session = Depends(get_db)) -> list[dict]:
    """List property metadata used by the frontend property selector."""
    properties = db.scalars(select(Property).order_by(Property.property_code)).all()
    snapshot_counts = dict(
        db.execute(
            select(RentRollSnapshot.property_code, func.count(RentRollSnapshot.id)).group_by(RentRollSnapshot.property_code)
        ).all()
    )
    website_counts = dict(
        db.execute(select(WebsitePage.property_code, func.count(WebsitePage.id)).group_by(WebsitePage.property_code)).all()
    )
    return [
        {
            "property_code": prop.property_code,
            "property_name": prop.property_name,
            "official_property_name": prop.official_property_name,
            "address": prop.address,
            "website_url": prop.website_url,
            "scrape_enabled": prop.scrape_enabled,
            "match_confidence": prop.match_confidence,
            "rent_roll_snapshot_count": int(snapshot_counts.get(prop.property_code, 0) or 0),
            "website_page_count": int(website_counts.get(prop.property_code, 0) or 0),
            "has_rent_roll_snapshots": bool(snapshot_counts.get(prop.property_code, 0)),
            "has_website_pages": bool(website_counts.get(prop.property_code, 0)),
        }
        for prop in properties
    ]


@router.get("/properties/{property_code}/overview")
def property_overview(property_code: str, db: Session = Depends(get_db)) -> dict:
    """Return latest scoped overview metrics for one property code."""
    result = get_property_overview(db, property_code.lower())
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/properties/{property_code}/months")
def property_months(property_code: str, db: Session = Depends(get_db)) -> dict:
    """Return available report months for one property code."""
    return get_available_months(db, property_code.lower())
