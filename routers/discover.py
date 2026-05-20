import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Cluster, Site, User
from services.ai_analysis import generate_discover_suggestions
from services.discovery_engine import generate_local_discover, search_discover
from services.interest_profile import ensure_profile
from lib.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("")
async def get_discover(
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Site)
        .where(Site.user_id == current_user.id)
        .order_by(Site.created_at.desc())
        .limit(200)
    )
    sites   = result.scalars().all()
    sources = [s.to_dict() for s in sites if not s.restricted]

    cluster_result = await db.execute(
        select(Cluster).where(Cluster.user_id == current_user.id)
    )
    clusters = [c.to_dict() for c in cluster_result.scalars().all()]

    profile = await ensure_profile(db, current_user.id)

    data = generate_local_discover(sources, user_profile=profile, clusters=clusters)

    try:
        ai = await generate_discover_suggestions(sources)
        if ai and not data.get("starter_mode"):
            if ai.get("interest_summary"):
                data["interest_summary"] = ai["interest_summary"]
            if ai.get("top_interests") and len(ai["top_interests"]) > len(data.get("top_interests", [])):
                data["top_interests"] = ai["top_interests"]
            existing_topics = {s["topic"] for s in data.get("suggestions", [])}
            for s in ai.get("suggestions", []):
                if s.get("topic") not in existing_topics:
                    data.setdefault("suggestions", []).append(s)
                    existing_topics.add(s["topic"])
            logger.info("AI enhancement applied to discover results")
    except Exception as e:
        logger.info(f"AI discover enhancement skipped ({type(e).__name__})")

    return data


@router.get("/search")
async def discover_search(
    q: str              = Query(..., min_length=1),
    db: AsyncSession    = Depends(get_db),
    current_user: User  = Depends(get_current_user),
):
    result = await db.execute(
        select(Site)
        .where(Site.user_id == current_user.id)
        .order_by(Site.created_at.desc())
        .limit(200)
    )
    sites   = result.scalars().all()
    sources = [s.to_dict() for s in sites if not s.restricted]
    return search_discover(q, sources)
