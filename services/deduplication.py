from typing import Optional
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Site

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "msclkid", "dclid", "twclid",
    "ref", "source", "_ga", "_gl", "mc_cid", "mc_eid",
    "igshid", "s", "si",
})


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {k: v for k, v in query.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(filtered, doseq=True)
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.params,
            new_query,
            "",  # drop fragment
        ))
    except Exception:
        return url


async def find_duplicate(url: str, user_id: str, db: AsyncSession) -> Optional[Site]:
    normalized = normalize_url(url)
    result = await db.execute(
        select(Site).where(Site.user_id == user_id, Site.url == normalized)
    )
    site = result.scalar_one_or_none()
    if site:
        return site
    # Also check the raw URL in case it was saved without normalization
    if normalized != url.strip().rstrip("/"):
        result2 = await db.execute(
            select(Site).where(Site.user_id == user_id, Site.url == url.strip().rstrip("/"))
        )
        return result2.scalar_one_or_none()
    return None
