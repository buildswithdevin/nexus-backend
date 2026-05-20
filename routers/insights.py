import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site, Cluster, User
from services.ai_analysis import generate_insights
from lib.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("")
async def get_insights(
    db: AsyncSession   = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt   = (
        select(Site)
        .where(Site.user_id == current_user.id)
        .order_by(Site.created_at.desc())
        .limit(500)
    )
    result = await db.execute(stmt)
    sites  = [s.to_dict() for s in result.scalars().all()]

    clusters_result = await db.execute(
        select(Cluster).where(Cluster.user_id == current_user.id)
    )
    cluster_count = len(clusters_result.scalars().all())

    if not sites:
        return {
            "total_sources": 0, "total_clusters": 0,
            "headline": "Your library is empty. Start by adding sources!",
            "insights": [], "trends": [], "recommended_topics": [],
            "collection_suggestions": [], "learning_path": "",
            "stats": {"categories": {}, "top_tags": {}},
        }

    categories: dict[str, int] = {}
    tags_count:  dict[str, int] = {}
    for s in sites:
        cat = s.get("category") or "Other"
        categories[cat] = categories.get(cat, 0) + 1
        for tag in s.get("tags") or []:
            tags_count[tag] = tags_count.get(tag, 0) + 1

    top_tags = dict(sorted(tags_count.items(), key=lambda x: x[1], reverse=True)[:10])
    ai = await generate_insights(sites)

    return {
        "total_sources":  len(sites),
        "total_clusters": cluster_count,
        "headline":       ai.get("headline", ""),
        "insights":       ai.get("insights", []),
        "trends":         ai.get("trends", []),
        "recommended_topics":     ai.get("recommended_topics", []),
        "collection_suggestions": ai.get("collection_suggestions", []),
        "learning_path":  ai.get("learning_path", ""),
        "stats": {"categories": categories, "top_tags": top_tags},
    }
