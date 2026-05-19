"""
User interest profile — local-only, no API calls.

Tracks liked/disliked tags and categories, recent Ask NEXUS queries (with timestamps),
and produces per-tool scoring boosts/penalties for the discovery engine.
"""
import re
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserProfile

logger = logging.getLogger(__name__)
_PROFILE_ID = "default"

# ── Intent → tags/categories mapping ─────────────────────────────────────────

INTENT_KEYWORD_MAP: list[dict] = [
    {
        "domain": "robotics",
        "triggers": [
            "robot", "robotics", "arduino", "esp32", "esp8266", "hardware", "embedded",
            "sensor", "sensors", "firmware", "microcontroller", "microcontrollers",
            "ros", "ros2", "jetson", "servo", "motor", "pwm", "gpio", "stm32",
            "raspberry pi", "mechatronics", "actuator", "iot", "lidar", "ultrasonic",
        ],
        "tags": ["robotics", "embedded systems", "microcontrollers", "sensors",
                 "hardware", "firmware", "computer vision", "iot"],
        "categories": ["Robotics & Hardware", "Embedded Systems", "Robotics", "Hardware"],
    },
    {
        "domain": "ai_ml",
        "triggers": [
            "ai", "machine learning", "ml", "deep learning", "neural", "llm",
            "gpt", "claude", "openai", "langchain", "vector", "embedding",
            "diffusion", "stable diffusion", "transformer", "huggingface",
            "pytorch", "tensorflow", "keras", "training", "fine-tuning",
            "inference", "rag", "agents", "agent", "chatbot", "generative",
        ],
        "tags": ["ai", "machine learning", "deep learning", "llm",
                 "neural networks", "transformers", "nlp", "computer vision"],
        "categories": ["AI & ML", "AI Tools", "Data Science"],
    },
    {
        "domain": "frontend",
        "triggers": [
            "react", "vue", "angular", "svelte", "next.js", "nextjs", "vite",
            "frontend", "ui", "css", "tailwind", "component", "web app", "spa",
            "figma", "design system", "shadcn", "radix", "website", "webpage",
            "html", "javascript", "typescript", "animation",
        ],
        "tags": ["frontend", "react", "javascript", "typescript",
                 "css", "ui", "web development"],
        "categories": ["Frontend Development", "Frontend", "Design", "Development"],
    },
    {
        "domain": "backend",
        "triggers": [
            "fastapi", "django", "flask", "express", "node", "api", "rest",
            "graphql", "backend", "server", "database", "sql", "postgres",
            "redis", "celery", "docker", "microservice", "endpoint", "crud",
        ],
        "tags": ["backend", "api", "python", "node.js", "database", "rest api"],
        "categories": ["Backend Development", "Backend", "Developer Tools", "Development"],
    },
    {
        "domain": "devops",
        "triggers": [
            "docker", "kubernetes", "k8s", "ci/cd", "github actions", "terraform",
            "aws", "gcp", "azure", "cloud", "devops", "deployment", "container",
            "helm", "ansible", "jenkins", "monitoring", "prometheus", "nginx",
            "vps", "hosting", "server", "deploy",
        ],
        "tags": ["devops", "cloud", "docker", "kubernetes", "ci/cd", "infrastructure"],
        "categories": ["Cloud & DevOps", "DevOps", "Developer Tools"],
    },
    {
        "domain": "data_science",
        "triggers": [
            "data", "pandas", "numpy", "jupyter", "matplotlib", "sklearn",
            "scikit", "data analysis", "visualization", "dashboard", "analytics",
            "bigquery", "spark", "dbt", "airflow", "pipeline", "etl",
            "dataset", "dataframe", "statistics", "chart",
        ],
        "tags": ["data science", "python", "data analysis",
                 "visualization", "machine learning"],
        "categories": ["Data Science"],
    },
    {
        "domain": "security",
        "triggers": [
            "security", "cybersecurity", "ctf", "pentest", "vulnerability",
            "exploit", "burp", "nmap", "wireshark", "cryptography", "auth",
            "oauth", "jwt", "hacking", "infosec", "zero-day", "malware",
        ],
        "tags": ["security", "cybersecurity", "pentesting", "cryptography"],
        "categories": ["Cybersecurity", "Security"],
    },
    {
        "domain": "resume_career",
        "triggers": [
            "resume", "cv", "job", "career", "linkedin", "interview",
            "application", "hire", "hiring", "portfolio", "salary",
            "internship", "recruiter", "cover letter", "apply",
        ],
        "tags": ["resume", "career", "job search", "portfolio", "linkedin"],
        "categories": ["Resume & Career", "Career"],
    },
    {
        "domain": "productivity",
        "triggers": [
            "productivity", "notion", "obsidian", "todo", "task", "workflow",
            "automation", "zapier", "make", "n8n", "note", "notes",
            "knowledge", "pkm", "second brain", "time management", "organize",
        ],
        "tags": ["productivity", "automation", "notes", "workflow", "knowledge management"],
        "categories": ["Productivity"],
    },
    {
        "domain": "writing",
        "triggers": [
            "writing", "blog", "article", "content", "copywriting", "grammar",
            "grammarly", "documentation", "docs", "markdown", "essay",
        ],
        "tags": ["writing", "content", "documentation", "blogging"],
        "categories": ["Writing Tools", "Writing"],
    },
    {
        "domain": "design",
        "triggers": [
            "design", "figma", "sketch", "ux", "prototype", "wireframe",
            "graphic", "adobe", "canva", "illustration", "animation", "motion",
            "branding", "logo", "color",
        ],
        "tags": ["design", "ui/ux", "figma", "graphics", "prototyping"],
        "categories": ["Design", "Creative & Media Tools"],
    },
]

# Pre-compile trigger patterns
_COMPILED: list[tuple[dict, list]] = [
    (entry, [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in entry["triggers"]])
    for entry in INTENT_KEYWORD_MAP
]

_STOP_WORDS = {
    "what", "tools", "help", "build", "make", "create", "find", "best", "good",
    "some", "with", "that", "this", "for", "the", "and", "can", "how", "want",
    "need", "looking", "recommend", "use", "using", "about", "learn", "learning",
    "tell", "show", "give", "get", "let", "will", "would", "could", "should",
    "very", "really", "also", "have", "has", "are", "was", "were",
}


def extract_query_intent(query: str) -> dict:
    """Local rule-based extraction of tags/categories from a query string."""
    q = query.lower()
    matched_tags: set[str] = set()
    matched_cats: set[str] = set()
    matched_domains: list[str] = []

    for entry, patterns in _COMPILED:
        for pat in patterns:
            if pat.search(q):
                matched_tags.update(entry["tags"])
                matched_cats.update(entry["categories"])
                matched_domains.append(entry["domain"])
                break

    keywords = [w for w in re.findall(r"\b[a-z]{3,}\b", q) if w not in _STOP_WORDS]

    return {
        "keywords":   keywords[:10],
        "tags":       list(matched_tags),
        "categories": list(matched_cats),
        "domains":    matched_domains,
    }


# ── Profile helpers ───────────────────────────────────────────────────────────

async def ensure_profile(db: AsyncSession) -> UserProfile:
    profile = await db.get(UserProfile, _PROFILE_ID)
    if not profile:
        profile = UserProfile(id=_PROFILE_ID)
        db.add(profile)
        await db.flush()
    return profile


async def get_profile_dict(db: AsyncSession) -> dict:
    profile = await db.get(UserProfile, _PROFILE_ID)
    return profile.to_dict() if profile else {}


# ── Feedback ──────────────────────────────────────────────────────────────────

def apply_feedback(
    profile: UserProfile,
    topic: str,
    category: str,
    tags: list[str],
    action: str,
) -> None:
    liked_tags    = dict(profile.liked_tags or {})
    disliked_tags = dict(profile.disliked_tags or {})
    liked_cats    = dict(profile.liked_categories or {})
    disliked_cats = dict(profile.disliked_categories or {})
    saved_topics  = list(profile.saved_topics or [])
    dismissed     = list(profile.dismissed_topics or [])

    if action in ("like", "save"):
        weight = 1.5 if action == "save" else 1.0
        for tag in tags:
            liked_tags[tag]     = liked_tags.get(tag, 0) + weight
            disliked_tags.pop(tag, None)
        if category:
            liked_cats[category] = liked_cats.get(category, 0) + weight
            disliked_cats.pop(category, None)
        if action == "save" and topic not in saved_topics:
            saved_topics.append(topic)

    elif action == "dislike":
        for tag in tags:
            disliked_tags[tag] = disliked_tags.get(tag, 0) + 1.0
            liked_tags.pop(tag, None)
        if category:
            disliked_cats[category] = disliked_cats.get(category, 0) + 1.0
            liked_cats.pop(category, None)
        if topic not in dismissed:
            dismissed.append(topic)

    elif action == "dismiss":
        if topic not in dismissed:
            dismissed.append(topic)

    profile.liked_tags          = liked_tags
    profile.disliked_tags       = disliked_tags
    profile.liked_categories    = liked_cats
    profile.disliked_categories = disliked_cats
    profile.saved_topics        = saved_topics[-100:]
    profile.dismissed_topics    = dismissed[-200:]


async def save_query_intent(profile: UserProfile, query: str) -> None:
    intent = extract_query_intent(query)
    if not intent["tags"] and not intent["categories"]:
        return

    recent = list(profile.recent_queries or [])
    recent.append({
        "query":      query[:200],
        "keywords":   intent["keywords"],
        "tags":       intent["tags"],
        "categories": intent["categories"],
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })
    profile.recent_queries = recent[-20:]


# ── Recent query sections (for Discover) ─────────────────────────────────────

def _age_label(age_hours: float) -> str:
    if age_hours < 0.5:
        return "Just now"
    if age_hours < 2:
        return f"{int(age_hours * 60)}m ago"
    if age_hours < 24:
        return f"{int(age_hours)}h ago"
    if age_hours < 48:
        return "Yesterday"
    return f"{int(age_hours / 24)}d ago"


def get_recent_query_sections(profile: UserProfile | None) -> list[dict]:
    """
    Return the last few unique-domain recent queries that are still fresh (<72h).
    Each entry has query, tags, categories, age_hours, decay, age_label.
    """
    if not profile or not profile.recent_queries:
        return []

    now = datetime.now(timezone.utc)
    sections = []
    seen_domains: set[str] = set()

    for entry in reversed(list(profile.recent_queries)):
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600
        except Exception:
            continue

        if age_hours > 72:
            continue

        decay = min(1.0, max(0.0, 1.0 - age_hours / 72.0))
        domain_key = ",".join(sorted(entry.get("categories", [])))
        if domain_key in seen_domains:
            continue
        seen_domains.add(domain_key)

        if entry.get("tags") or entry.get("categories"):
            sections.append({
                "query":      entry["query"],
                "tags":       entry.get("tags", []),
                "categories": entry.get("categories", []),
                "age_hours":  round(age_hours, 1),
                "age_label":  _age_label(age_hours),
                "decay":      round(decay, 3),
            })

        if len(sections) >= 3:
            break

    return sections


# ── Per-tool profile scoring ──────────────────────────────────────────────────

def compute_profile_score(tool: dict, profile: UserProfile | None) -> float:
    """
    Returns a float bonus/penalty for a curated tool based on the user's
    interaction history. Positive = boost, negative = suppress.
    """
    if not profile:
        return 0.0

    tool_tags = {t.lower() for t in (tool.get("tags") or [])}
    tool_cat  = (tool.get("category") or "").strip()
    now       = datetime.now(timezone.utc)

    liked_tags    = profile.liked_tags or {}
    disliked_tags = profile.disliked_tags or {}
    liked_cats    = profile.liked_categories or {}
    disliked_cats = profile.disliked_categories or {}

    score = 0.0

    for tag in tool_tags:
        if tag in liked_tags:
            score += liked_tags[tag] * 8
        if tag in disliked_tags:
            score -= disliked_tags[tag] * 10

    if tool_cat in liked_cats:
        score += liked_cats[tool_cat] * 12
    if tool_cat in disliked_cats:
        score -= disliked_cats[tool_cat] * 15

    # Recent query boost with time decay
    for entry in (profile.recent_queries or [])[-10:]:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600
        except Exception:
            continue

        if age_hours > 72:
            continue

        decay = min(1.0, max(0.0, 1.0 - age_hours / 72.0))
        q_tags = {t.lower() for t in entry.get("tags", [])}
        q_cats = set(entry.get("categories", []))

        kw_match  = len(tool_tags & q_tags)
        cat_match = 1 if tool_cat in q_cats else 0
        score += (kw_match * 3 + cat_match * 5) * decay * 15

    # Strong suppression for dismissed topics
    topic = (tool.get("topic") or "").lower()
    if topic in {d.lower() for d in (profile.dismissed_topics or [])}:
        score -= 100.0

    return score
