from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, diagnostics, ingest, properties
from app.config import get_settings
from app.database import init_db


app = FastAPI(title="Asset AI", version="1.0.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database tables when FastAPI starts."""
    try:
        init_db()
    except Exception as exc:
        # Keep the container alive so /api/health can expose the DB problem.
        app.state.startup_db_error = str(exc)


@app.get("/api/health")
def health() -> dict:
    """Return combined API, database, Chroma, and model health status."""
    from app.api.diagnostics import diagnostics_payload
    from app.database import SessionLocal

    with SessionLocal() as db:
        payload = diagnostics_payload(db)
    return {"status": "ok" if payload["db_connected"] else "degraded", **payload}


app.include_router(properties.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(diagnostics.router, prefix="/api")
app.include_router(ingest.router)
