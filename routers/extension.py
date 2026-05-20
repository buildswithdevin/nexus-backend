import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site, User
from services.ai_analysis import analyze_site
from services.embeddings import embedding_service
from services.collections import auto_assign_to_collection
from services.safety import classify_content, log_blocked
from lib.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/extension", tags=["extension"])


class ExtensionSaveRequest(BaseModel):
    url:              str
    title:            str
    source_type:      str = "webpage"            # webpage | article | video | tool | other
    selected_text:    Optional[str] = None
    page_description: Optional[str] = None


@router.post("/save")
async def extension_save(
    body: ExtensionSaveRequest,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save a URL from the browser extension to the logged-in user's library.
    Mirrors /api/ingest but accepts pre-supplied content instead of scraping.
    """
    url = body.url.strip().rstrip("/")

    # Duplicate check per user
    existing = await db.execute(
        select(Site).where(Site.url == url, Site.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        return {"status": "duplicate", "message": "URL already in your NEXUS library"}

    raw_content = body.selected_text or ""

    # Safety check
    content_safety = classify_content(body.title, url, raw_content[:2000])
    is_restricted  = not content_safety.safe

    if is_restricted:
        log_blocked(f"{body.title} | {url}", content_safety.category or "unknown", "extension_save")
        logger.warning(f"Extension: restricted content flagged: {url}")
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
        logger.info(f"Extension: AI analysis for {url}")
        ai = await analyze_site(
            url=url,
            title=body.title,
            description=body.page_description or "",
            raw_content=raw_content,
        )

    site = Site(
        id                = str(uuid.uuid4()),
        user_id           = current_user.id,
        title             = body.title,
        url               = url,
        description       = body.page_description or ai.get("summary", ""),
        summary           = ai.get("summary", ""),
        raw_content       = raw_content[:10000] if raw_content else None,
        category          = ai.get("category", "Other"),
        tags              = [t.lower() for t in ai.get("tags", [])],
        technologies      = ai.get("technologies", []),
        topics            = ai.get("topics", []),
        notes             = "",
        use_case          = ai.get("use_case", ""),
        learning_value    = ai.get("learning_value", "intermediate"),
        pinned            = False,
        restricted        = is_restricted,
        restricted_reason = content_safety.category if is_restricted else None,
    )

    try:
        embed_data     = {**site.to_dict(), "raw_content": site.raw_content or ""}
        chroma_id      = embedding_service.upsert(site.id, embed_data, user_id=current_user.id)
        site.chroma_id = chroma_id
    except Exception as e:
        logger.error(f"Extension: embedding failed for {url}: {e}")

    db.add(site)
    await db.flush()

    collection_info: dict | None = None
    try:
        collection_info = await auto_assign_to_collection(site, db)
    except Exception as e:
        logger.warning(f"Extension: collection auto-assign failed for {site.id}: {e}")

    logger.info(f"Extension save: {body.title} ({url}) → user {current_user.id}")

    return {
        "status":     "created",
        "message":    "Saved to your NEXUS library",
        "site":       site.to_dict(),
        "collection": collection_info,
    }
