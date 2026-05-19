import asyncio
import io
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from config import settings

logger = logging.getLogger(__name__)

_STRIP_TAGS = {
    "script", "style", "noscript", "iframe", "head",
    "nav", "footer", "aside", "form", "button", "input",
    "select", "textarea", "svg", "canvas", "figure",
}

_JS_HEAVY_DOMAINS = {
    "twitter.com", "x.com", "linkedin.com", "instagram.com",
    "notion.so", "figma.com", "vercel.com",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── URL type detection ────────────────────────────────────────────────────────

def _is_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com/watch|youtu\.be/|youtube\.com/embed)", url))


def _is_github_repo(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in ("github.com", "www.github.com"):
        return False
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) >= 2  # at least /user/repo


def _is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _is_js_heavy(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain.endswith(d) for d in _JS_HEAVY_DOMAINS)
    except Exception:
        return False


# ── YouTube ───────────────────────────────────────────────────────────────────

def _extract_youtube_id(url: str) -> Optional[str]:
    for pat in [r"[?&]v=([a-zA-Z0-9_-]{11})", r"youtu\.be/([a-zA-Z0-9_-]{11})",
                r"embed/([a-zA-Z0-9_-]{11})"]:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


async def _scrape_youtube(url: str) -> dict:
    result: dict = {"raw_content": None, "title": None,
                    "favicon_url": "https://www.youtube.com/favicon.ico", "error": None}
    video_id = _extract_youtube_id(url)
    if not video_id:
        result["error"] = "Could not extract YouTube video ID"
        return result

    # Title via oEmbed (no API key needed)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://www.youtube.com/oembed?url=https://youtube.com/watch?v={video_id}&format=json"
            )
            if r.status_code == 200:
                result["title"] = r.json().get("title", "")
    except Exception:
        pass

    # Transcript
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        loop = asyncio.get_event_loop()
        transcript = await loop.run_in_executor(
            None, lambda: YouTubeTranscriptApi.get_transcript(video_id)
        )
        text = " ".join(e["text"] for e in transcript)
        result["raw_content"] = text[: settings.max_content_length]
        logger.info(f"YouTube transcript: {len(text):,} chars for {video_id}")
    except ImportError:
        logger.warning("youtube-transcript-api not installed — falling back to page scrape")
        result["error"] = "youtube-transcript-api not installed"
    except Exception as e:
        logger.warning(f"YouTube transcript unavailable for {video_id}: {e}")
        result["error"] = f"No transcript: {e}"

    return result


# ── GitHub ────────────────────────────────────────────────────────────────────

async def _scrape_github(url: str) -> dict:
    result: dict = {"raw_content": None, "title": None,
                    "favicon_url": "https://github.com/favicon.ico", "error": None}
    parsed = urlparse(url)
    parts  = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return result

    owner = parts[0]
    repo  = parts[1].rstrip(".git")
    gh_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15, headers=gh_headers) as client:
        try:
            repo_r   = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            readme_r = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/readme",
                headers={**gh_headers, "Accept": "application/vnd.github.raw"},
            )
            repo_data = repo_r.json() if repo_r.status_code == 200 else {}
            readme    = readme_r.text if readme_r.status_code == 200 else ""

            # Strip markdown
            clean = re.sub(r"```[\s\S]*?```", "", readme)
            clean = re.sub(r"#{1,6}\s+", "", clean)
            clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)
            clean = re.sub(r"[*_]{1,2}([^*_\n]+)[*_]{1,2}", r"\1", clean)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = re.sub(r"\s{2,}", " ", clean).strip()

            desc   = repo_data.get("description") or ""
            stars  = repo_data.get("stargazers_count", 0)
            lang   = repo_data.get("language") or ""
            topics = repo_data.get("topics") or []

            result["title"] = repo_data.get("full_name", f"{owner}/{repo}")
            result["raw_content"] = (
                f"{desc}\n"
                f"Language: {lang}  Stars: {stars:,}  Topics: {', '.join(topics)}\n\n"
                f"{clean}"
            )[: settings.max_content_length]
            logger.info(f"GitHub scraped: {owner}/{repo} ({stars:,} ⭐)")
        except Exception as e:
            logger.warning(f"GitHub scrape failed for {url}: {e}")
            result["error"] = str(e)

    return result


# ── PDF ───────────────────────────────────────────────────────────────────────

async def _scrape_pdf(url: str) -> dict:
    result: dict = {"raw_content": None, "title": None, "favicon_url": None, "error": None}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=_HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()

        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            logger.warning("pypdf not installed — PDF ingestion unavailable")
            result["error"] = "pypdf not installed"
            return result

        reader = PdfReader(io.BytesIO(r.content))
        pages  = []
        for i, page in enumerate(reader.pages):
            if i >= 30:
                break
            pages.append(page.extract_text() or "")

        text = "\n".join(pages)
        meta = reader.metadata or {}
        result["title"]       = (meta.get("/Title") or "").strip() or url.split("/")[-1].removesuffix(".pdf")
        result["raw_content"] = text[: settings.max_content_length]
        logger.info(f"PDF extracted: {len(text):,} chars, {len(reader.pages)} pages")
    except Exception as e:
        logger.warning(f"PDF scrape failed for {url}: {e}")
        result["error"] = str(e)

    return result


# ── General web scraping ──────────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    main = (
        soup.find("main") or soup.find("article") or
        soup.find(id=re.compile(r"content|main|body", re.I)) or
        soup.find(class_=re.compile(r"content|main|body|post", re.I)) or
        soup.body or soup
    )
    text = main.get_text(separator=" ", strip=True)
    return re.sub(r"\s{2,}", " ", text).strip()


async def _fetch_with_httpx(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=settings.scraper_timeout,
                                      headers=_HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
    except Exception as e:
        logger.warning(f"httpx fetch failed for {url}: {e}")
        return None


async def _fetch_with_playwright(url: str) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page    = await browser.new_page()
            await page.goto(url, timeout=settings.scraper_timeout * 1000, wait_until="networkidle")
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
        return None


async def _scrape_generic(url: str) -> dict:
    result: dict = {"raw_content": None, "title": None, "favicon_url": None, "error": None}
    html = None
    if not _is_js_heavy(url):
        html = await _fetch_with_httpx(url)
    if html is None:
        html = await _fetch_with_playwright(url)
    if html is None:
        result["error"] = "Could not fetch page content"
        return result

    soup     = BeautifulSoup(html, "html.parser")
    og_title = soup.find("meta", property="og:title")
    title_el = soup.find("title")
    result["title"] = (
        (og_title.get("content") if og_title else None) or
        (title_el.get_text(strip=True) if title_el else None)
    )
    try:
        parsed    = urlparse(url)
        base      = f"{parsed.scheme}://{parsed.netloc}"
        icon_link = soup.find("link", rel=lambda v: v and "icon" in " ".join(v).lower())
        if icon_link and icon_link.get("href"):
            href = icon_link["href"]
            result["favicon_url"] = href if href.startswith("http") else base + href
        else:
            result["favicon_url"] = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64"
    except Exception:
        pass

    result["raw_content"] = _clean_html(html)[: settings.max_content_length]
    return result


# ── Public entrypoint ─────────────────────────────────────────────────────────

async def scrape(url: str) -> dict:
    """Dispatch to the right scraper based on URL type."""
    if _is_youtube(url):
        logger.info(f"YouTube detected: {url}")
        result = await _scrape_youtube(url)
        # If transcript failed, supplement with generic scrape for title/favicon
        if not result.get("raw_content"):
            fallback = await _scrape_generic(url)
            result.setdefault("title",       fallback.get("title"))
            result.setdefault("favicon_url", fallback.get("favicon_url"))
        return result

    if _is_github_repo(url):
        logger.info(f"GitHub detected: {url}")
        result = await _scrape_github(url)
        if result.get("raw_content"):
            return result
        # GitHub API failed → fall through to generic

    if _is_pdf(url):
        logger.info(f"PDF detected: {url}")
        result = await _scrape_pdf(url)
        if result.get("raw_content"):
            return result

    return await _scrape_generic(url)
