import logging
import re
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site, SourceRelationship, User
from services.embeddings import embedding_service
from services.collections import reassign_source
from services.enrichment import run_enrichment
from services.relationships import detect_and_save_relationships
from lib.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sites", tags=["sites"])

_UUID_RE = re.compile(r'^[0-9a-f-]{36}$', re.I)


class SiteUpdate(BaseModel):
    title:        Optional[str]  = None
    description:  Optional[str]  = None
    notes:        Optional[str]  = None
    tags:         Optional[list] = None
    category:     Optional[str]  = None
    pinned:       Optional[bool] = None
    technologies: Optional[list] = None
    topics:       Optional[list] = None


@router.get("")
async def list_sites(
    category: Optional[str] = Query(None),
    pinned:   Optional[bool] = Query(None),
    tag:      Optional[str]  = Query(None),
    limit:    int            = Query(100, ge=1, le=500),
    offset:   int            = Query(0, ge=0),
    db: AsyncSession         = Depends(get_db),
    current_user: User       = Depends(get_current_user),
):
    stmt = (
        select(Site)
        .where(Site.user_id == current_user.id)
        .order_by(Site.pinned.desc(), Site.created_at.desc())
    )
    if category:
        stmt = stmt.where(Site.category == category)
    if pinned is not None:
        stmt = stmt.where(Site.pinned == pinned)
    result = await db.execute(stmt)
    sites = result.scalars().all()
    if tag:
        tag_lower = tag.lower()
        sites = [s for s in sites if tag_lower in [t.lower() for t in (s.tags or [])]]
    total = len(sites)
    sites = sites[offset: offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "sites": [s.to_dict() for s in sites]}


# Static sub-routes must come before /{site_id} to avoid shadowing

@router.get("/recent")
async def recent_sites(
    limit: int         = Query(10, ge=1, le=50),
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Site)
        .where(Site.user_id == current_user.id)
        .order_by(Site.created_at.desc())
        .limit(limit)
    )
    sites = result.scalars().all()
    return {"sites": [s.to_dict() for s in sites]}


@router.get("/enrichment-status")
async def batch_enrichment_status(
    ids: str           = Query(..., description="Comma-separated site IDs"),
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    id_list = [i.strip() for i in ids.split(",") if _UUID_RE.match(i.strip())][:50]
    if not id_list:
        return {"statuses": []}
    result = await db.execute(
        select(Site).where(Site.id.in_(id_list), Site.user_id == current_user.id)
    )
    sites = result.scalars().all()
    return {
        "statuses": [
            {
                "id": s.id,
                "enrichment_status": s.enrichment_status or "completed",
                "title": s.title,
                "category": s.category,
                "tags": s.tags or [],
                "summary": s.summary,
                "description": s.description,
                "enrichment_error": s.enrichment_error,
            }
            for s in sites
        ]
    }


@router.post("/clear-all")
async def clear_all_sites(
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Site).where(Site.user_id == current_user.id))
    sites  = result.scalars().all()
    count  = len(sites)
    for site in sites:
        try:
            embedding_service.delete(site.id)
        except Exception as e:
            logger.warning(f"Embedding delete failed for {site.id}: {e}")
    await db.execute(delete(Site).where(Site.user_id == current_user.id))
    logger.info(f"User {current_user.id} cleared {count} sites")
    return {"deleted": count, "message": f"Removed {count} sources from NEXUS"}


@router.get("/{site_id}")
async def get_site(
    site_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")
    return site.to_dict()


@router.put("/{site_id}")
async def update_site(
    site_id: str,
    body: SiteUpdate,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")
    updated = body.model_dump(exclude_none=True)
    for field, value in updated.items():
        setattr(site, field, value)
    await db.flush()
    re_embed = any(f in updated for f in ("title", "tags", "topics", "technologies", "category"))
    if re_embed:
        try:
            embedding_service.upsert(site.id, site.to_dict(), user_id=current_user.id)
        except Exception as e:
            logger.warning(f"Re-embed failed for {site_id}: {e}")
        try:
            await reassign_source(site, db)
        except Exception as e:
            logger.warning(f"Collection re-assign failed for {site_id}: {e}")
    return site.to_dict()


@router.delete("/{site_id}")
async def delete_site(
    site_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")
    embedding_service.delete(site_id)
    await db.delete(site)
    return {"deleted": site_id}


@router.get("/{site_id}/related")
async def related_sites(
    site_id: str,
    limit: int         = Query(10, ge=1, le=50),
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")

    result = await db.execute(
        select(SourceRelationship)
        .where(SourceRelationship.source_id == site_id)
        .order_by(SourceRelationship.confidence_score.desc())
        .limit(limit)
    )
    rels = result.scalars().all()

    related = []
    for rel in rels:
        related_site = await db.get(Site, rel.related_source_id)
        if related_site and related_site.user_id == current_user.id:
            related.append({**rel.to_dict(), "site": related_site.to_dict()})

    return {"site_id": site_id, "related": related}


@router.post("/{site_id}/reanalyze")
async def reanalyze_site(
    site_id: str,
    background: BackgroundTasks,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")
    if site.enrichment_status == "processing":
        return {"status": "already_processing", "message": "Enrichment already in progress"}

    site.enrichment_status = "pending"
    site.enrichment_error  = None
    await db.flush()

    background.add_task(run_enrichment, site_id, site.raw_content or "")
    background.add_task(detect_and_save_relationships, site_id)

    return {"status": "queued", "message": "Re-analysis queued", "site_id": site_id}
