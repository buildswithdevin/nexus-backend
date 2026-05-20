import logging
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site, User
from lib.auth import get_current_user
from lib.events import emit
from services.deduplication import find_duplicate, normalize_url
from services.enrichment import run_enrichment, detect_content_type
from services.relationships import detect_and_save_relationships

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/extension", tags=["extension"])


class ExtensionSaveRequest(BaseModel):
    url:              str
    title:            str
    source_type:      str           = "browser_extension"
    capture_method:   Optional[str] = None
    selected_text:    Optional[str] = None
    page_description: Optional[str] = None
    note:             Optional[str] = None


@router.post("/save")
async def extension_save(
    body:       ExtensionSaveRequest,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
    current_user: User       = Depends(get_current_user),
):
    url = normalize_url(body.url)

    # Duplicate check
    duplicate = await find_duplicate(url, current_user.id, db)
    if duplicate:
        emit("duplicate_detected", url=url, user_id=current_user.id, existing_id=duplicate.id)
        return {
            "status": "duplicate",
            "message": "URL already in your NEXUS library",
            "site": duplicate.to_dict(),
        }

    raw_content = (body.selected_text or "").strip()

    site = Site(
        id               = str(uuid.uuid4()),
        user_id          = current_user.id,
        title            = body.title or url,
        url              = url,
        description      = body.page_description or "",
        raw_content      = raw_content[:10000] if raw_content else None,
        notes            = body.note or "",
        capture_method   = body.capture_method or body.source_type,
        content_type     = detect_content_type(url),
        enrichment_status = "pending",
        pinned           = False,
        restricted       = False,
    )

    db.add(site)
    await db.flush()

    emit("save_created", site_id=site.id, url=url, user_id=current_user.id)
    logger.info(f"Extension: instant save {url} → site {site.id}")

    background.add_task(run_enrichment, site.id, raw_content)
    background.add_task(detect_and_save_relationships, site.id)

    return {
        "status":           "created",
        "message":          "Saved to NEXUS — enriching in background",
        "id":               site.id,
        "enrichment_status": "queued",
        "site":             site.to_dict(),
    }
