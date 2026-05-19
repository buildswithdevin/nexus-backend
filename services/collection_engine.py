"""
Local rule-based collection engine.

Scores sources against predefined collection definitions using title, tags,
category, domain, description, and content. No AI or API keys required.
"""
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Collection definitions ────────────────────────────────────────────────────

COLLECTION_DEFINITIONS: dict[str, dict] = {
    "AI Tools": {
        "color":       "#8b5cf6",
        "description": "AI assistants, LLMs, machine learning tools, and automation platforms",
        "keywords": [
            "artificial intelligence", "large language model", "generative ai",
            "machine learning", "deep learning", "neural network", "transformer",
            "fine-tuning", "stable diffusion", "computer vision",
            "llm", "gpt", "chatgpt", "gemini", "claude", "anthropic", "openai",
            "copilot", "midjourney", "whisper", "mistral", "ollama", "langchain",
            "llamaindex", "notebooklm", "huggingface", "replicate", "perplexity",
            "agent", "rag", "nlp", "inference", "embedding", "vector database",
            "ai model", "generative", "cursor ai", "cohere", "groq",
        ],
        "domain_hints":    ["openai.com", "anthropic.com", "huggingface.co", "cohere.com",
                            "mistral.ai", "groq.com", "together.ai", "replicate.com",
                            "perplexity.ai", "notebooklm.google", "cursor.sh"],
        "category_hints":  ["AI & ML"],
    },

    "Robotics & Hardware": {
        "color":       "#10b981",
        "description": "Robotics systems, embedded hardware, microcontrollers, and firmware resources",
        "keywords": [
            "robotics", "robot", "autonomous", "servo", "motor driver", "manipulator",
            "esp32", "arduino", "raspberry pi", "jetson", "microcontroller", "firmware",
            "embedded", "fpga", "pcb", "electronics", "circuit", "wiring",
            "sensor", "actuator", "ros", "drone", "tinkercad", "soldering",
            "oscilloscope", "breadboard", "gpio", "i2c", "spi", "uart",
        ],
        "domain_hints":    ["arduino.cc", "raspberrypi.org", "espressif.com", "ros.org",
                            "adafruit.com", "sparkfun.com"],
        "category_hints":  ["Embedded Systems", "Robotics", "Hardware"],
    },

    "Frontend Development": {
        "color":       "#3b82f6",
        "description": "Web frontend frameworks, UI libraries, CSS tools, and browser technologies",
        "keywords": [
            "react", "vue", "angular", "svelte", "nextjs", "gatsby", "remix",
            "tailwind", "css", "scss", "sass", "styled-components",
            "frontend", "component", "ui library", "web design",
            "html", "dom", "browser", "typescript", "javascript",
            "vite", "webpack", "shadcn", "radix", "framer motion",
            "responsive design", "accessibility", "web app",
        ],
        "domain_hints":    ["react.dev", "vuejs.org", "nextjs.org", "tailwindcss.com",
                            "developer.mozilla.org", "svelte.dev", "angular.io"],
        "category_hints":  ["Design"],
    },

    "Backend Development": {
        "color":       "#6366f1",
        "description": "Server-side frameworks, APIs, databases, and backend infrastructure",
        "keywords": [
            "fastapi", "django", "flask", "express", "spring boot", "laravel", "rails",
            "backend", "server", "rest api", "graphql", "grpc", "microservice",
            "postgresql", "mysql", "sqlite", "mongodb", "redis", "orm",
            "authentication", "jwt", "oauth", "websocket",
            "nodejs", "golang", "rust", "java", "php",
        ],
        "domain_hints":    ["fastapi.tiangolo.com", "django-rest-framework.org", "expressjs.com"],
        "category_hints":  [],
    },

    "Resume & Career": {
        "color":       "#f59e0b",
        "description": "Job hunting, resume building, career development, and interview preparation",
        "keywords": [
            "resume", "curriculum vitae", "portfolio", "job search", "interview",
            "career", "hiring", "recruiter", "salary", "employment",
            "cover letter", "internship", "networking", "work experience",
            "technical interview", "leetcode", "system design interview",
        ],
        "domain_hints":    ["linkedin.com", "indeed.com", "glassdoor.com", "levels.fyi",
                            "resume.io", "leetcode.com"],
        "category_hints":  [],
    },

    "Learning Resources": {
        "color":       "#14b8a6",
        "description": "Tutorials, courses, documentation, and educational content",
        "keywords": [
            "tutorial", "course", "documentation", "guide", "education", "learn",
            "lecture", "lesson", "bootcamp", "certification", "roadmap",
            "cheatsheet", "getting started", "introduction to", "beginner",
            "freecodecamp", "coursera", "udemy", "edx", "khan academy",
        ],
        "domain_hints":    ["coursera.org", "udemy.com", "edx.org", "khanacademy.org",
                            "freecodecamp.org", "pluralsight.com", "codecademy.com"],
        "category_hints":  ["Research"],
    },

    "Productivity": {
        "color":       "#ec4899",
        "description": "Productivity apps, note-taking tools, workflow automation, and personal organization",
        "keywords": [
            "productivity", "workflow", "automation", "task management", "todo",
            "notes", "note-taking", "knowledge base", "second brain",
            "notion", "obsidian", "roam", "logseq", "airtable", "trello",
            "zapier", "make.com", "calendar", "time tracking", "project management",
        ],
        "domain_hints":    ["notion.so", "obsidian.md", "roamresearch.com", "logseq.com",
                            "todoist.com", "trello.com", "airtable.com"],
        "category_hints":  ["Productivity"],
    },

    "Creative & Media Tools": {
        "color":       "#ef4444",
        "description": "Image editors, video tools, audio processing, and creative design software",
        "keywords": [
            "image editor", "video editor", "audio editor", "photo editing",
            "illustration", "animation", "3d modeling", "blender", "figma",
            "canva", "adobe", "photoshop", "illustrator", "premiere", "davinci",
            "color grading", "podcast", "music production", "sound design",
            "creative suite", "media converter", "screen recording",
        ],
        "domain_hints":    ["figma.com", "canva.com", "adobe.com", "blender.org",
                            "dribbble.com", "behance.net"],
        "category_hints":  ["Design"],
    },

    "Research Papers": {
        "color":       "#a78bfa",
        "description": "Academic papers, research studies, and scientific literature",
        "keywords": [
            "research paper", "arxiv", "academic paper", "journal article",
            "conference paper", "preprint", "citation", "abstract", "methodology",
            "benchmark", "dataset", "experiment", "survey paper",
            "peer-reviewed", "scholarly", "ieee", "acm", "nature", "science",
        ],
        "domain_hints":    ["arxiv.org", "scholar.google.com", "semanticscholar.org",
                            "researchgate.net", "pubmed.ncbi", "ieeexplore.ieee.org"],
        "category_hints":  ["Research"],
    },

    "Developer Tools": {
        "color":       "#818cf8",
        "description": "CLI tools, IDEs, debugging utilities, and developer productivity software",
        "keywords": [
            "github", "gitlab", "version control", "git", "vscode", "neovim", "vim",
            "cli tool", "shell script", "devtools", "debugging", "profiling",
            "linting", "testing", "unit test", "ci cd", "github actions",
            "docker", "kubernetes", "helm", "terraform", "monitoring",
            "logging", "deployment", "devops", "infrastructure",
        ],
        "domain_hints":    ["github.com", "gitlab.com", "code.visualstudio.com",
                            "docker.com", "kubernetes.io"],
        "category_hints":  ["Cloud & DevOps"],
    },

    "Data Science": {
        "color":       "#60a5fa",
        "description": "Data analysis, ML experiments, visualization, and data engineering",
        "keywords": [
            "data science", "data analysis", "data engineering", "data pipeline",
            "pandas", "numpy", "matplotlib", "seaborn", "jupyter notebook",
            "kaggle", "spark", "tableau", "power bi", "statistics",
            "regression", "classification", "clustering", "feature engineering",
            "etl", "sql analytics", "business intelligence",
        ],
        "domain_hints":    ["kaggle.com", "jupyter.org", "pandas.pydata.org", "plotly.com"],
        "category_hints":  ["Data Science"],
    },

    "Security": {
        "color":       "#f87171",
        "description": "Cybersecurity, ethical hacking, vulnerability research, and security tools",
        "keywords": [
            "cybersecurity", "ethical hacking", "penetration testing", "pentest",
            "vulnerability", "exploit", "ctf", "capture the flag",
            "encryption", "cryptography", "malware analysis", "reverse engineering",
            "osint", "network security", "web security", "owasp",
            "firewall", "intrusion detection", "threat intelligence",
        ],
        "domain_hints":    ["owasp.org", "exploit-db.com", "hackthebox.com",
                            "tryhackme.com", "shodan.io"],
        "category_hints":  ["Cybersecurity"],
    },

    "Writing Tools": {
        "color":       "#fbbf24",
        "description": "Writing assistants, grammar tools, content creation, and publishing platforms",
        "keywords": [
            "writing assistant", "grammar checker", "proofreading", "copywriting",
            "content writing", "technical writing", "blog", "newsletter",
            "substack", "medium", "ghost", "markdown editor",
            "documentation writing", "grammarly", "hemingway",
        ],
        "domain_hints":    ["substack.com", "medium.com", "ghost.org",
                            "grammarly.com", "hemingwayapp.com"],
        "category_hints":  [],
    },

    "Business Tools": {
        "color":       "#34d399",
        "description": "Business software, SaaS analytics, CRM, and professional services",
        "keywords": [
            "business", "startup", "saas", "crm", "analytics", "marketing",
            "seo", "growth hacking", "sales", "customer success",
            "revenue", "pricing", "b2b", "enterprise software",
            "hubspot", "salesforce", "stripe", "shopify", "ecommerce",
        ],
        "domain_hints":    ["hubspot.com", "salesforce.com", "stripe.com", "shopify.com"],
        "category_hints":  [],
    },

    "System & Utilities": {
        "color":       "#2dd4bf",
        "description": "System utilities, OS tools, file management, and technical infrastructure",
        "keywords": [
            "linux", "ubuntu", "debian", "fedora", "arch linux", "windows",
            "system utility", "file manager", "bash scripting", "shell scripting",
            "cron job", "daemon", "kernel", "network config", "dns",
            "vpn", "server config", "sysadmin", "package manager",
        ],
        "domain_hints":    ["ubuntu.com", "debian.org", "archlinux.org", "man7.org"],
        "category_hints":  [],
    },
}

# Pre-compiled regex patterns per collection (built lazily, reused)
_COMPILED: dict[str, list[tuple[str, re.Pattern]]] = {}

# Score weights
_W_TITLE    = 5
_W_TAG      = 4
_W_CATEGORY = 4
_W_DOMAIN   = 3
_W_DESC     = 2
_W_CONTENT  = 1

# Assignment thresholds
THRESHOLD_PRIMARY   = 7   # min score to become primary collection
THRESHOLD_SECONDARY = 5   # min score for a secondary collection assignment


def _patterns(coll_name: str) -> list[tuple[str, re.Pattern]]:
    """Return (keyword, compiled_regex) pairs for a collection, building once."""
    if coll_name not in _COMPILED:
        keywords = COLLECTION_DEFINITIONS[coll_name]["keywords"]
        _COMPILED[coll_name] = [
            (kw, re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE))
            for kw in sorted(keywords, key=len, reverse=True)
        ]
    return _COMPILED[coll_name]


def score_source_for_collection(source: dict, coll_name: str) -> tuple[int, list[str]]:
    """
    Score a source dict against a named collection.
    Returns (score, reasons) where reasons are human-readable match explanations.
    """
    coll_def     = COLLECTION_DEFINITIONS[coll_name]
    kw_patterns  = _patterns(coll_name)
    domain_hints = coll_def.get("domain_hints", [])
    cat_hints    = [c.lower() for c in coll_def.get("category_hints", [])]

    title   = source.get("title") or ""
    url     = source.get("url") or ""
    domain  = urlparse(url).netloc.lower().replace("www.", "")
    desc    = (source.get("description") or "") + " " + (source.get("summary") or "")
    tags    = [t.lower() for t in (source.get("tags") or [])]
    cat     = (source.get("category") or "").lower()
    content = ((source.get("content_excerpt") or "") + " " + (source.get("notes") or ""))[:600]

    score   = 0
    reasons: list[str] = []

    # ── Title matches (+5 each, cap 15) ──────────────────────────────────────
    title_hits = [kw for kw, pat in kw_patterns if pat.search(title)]
    if title_hits:
        pts = min(len(title_hits) * _W_TITLE, 15)
        score += pts
        reasons.append(f"title: {', '.join(title_hits[:3])}")

    # ── Tag matches (+4 each, cap 16) ────────────────────────────────────────
    tag_hits: list[str] = []
    for kw, pat in kw_patterns:
        if any(pat.search(tag) for tag in tags):
            tag_hits.append(kw)
    if tag_hits:
        pts = min(len(tag_hits) * _W_TAG, 16)
        score += pts
        reasons.append(f"tags: {', '.join(tag_hits[:3])}")

    # ── Category match (+4) ──────────────────────────────────────────────────
    if any(hint in cat for hint in cat_hints):
        score += _W_CATEGORY
        reasons.append(f"category: {source.get('category', '')}")

    # ── Domain match (+3, exact known domain gives +6) ──────────────────────
    domain_hit = next((d for d in domain_hints if d in domain), None)
    if domain_hit:
        pts = 6 if domain.rstrip("/") == domain_hit.replace("www.", "") else _W_DOMAIN
        score += pts
        reasons.append(f"domain: {domain_hit}")

    # ── Description / summary (+2 each, cap 8) ───────────────────────────────
    desc_hits = [kw for kw, pat in kw_patterns if pat.search(desc)]
    if desc_hits:
        pts = min(len(desc_hits) * _W_DESC, 8)
        score += pts
        reasons.append(f"description: {', '.join(desc_hits[:2])}")

    # ── Content / URL (+1 each, cap 4) ───────────────────────────────────────
    content_hits = [kw for kw, pat in kw_patterns if pat.search(content) or pat.search(url)]
    if content_hits:
        score += min(len(content_hits), 4)

    return score, reasons


def auto_organize_library(sources: list[dict]) -> list[dict]:
    """
    Assign all sources to collections using local rules.
    Returns a list of cluster dicts ready to be written to the DB.
    Each dict: {name, description, color, site_ids, insight, learning_path}.
    """
    if not sources:
        return []

    # Score every source against every collection
    bucket: dict[str, list[dict]] = {name: [] for name in COLLECTION_DEFINITIONS}
    unsorted_ids: list[str] = []

    for source in sources:
        scored: list[tuple[str, int, list[str]]] = []
        for coll_name in COLLECTION_DEFINITIONS:
            s, reasons = score_source_for_collection(source, coll_name)
            if s >= THRESHOLD_PRIMARY:
                scored.append((coll_name, s, reasons))

        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            unsorted_ids.append(source["id"])
            continue

        primary_name, primary_score, primary_reasons = scored[0]
        bucket[primary_name].append({
            "id":      source["id"],
            "score":   primary_score,
            "reasons": primary_reasons,
            "primary": True,
        })

        # Allow one secondary assignment if score is within 60% of primary and above threshold
        for sec_name, sec_score, sec_reasons in scored[1:2]:
            if sec_score >= THRESHOLD_SECONDARY and sec_score >= primary_score * 0.60:
                bucket[sec_name].append({
                    "id":      source["id"],
                    "score":   sec_score,
                    "reasons": sec_reasons,
                    "primary": False,
                })

    # Build result collections (only non-empty ones)
    result: list[dict] = []
    for coll_name, coll_def in COLLECTION_DEFINITIONS.items():
        members = bucket[coll_name]
        if not members:
            continue

        insight = _build_insight(coll_name, members)
        result.append({
            "name":        coll_name,
            "description": coll_def["description"],
            "color":       coll_def["color"],
            "site_ids":    [m["id"] for m in members],
            "insight":     insight,
            "learning_path": "",
        })

    if unsorted_ids:
        result.append({
            "name":        "Unsorted",
            "description": "Sources that don't strongly match any collection yet",
            "color":       "#6b7280",
            "site_ids":    unsorted_ids,
            "insight":     "These sources didn't match any predefined category. Try adding more descriptive tags or manually move them to an appropriate collection.",
            "learning_path": "",
        })

    logger.info(
        f"auto_organize_library: {len(sources)} sources → "
        f"{len(result)} collections ({len(unsorted_ids)} unsorted)"
    )
    return result


def assign_source_locally(source: dict, existing_collections: list[dict]) -> dict | None:
    """
    Score a single source against the names of existing collections.

    existing_collections: list of {id, name, description, color, ...}
    Returns: {cluster_id, cluster_name, cluster_color, confidence, reason} or None
    """
    if not existing_collections:
        return None

    best_score   = 0
    best_cluster: dict | None = None
    best_reasons: list[str]   = []

    for cluster in existing_collections:
        coll_name = cluster.get("name", "")

        if coll_name in COLLECTION_DEFINITIONS:
            s, reasons = score_source_for_collection(source, coll_name)
        else:
            # User-created collection not in our definitions — fall back to name overlap
            s, reasons = _score_against_custom_collection(source, cluster)

        if s > best_score:
            best_score   = s
            best_cluster = cluster
            best_reasons = reasons

    if not best_cluster or best_score < THRESHOLD_PRIMARY:
        return None

    confidence = min(best_score / 20.0, 1.0)
    reason_str = "; ".join(best_reasons[:2]) if best_reasons else "keyword match"

    return {
        "cluster_id":    best_cluster["id"],
        "cluster_name":  best_cluster["name"],
        "cluster_color": best_cluster.get("color", "#8b5cf6"),
        "confidence":    round(confidence, 3),
        "reason":        f"Matched on {reason_str}",
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_insight(coll_name: str, members: list[dict]) -> str:
    """Summarise why these sources were grouped here."""
    kw_freq: dict[str, int] = {}
    for m in members:
        for reason in m["reasons"]:
            for kw in reason.split(": ", 1)[-1].split(", "):
                kw = kw.strip()
                if kw:
                    kw_freq[kw] = kw_freq.get(kw, 0) + 1

    top = [kw for kw, _ in sorted(kw_freq.items(), key=lambda x: x[1], reverse=True)[:5]]
    if top:
        return f"Grouped because these sources strongly relate to {', '.join(top)}."
    return f"Sources grouped under {coll_name} by category and domain signals."


def _score_against_custom_collection(source: dict, cluster: dict) -> tuple[int, list[str]]:
    """Tokenise collection name/description and overlap with source text."""
    coll_text = f"{cluster.get('name', '')} {cluster.get('description', '')}".lower()
    coll_tokens = {w for w in re.split(r'\W+', coll_text) if len(w) > 2}
    if not coll_tokens:
        return 0, []

    source_text = " ".join([
        source.get("title", ""),
        source.get("category", ""),
        " ".join(source.get("tags", []) or []),
        source.get("summary", "") or "",
    ]).lower()
    source_tokens = {w for w in re.split(r'\W+', source_text) if len(w) > 2}

    overlap = len(coll_tokens & source_tokens)
    denom   = min(len(coll_tokens), len(source_tokens))
    ratio   = overlap / denom if denom else 0.0
    score   = int(ratio * 20)
    reasons = [f"name overlap: {', '.join(list(coll_tokens & source_tokens)[:3])}"] if overlap else []
    return score, reasons
