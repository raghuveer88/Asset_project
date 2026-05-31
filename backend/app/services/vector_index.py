from __future__ import annotations

import os
import logging
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry.product.posthog").disabled = True

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import WebsitePage
from app.services.retrieval_service import COLLECTION_NAME


def chunk_text(text: str, target_size: int = 850, overlap: int = 130) -> list[str]:
    """
    Split scraped website text into overlapping chunks for retrieval.

    Overlap preserves context across boundaries, especially for amenities,
    neighborhood copy, floor-plan descriptions, and contact details.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= target_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + target_size, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("! ", start, end), text.rfind("? ", start, end))
            if boundary > start + int(target_size * 0.6):
                end = boundary + 1
        chunk = text[start:end].strip()
        if len(chunk) > 120:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def rebuild_index(db: Session) -> dict[str, Any]:
    """
    Rebuild the Chroma collection from locally scraped website pages.

    Existing chunks are replaced to avoid duplicates. Every chunk receives
    property_code metadata so retrieval can enforce strict property scoping.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to build embeddings.")
    chroma_path = settings.resolve_backend_path(settings.chroma_persist_dir)
    client = chromadb.PersistentClient(path=str(chroma_path), settings=ChromaSettings(anonymized_telemetry=False))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    openai = OpenAI(api_key=settings.openai_api_key)
    pages = db.query(WebsitePage).order_by(WebsitePage.property_code, WebsitePage.id).all()
    ids: list[str] = []
    docs: list[str] = []
    metadatas: list[dict[str, Any]] = []
    total_chunks = 0
    for page in pages:
        path = Path(page.local_file_path)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = chunk_text(text)
        for idx, chunk in enumerate(chunks):
            ids.append(f"{page.property_code}:{page.id}:{idx}")
            docs.append(chunk)
            metadatas.append(
                {
                    "property_code": page.property_code,
                    "url": page.url,
                    "page_title": page.page_title or "Property website",
                    "local_file_path": str(path),
                    "chunk_index": idx,
                    "chunk_size": len(chunk),
                    "scraped_at": page.scraped_at.isoformat() if page.scraped_at else "",
                }
            )
            total_chunks += 1
            if len(docs) >= 96:
                _flush(collection, openai, ids, docs, metadatas)
                ids, docs, metadatas = [], [], []
    if docs:
        _flush(collection, openai, ids, docs, metadatas)
    return {
        "collection": COLLECTION_NAME,
        "embedding_model": settings.openai_embedding_model,
        "pages_indexed": len(pages),
        "chunks_indexed": total_chunks,
    }


def collection_status() -> dict[str, Any]:
    """Return Chroma collection metadata for diagnostics without reading documents."""
    settings = get_settings()
    try:
        client = chromadb.PersistentClient(
            path=str(settings.resolve_backend_path(settings.chroma_persist_dir)),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        return {"collection": COLLECTION_NAME, "count": collection.count(), "persist_dir": str(settings.resolve_backend_path(settings.chroma_persist_dir))}
    except Exception as exc:
        return {"collection": COLLECTION_NAME, "error": str(exc)}


def _flush(collection: Any, openai: OpenAI, ids: list[str], docs: list[str], metadatas: list[dict[str, Any]]) -> None:
    """Embed and add one batch of chunks to Chroma with their scoped metadata."""
    settings = get_settings()
    embeddings = openai.embeddings.create(model=settings.openai_embedding_model, input=docs).data
    collection.add(ids=ids, documents=docs, metadatas=metadatas, embeddings=[item.embedding for item in embeddings])
