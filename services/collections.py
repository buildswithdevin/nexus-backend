"""
Collection auto-assignment service.

Called after a site is ingested to automatically place it in the best
matching collection (cluster). Uses local scoring first, AI as enhancement.
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Cluster, Site
from services.ai_analysis import suggest_collection_assignment
from services.collection_engine import assign_source_locally

logger = logging.getLogger(__name__)

_AI_MIN_CONFIDENCE    = 0.60
_LOCAL_MIN_CONFIDENCE = 0.35


async def auto_assign_to_collection(site: Site, db: AsyncSession) -> dict | None:
    """
    Assign *site* to the best matching existing collection.

    Strategy:
      1. Local rule-based scoring (always runs, zero API calls)
      2. AI suggestion (runs if API key present, must beat local score)

    Returns assignment dict or None. Safe inside an open transaction.
    """
    cluster_result = await db.execute(select(Cluster))
    clusters       = cluster_result.scalars().all()

    if not clusters:
        logger.debug(f"auto_assign: no clusters exist for site {site.id}")
        return None

    cluster_dicts = [c.to_dict() for c in clusters]
    site_data     = site.to_dict()

    # ── 1. Local scoring ──────────────────────────────────────────────────────
    local = assign_source_locally(site_data, cluster_dicts)
    chosen: dict | None = local

    # ── 2. Try AI (optional, non-blocking) ───────────────────────────────────
    try:
        all_site_ids = list({sid for c in clusters for sid in (c.site_ids or [])})
        sites_by_id: dict = {}
        if all_site_ids:
            sr = await db.execute(select(Site).where(Site.id.in_(all_site_ids)))
            sites_by_id = {s.id: s for s in sr.scalars().all()}

        cluster_source_tags: dict[str, list[str]] = {}
        for cluster in clusters:
            tag_set: set[str] = set()
            for sid in (cluster.site_ids or []):
                s = sites_by_id.get(sid)
                if s:
                    tag_set.update(s.tags or [])
            cluster_source_tags[cluster.id] = list(tag_set)

        ai = await suggest_collection_assignment(site_data, cluster_dicts, cluster_source_tags)
        ai_conf = ai.get("confidence", 0.0)
        ai_id   = ai.get("assigned_cluster_id")

        # Use AI result only if it's confident and found a valid cluster
        if ai_id and ai_conf >= _AI_MIN_CONFIDENCE:
            chosen = {
                "cluster_id":    ai_id,
                "cluster_name":  next((c.get("name", "") for c in cluster_dicts if c["id"] == ai_id), ""),
                "cluster_color": next((c.get("color", "#8b5cf6") for c in cluster_dicts if c["id"] == ai_id), "#8b5cf6"),
                "confidence":    ai_conf,
                "reason":        ai.get("reason", ""),
            }
    except Exception as e:
        logger.debug(f"auto_assign: AI unavailable ({type(e).__name__}), using local result")

    if not chosen:
        logger.info(f"auto_assign: no match found for '{site.title}'")
        return None

    if chosen.get("confidence", 0) < _LOCAL_MIN_CONFIDENCE:
        logger.info(f"auto_assign: score too low for '{site.title}' ({chosen['confidence']:.2f})")
        return None

    # ── Persist ───────────────────────────────────────────────────────────────
    target = next((c for c in clusters if c.id == chosen["cluster_id"]), None)
    if not target:
        logger.warning(f"auto_assign: cluster {chosen['cluster_id']} not found")
        return None

    site_ids = list(target.site_ids or [])
    if site.id not in site_ids:
        site_ids.append(site.id)
        target.site_ids = site_ids
        await db.flush()

    logger.info(
        f"auto_assign: '{site.title}' → '{target.name}' "
        f"(conf={chosen['confidence']:.2f}, reason={chosen.get('reason','')})"
    )
    return {
        "cluster_id":    target.id,
        "cluster_name":  target.name,
        "cluster_color": target.color or "#8b5cf6",
        "confidence":    chosen["confidence"],
        "reason":        chosen.get("reason", ""),
    }


async def reassign_source(site: Site, db: AsyncSession) -> dict | None:
    """Remove *site* from all collections then re-run auto-assignment."""
    cluster_result = await db.execute(select(Cluster))
    for cluster in cluster_result.scalars().all():
        if site.id in (cluster.site_ids or []):
            cluster.site_ids = [sid for sid in cluster.site_ids if sid != site.id]
    await db.flush()
    return await auto_assign_to_collection(site, db)
