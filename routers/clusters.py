import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Cluster, Site, User
from services.ai_analysis import auto_organize_clusters
from services.collection_engine import auto_organize_library, assign_source_locally, COLLECTION_DEFINITIONS
from services.collections import reassign_source
from lib.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clusters", tags=["clusters"])


class ClusterCreate(BaseModel):
    name:        str
    description: Optional[str]  = None
    color:       Optional[str]  = "#8b5cf6"
    site_ids:    list[str]      = []


class ClusterUpdate(BaseModel):
    name:        Optional[str]  = None
    description: Optional[str]  = None
    color:       Optional[str]  = None
    site_ids:    Optional[list] = None
    insight:     Optional[str]  = None


def _enrich_cluster(cluster: Cluster, sites_by_id: dict) -> dict:
    site_ids = cluster.site_ids or []
    sources  = [sites_by_id[sid] for sid in site_ids if sid in sites_by_id]
    tag_counts: dict[str, int] = {}
    for s in sources:
        for tag in (s.tags or []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tags = [t for t, _ in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:6]]
    sorted_sources = sorted(sources, key=lambda s: s.created_at.isoformat() if s.created_at else "", reverse=True)
    recent_sources = [
        {"id": s.id, "title": s.title, "favicon_url": s.favicon_url, "url": s.url}
        for s in sorted_sources[:3]
    ]
    data = cluster.to_dict()
    data["source_count"]   = len(sources)
    data["top_tags"]       = top_tags
    data["recent_sources"] = recent_sources
    return data


async def _load_sites_for_clusters(clusters: list[Cluster], db: AsyncSession) -> dict:
    all_site_ids = list({sid for c in clusters for sid in (c.site_ids or [])})
    if not all_site_ids:
        return {}
    result = await db.execute(select(Site).where(Site.id.in_(all_site_ids)))
    return {s.id: s for s in result.scalars().all()}


@router.get("")
async def list_clusters(
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result   = await db.execute(
        select(Cluster)
        .where(Cluster.user_id == current_user.id)
        .order_by(Cluster.created_at.desc())
    )
    clusters = result.scalars().all()
    return {"total": len(clusters), "clusters": [c.to_dict() for c in clusters]}


@router.get("/enriched")
async def list_clusters_enriched(
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result   = await db.execute(
        select(Cluster)
        .where(Cluster.user_id == current_user.id)
        .order_by(Cluster.created_at.desc())
    )
    clusters = result.scalars().all()
    if not clusters:
        return {"total": 0, "clusters": []}
    sites_by_id = await _load_sites_for_clusters(list(clusters), db)
    enriched    = [_enrich_cluster(c, sites_by_id) for c in clusters]
    return {"total": len(enriched), "clusters": enriched}


@router.post("")
async def create_cluster(
    body: ClusterCreate,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = Cluster(
        id          = str(uuid.uuid4()),
        user_id     = current_user.id,
        name        = body.name,
        description = body.description or "",
        color       = body.color or "#8b5cf6",
        site_ids    = body.site_ids,
    )
    db.add(cluster)
    await db.flush()
    logger.info(f"Created cluster: {cluster.name} for user {current_user.id}")
    return cluster.to_dict()


@router.put("/{cluster_id}")
async def update_cluster(
    cluster_id: str,
    body: ClusterUpdate,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = await db.get(Cluster, cluster_id)
    if not cluster or cluster.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cluster, field, value)
    await db.flush()
    return cluster.to_dict()


@router.delete("/{cluster_id}")
async def delete_cluster(
    cluster_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = await db.get(Cluster, cluster_id)
    if not cluster or cluster.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    await db.delete(cluster)
    return {"deleted": cluster_id}


@router.post("/{cluster_id}/sources/{site_id}")
async def add_source_to_cluster(
    cluster_id: str,
    site_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = await db.get(Cluster, cluster_id)
    if not cluster or cluster.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")

    all_clusters_result = await db.execute(
        select(Cluster).where(Cluster.user_id == current_user.id)
    )
    for c in all_clusters_result.scalars().all():
        if c.id != cluster_id and site_id in (c.site_ids or []):
            c.site_ids = [sid for sid in c.site_ids if sid != site_id]

    site_ids = list(cluster.site_ids or [])
    if site_id not in site_ids:
        site_ids.append(site_id)
        cluster.site_ids = site_ids

    await db.flush()
    return {"cluster_id": cluster_id, "site_id": site_id, "action": "added"}


@router.delete("/{cluster_id}/sources/{site_id}")
async def remove_source_from_cluster(
    cluster_id: str,
    site_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cluster = await db.get(Cluster, cluster_id)
    if not cluster or cluster.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    cluster.site_ids = [sid for sid in (cluster.site_ids or []) if sid != site_id]
    await db.flush()
    return {"cluster_id": cluster_id, "site_id": site_id, "action": "removed"}


@router.post("/reassign-source/{site_id}")
async def reassign_site_collection(
    site_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if not site or site.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Site not found")
    result = await reassign_source(site, db)
    return {"site_id": site_id, "collection": result}


@router.post("/auto-organize")
async def auto_organize(
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt   = (
        select(Site)
        .where(Site.user_id == current_user.id)
        .order_by(Site.created_at.desc())
        .limit(200)
    )
    result = await db.execute(stmt)
    sites  = [s.to_dict() for s in result.scalars().all()]

    if not sites:
        return {"clusters": [], "message": "No sources to organize"}

    suggested = auto_organize_library(sites)
    if not suggested:
        return {"clusters": [], "message": "Add at least 2 sources to organize your library"}

    try:
        ai_suggestions = await auto_organize_clusters(sites)
        if ai_suggestions:
            ai_by_name = {s["name"]: s for s in ai_suggestions}
            for local in suggested:
                name = local["name"]
                if name in ai_by_name:
                    ai = ai_by_name[name]
                    if ai.get("description"):
                        local["description"] = ai["description"]
                    if ai.get("insight") and local.get("name") != "Unsorted":
                        local["insight"] = ai["insight"]
            logger.info("AI enhancement applied to local collection results")
    except Exception as e:
        logger.info(f"AI enhancement skipped ({type(e).__name__}) — using local results")

    auto_names = set(COLLECTION_DEFINITIONS.keys()) | {"Unsorted"}
    existing = await db.execute(
        select(Cluster).where(Cluster.user_id == current_user.id)
    )
    for c in existing.scalars().all():
        if c.name in auto_names:
            await db.delete(c)

    created: list[Cluster] = []
    for s in suggested:
        cluster = Cluster(
            id          = str(uuid.uuid4()),
            user_id     = current_user.id,
            name        = s["name"],
            description = s.get("description", ""),
            color       = s.get("color", "#8b5cf6"),
            site_ids    = s.get("site_ids", []),
            insight     = s.get("insight", ""),
        )
        db.add(cluster)
        created.append(cluster)

    await db.flush()
    sites_by_id = await _load_sites_for_clusters(created, db)
    enriched    = [_enrich_cluster(c, sites_by_id) for c in created]

    logger.info(f"Auto-organized {len(sites)} sources into {len(created)} collections for user {current_user.id}")
    return {
        "clusters": enriched,
        "message":  f"Organized {len(sites)} sources into {len(created)} collections",
    }


@router.post("/merge")
async def merge_clusters(
    source_id: str,
    target_id: str,
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = await db.get(Cluster, source_id)
    target = await db.get(Cluster, target_id)
    if not source or source.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Source cluster not found")
    if not target or target.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Target cluster not found")

    merged_ids = list(dict.fromkeys((target.site_ids or []) + (source.site_ids or [])))
    target.site_ids = merged_ids
    await db.delete(source)
    await db.flush()
    return target.to_dict()
