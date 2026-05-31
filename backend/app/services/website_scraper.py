from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import init_db
from app.models import Property, WebsitePage


@dataclass
class ScrapeSummary:
    properties_seen: int = 0
    properties_scraped: int = 0
    pages_scraped: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a printable scrape summary for the CLI."""
        return self.__dict__


def scrape_from_json(db: Session, json_path: str | Path, high_confidence_only: bool = True) -> ScrapeSummary:
    """
    Scrape enabled property website URLs from a metadata JSON file.

    Property metadata is upserted for every record, but only enabled and
    high-confidence records are fetched by default. Clean text is stored locally
    under a property_code directory and website_pages rows preserve source URLs.
    """
    init_db()
    settings = get_settings()
    out_root = settings.resolve_backend_path(settings.scraped_content_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    records = data.get("properties", data) if isinstance(data, dict) else data
    summary = ScrapeSummary(properties_seen=len(records))
    for record in records:
        code = str(record.get("property_code", "")).strip().lower()
        if not code:
            summary.skipped.append("record missing property_code")
            continue
        upsert_property_metadata(db, record)
        if not record.get("scrape_enabled"):
            summary.skipped.append(f"{code}: scrape disabled")
            continue
        if high_confidence_only and str(record.get("match_confidence", "")).lower() not in {"high", "exact"}:
            summary.skipped.append(f"{code}: match_confidence not high")
            continue
        scrape_urls = record.get("scrape_urls") or []
        if isinstance(scrape_urls, str):
            scrape_urls = [scrape_urls]
        if not scrape_urls and record.get("website_url"):
            scrape_urls = [record["website_url"]]
        property_dir = out_root / code
        property_dir.mkdir(parents=True, exist_ok=True)
        scraped_for_property = 0
        for url in scrape_urls:
            try:
                page = fetch_clean_page(url)
                if len(page["text"]) < 80:
                    summary.skipped.append(f"{code}: {url} produced very little text")
                    continue
                filename = safe_page_name(url) + ".txt"
                local_path = property_dir / filename
                content = f"Title: {page['title']}\nURL: {url}\nScraped At: {datetime.utcnow().isoformat()}\n\n{page['text']}\n"
                local_path.write_text(content, encoding="utf-8")
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                upsert_website_page(db, code, url, page["title"], local_path, content_hash)
                summary.pages_scraped += 1
                scraped_for_property += 1
            except Exception as exc:
                summary.errors.append(f"{code}: {url}: {exc}")
        if scraped_for_property:
            summary.properties_scraped += 1
    db.commit()
    return summary


def fetch_clean_page(url: str) -> dict[str, str]:
    """
    Fetch one web page and extract clean text for retrieval.

    Script, navigation, footer, and other noisy elements are removed before the
    page text is saved for later Chroma indexing.
    """
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "AssetAI/1.0 (+local interview project)"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    for tag in soup.find_all(["br", "p", "li", "h1", "h2", "h3"]):
        tag.append("\n")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {"title": title[:500], "text": text.strip()}


def upsert_property_metadata(db: Session, record: dict[str, Any]) -> None:
    """Upsert non-secret property metadata from the website JSON record."""
    code = str(record.get("property_code", "")).strip().lower()
    prop = db.scalar(select(Property).where(Property.property_code == code))
    if not prop:
        prop = Property(property_code=code)
        db.add(prop)
    prop.property_name = record.get("property_name") or prop.property_name
    prop.official_property_name = record.get("official_property_name") or prop.official_property_name
    prop.address = record.get("address") or prop.address
    prop.website_url = record.get("website_url") or prop.website_url
    prop.scrape_enabled = bool(record.get("scrape_enabled"))
    prop.match_confidence = record.get("match_confidence")
    prop.notes = record.get("notes")


def upsert_website_page(
    db: Session, property_code: str, url: str, title: str, local_path: Path, content_hash: str
) -> None:
    """
    Upsert a scraped website page row for one property.

    The unique key includes property_code and URL, keeping page metadata scoped
    and preventing duplicate rows when the scraper is rerun.
    """
    url = url[:700]
    page = db.scalar(select(WebsitePage).where(WebsitePage.property_code == property_code, WebsitePage.url == url))
    if not page:
        page = WebsitePage(property_code=property_code, url=url, local_file_path=str(local_path), content_hash=content_hash)
        db.add(page)
    page.page_title = title
    page.local_file_path = str(local_path)
    page.scraped_at = datetime.utcnow()
    page.content_hash = content_hash


def safe_page_name(url: str) -> str:
    """Convert a URL into a stable, filesystem-safe text filename."""
    value = re.sub(r"^https?://", "", url.lower()).strip("/")
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value[:120] or "page"
