from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Property
from app.schemas import ChatRequest, ChatResponse
from app.services.llm_service import handle_chat

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """
    Handle one chat request for an active property.

    The property must exist before orchestration begins. From this point forward,
    services use the normalized request property_code and do not accept property
    overrides from the LLM.
    """
    property_code = request.property_code.lower().strip()
    exists = db.scalar(select(Property.id).where(Property.property_code == property_code))
    if not exists:
        raise HTTPException(status_code=404, detail=f"Property {property_code} was not found.")
    request.property_code = property_code
    return handle_chat(db, request)
