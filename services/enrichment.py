import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from database.db import AsyncSessionLocal
from database.models import Site
from services.ai_analysis import analyze_site
from services.embeddings import embedding_service
from services.collections import auto_assign_to_collection
from services.safety import classify_content, log_blocked
from lib.events import emit

logger = logging.getLogger(__name__)

_CONTENT_TYPE_MAP: list[tuple[str, list[str]]] = [
    ("video",      ["youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "loom.com"]),
    ("repository", ["github.com", "gitlab.com", "bitbucket.org", "codeberg.org"]),
    ("docs",       ["readthedocs.io", "devdocs.io", "/docs/", "/documentation/"]),
    ("paper",      ["arxiv.org", "papers.ssrn.com", "semanticscholar.org", "dl.acm.org"]),
    ("podcast",    ["spotify.com/show", "podcasts.apple.com", "overcast.fm"]),
    ("tool",       ["npmjs.com", "pypi.org", "hub.docker.com", "crates.io", "rubygems.org"]),
    ("news",       ["news.ycombinator.com", "techcrunch.com", "wired.com", "theverge.com"]),
]


def detect_content_type(url: str) -> str:
    lower = url.lower()
    for ct, patterns in _CONTENT_TYPE_MAP:
        if any(p in lower for p in patterns):
            return ct
    return "article"


async def run_enrichment(site_id: str, raw_content: str = "") -> None:
    async with AsyncSessionLocal() as db:
        site: Site | None = None
        try:
            site = await db.get(Site, site_id)
            if not site:
                return

            site.enrichment_status = "processing"
            await db.flush()

            url   = site.url
            title = site.title

            site.content_type = detect_content_type(url)

            content_safety = classify_content(title, url, raw_content[:2000])
            is_restricted  = not content_safety.safe

            if is_restricted:
                log_blocked(f"{title} | {url}", content_safety.category or "unknown", "enrichment")
                ai: dict = {
                    "summary":        "This content has been flagged and will not be analysed.",
                    "category":       "Other",
                    "tags":           [],
                    "technologies":   [],
                    "topics":         [],
                    "use_case":       "",
                    "learning_value": "intermediate",
                }
                site.restricted        = True
                site.restricted_reason = content_safety.category
            else:
                ai = await analyze_site(
                    url=url,
                    title=title,
                    description=site.description or "",
                    raw_content=raw_content,
                )

            site.summary       = ai.get("summary", "")
            site.description   = site.description or ai.get("summary", "")
            site.category      = ai.get("category", "Other")
            site.tags          = [t.lower() for t in ai.get("tags", [])]
            site.technologies  = ai.get("technologies", [])
            site.topics        = ai.get("topics", [])
            site.use_case      = ai.get("use_case", "")
            site.learning_value = ai.get("learning_value", "intermediate")

            try:
                embed_data    = {**site.to_dict(), "raw_content": raw_content}
                chroma_id     = embedding_service.upsert(site.id, embed_data, user_id=site.user_id)
                site.chroma_id = chroma_id
            except Exception as e:
                logger.error(f"Enrichment: embedding failed for {url}: {e}")

            site.enrichment_status = "completed"
            site.enriched_at       = datetime.now(timezone.utc)
            await db.flush()

            try:
                await auto_assign_to_collection(site, db)
            except Exception as e:
                logger.warning(f"Enrichment: collection assign failed for {site_id}: {e}")

            await db.commit()
            emit("enrichment_completed", site_id=site_id, url=url)
            logger.info(f"Enrichment complete: {title} ({url})")

        except Exception as e:
            logger.error(f"Enrichment failed for {site_id}: {e}", exc_info=True)
            try:
                async with AsyncSessionLocal() as err_db:
                    err_site = await err_db.get(Site, site_id)
                    if err_site:
                        err_site.enrichment_status = "failed"
                        err_site.enrichment_error  = str(e)[:500]
                        await err_db.commit()
            except Exception:
                pass
            emit("enrichment_failed", site_id=site_id, error=str(e))
