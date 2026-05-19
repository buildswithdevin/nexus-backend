import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from services.interest_profile import (
    ensure_profile, get_profile_dict, apply_feedback,
    save_query_intent, extract_query_intent,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profile", tags=["profile"])


class FeedbackRequest(BaseModel):
    topic:    str
    category: str
    tags:     list[str] = []
    action:   str  # 'like' | 'dislike' | 'save' | 'dismiss'


class QueryIntentRequest(BaseModel):
    query: str


@router.get("")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """Return the user's current interest profile."""
    return await get_profile_dict(db)


@router.post("/feedback")
async def feedback(body: FeedbackRequest, db: AsyncSession = Depends(get_db)):
    """Record a like, dislike, save, or dismiss on a Discover item."""
    if body.action not in ("like", "dislike", "save", "dismiss"):
        return {"error": "invalid action — must be like/dislike/save/dismiss"}
    profile = await ensure_profile(db)
    apply_feedback(profile, body.topic, body.category, body.tags, body.action)
    logger.info(f"Profile feedback: {body.action} on '{body.topic}'")
    return {"ok": True, "action": body.action, "topic": body.topic}


@router.post("/query-intent")
async def record_query_intent(body: QueryIntentRequest, db: AsyncSession = Depends(get_db)):
    """Save an Ask NEXUS query to the recent-queries list for Discover influence."""
    profile = await ensure_profile(db)
    await save_query_intent(profile, body.query)
    intent  = extract_query_intent(body.query)
    logger.info(f"Query intent saved: '{body.query[:60]}' → domains={intent['domains']}")
    return {"ok": True, "intent": intent}


@router.delete("/reset")
async def reset_profile(db: AsyncSession = Depends(get_db)):
    """Wipe all interaction history."""
    profile = await ensure_profile(db)
    profile.liked_tags          = {}
    profile.disliked_tags       = {}
    profile.liked_categories    = {}
    profile.disliked_categories = {}
    profile.saved_topics        = []
    profile.dismissed_topics    = []
    profile.recent_queries      = []
    logger.info("User profile reset")
    return {"ok": True, "message": "Profile reset"}
