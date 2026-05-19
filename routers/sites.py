import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site
from services.embeddings import embedding_service
from services.collections import reassign_source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sites", tags=["sites"])


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
):
    stmt = select(Site).order_by(Site.pinned.desc(), Site.created_at.desc())
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


@router.get("/{site_id}")
async def get_site(site_id: str, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site.to_dict()


@router.put("/{site_id}")
async def update_site(site_id: str, body: SiteUpdate, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    updated = body.model_dump(exclude_none=True)
    for field, value in updated.items():
        setattr(site, field, value)
    await db.flush()
    re_embed = any(f in updated for f in ("title", "tags", "topics", "technologies", "category"))
    if re_embed:
        try:
            embedding_service.upsert(site.id, site.to_dict())
        except Exception as e:
            logger.warning(f"Re-embed failed for {site_id}: {e}")
        try:
            await reassign_source(site, db)
        except Exception as e:
            logger.warning(f"Collection re-assign failed for {site_id}: {e}")
    return site.to_dict()


@router.delete("/{site_id}")
async def delete_site(site_id: str, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    embedding_service.delete(site_id)
    await db.delete(site)
    return {"deleted": site_id}


@router.post("/clear-all")
async def clear_all_sites(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Site))
    sites = result.scalars().all()
    count = len(sites)
    for site in sites:
        try:
            embedding_service.delete(site.id)
        except Exception as e:
            logger.warning(f"Embedding delete failed for {site.id}: {e}")
    await db.execute(delete(Site))
    logger.info(f"Cleared all {count} sites and embeddings")
    return {"deleted": count, "message": f"Removed {count} sources from NEXUS"}
