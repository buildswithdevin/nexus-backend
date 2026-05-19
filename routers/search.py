import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site
from services.embeddings import embedding_service
from services.ai_analysis import semantic_command, synthesize_answer, compare_sources_ai, _detect_comparison_subjects
from services.interest_profile import ensure_profile, save_query_intent
from services.safety import classify_query, log_blocked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


class SemanticSearchRequest(BaseModel):
    query:     str
    limit:     int           = 10
    category:  Optional[str] = None
    min_score: float         = 0.0


class CommandRequest(BaseModel):
    command: str
    limit:   int = 20


@router.post("/semantic")
async def semantic_search(body: SemanticSearchRequest, db: AsyncSession = Depends(get_db)):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    where = {"category": body.category} if body.category else None
    hits  = embedding_service.search(query=body.query, n_results=min(body.limit, 50), where=where)
    hits  = [h for h in hits if h["score"] >= body.min_score]
    if not hits:
        return {"query": body.query, "results": [], "total": 0}
    site_ids    = [h["site_id"] for h in hits if h["site_id"]]
    stmt        = select(Site).where(Site.id.in_(site_ids))
    result      = await db.execute(stmt)
    sites_by_id = {s.id: s for s in result.scalars().all()}
    results = []
    for hit in hits:
        site = sites_by_id.get(hit["site_id"])
        if site:
            data = site.to_dict()
            data["_score"] = hit["score"]
            if site.raw_content:
                data["content_excerpt"] = site.raw_content[:500].strip()
            results.append(data)
    results.sort(key=lambda r: r["_score"], reverse=True)
    logger.info(f"Semantic search '{body.query}' → {len(results)} results")
    return {"query": body.query, "total": len(results), "results": results}


@router.get("")
async def keyword_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Keyword fallback: searches title, summary, description, notes, raw_content."""
    term = f"%{q.lower()}%"
    stmt = (
        select(Site)
        .where(
            or_(
                Site.title.ilike(term),
                Site.summary.ilike(term),
                Site.description.ilike(term),
                Site.notes.ilike(term),
                Site.raw_content.ilike(term),
            )
        )
        .order_by(Site.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    sites = result.scalars().all()
    results = []
    for site in sites:
        data = site.to_dict()
        data["_score"] = 1.0
        if site.raw_content:
            data["content_excerpt"] = site.raw_content[:500].strip()
        results.append(data)
    logger.info(f"Keyword search '{q}' → {len(results)} results")
    return {"query": q, "total": len(results), "results": results}


class AskRequest(BaseModel):
    query: str
    limit: int = 8


@router.post("/ask")
async def ask_library(body: AskRequest, db: AsyncSession = Depends(get_db)):
    """
    Full Ask NEXUS pipeline:
      1. Safety classification
      2. Lazy-reindex sources whose embeddings are title-only (no summary/tags yet)
      3. Semantic vector search
      4. Keyword fallback if semantic returns nothing
      5. Claude synthesis (or local fallback if no credits)
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ── 0. Safety check ──────────────────────────────────────────────────────────
    safety = classify_query(query)
    if not safety.safe:
        log_blocked(query, safety.category or "unknown", "blocked_ask", safety.is_self_harm)
        logger.info(f"Blocked ask query — category={safety.category}")
        return {
            "query":              query,
            "blocked":            True,
            "blocked_category":   safety.category,
            "answer":             safety.message,
            "recommendations":    [],
            "missing_topics":     [],
            "total_searched":     0,
            "synthesis_method":   "blocked",
            "query_intent":       "general",
            "confidence_summary": {},
        }

    # ── 1. Lazy reindex: re-embed sources that have raw_content but no metadata ──
    sparse_stmt = (
        select(Site)
        .where(Site.raw_content.isnot(None))
        .where(or_(Site.summary.is_(None), Site.summary == ""))
    )
    sparse_result = await db.execute(sparse_stmt)
    sparse_sites  = sparse_result.scalars().all()
    reindexed = 0
    for site in sparse_sites:
        try:
            embed_data = {**site.to_dict(), "raw_content": site.raw_content or ""}
            embedding_service.upsert(site.id, embed_data)
            reindexed += 1
        except Exception as e:
            logger.warning(f"Reindex failed for {site.id}: {e}")
    if reindexed:
        logger.info(f"Lazy-reindexed {reindexed} sparse source(s) before ask")

    # ── 2. Semantic search ───────────────────────────────────────────────────────
    hits = embedding_service.search(query=query, n_results=min(body.limit * 2, 20))
    hits = [h for h in hits if h["score"] >= 0.08]

    results: list[dict] = []

    if hits:
        site_ids    = [h["site_id"] for h in hits]
        stmt        = select(Site).where(Site.id.in_(site_ids))
        db_result   = await db.execute(stmt)
        sites_by_id = {s.id: s for s in db_result.scalars().all()}
        for hit in hits[: body.limit]:
            site = sites_by_id.get(hit["site_id"])
            if site:
                data = {**site.to_dict(), "_score": hit["score"]}
                if site.raw_content:
                    data["content_excerpt"] = site.raw_content[:400].strip()
                results.append(data)
        results.sort(key=lambda r: r["_score"], reverse=True)

    # ── 3. Keyword fallback ──────────────────────────────────────────────────────
    if not results:
        term     = f"%{query.lower()}%"
        fb_stmt  = (
            select(Site)
            .where(or_(
                Site.title.ilike(term),
                Site.summary.ilike(term),
                Site.raw_content.ilike(term),
                Site.notes.ilike(term),
            ))
            .limit(body.limit)
        )
        fb_db    = await db.execute(fb_stmt)
        fb_sites = fb_db.scalars().all()
        for site in fb_sites:
            data = {**site.to_dict(), "_score": 0.6}
            if site.raw_content:
                data["content_excerpt"] = site.raw_content[:400].strip()
            results.append(data)
        if results:
            logger.info(f"Keyword fallback found {len(results)} result(s) for: {query[:60]}")

    # ── 4. Synthesis ─────────────────────────────────────────────────────────────
    synthesis    = await synthesize_answer(query, results)
    sources_by_id = {r["id"]: r for r in results}

    # Merge synthesis recommendations with full source data
    recommendations = []
    seen_ids: set[str] = set()
    for rec in synthesis.get("recommendations", []):
        src = sources_by_id.get(rec.get("id", ""))
        if src and src["id"] not in seen_ids:
            recommendations.append({
                "source":    src,
                "reason":    rec.get("reason", ""),
                "relevance": rec.get("relevance", "medium"),
            })
            seen_ids.add(src["id"])

    # If synthesis produced no recs AND this isn't an honest-no-match, fall back to ranked results
    is_honest_no_match = synthesis.get("method") == "honest-no-match"
    if not recommendations and not is_honest_no_match:
        for r in results[: body.limit]:
            if r["id"] not in seen_ids:
                conf = r.get("_confidence", r.get("_score", 0))
                recommendations.append({
                    "source":    r,
                    "reason":    "",
                    "relevance": "high" if conf >= 0.45 else "medium" if conf >= 0.27 else "low",
                })
                seen_ids.add(r["id"])

    total_vectors = embedding_service.stats().get("total_vectors", 0)
    logger.info(
        f"Ask '{query[:50]}' → {len(recommendations)} rec(s), "
        f"method={synthesis.get('method','local')}, vectors={total_vectors}"
    )

    # Fire-and-forget: save query intent to user profile for Discover influence
    try:
        profile = await ensure_profile(db)
        await save_query_intent(profile, query)
    except Exception:
        pass  # never fail the ask response over this

    return {
        "query":              query,
        "answer":             synthesis.get("answer", ""),
        "recommendations":    recommendations,
        "missing_topics":     synthesis.get("missing_topics", []),
        "total_searched":     total_vectors,
        "synthesis_method":   synthesis.get("method", "local"),
        "query_intent":       synthesis.get("query_intent", "general"),
        "confidence_summary": synthesis.get("confidence_summary", {}),
    }


@router.post("/command")
async def command_search(body: CommandRequest, db: AsyncSession = Depends(get_db)):
    if not body.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty")
    stmt      = select(Site).order_by(Site.created_at.desc()).limit(200)
    result    = await db.execute(stmt)
    all_sites = [s.to_dict() for s in result.scalars().all()]
    if not all_sites:
        return {"command": body.command, "interpretation": "No sites in database.", "insight": "", "results": [], "total": 0}
    ai_result     = await semantic_command(body.command, all_sites)
    matched_sites = [all_sites[i] for i in ai_result.get("indices", []) if 0 <= i < len(all_sites)][: body.limit]
    return {
        "command":        body.command,
        "interpretation": ai_result.get("interpretation", ""),
        "insight":        ai_result.get("insight", ""),
        "total":          len(matched_sites),
        "results":        matched_sites,
    }


# ── Source Comparison ────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    query: str  # full comparison query, e.g. "Compare React vs Vue"


@router.post("/compare")
async def compare_sources(body: CompareRequest, db: AsyncSession = Depends(get_db)):
    """
    Detect comparison intent in the query, find matching library sources,
    and return a structured side-by-side comparison via Claude.
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    safety = classify_query(query)
    if not safety.safe:
        log_blocked(query, safety.category or "unknown", "blocked_compare", safety.is_self_harm)
        raise HTTPException(status_code=400, detail=safety.message)

    subjects = _detect_comparison_subjects(query)
    if not subjects:
        raise HTTPException(status_code=422, detail="Could not detect two subjects to compare. Try: 'Compare X vs Y'")

    name_a, name_b = subjects

    # Search library for each subject using semantic + keyword
    async def find_sources(name: str) -> list[dict]:
        hits = embedding_service.search(query=name, n_results=5)
        site_ids = [h["site_id"] for h in hits if h.get("site_id")]
        if site_ids:
            res  = await db.execute(select(Site).where(Site.id.in_(site_ids)))
            sites = {s.id: s for s in res.scalars().all()}
            ordered = [sites[h["site_id"]].to_dict() for h in hits if h.get("site_id") in sites]
        else:
            ordered = []
        # Keyword fallback to catch by title/tags
        if len(ordered) < 2:
            term  = f"%{name.lower()}%"
            kw_res = await db.execute(
                select(Site).where(
                    or_(Site.title.ilike(term), Site.tags.ilike(term), Site.summary.ilike(term))
                ).limit(3)
            )
            kw_sites = [s.to_dict() for s in kw_res.scalars().all()]
            seen_ids = {s["id"] for s in ordered}
            ordered += [s for s in kw_sites if s["id"] not in seen_ids]
        return ordered[:3]

    sources_a, sources_b = await find_sources(name_a), await find_sources(name_b)

    comparison = await compare_sources_ai(query, sources_a, sources_b)
    comparison["query"]     = query
    comparison["source_ids_a"] = [s["id"] for s in sources_a]
    comparison["source_ids_b"] = [s["id"] for s in sources_b]
    return comparison
