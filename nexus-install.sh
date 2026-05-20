#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  NEXUS Backend — Self-Contained Installer for Fedora Linux
#  Paste this entire script into your terminal and run it.
#  It will pause and ask for your ANTHROPIC_API_KEY before starting the server.
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
G='\033[0;32m'; C='\033[0;36m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; NC='\033[0m'
info()  { echo -e "${C}[NEXUS]${NC} $*"; }
ok()    { echo -e "${G}[  OK ]${NC} $*"; }
warn()  { echo -e "${Y}[ WARN]${NC} $*"; }
err()   { echo -e "${R}[ERROR]${NC} $*"; exit 1; }
step()  { echo -e "\n${B}━━━ $* ━━━${NC}"; }

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_DIR="$HOME/Projects/nexus-backend"

# ═══════════════════════════════════════════════════════════════════════════════
step "1 · Creating project directory"
# ═══════════════════════════════════════════════════════════════════════════════
mkdir -p "$PROJECT_DIR"/{database,services,routers,data/chroma}
cd "$PROJECT_DIR"
ok "Directory ready: $PROJECT_DIR"

# ═══════════════════════════════════════════════════════════════════════════════
step "2 · Writing source files"
# ═══════════════════════════════════════════════════════════════════════════════

# ── requirements.txt ──────────────────────────────────────────────────────────
cat > requirements.txt << 'HEREDOC'
fastapi==0.115.5
uvicorn[standard]==0.32.1
sqlalchemy==2.0.36
aiosqlite==0.20.0
chromadb==0.5.20
sentence-transformers==3.3.1
anthropic==0.40.0
playwright==1.49.0
beautifulsoup4==4.12.3
httpx==0.28.0
python-dotenv==1.0.1
pydantic==2.10.3
pydantic-settings==2.6.1
python-multipart==0.0.18
aiofiles==24.1.0
HEREDOC

# ── .env.example ──────────────────────────────────────────────────────────────
cat > .env.example << 'HEREDOC'
ANTHROPIC_API_KEY=sk-ant-your-key-here
DATABASE_URL=sqlite+aiosqlite:///./data/nexus.db
CHROMA_PATH=./data/chroma
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,chrome-extension://*
SCRAPER_TIMEOUT=15
MAX_CONTENT_LENGTH=8000
HEREDOC

# ── config.py ─────────────────────────────────────────────────────────────────
cat > config.py << 'HEREDOC'
from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./data/nexus.db"
    chroma_path: str = "./data/chroma"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    scraper_timeout: int = 15
    max_content_length: int = 8000

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
os.makedirs(settings.chroma_path, exist_ok=True)
os.makedirs("./data", exist_ok=True)
HEREDOC

# ── database/__init__.py ──────────────────────────────────────────────────────
touch database/__init__.py

# ── database/db.py ────────────────────────────────────────────────────────────
cat > database/db.py << 'HEREDOC'
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    from database.models import Site, Cluster  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
HEREDOC

# ── database/models.py ────────────────────────────────────────────────────────
cat > database/models.py << 'HEREDOC'
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Text, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from database.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Site(Base):
    __tablename__ = "sites"

    id:             Mapped[str]            = mapped_column(String,        primary_key=True, default=new_id)
    title:          Mapped[str]            = mapped_column(String(512),   nullable=False)
    url:            Mapped[str]            = mapped_column(String(2048),  nullable=False, unique=True, index=True)
    description:    Mapped[Optional[str]]  = mapped_column(Text)
    summary:        Mapped[Optional[str]]  = mapped_column(Text)
    favicon_url:    Mapped[Optional[str]]  = mapped_column(String(2048))
    raw_content:    Mapped[Optional[str]]  = mapped_column(Text)
    category:       Mapped[Optional[str]]  = mapped_column(String(128))
    tags:           Mapped[Optional[list]] = mapped_column(JSON, default=list)
    technologies:   Mapped[Optional[list]] = mapped_column(JSON, default=list)
    topics:         Mapped[Optional[list]] = mapped_column(JSON, default=list)
    notes:          Mapped[Optional[str]]  = mapped_column(Text)
    pinned:         Mapped[bool]           = mapped_column(Boolean, default=False)
    use_case:       Mapped[Optional[str]]  = mapped_column(Text)
    learning_value: Mapped[Optional[str]]  = mapped_column(String(32))
    chroma_id:      Mapped[Optional[str]]  = mapped_column(String(128))
    created_at:     Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:     Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "title":          self.title,
            "url":            self.url,
            "description":    self.description,
            "summary":        self.summary,
            "favicon_url":    self.favicon_url,
            "category":       self.category,
            "tags":           self.tags or [],
            "technologies":   self.technologies or [],
            "topics":         self.topics or [],
            "notes":          self.notes,
            "pinned":         self.pinned,
            "use_case":       self.use_case,
            "learning_value": self.learning_value,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
            "updated_at":     self.updated_at.isoformat() if self.updated_at else None,
        }


class Cluster(Base):
    __tablename__ = "clusters"

    id:            Mapped[str]            = mapped_column(String,       primary_key=True, default=new_id)
    name:          Mapped[str]            = mapped_column(String(256),  nullable=False)
    description:   Mapped[Optional[str]]  = mapped_column(Text)
    color:         Mapped[Optional[str]]  = mapped_column(String(16))
    site_ids:      Mapped[Optional[list]] = mapped_column(JSON, default=list)
    learning_path: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    insight:       Mapped[Optional[str]]  = mapped_column(Text)
    created_at:    Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "name":          self.name,
            "description":   self.description,
            "color":         self.color,
            "site_ids":      self.site_ids or [],
            "learning_path": self.learning_path or [],
            "insight":       self.insight,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }
HEREDOC

# ── services/__init__.py ──────────────────────────────────────────────────────
touch services/__init__.py

# ── services/embeddings.py ────────────────────────────────────────────────────
cat > services/embeddings.py << 'HEREDOC'
import logging
from typing import List, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from config import settings

logger = logging.getLogger(__name__)
COLLECTION_NAME = "nexus_sites"


class EmbeddingService:
    def __init__(self):
        self._model: Optional[SentenceTransformer] = None
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection = None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info(f"Loading embedding model: {settings.embedding_model}")
            self._model = SentenceTransformer(settings.embedding_model)
            logger.info("Embedding model loaded.")
        return self._model

    def _get_client(self) -> chromadb.PersistentClient:
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=settings.chroma_path,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def _get_collection(self):
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _build_text(self, site_data: dict) -> str:
        parts = [
            site_data.get("title", ""),
            site_data.get("summary") or site_data.get("description", ""),
            " ".join(site_data.get("tags", [])),
            " ".join(site_data.get("topics", [])),
            " ".join(site_data.get("technologies", [])),
            site_data.get("category", ""),
            site_data.get("use_case", ""),
        ]
        return " | ".join(p for p in parts if p).strip()

    def embed_text(self, text: str) -> List[float]:
        return self._get_model().encode(text, normalize_embeddings=True).tolist()

    def upsert(self, site_id: str, site_data: dict) -> str:
        text = self._build_text(site_data)
        vector = self.embed_text(text)
        collection = self._get_collection()
        chroma_id = f"site_{site_id}"
        collection.upsert(
            ids=[chroma_id],
            embeddings=[vector],
            metadatas=[{
                "site_id":  site_id,
                "title":    site_data.get("title", ""),
                "url":      site_data.get("url", ""),
                "category": site_data.get("category", ""),
            }],
            documents=[text],
        )
        logger.info(f"Upserted vector for site {site_id}")
        return chroma_id

    def search(self, query: str, n_results: int = 10, where: Optional[dict] = None) -> List[dict]:
        query_vector = self.embed_text(query)
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return []
        n_results = min(n_results, count)
        kwargs = {
            "query_embeddings": [query_vector],
            "n_results": n_results,
            "include": ["metadatas", "distances", "documents"],
        }
        if where:
            kwargs["where"] = where
        results = collection.query(**kwargs)
        hits = []
        if results["ids"] and results["ids"][0]:
            for i, _ in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                score    = round(1 - distance, 4)
                metadata = results["metadatas"][0][i]
                hits.append({"site_id": metadata.get("site_id"), "score": score, "metadata": metadata})
        return hits

    def delete(self, site_id: str) -> None:
        try:
            self._get_collection().delete(ids=[f"site_{site_id}"])
        except Exception as e:
            logger.warning(f"Could not delete vector for {site_id}: {e}")

    def stats(self) -> dict:
        return {"total_vectors": self._get_collection().count()}


embedding_service = EmbeddingService()
HEREDOC

# ── services/scraper.py ───────────────────────────────────────────────────────
cat > services/scraper.py << 'HEREDOC'
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


def _is_js_heavy(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain.endswith(d) for d in _JS_HEAVY_DOMAINS)
    except Exception:
        return False


async def _fetch_with_httpx(url: str) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=settings.scraper_timeout, headers=headers) as client:
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
            page = await browser.new_page()
            await page.goto(url, timeout=settings.scraper_timeout * 1000, wait_until="networkidle")
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
        return None


async def scrape(url: str) -> dict:
    result = {"raw_content": None, "title": None, "favicon_url": None, "error": None}
    html = None
    if not _is_js_heavy(url):
        html = await _fetch_with_httpx(url)
    if html is None:
        html = await _fetch_with_playwright(url)
    if html is None:
        result["error"] = "Could not fetch page content"
        return result

    soup = BeautifulSoup(html, "html.parser")
    og_title  = soup.find("meta", property="og:title")
    title_tag = soup.find("title")
    result["title"] = (
        (og_title.get("content") if og_title else None) or
        (title_tag.get_text(strip=True) if title_tag else None)
    )
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        icon_link = soup.find("link", rel=lambda v: v and "icon" in " ".join(v).lower())
        if icon_link and icon_link.get("href"):
            href = icon_link["href"]
            result["favicon_url"] = href if href.startswith("http") else base + href
        else:
            result["favicon_url"] = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64"
    except Exception:
        pass

    raw = _clean_html(html)
    result["raw_content"] = raw[: settings.max_content_length]
    return result
HEREDOC

# ── services/ai_analysis.py ───────────────────────────────────────────────────
cat > services/ai_analysis.py << 'HEREDOC'
import json
import logging
import re
from typing import Optional

import anthropic
from config import settings

logger = logging.getLogger(__name__)

CATEGORIES = [
    "AI & ML", "Cybersecurity", "Robotics", "Embedded Systems",
    "Productivity", "Development", "Design", "Research",
    "Data Science", "Cloud & DevOps", "Hardware", "Other",
]

_client: Optional[anthropic.AsyncAnthropic] = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _parse_json(text: str) -> dict:
    text = re.sub(r"```json|```", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning(f"Could not parse JSON from response: {text[:200]}")
    return {}


async def analyze_site(url: str, title: str, description: str = "", raw_content: str = "") -> dict:
    content_preview = raw_content[:3000] if raw_content else ""
    prompt = f"""You are an expert knowledge curator. Analyze this website and return structured metadata.

URL: {url}
TITLE: {title}
DESCRIPTION: {description}
PAGE CONTENT (excerpt): {content_preview}

Return ONLY a valid JSON object with these exact fields — no markdown, no explanation:
{{
  "summary": "2-3 sentence summary: what the site does, who uses it, and why it matters",
  "category": "exactly one of: {', '.join(CATEGORIES)}",
  "tags": ["5-8 specific lowercase tags"],
  "technologies": ["programming languages, frameworks, tools mentioned or implied"],
  "topics": ["domain topics this site covers"],
  "use_case": "one sentence: specific situation when someone would visit this",
  "learning_value": "beginner or intermediate or advanced",
  "relationships": ["3-5 related concepts or fields this connects to"]
}}"""

    try:
        message = await _get_client().messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text if message.content else ""
        result = _parse_json(text)
        result["category"] = result.get("category", "Other")
        if result["category"] not in CATEGORIES:
            result["category"] = "Other"
        for field in ("tags", "technologies", "topics", "relationships"):
            if not isinstance(result.get(field), list):
                result[field] = []
        result.setdefault("summary", description or "No summary available.")
        result.setdefault("use_case", "")
        result.setdefault("learning_value", "intermediate")
        logger.info(f"AI analysis complete for: {url}")
        return result
    except anthropic.AuthenticationError:
        logger.error("Invalid Anthropic API key")
        raise
    except Exception as e:
        logger.error(f"AI analysis failed for {url}: {e}")
        return {
            "summary": description or "", "category": "Other",
            "tags": [], "technologies": [], "topics": [],
            "use_case": "", "learning_value": "intermediate", "relationships": [],
        }


async def semantic_command(query: str, sites: list[dict]) -> dict:
    if not sites:
        return {"indices": [], "interpretation": "No sites in database.", "insight": ""}

    site_list = "\n".join(
        f"[{i}] {s['title']} | {s.get('category','')} | "
        f"tags: {','.join(s.get('tags',[]))} | {s.get('summary','')[:120]}"
        for i, s in enumerate(sites)
    )
    prompt = f"""You are the NEXUS intelligence system. Execute this command against the bookmark database.

COMMAND: "{query}"

DATABASE ({len(sites)} sites):
{site_list}

Return ONLY valid JSON:
{{
  "indices": [ordered array of matching site indices, most relevant first],
  "interpretation": "one sentence describing what you understood the command to mean",
  "insight": "one non-obvious observation about the results or pattern you noticed"
}}"""

    try:
        message = await _get_client().messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text if message.content else ""
        result = _parse_json(text)
        result.setdefault("indices", [])
        result.setdefault("interpretation", "")
        result.setdefault("insight", "")
        result["indices"] = [i for i in result["indices"] if isinstance(i, int) and 0 <= i < len(sites)]
        return result
    except Exception as e:
        logger.error(f"Semantic command failed: {e}")
        return {"indices": [], "interpretation": str(e), "insight": ""}
HEREDOC

# ── routers/__init__.py ───────────────────────────────────────────────────────
touch routers/__init__.py

# ── routers/ingest.py ─────────────────────────────────────────────────────────
cat > routers/ingest.py << 'HEREDOC'
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site
from services.scraper import scrape
from services.ai_analysis import analyze_site
from services.embeddings import embedding_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ingest"])


class IngestRequest(BaseModel):
    url:         str
    title:       Optional[str]  = None
    description: Optional[str]  = None
    notes:       Optional[str]  = None
    tags:        Optional[list] = None
    favicon_url: Optional[str]  = None
    raw_content: Optional[str]  = None


@router.post("/ingest")
async def ingest_site(body: IngestRequest, db: AsyncSession = Depends(get_db)):
    url = str(body.url).strip().rstrip("/")

    existing = await db.execute(select(Site).where(Site.url == url))
    existing_site = existing.scalar_one_or_none()
    if existing_site:
        return {"status": "duplicate", "message": "URL already in NEXUS", "site": existing_site.to_dict()}

    scraped_title   = body.title
    scraped_favicon = body.favicon_url
    scraped_content = body.raw_content

    if not scraped_content:
        logger.info(f"Scraping: {url}")
        scrape_result   = await scrape(url)
        scraped_content = scrape_result.get("raw_content") or ""
        if not scraped_title:
            scraped_title = scrape_result.get("title") or url
        if not scraped_favicon:
            scraped_favicon = scrape_result.get("favicon_url")
    else:
        logger.info(f"Using pre-supplied content for: {url}")

    title = scraped_title or url

    logger.info(f"Running AI analysis for: {url}")
    ai = await analyze_site(url=url, title=title, description=body.description or "", raw_content=scraped_content)

    user_tags   = [t.lower() for t in (body.tags or [])]
    ai_tags     = [t.lower() for t in ai.get("tags", [])]
    merged_tags = list(dict.fromkeys(user_tags + ai_tags))

    site = Site(
        id            = str(uuid.uuid4()),
        title         = title,
        url           = url,
        description   = body.description or ai.get("summary", ""),
        summary       = ai.get("summary", ""),
        favicon_url   = scraped_favicon,
        raw_content   = scraped_content[:10000] if scraped_content else None,
        category      = ai.get("category", "Other"),
        tags          = merged_tags,
        technologies  = ai.get("technologies", []),
        topics        = ai.get("topics", []),
        notes         = body.notes or "",
        use_case      = ai.get("use_case", ""),
        learning_value= ai.get("learning_value", "intermediate"),
        pinned        = False,
    )

    try:
        chroma_id    = embedding_service.upsert(site.id, site.to_dict())
        site.chroma_id = chroma_id
    except Exception as e:
        logger.error(f"Embedding failed for {url}: {e}")

    db.add(site)
    await db.flush()
    logger.info(f"Ingested: {title} ({url})")
    return {"status": "created", "message": "Site captured and analyzed", "site": site.to_dict()}
HEREDOC

# ── routers/sites.py ──────────────────────────────────────────────────────────
cat > routers/sites.py << 'HEREDOC'
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site
from services.embeddings import embedding_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sites", tags=["sites"])


class SiteUpdate(BaseModel):
    title:        Optional[str]  = None
    description:  Optional[str]  = None
    notes:        Optional[str]  = None
    tags:         Optional[list] = None
    category:     Optional[str]  = None
    pinned:       Optional[bool] = None
    technologies: Optional[list] = None
    topics:       Optional[list] = None


@router.get("")
async def list_sites(
    category: Optional[str] = Query(None),
    pinned:   Optional[bool] = Query(None),
    tag:      Optional[str]  = Query(None),
    limit:    int            = Query(100, ge=1, le=500),
    offset:   int            = Query(0, ge=0),
    db: AsyncSession         = Depends(get_db),
):
    stmt = select(Site).order_by(Site.pinned.desc(), Site.created_at.desc())
    if category:
        stmt = stmt.where(Site.category == category)
    if pinned is not None:
        stmt = stmt.where(Site.pinned == pinned)
    result = await db.execute(stmt)
    sites = result.scalars().all()
    if tag:
        tag_lower = tag.lower()
        sites = [s for s in sites if tag_lower in [t.lower() for t in (s.tags or [])]]
    total = len(sites)
    sites = sites[offset: offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "sites": [s.to_dict() for s in sites]}


@router.get("/{site_id}")
async def get_site(site_id: str, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site.to_dict()


@router.put("/{site_id}")
async def update_site(site_id: str, body: SiteUpdate, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    updated = body.model_dump(exclude_none=True)
    for field, value in updated.items():
        setattr(site, field, value)
    await db.flush()
    if any(f in updated for f in ("title", "tags", "topics", "technologies", "category")):
        try:
            embedding_service.upsert(site.id, site.to_dict())
        except Exception as e:
            logger.warning(f"Re-embed failed for {site_id}: {e}")
    return site.to_dict()


@router.delete("/{site_id}")
async def delete_site(site_id: str, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    embedding_service.delete(site_id)
    await db.delete(site)
    return {"deleted": site_id}
HEREDOC

# ── routers/search.py ─────────────────────────────────────────────────────────
cat > routers/search.py << 'HEREDOC'
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site
from services.embeddings import embedding_service
from services.ai_analysis import semantic_command

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
            results.append(data)
    results.sort(key=lambda r: r["_score"], reverse=True)
    return {"query": body.query, "total": len(results), "results": results}


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
HEREDOC

# ── routers/export.py ─────────────────────────────────────────────────────────
cat > routers/export.py << 'HEREDOC'
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import Site, Cluster
from services.embeddings import embedding_service

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/export")
async def export_all(db: AsyncSession = Depends(get_db)):
    sites_result    = await db.execute(select(Site).order_by(Site.created_at))
    sites           = [s.to_dict() for s in sites_result.scalars().all()]
    clusters_result = await db.execute(select(Cluster).order_by(Cluster.created_at))
    clusters        = [c.to_dict() for c in clusters_result.scalars().all()]
    vector_stats    = embedding_service.stats()
    payload = {
        "export_version": "2.0",
        "exported_at":    datetime.now(timezone.utc).isoformat(),
        "stats": {"total_sites": len(sites), "total_clusters": len(clusters), "total_vectors": vector_stats.get("total_vectors", 0)},
        "sites":    sites,
        "clusters": clusters,
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="nexus-export-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json"'},
    )
HEREDOC

# ── main.py ───────────────────────────────────────────────────────────────────
cat > main.py << 'HEREDOC'
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database.db import init_db
from services.embeddings import embedding_service
from routers import sites, ingest, search, export

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nexus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("━━━ NEXUS BACKEND STARTING ━━━")
    logger.info("Initializing database …")
    await init_db()
    logger.info("Database ready.")
    logger.info("Warming up ChromaDB …")
    _ = embedding_service._get_collection()
    logger.info("ChromaDB ready.")
    logger.info("Loading embedding model (first run downloads ~90 MB) …")
    _ = embedding_service._get_model()
    logger.info(f"Embedding model ready: {settings.embedding_model}")
    logger.info("━━━ NEXUS BACKEND READY — http://localhost:8000 ━━━")
    yield
    logger.info("Shutting down …")


app = FastAPI(
    title="NEXUS Knowledge Hub API",
    description="AI-powered bookmark and knowledge management backend.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(export.router)


@app.get("/health", tags=["system"])
async def health():
    try:
        vec_stats = embedding_service.stats()
        return {
            "status":          "ok",
            "embedding_model": settings.embedding_model,
            "chroma_vectors":  vec_stats.get("total_vectors", 0),
            "version":         "2.0.0",
        }
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "error": str(e)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True, log_level="info")
HEREDOC

ok "All source files written."

# ═══════════════════════════════════════════════════════════════════════════════
step "3 · Verifying file structure"
# ═══════════════════════════════════════════════════════════════════════════════
REQUIRED=(
    main.py config.py requirements.txt
    database/__init__.py database/db.py database/models.py
    services/__init__.py services/embeddings.py services/scraper.py services/ai_analysis.py
    routers/__init__.py  routers/ingest.py routers/sites.py routers/search.py routers/export.py
)
ALL_GOOD=true
for f in "${REQUIRED[@]}"; do
    if [[ -f "$f" ]]; then
        ok "$f"
    else
        err "MISSING: $f"
        ALL_GOOD=false
    fi
done
$ALL_GOOD || err "File structure incomplete — aborting."

# ═══════════════════════════════════════════════════════════════════════════════
step "4 · Installing system dependencies (Fedora)"
# ═══════════════════════════════════════════════════════════════════════════════
info "Checking for Python 3.11+ …"
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_OK=$(python3  -c 'import sys; print(sys.version_info >= (3,11))')
info "Python version: $PY_VER"
if [[ "$PY_OK" != "True" ]]; then
    warn "Python 3.11+ recommended. Installing via dnf …"
    sudo dnf install -y python3.11 python3.11-pip python3.11-devel || \
        warn "Could not install Python 3.11 — proceeding with $PY_VER"
fi

info "Installing Playwright system deps (dnf) …"
sudo dnf install -y \
    nss atk at-spi2-atk cups-libs libdrm libXcomposite libXdamage \
    libXfixes libXrandr libgbm pango cairo alsa-lib \
    gtk3 libXScrnSaver libxshmfence xorg-x11-server-Xvfb \
    mesa-libgbm mesa-libGL \
    2>/dev/null || warn "Some system deps may have failed — Playwright may fall back to httpx scraper (that's fine)"
ok "System deps done."

# ═══════════════════════════════════════════════════════════════════════════════
step "5 · Creating Python virtual environment"
# ═══════════════════════════════════════════════════════════════════════════════
if [[ -d venv ]]; then
    warn "venv already exists — reusing it."
else
    python3 -m venv venv
    ok "Virtual environment created."
fi

source venv/bin/activate
pip install --upgrade pip --quiet
ok "pip upgraded."

# ═══════════════════════════════════════════════════════════════════════════════
step "6 · Installing Python dependencies"
# ═══════════════════════════════════════════════════════════════════════════════
info "This may take 2-5 minutes on first run (downloading sentence-transformers etc.) …"
pip install -r requirements.txt 2>&1 | tail -5
ok "Python packages installed."

# ═══════════════════════════════════════════════════════════════════════════════
step "7 · Installing Playwright Chromium browser"
# ═══════════════════════════════════════════════════════════════════════════════
playwright install chromium 2>/dev/null || warn "Playwright browser install had issues — httpx fallback will be used for scraping."
ok "Playwright ready."

# ═══════════════════════════════════════════════════════════════════════════════
step "8 · Creating .env from .env.example"
# ═══════════════════════════════════════════════════════════════════════════════
cp .env.example .env
ok ".env file created."

# ═══════════════════════════════════════════════════════════════════════════════
step "9 · ANTHROPIC_API_KEY"
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${Y}  Your Anthropic API key is needed for AI page analysis.${NC}"
echo -e "${Y}  Get one at: https://console.anthropic.com/settings/keys${NC}"
echo -e "${Y}  It will be written ONLY to: $PROJECT_DIR/.env${NC}"
echo -e "${Y}  (Never committed, never shared)${NC}"
echo ""
read -rsp "  Paste your ANTHROPIC_API_KEY and press Enter: " API_KEY
echo ""

if [[ -z "$API_KEY" ]]; then
    warn "No API key entered. AI analysis will be disabled. You can add it later:"
    warn "  echo 'ANTHROPIC_API_KEY=sk-ant-...' >> $PROJECT_DIR/.env"
else
    # Replace the placeholder in .env
    sed -i "s|ANTHROPIC_API_KEY=sk-ant-your-key-here|ANTHROPIC_API_KEY=$API_KEY|" .env
    ok "API key written to .env"
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "10 · Starting NEXUS backend"
# ═══════════════════════════════════════════════════════════════════════════════
info "Starting server on http://localhost:8000 …"
info "(First boot downloads the ~90MB embedding model — this takes ~60s)"
info "Press Ctrl+C to stop."
echo ""

# Start server in background, capture PID
python main.py &
SERVER_PID=$!

# Wait for it to be ready (poll health endpoint)
echo -ne "${C}[NEXUS]${NC} Waiting for server"
ATTEMPTS=0
MAX=60
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    sleep 2
    echo -n "."
    ATTEMPTS=$((ATTEMPTS + 2))
    if [[ $ATTEMPTS -ge $MAX ]]; then
        echo ""
        err "Server did not start within ${MAX}s. Check output above for errors."
    fi
    # Check process is still alive
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo ""
        err "Server process died. Check errors above."
    fi
done
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
step "11 · Health check"
# ═══════════════════════════════════════════════════════════════════════════════
HEALTH=$(curl -sf http://localhost:8000/health)
echo ""
echo -e "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${G}  NEXUS BACKEND IS RUNNING${NC}"
echo -e "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Health: $HEALTH"
echo ""
echo "  Endpoints:"
echo "    GET  http://localhost:8000/health"
echo "    POST http://localhost:8000/api/ingest"
echo "    GET  http://localhost:8000/api/sites"
echo "    POST http://localhost:8000/api/search/semantic"
echo "    GET  http://localhost:8000/api/export"
echo "    GET  http://localhost:8000/docs   ← Interactive API docs"
echo ""
echo "  Project: $PROJECT_DIR"
echo ""
echo -e "${C}  To restart later:${NC}"
echo "    cd $PROJECT_DIR"
echo "    source venv/bin/activate"
echo "    python main.py"
echo ""
echo -e "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Hand off to the foreground so logs stay visible
wait $SERVER_PID
