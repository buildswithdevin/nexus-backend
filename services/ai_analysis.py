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

# ── Local fallback analysis ────────────────────────────────────────────────────

_DOMAIN_CATEGORY: list[tuple[set[str], str]] = [
    ({"github.com", "gitlab.com", "bitbucket.org"}, "Development"),
    ({"stackoverflow.com", "stackexchange.com"}, "Development"),
    ({"docs.", "documentation.", "devdocs.io", "developer."}, "Development"),
    ({"arxiv.org", "scholar.google", "semanticscholar.org", "researchgate.net"}, "Research"),
    ({"youtube.com", "youtu.be", "vimeo.com", "twitch.tv"}, "Design"),
    ({"figma.com", "dribbble.com", "behance.net", "sketch.com"}, "Design"),
    ({"kaggle.com", "huggingface.co", "openai.com", "anthropic.com"}, "AI & ML"),
    ({"coursera.org", "udemy.com", "edx.org", "khanacademy.org", "pluralsight.com"}, "Research"),
    ({"notion.so", "obsidian.md", "roamresearch.com", "logseq.com"}, "Productivity"),
    ({"aws.amazon.com", "cloud.google.com", "azure.microsoft.com", "digitalocean.com"}, "Cloud & DevOps"),
    ({"arduino.cc", "esp32", "raspberrypi.org", "adafruit.com"}, "Hardware"),
    ({"ros.org", "robotics.", "robot.", "rover."}, "Robotics"),
]

_KEYWORD_TAGS: list[tuple[list[str], str]] = [
    (["python", "pytorch", "pandas", "numpy", "flask", "django", "fastapi"], "python"),
    (["javascript", "js", "node.js", "nodejs", "express", "npm", "deno"], "javascript"),
    (["typescript", "ts"], "typescript"),
    (["react", "reactjs", "next.js", "nextjs", "gatsby", "remix"], "react"),
    (["tailwind", "tailwindcss"], "tailwind"),
    (["css", "stylesheet", "scss", "sass", "styled-components"], "css"),
    (["html", "html5", "dom"], "html"),
    (["machine learning", "ml", "deep learning", "neural network", "bert", "transformers"], "machine-learning"),
    (["llm", "large language model", "gpt", "chatgpt", "openai", "claude", "anthropic", "gemini"], "llm"),
    (["ai", "artificial intelligence", "generative ai"], "ai"),
    (["robot", "robotics", "ros", "autonomy", "drone"], "robotics"),
    (["arduino", "esp32", "raspberry pi", "microcontroller", "firmware", "embedded"], "embedded"),
    (["linux", "ubuntu", "debian", "fedora", "bash", "shell", "unix", "terminal"], "linux"),
    (["docker", "kubernetes", "k8s", "container", "devops", "ci/cd", "github actions"], "devops"),
    (["database", "sql", "postgresql", "mysql", "mongodb", "redis", "sqlite", "nosql"], "database"),
    (["api", "rest", "graphql", "grpc", "webhook", "openapi", "swagger"], "api"),
    (["resume", "cv", "portfolio", "job", "interview", "career", "hiring"], "career"),
    (["design", "figma", "sketch", "ui", "ux", "user interface", "prototyping"], "design"),
    (["tutorial", "how to", "guide", "learn", "introduction to", "getting started"], "tutorial"),
    (["course", "lecture", "lesson", "bootcamp", "training", "certification"], "learning"),
    (["productivity", "workflow", "automation", "zapier", "make.com", "notion"], "productivity"),
    (["video", "youtube", "stream", "podcast", "mp4"], "video"),
    (["security", "cybersecurity", "vulnerability", "pentest", "hacking", "ctf"], "security"),
    (["data science", "data analysis", "visualization", "jupyter", "pandas", "matplotlib"], "data-science"),
    (["cloud", "aws", "azure", "gcp", "serverless", "lambda", "vercel", "netlify"], "cloud"),
    (["hardware", "pcb", "circuit", "electronics", "raspberry", "sensor"], "hardware"),
    (["writing", "blog", "article", "essay", "newsletter", "substack"], "writing"),
    (["research", "paper", "study", "survey", "journal", "arxiv"], "research"),
    (["game", "unity", "unreal", "gamedev", "godot", "pygame"], "game-dev"),
    (["mobile", "ios", "android", "swift", "kotlin", "react native", "flutter"], "mobile"),
]

_KEYWORD_CATEGORY: list[tuple[list[str], str]] = [
    (["machine learning", "deep learning", "llm", "gpt", "transformer", "neural", "ai model", "artificial intelligence", "generative", "openai", "anthropic", "hugging face"], "AI & ML"),
    (["robot", "robotics", "ros", "autonomous", "servo", "motor driver", "manipulator"], "Robotics"),
    (["arduino", "esp32", "microcontroller", "raspberry pi", "embedded", "firmware", "fpga", "circuit board", "pcb"], "Embedded Systems"),
    (["design", "figma", "ui", "ux", "user experience", "prototype", "wireframe", "dribbble", "typography", "color palette"], "Design"),
    (["security", "cybersecurity", "hacking", "pentest", "vulnerability", "exploit", "ctf", "firewall"], "Cybersecurity"),
    (["data science", "data analysis", "pandas", "matplotlib", "kaggle", "spark", "tableau", "bi dashboard"], "Data Science"),
    (["aws", "azure", "gcp", "kubernetes", "docker", "devops", "ci/cd", "terraform", "cloud infrastructure"], "Cloud & DevOps"),
    (["hardware", "electronics", "pcb", "soldering", "sensor", "power supply", "oscilloscope"], "Hardware"),
    (["research", "paper", "arxiv", "journal", "academic", "study", "scholarly"], "Research"),
    (["productivity", "workflow", "notion", "obsidian", "task management", "automation", "time tracking"], "Productivity"),
    (["python", "javascript", "typescript", "react", "api", "framework", "library", "developer", "programming", "coding", "software", "backend", "frontend"], "Development"),
]


def _local_analyze_site(url: str, title: str, description: str = "", raw_content: str = "") -> dict:
    """Rule-based analysis — always produces a useful result without an API key."""
    from urllib.parse import urlparse
    import re

    domain = urlparse(url).netloc.lower().replace("www.", "")
    combined = f"{title} {description} {url} {raw_content[:2000]}".lower()

    # ── Category inference ────────────────────────────────
    category = "Other"
    for domains_set, cat in _DOMAIN_CATEGORY:
        if any(d in domain for d in domains_set):
            category = cat
            break
    if category == "Other":
        for keywords, cat in _KEYWORD_CATEGORY:
            if any(kw in combined for kw in keywords):
                category = cat
                break

    # ── Tag extraction ────────────────────────────────────
    found_tags: list[str] = []
    for keywords, tag in _KEYWORD_TAGS:
        if any(kw in combined for kw in keywords):
            found_tags.append(tag)
        if len(found_tags) >= 7:
            break
    # Always have at least one tag based on category
    if not found_tags:
        cat_tag_map = {
            "Development": "developer-tools",
            "AI & ML": "ai",
            "Design": "design",
            "Research": "research",
            "Productivity": "productivity",
            "Robotics": "robotics",
            "Embedded Systems": "embedded",
            "Cybersecurity": "security",
            "Data Science": "data-science",
            "Cloud & DevOps": "devops",
            "Hardware": "hardware",
        }
        found_tags = [cat_tag_map.get(category, "resource")]

    # ── Summary ───────────────────────────────────────────
    if description and len(description) > 40:
        summary = description
    elif raw_content:
        # Take first meaningful sentence from content
        sentences = re.split(r'(?<=[.!?])\s+', raw_content[:600].strip())
        usable = [s.strip() for s in sentences if len(s.strip()) > 30]
        if usable:
            summary = " ".join(usable[:2])
        else:
            summary = f"{title} — a resource in the {category} space. No description available yet. Click retry to re-analyze this source."
    else:
        summary = f"{title} — a {category.lower()} resource. No description available yet. Click retry to re-analyze this source."

    # ── Use case ──────────────────────────────────────────
    use_case_map = {
        "AI & ML": "When building, evaluating, or researching AI/ML models and tools.",
        "Development": "When coding, debugging, or learning software development techniques.",
        "Design": "When working on UI/UX, visual design, or creative projects.",
        "Research": "When exploring academic knowledge, papers, or in-depth studies.",
        "Productivity": "When optimizing your workflow or looking for tools to get more done.",
        "Robotics": "When building or programming robotic systems and autonomous machines.",
        "Embedded Systems": "When working with microcontrollers, firmware, or hardware-level programming.",
        "Cybersecurity": "When securing systems, testing vulnerabilities, or studying cyber threats.",
        "Data Science": "When analyzing data, building models, or exploring datasets.",
        "Cloud & DevOps": "When deploying, scaling, or automating cloud infrastructure.",
        "Hardware": "When designing circuits, selecting components, or building physical devices.",
    }
    use_case = use_case_map.get(category, "A useful reference for future research and exploration.")

    return {
        "summary": summary[:500],
        "category": category,
        "tags": found_tags[:7],
        "technologies": [],
        "topics": [category],
        "use_case": use_case,
        "learning_value": "intermediate",
        "relationships": [],
    }

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
        logger.warning("Anthropic API key invalid — using local fallback analysis")
        return _local_analyze_site(url, title, description, raw_content)
    except Exception as e:
        logger.error(f"AI analysis failed for {url}: {e} — using local fallback")
        return _local_analyze_site(url, title, description, raw_content)


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


# ── Query intent detection & confidence scoring ──────────────────────────────

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "is", "in", "of", "to", "for", "with",
    "how", "what", "why", "which", "when", "where", "does", "do", "can",
    "i", "my", "me", "you", "it", "this", "that", "are", "was", "be",
    "been", "have", "has", "had", "will", "would", "should", "could",
    "about", "from", "on", "at", "by", "as", "vs", "versus", "compare",
    "between", "show", "get", "use", "using", "tell", "give", "list",
    "some", "any", "all", "more", "most", "best", "good", "better",
}

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("compare",   [r"\bvs\.?\b", r"\bversus\b", r"\bcompare\b", r"\bdifference between\b", r"\bwhich is better\b"]),
    ("recommend", [r"\brecommend\b", r"\bsuggestion\b", r"\bwhat should i\b", r"\bbest\b.{0,20}\bfor\b", r"\btop\b.{0,20}\bfor\b"]),
    ("explain",   [r"\bexplain\b", r"\bwhat is\b", r"\bhow does\b", r"\bhow do\b", r"\bwhat are\b", r"\bunderstand\b", r"\bdefinition\b"]),
    ("find",      [r"\bfind\b", r"\bwhere\b", r"\blook up\b", r"\bsearch for\b", r"\bshow me\b"]),
    ("learn",     [r"\blearn\b", r"\btutorial\b", r"\bguide\b", r"\bget started\b", r"\bbeginner", r"\bhow to\b"]),
]


def detect_query_intent(query: str) -> str:
    q = query.lower()
    for intent, patterns in _INTENT_PATTERNS:
        for pat in patterns:
            if re.search(pat, q):
                return intent
    return "general"


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r'\b[a-z0-9][a-z0-9+#.\-]*\b', text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) >= 2}


def compute_retrieval_confidence(source: dict, query_tokens: set[str]) -> float:
    """Multi-factor confidence: semantic (55%) + title (22%) + tags (15%) + summary (8%)."""
    semantic = min(source.get("_score", 0.0), 1.0)
    if not query_tokens:
        return semantic

    title_tokens   = _tokenize(source.get("title") or "")
    tag_tokens     = _tokenize(" ".join(source.get("tags") or []))
    summary_tokens = _tokenize(((source.get("summary") or "") + " " + (source.get("description") or ""))[:500])

    n = len(query_tokens)
    title_overlap   = len(query_tokens & title_tokens)   / n
    tag_overlap     = len(query_tokens & tag_tokens)     / n
    summary_overlap = len(query_tokens & summary_tokens) / n

    return min(
        semantic * 0.55 + title_overlap * 0.22 + tag_overlap * 0.15 + summary_overlap * 0.08,
        1.0,
    )


def build_honest_no_match_response(query: str, intent: str, weak_sources: list[dict] | None = None) -> dict:
    """Return an honest answer when library has no strong/moderate matches."""
    q = query.strip()
    messages = {
        "find":      f'I searched your library for "{q}" but didn\'t find any closely matching sources. Try importing relevant pages first.',
        "learn":     f'Your library doesn\'t have strong learning resources about "{q}" yet. Save some tutorials or guides on this topic, then ask again.',
        "explain":   f'I couldn\'t find detailed sources about "{q}" in your library. Once you save relevant content, I can explain concepts by synthesizing it.',
        "recommend": f'Your library doesn\'t have strong resources matching "{q}" yet. Save some relevant sources first, then I can make specific recommendations.',
    }
    answer = messages.get(intent, f'I searched your library but couldn\'t find sources that strongly match "{q}". Consider importing relevant content to get better answers.')

    recs = []
    if weak_sources:
        for s in weak_sources[:3]:
            recs.append({
                "id":       s["id"],
                "reason":   "Loosely related — add more specific sources for better answers",
                "relevance": "low",
            })

    return {
        "answer":             answer,
        "recommendations":    recs,
        "missing_topics":     [q],
        "method":             "honest-no-match",
        "query_intent":       intent,
        "confidence_summary": {"strong": 0, "moderate": 0, "weak": len(weak_sources or [])},
    }


# ── Ask NEXUS synthesis ──────────────────────────────────────────────────────

def _local_synthesize(query: str, sources: list[dict]) -> dict:
    """Rule-based synthesis — works offline, no API key needed."""
    def conf(s: dict) -> float:
        return s.get("_confidence", s.get("_score", 0))

    high = [s for s in sources if conf(s) >= 0.45]
    med  = [s for s in sources if 0.27 <= conf(s) < 0.45]

    lines = []
    if high:
        names = " and ".join(f'"{s["title"]}"' for s in high[:2])
        extra = f", plus {len(high) - 2} more" if len(high) > 2 else ""
        lines.append(f"Your library has strong matches: {names}{extra}.")
    elif med:
        names = " and ".join(f'"{s["title"]}"' for s in med[:2])
        lines.append(f"I found potentially related sources: {names}.")
    else:
        lines.append(f"I found {len(sources)} related source(s) in your library.")

    top = sources[0]
    excerpt = top.get("content_excerpt") or top.get("summary") or top.get("description") or ""
    if excerpt:
        short = excerpt[:260].rstrip()
        if len(excerpt) > 260:
            short += "…"
        lines.append(f'\nFrom "{top["title"]}": {short}')

    recommendations = []
    for s in sources[:6]:
        c      = conf(s)
        tags   = [t for t in (s.get("tags") or []) if t]
        topics = [t for t in (s.get("topics") or []) if t]
        cat    = s.get("category") or ""
        features = (tags + topics)[:3]
        if features:
            reason = f"Covers {', '.join(features)}"
        elif cat and cat not in ("Other", ""):
            reason = f"Saved as {cat}"
        else:
            reason = "Semantically related to your query"
        recommendations.append({
            "id":        s["id"],
            "reason":    reason,
            "relevance": "high" if c >= 0.45 else "medium" if c >= 0.27 else "low",
        })

    return {
        "answer":          " ".join(lines),
        "recommendations": recommendations,
        "missing_topics":  [],
        "method":          "local",
    }


async def _claude_synthesize(query: str, sources: list[dict]) -> dict:
    """Claude-powered synthesis — explains relevance in natural language."""
    source_lines = []
    for s in sources[:8]:
        excerpt = (s.get("content_excerpt") or s.get("summary") or s.get("description") or "")[:200]
        tags    = ", ".join((s.get("tags") or [])[:5])
        conf    = s.get("_confidence", s.get("_score", 0))
        tier    = "strong" if conf >= 0.45 else "moderate"
        source_lines.append(
            f'[{s["id"]}] "{s["title"]}" | {s.get("category", "")} | tags: {tags} | match: {tier} ({conf:.2f})\n'
            f'  excerpt: {excerpt}'
        )

    prompt = f"""You are NEXUS, a personal AI knowledge assistant. The user asked: "{query}"

THEIR SAVED LIBRARY ({len(sources)} sources):
{chr(10).join(source_lines)}

Write a helpful response. Return ONLY valid JSON — no markdown fences:
{{
  "answer": "2-3 sentences directly answering the question, naturally citing specific source titles",
  "recommendations": [
    {{"id": "exact_id_from_brackets", "reason": "one sentence: why this source helps with this specific query", "relevance": "high|medium|low"}}
  ],
  "missing_topics": ["0-2 topics the user might want to save more about — omit if well covered"]
}}"""

    message = await _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    text   = message.content[0].text if message.content else ""
    result = _parse_json(text)

    result.setdefault("answer", "")
    result.setdefault("recommendations", [])
    result.setdefault("missing_topics", [])

    valid_ids = {s["id"] for s in sources}
    result["recommendations"] = [
        r for r in result["recommendations"]
        if isinstance(r, dict)
        and r.get("id") in valid_ids
        and r.get("reason")
        and r.get("relevance") in ("high", "medium", "low")
    ]
    return result


async def synthesize_answer(query: str, sources: list[dict]) -> dict:
    """Orchestrator: confidence-scores sources, synthesizes only strong+moderate matches."""
    intent = detect_query_intent(query)

    if not sources:
        return build_honest_no_match_response(query, intent)

    # Score each source with multi-factor confidence
    query_tokens = _tokenize(query)
    for s in sources:
        s["_confidence"] = compute_retrieval_confidence(s, query_tokens)
    sources.sort(key=lambda s: s["_confidence"], reverse=True)

    strong   = [s for s in sources if s["_confidence"] >= 0.45]
    moderate = [s for s in sources if 0.27 <= s["_confidence"] < 0.45]
    weak     = [s for s in sources if s["_confidence"] < 0.27]
    quality  = strong + moderate

    confidence_summary = {"strong": len(strong), "moderate": len(moderate), "weak": len(weak)}
    logger.info(
        f"Confidence buckets for '{query[:50]}': "
        f"strong={len(strong)}, moderate={len(moderate)}, weak={len(weak)}, intent={intent}"
    )

    if not quality:
        result = build_honest_no_match_response(query, intent, weak_sources=weak)
        result["confidence_summary"] = confidence_summary
        return result

    try:
        result = await _claude_synthesize(query, quality)
        result["method"] = "ai"
        logger.info(f"Claude synthesis succeeded for: {query[:60]}")
    except Exception as e:
        logger.warning(f"Claude synthesis unavailable ({type(e).__name__}), using local fallback")
        result = _local_synthesize(query, quality)

    result["query_intent"]       = intent
    result["confidence_summary"] = confidence_summary
    return result


# ── Library Insights ─────────────────────────────────────────────────────────

async def generate_insights(sites: list[dict]) -> dict:
    """Generate AI-powered insights from the full library."""
    if len(sites) < 2:
        return {
            "headline": f"Library with {len(sites)} source(s). Add more to unlock AI insights.",
            "insights": ["Add more sources to unlock deeper AI insights."],
            "trends": [], "recommended_topics": [],
            "collection_suggestions": [], "learning_path": "",
        }

    categories: dict[str, int] = {}
    tags_count: dict[str, int] = {}
    for s in sites:
        cat = s.get("category") or "Other"
        categories[cat] = categories.get(cat, 0) + 1
        for tag in s.get("tags") or []:
            tags_count[tag] = tags_count.get(tag, 0) + 1

    top_tags = sorted(tags_count.items(), key=lambda x: x[1], reverse=True)
    cat_summary  = ", ".join(f"{k}: {v}" for k, v in sorted(categories.items(), key=lambda x: x[1], reverse=True))
    tag_summary  = ", ".join(f"{k}({v})" for k, v in top_tags[:15])
    titles_block = "\n".join(s.get("title", "") for s in sites[:30])

    prompt = f"""Analyze this personal knowledge library and generate actionable insights.

LIBRARY STATS:
- Total sources: {len(sites)}
- Categories: {cat_summary}
- Top tags: {tag_summary}
- Sample titles:
{titles_block}

Return ONLY valid JSON (no markdown):
{{
  "headline": "one compelling sentence revealing what this library says about the owner's focus areas",
  "insights": ["3-5 specific, non-obvious observations about this library"],
  "trends": ["2-3 learning patterns or emerging focus areas"],
  "recommended_topics": ["3-5 specific topics that would complement this library"],
  "collection_suggestions": [
    {{"name": "collection name", "description": "what it covers", "reasoning": "why group these"}}
  ],
  "learning_path": "a concrete suggested focus or sequence for getting value from these resources"
}}"""

    try:
        message = await _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text   = message.content[0].text if message.content else ""
        result = _parse_json(text)
        result.setdefault("headline", f"Library with {len(sites)} sources across {len(categories)} categories")
        for key in ("insights", "trends", "recommended_topics", "collection_suggestions"):
            if not isinstance(result.get(key), list):
                result[key] = []
        result.setdefault("learning_path", "")
        logger.info(f"generate_insights: OK ({len(sites)} sources)")
        return result
    except Exception as e:
        logger.error(f"generate_insights failed: {e}")
        best_cat = max(categories.items(), key=lambda x: x[1])[0] if categories else "Unknown"
        return {
            "headline": f"Library with {len(sites)} sources focused on {best_cat}",
            "insights": [
                f"You have {len(sites)} sources saved",
                f"Most active category: {best_cat}",
                f"Most common tag: {top_tags[0][0]}" if top_tags else "No tags yet",
            ],
            "trends": [], "recommended_topics": [],
            "collection_suggestions": [], "learning_path": "",
        }


async def auto_organize_clusters(sites: list[dict]) -> list[dict]:
    """Use AI to group sources into specific, meaningful themed collections."""
    cap = sites[:80]
    if len(cap) < 2:
        return []

    site_list = "\n".join(
        f"[{i}] {s['title']} | {s.get('category','')} | tags: {','.join((s.get('tags') or [])[:4])}"
        for i, s in enumerate(cap)
    )

    prompt = f"""Group these {len(cap)} saved sources into SPECIFIC, named collections.

SOURCES:
{site_list}

STRICT RULES:
1. Collection names MUST be specific — "ESP32 Robotics" not "Robotics"; "Python AI Tools" not "AI"
2. FORBIDDEN names: Tools, Websites, Resources, Links, Various, Other, Misc, General, Uncategorized
3. Each collection must have a clear reason to exist — could you explain in one sentence why these belong together?
4. Create 3-8 collections. Cover ≥ 70% of sources.
5. Each source belongs to at most one collection.
6. Merge very similar topics (e.g. "OpenAI" + "Anthropic" → "AI APIs")

GOOD examples: "React Frontend", "AI Agents & LLMs", "Resume & Job Tools", "Arduino & ESP32", "Academic Research", "Productivity Apps"

Return ONLY valid JSON:
{{
  "clusters": [
    {{
      "name": "Specific Collection Name",
      "description": "one sentence: what connects these sources",
      "insight": "These sources were grouped because [specific reason about content/theme]",
      "color": "#hex",
      "site_indices": [0, 1, 2]
    }}
  ]
}}

Colors: #8b5cf6 #6366f1 #3b82f6 #10b981 #f59e0b #ef4444 #ec4899 #14b8a6"""

    try:
        message = await _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text     = message.content[0].text if message.content else ""
        result   = _parse_json(text)
        clusters = result.get("clusters", [])

        _GENERIC = {"tools", "websites", "resources", "links", "various", "other", "misc",
                    "general", "uncategorized", "bookmarks", "saved", "collection"}

        resolved: list[dict] = []
        used_indices: set[int] = set()
        for cluster in clusters:
            name = cluster.get("name", "Untitled").strip()
            # Reject overly generic names
            if name.lower() in _GENERIC or len(name) < 3:
                logger.warning(f"auto_organize: rejected generic cluster name '{name}'")
                continue
            indices = [
                i for i in cluster.get("site_indices", [])
                if isinstance(i, int) and 0 <= i < len(cap) and i not in used_indices
            ]
            used_indices.update(indices)
            site_ids = [cap[i]["id"] for i in indices]
            if site_ids:
                resolved.append({
                    "name":        name,
                    "description": cluster.get("description", ""),
                    "insight":     cluster.get("insight", ""),
                    "color":       cluster.get("color", "#8b5cf6"),
                    "site_ids":    site_ids,
                })
        logger.info(f"auto_organize: {len(resolved)} clusters for {len(cap)} sources")
        return resolved
    except Exception as e:
        logger.error(f"auto_organize_clusters failed: {e}")
        return []


# ── Collection Assignment ──────────────────────────────────────────────────────

def _suggest_cluster_name_from_site(site_data: dict) -> str:
    """Derive a reasonable collection name from a site's metadata."""
    cat = site_data.get("category", "")
    if cat and cat not in ("Other", ""):
        return cat
    tags = [t for t in (site_data.get("tags") or []) if len(t) > 2]
    if tags:
        return tags[0].title()
    return "Saved Resources"


def _keyword_collection_match(
    site_data: dict,
    clusters: list[dict],
    cluster_source_tags: dict[str, list[str]],
) -> dict:
    """Pure-Python fallback when AI is unavailable."""
    def tokenize(text: str) -> set[str]:
        import re
        words = set(re.split(r'\W+', text.lower()))
        return {w for w in words if len(w) > 2}

    site_words = tokenize(" ".join([
        site_data.get("title", ""),
        site_data.get("category", ""),
        " ".join(site_data.get("tags", []) or []),
        " ".join(site_data.get("topics", []) or []),
        site_data.get("summary", "") or "",
    ]))

    best_id    = None
    best_score = 0.0
    best_name  = ""

    for cluster in clusters:
        c_words = tokenize(" ".join([
            cluster.get("name", ""),
            cluster.get("description", "") or "",
            " ".join(cluster_source_tags.get(cluster["id"], [])),
        ]))
        if not c_words:
            continue
        overlap = len(site_words & c_words)
        denom   = min(len(site_words), len(c_words))
        score   = overlap / denom if denom > 0 else 0.0
        if score > best_score:
            best_score = score
            best_id    = cluster["id"]
            best_name  = cluster.get("name", "")

    if best_id and best_score >= 0.15:
        return {
            "assigned_cluster_id": best_id,
            "confidence":          round(best_score, 3),
            "reason":              f"Keyword match with '{best_name}' collection",
            "suggest_new_cluster": False,
            "suggested_cluster_name": None,
        }
    return {
        "assigned_cluster_id": None,
        "confidence":          0.0,
        "reason":              "No matching collection found",
        "suggest_new_cluster": True,
        "suggested_cluster_name": _suggest_cluster_name_from_site(site_data),
    }


async def suggest_collection_assignment(
    site_data: dict,
    clusters: list[dict],
    cluster_source_tags: dict[str, list[str]],
) -> dict:
    """
    Assign a newly ingested source to the best matching collection.
    Uses AI with keyword fallback.

    Returns:
        assigned_cluster_id: str | None
        confidence: float
        reason: str
        suggest_new_cluster: bool
        suggested_cluster_name: str | None
    """
    if not clusters:
        return {
            "assigned_cluster_id": None,
            "confidence": 0.0,
            "reason": "No collections exist yet",
            "suggest_new_cluster": False,
            "suggested_cluster_name": None,
        }

    # Build a compact cluster list for the prompt (cap at 12 to keep prompt short)
    shown = clusters[:12]
    cluster_lines = "\n".join(
        f"[{i}] \"{c['name']}\" ({len(cluster_source_tags.get(c['id'], []))} tag types) | "
        f"tags: {', '.join(cluster_source_tags.get(c['id'], [])[:8])}"
        for i, c in enumerate(shown)
    )

    site_text = (
        f"Title: {site_data.get('title','')}\n"
        f"Category: {site_data.get('category','')}\n"
        f"Tags: {', '.join(site_data.get('tags',[]) or [])}\n"
        f"Summary: {(site_data.get('summary') or '')[:150]}"
    )

    prompt = f"""You are NEXUS. Assign this saved source to its best matching collection, or return null if nothing fits well.

SOURCE:
{site_text}

EXISTING COLLECTIONS:
{cluster_lines}

Return ONLY valid JSON — no markdown:
{{
  "cluster_index": 0,
  "confidence": 0.88,
  "reason": "one sentence explaining why this source belongs in that collection"
}}

Rules:
- Assign if confidence ≥ 0.65 (genuine topical fit)
- Return {{"cluster_index": null, "confidence": 0.0, "reason": "..."}} if nothing fits
- NEVER assign to a collection just because it's the closest — require real relevance"""

    try:
        message = await _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text   = message.content[0].text if message.content else ""
        result = _parse_json(text)

        idx        = result.get("cluster_index")
        confidence = float(result.get("confidence", 0))
        reason     = result.get("reason", "")

        if idx is not None and isinstance(idx, int) and 0 <= idx < len(shown) and confidence >= 0.60:
            return {
                "assigned_cluster_id": shown[idx]["id"],
                "confidence":          round(confidence, 3),
                "reason":              reason,
                "suggest_new_cluster": False,
                "suggested_cluster_name": None,
            }

        return {
            "assigned_cluster_id": None,
            "confidence":          0.0,
            "reason":              reason or "No collection is a good fit",
            "suggest_new_cluster": False,
            "suggested_cluster_name": None,
        }

    except Exception as e:
        logger.warning(f"suggest_collection_assignment AI failed ({e}), using keyword fallback")
        return _keyword_collection_match(site_data, clusters, cluster_source_tags)


# ── Discover Suggestions ──────────────────────────────────────────────────────

def _local_discover(sites: list[dict]) -> dict:
    """Rule-based discover fallback when AI unavailable."""
    tags_count: dict[str, int] = {}
    categories: dict[str, int] = {}
    for s in sites:
        cat = s.get("category") or "Other"
        categories[cat] = categories.get(cat, 0) + 1
        for tag in (s.get("tags") or []):
            tags_count[tag] = tags_count.get(tag, 0) + 1

    top_interests = [t for t, _ in sorted(tags_count.items(), key=lambda x: x[1], reverse=True)[:6]]
    top_cat = max(categories.items(), key=lambda x: x[1])[0] if categories else "Development"

    suggestions = [
        {
            "topic": f"Advanced {top_cat} patterns",
            "description": f"Explore deeper {top_cat} techniques beyond the basics.",
            "reason": f"You have the most sources in {top_cat}.",
            "category": top_cat,
            "search_query": f"What {top_cat} resources do I have?",
        },
        {
            "topic": "Productivity systems",
            "description": "Systems for organizing research and making ideas actionable.",
            "reason": "Complements any technical knowledge base.",
            "category": "Productivity",
            "search_query": "What productivity tools have I saved?",
        },
    ]
    return {
        "interest_summary": f"Your library focuses on {top_cat} with {len(sites)} saved sources.",
        "top_interests": top_interests,
        "suggestions": suggestions,
        "knowledge_gaps": [
            {"area": "Documentation & note-taking", "reason": "Helps consolidate what you've researched."}
        ],
        "trending_in_your_space": top_interests[:3],
    }


async def generate_discover_suggestions(sites: list[dict]) -> dict:
    """Generate personalized discovery recommendations from library profile."""
    if len(sites) < 2:
        return {
            "interest_summary": "Add more sources to unlock personalized discovery.",
            "top_interests": [],
            "suggestions": [],
            "knowledge_gaps": [],
            "trending_in_your_space": [],
        }

    tags_count: dict[str, int] = {}
    categories: dict[str, int] = {}
    for s in sites:
        cat = s.get("category") or "Other"
        categories[cat] = categories.get(cat, 0) + 1
        for tag in (s.get("tags") or []):
            tags_count[tag] = tags_count.get(tag, 0) + 1

    top_tags  = sorted(tags_count.items(), key=lambda x: x[1], reverse=True)[:14]
    top_cats  = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
    titles    = [s.get("title", "") for s in sites[:25]]

    prompt = f"""You are the NEXUS discovery engine. Analyze this person's knowledge library and suggest what they should explore next.

LIBRARY PROFILE:
- Total sources: {len(sites)}
- Top categories: {', '.join(f'{k}({v})' for k, v in top_cats)}
- Top interests (by tag frequency): {', '.join(f'{k}({v})' for k, v in top_tags)}
- Sample titles: {', '.join(titles[:15])}

Return ONLY valid JSON — no markdown:
{{
  "interest_summary": "one revealing sentence: what this library says about the person's focus",
  "top_interests": ["interest 1", "interest 2", "interest 3", "interest 4", "interest 5"],
  "suggestions": [
    {{
      "topic": "specific tool/topic name (e.g. 'Transformer fine-tuning with LoRA', not 'AI')",
      "description": "2 sentences: what it is and why it fits this person's interests",
      "reason": "one sentence: which saved topics/categories led to this recommendation",
      "category": "category name from their library",
      "search_query": "a short Ask NEXUS query to find related saved content"
    }}
  ],
  "knowledge_gaps": [
    {{
      "area": "area name",
      "reason": "why this would complement their existing knowledge"
    }}
  ],
  "trending_in_your_space": ["topic 1", "topic 2", "topic 3", "topic 4"]
}}

Rules:
- Generate 6-8 suggestions, each SPECIFIC (not generic)
- knowledge_gaps: 3-4 complementary areas they haven't saved much about
- trending_in_your_space: hot topics adjacent to their interests
- Make every suggestion feel personally relevant, not random"""

    try:
        message = await _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        text   = message.content[0].text if message.content else ""
        result = _parse_json(text)
        result.setdefault("interest_summary", "")
        result.setdefault("top_interests", [])
        result.setdefault("suggestions", [])
        result.setdefault("knowledge_gaps", [])
        result.setdefault("trending_in_your_space", [])
        logger.info(f"generate_discover_suggestions: {len(result['suggestions'])} suggestions")
        return result
    except Exception as e:
        logger.warning(f"generate_discover_suggestions failed ({e}), using local fallback")
        return _local_discover(sites)


# ── Source Comparison ─────────────────────────────────────────────────────────

import re as _re

def _detect_comparison_subjects(query: str) -> tuple[str, str] | None:
    """Extract two comparison subjects from a natural-language query."""
    q = query.strip()
    patterns = [
        r"compare\s+(.+?)\s+(?:vs\.?|versus|and|with)\s+(.+?)(?:\?|$)",
        r"(.+?)\s+vs\.?\s+(.+?)(?:\?|$)",
        r"(.+?)\s+versus\s+(.+?)(?:\?|$)",
        r"(?:which is better|difference between|compare)\s+(.+?)\s+(?:or|and)\s+(.+?)(?:\?|$)",
    ]
    for pat in patterns:
        m = _re.search(pat, q, _re.IGNORECASE)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            if a and b and a.lower() != b.lower():
                return (a, b)
    return None


async def compare_sources_ai(query: str, sources_a: list[dict], sources_b: list[dict]) -> dict:
    """Generate a detailed comparison between two subjects using Claude."""
    subject_a = _detect_comparison_subjects(query)
    name_a = subject_a[0] if subject_a else "Subject A"
    name_b = subject_a[1] if subject_a else "Subject B"

    def fmt_sources(sources: list[dict], name: str) -> str:
        if not sources:
            return f"(No saved sources for '{name}' — using general knowledge)"
        return "\n".join(
            f'  - "{s["title"]}": {(s.get("summary") or s.get("description") or "")[:200]}'
            for s in sources[:3]
        )

    prompt = f"""You are NEXUS. Compare these two subjects based on the user's library and your knowledge.

USER QUERY: "{query}"

SUBJECT A — {name_a}:
{fmt_sources(sources_a, name_a)}

SUBJECT B — {name_b}:
{fmt_sources(sources_b, name_b)}

Return ONLY valid JSON:
{{
  "subject_a": {{
    "name": "{name_a}",
    "tagline": "what it is in 5-8 words",
    "strengths": ["strength 1", "strength 2", "strength 3"],
    "weaknesses": ["weakness 1", "weakness 2"],
    "best_for": "who should use this"
  }},
  "subject_b": {{
    "name": "{name_b}",
    "tagline": "what it is in 5-8 words",
    "strengths": ["strength 1", "strength 2", "strength 3"],
    "weaknesses": ["weakness 1", "weakness 2"],
    "best_for": "who should use this"
  }},
  "summary": "2-3 sentences comparing both at a high level",
  "verdict": "one clear recommendation: which is better in most cases and why",
  "when_to_choose_a": "specific scenario where A wins",
  "when_to_choose_b": "specific scenario where B wins"
}}"""

    try:
        message = await _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text   = message.content[0].text if message.content else ""
        result = _parse_json(text)
        for key in ("subject_a", "subject_b", "summary", "verdict", "when_to_choose_a", "when_to_choose_b"):
            result.setdefault(key, None if key in ("subject_a", "subject_b") else "")
        return result
    except Exception as e:
        logger.error(f"compare_sources_ai failed: {e}")
        return {
            "subject_a": {"name": name_a, "tagline": "", "strengths": [], "weaknesses": [], "best_for": ""},
            "subject_b": {"name": name_b, "tagline": "", "strengths": [], "weaknesses": [], "best_for": ""},
            "summary": f"Comparing {name_a} and {name_b} based on your saved library.",
            "verdict": "Could not generate comparison — AI unavailable.",
            "when_to_choose_a": "",
            "when_to_choose_b": "",
        }
