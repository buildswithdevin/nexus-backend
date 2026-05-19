import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site
from services.scraper import scrape
from services.ai_analysis import analyze_site
from services.embeddings import embedding_service
from services.collections import auto_assign_to_collection
from services.safety import classify_content, log_blocked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ingest"])


class IngestRequest(BaseModel):
    url:         str
    title:       Optional[str]  = None
    description: Optional[str]  = None
    notes:       Optional[str]  = None
    tags:        Optional[list] = None
    favicon_url: Optional[str]  = None
    raw_content: Optional[str]  = None


@router.post("/ingest")
async def ingest_site(body: IngestRequest, db: AsyncSession = Depends(get_db)):
    url = str(body.url).strip().rstrip("/")

    existing = await db.execute(select(Site).where(Site.url == url))
    existing_site = existing.scalar_one_or_none()
    if existing_site:
        return {
            "status":     "duplicate",
            "message":    "URL already in NEXUS",
            "site":       existing_site.to_dict(),
            "collection": None,
        }

    scraped_title   = body.title
    scraped_favicon = body.favicon_url
    scraped_content = body.raw_content

    if not scraped_content:
        logger.info(f"Scraping: {url}")
        scrape_result   = await scrape(url)
        scraped_content = scrape_result.get("raw_content") or ""
        if not scraped_title:
            scraped_title = scrape_result.get("title") or url
        if not scraped_favicon:
            scraped_favicon = scrape_result.get("favicon_url")
    else:
        logger.info(f"Using pre-supplied content for: {url}")

    title = scraped_title or url

    # ── Safety check ──────────────────────────────────────────────────────────────
    content_safety = classify_content(title, url, scraped_content[:2000] if scraped_content else "")
    is_restricted  = not content_safety.safe

    if is_restricted:
        log_blocked(f"{title} | {url}", content_safety.category or "unknown", "flagged_ingest")
        logger.warning(f"Restricted content flagged on ingest: {url} (category={content_safety.category})")

    # Don't run AI analysis on restricted content — no summarising harmful instructions.
    if is_restricted:
        ai: dict = {
            "summary":        "This content has been flagged and will not be analysed.",
            "category":       "Other",
            "tags":           [],
            "technologies":   [],
            "topics":         [],
            "use_case":       "",
            "learning_value": "intermediate",
        }
    else:
        logger.info(f"Running AI analysis for: {url}")
        ai = await analyze_site(
            url=url, title=title,
            description=body.description or "",
            raw_content=scraped_content,
        )

    user_tags   = [t.lower() for t in (body.tags or [])]
    ai_tags     = [t.lower() for t in ai.get("tags", [])]
    merged_tags = list(dict.fromkeys(user_tags + ai_tags))

    site = Site(
        id                 = str(uuid.uuid4()),
        title              = title,
        url                = url,
        description        = body.description or ai.get("summary", ""),
        summary            = ai.get("summary", ""),
        favicon_url        = scraped_favicon,
        raw_content        = scraped_content[:10000] if scraped_content else None,
        category           = ai.get("category", "Other"),
        tags               = merged_tags,
        technologies       = ai.get("technologies", []),
        topics             = ai.get("topics", []),
        notes              = body.notes or "",
        use_case           = ai.get("use_case", ""),
        learning_value     = ai.get("learning_value", "intermediate"),
        pinned             = False,
        restricted         = is_restricted,
        restricted_reason  = content_safety.category if is_restricted else None,
    )

    try:
        embed_data     = {**site.to_dict(), "raw_content": site.raw_content or ""}
        chroma_id      = embedding_service.upsert(site.id, embed_data)
        site.chroma_id = chroma_id
    except Exception as e:
        logger.error(f"Embedding failed for {url}: {e}")

    db.add(site)
    await db.flush()

    # ── Auto-assign to collection ──────────────────────────────────────────────
    collection_info: dict | None = None
    try:
        collection_info = await auto_assign_to_collection(site, db)
    except Exception as e:
        logger.warning(f"Collection auto-assign failed for {site.id}: {e}")

    logger.info(f"Ingested: {title} ({url})"
                + (f" → collection '{collection_info['cluster_name']}'" if collection_info else ""))

    return {
        "status":     "created",
        "message":    "Site captured and analyzed",
        "site":       site.to_dict(),
        "collection": collection_info,
    }
