from __future__ import annotations

import os
import logging
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry.product.posthog").disabled = True

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

from app.config import get_settings

COLLECTION_NAME = "asset_ai_property_pages"


class RetrievalService:
    def __init__(self) -> None:
        """Open Chroma and OpenAI clients using environment-backed settings."""
        self.settings = get_settings()
        self.client = chromadb.PersistentClient(
            path=str(self.settings.resolve_backend_path(self.settings.chroma_persist_dir)),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
        self.openai = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

    def _embed(self, text: str) -> list[float]:
        """Create one query embedding using the environment-configured embedding model."""
        if not self.openai:
            raise RuntimeError("OPENAI_API_KEY is required for vector retrieval.")
        result = self.openai.embeddings.create(model=self.settings.openai_embedding_model, input=text)
        return result.data[0].embedding

    def search(self, property_code: str, query: str, top_k: int = 5) -> dict[str, Any]:
        """
        Search website chunks for one active property only.

        Chroma is always filtered by metadata.property_code, so retrieval results
        cannot include another property's website text even if the user asks for it.
        """
        top_k = min(max(int(top_k or 5), 1), 10)
        if self.collection.count() == 0:
            return {"property_code": property_code, "query": query, "results": [], "warning": "Vector index is empty."}
        embedding = self._embed(query)
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where={"property_code": property_code},
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        compact = []
        min_similarity = max(0.0, min(float(self.settings.retrieval_min_similarity), 1.0))
        for doc, meta, distance in zip(docs, metas, distances):
            snippet = " ".join((doc or "").split())
            similarity = round(1 / (1 + float(distance)), 4) if distance is not None else None
            if similarity is not None and similarity < min_similarity:
                continue
            compact.append(
                {
                    "snippet": snippet[:900],
                    "url": meta.get("url"),
                    "page_title": meta.get("page_title"),
                    "local_file_path": meta.get("local_file_path"),
                    "chunk_index": meta.get("chunk_index"),
                    "similarity_score": similarity,
                }
            )
        if not compact:
            return {
                "property_code": property_code,
                "query": query,
                "results": [],
                "warning": "No confident website context found for this property/query.",
            }
        return {"property_code": property_code, "query": query, "results": compact}


def retrieve_property_context(property_code: str, query: str, top_k: int = 5) -> dict[str, Any]:
    """
    Public retrieval tool for website-grounded property context.

    The active property_code comes from the backend tool registry, not the LLM,
    and RetrievalService.search applies the Chroma metadata filter.
    """
    return RetrievalService().search(property_code=property_code, query=query, top_k=top_k)
