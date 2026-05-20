import logging
from urllib.parse import urlparse

from sqlalchemy import select, or_, and_

from database.db import AsyncSessionLocal
from database.models import Site, SourceRelationship

logger = logging.getLogger(__name__)

_MAX_CANDIDATES = 200
_MAX_NEW_RELS    = 20


async def detect_and_save_relationships(site_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            site = await db.get(Site, site_id)
            if not site:
                return

            result = await db.execute(
                select(Site).where(
                    Site.user_id == site.user_id,
                    Site.id != site_id,
                    Site.enrichment_status == "completed",
                ).limit(_MAX_CANDIDATES)
            )
            others = result.scalars().all()
            if not others:
                return

            site_domain = urlparse(site.url).netloc.lower()
            site_tags   = set(t.lower() for t in (site.tags or []))
            site_cat    = site.category

            # Load existing relationship IDs to skip
            existing_result = await db.execute(
                select(SourceRelationship.related_source_id).where(
                    SourceRelationship.source_id == site_id
                )
            )
            existing_related = {r for (r,) in existing_result.all()}

            new_rels: list[SourceRelationship] = []
            for other in others:
                if other.id in existing_related:
                    continue

                other_domain = urlparse(other.url).netloc.lower()
                other_tags   = set(t.lower() for t in (other.tags or []))

                rel_type   = None
                confidence = 0.0
                reason     = None

                if site_domain and site_domain == other_domain:
                    rel_type   = "same_domain"
                    confidence = 0.9
                    reason     = f"Both from {site_domain}"
                elif site_tags and other_tags:
                    shared  = site_tags & other_tags
                    overlap = len(shared) / max(len(site_tags | other_tags), 1)
                    if overlap >= 0.25:
                        rel_type   = "related_tag"
                        confidence = round(min(overlap * 1.5, 1.0), 2)
                        reason     = f"Shared tags: {', '.join(sorted(shared)[:3])}"
                elif site_cat and site_cat == other.category:
                    rel_type   = "same_category"
                    confidence = 0.5
                    reason     = f"Both in {site_cat}"

                if rel_type:
                    new_rels.append(SourceRelationship(
                        user_id           = site.user_id,
                        source_id         = site_id,
                        related_source_id = other.id,
                        relationship_type = rel_type,
                        confidence_score  = confidence,
                        reason            = reason,
                    ))
                    if len(new_rels) >= _MAX_NEW_RELS:
                        break

            for rel in new_rels:
                db.add(rel)
            await db.commit()

            if new_rels:
                logger.info(f"Relationships: {len(new_rels)} new for site {site_id}")

        except Exception as e:
            logger.error(f"Relationship detection failed for {site_id}: {e}", exc_info=True)
