import json
import logging
import re
from typing import Optional

import anthropic
from config import settings

logger = logging.getLogger(__name__)

# Rich taxonomy used as AI hints — organized by domain
CATEGORY_TAXONOMY: dict[str, list[str]] = {
    "Technology": [
        "Programming", "Web Development", "Machine Learning", "Deep Learning",
        "Natural Language Processing", "Computer Vision", "Data Science",
        "Cybersecurity", "DevOps & Cloud", "Cloud Computing", "Networking",
        "Linux & System Administration", "Embedded Systems", "IoT",
        "Robotics", "Hardware & Electronics", "Game Development",
        "Computer Graphics", "Distributed Systems", "Algorithms & Data Structures",
        "Databases", "Reverse Engineering", "Homelabs & Self-Hosting",
        "Mobile Development", "API Development", "Compilers & Languages",
        "Computer Architecture", "Operating Systems", "System Design",
    ],
    "Science": [
        "Physics", "Chemistry", "Biology", "Neuroscience",
        "Astronomy & Space", "Genetics & Genomics", "Environmental Science",
        "Earth Science", "Microbiology", "Ecology", "Scientific Research",
        "Immunology", "Botany & Zoology",
    ],
    "Mathematics": [
        "Calculus & Analysis", "Linear Algebra", "Statistics & Probability",
        "Discrete Mathematics", "Number Theory", "Applied Mathematics",
        "Mathematical Logic", "Mathematical Modeling",
    ],
    "Engineering": [
        "Mechanical Engineering", "Electrical Engineering", "Civil Engineering",
        "Aerospace Engineering", "Chemical Engineering", "Biomedical Engineering",
        "Materials Science", "Manufacturing & CAD", "Renewable Energy",
        "Electronics & Circuits", "Industrial Engineering",
    ],
    "Medicine & Health": [
        "Medicine & Healthcare", "Mental Health & Psychology",
        "Nutrition & Dietetics", "Fitness & Exercise Science",
        "Pharmacology", "Public Health & Epidemiology",
        "Medical Research", "Anatomy & Physiology",
        "Preventive Health", "Sleep & Recovery", "Nursing",
        "Physical Therapy", "Emergency Medicine",
    ],
    "Business & Finance": [
        "Startups & Entrepreneurship", "Marketing & Growth",
        "Finance & Investing", "Cryptocurrency & Web3",
        "Economics & Macroeconomics", "eCommerce & SaaS",
        "Management & Leadership", "Productivity & Systems",
        "Personal Finance", "Real Estate", "Sales",
        "Trading & Markets", "Taxes", "Business Strategy",
    ],
    "Social Sciences": [
        "Sociology & Anthropology", "Political Science",
        "International Relations", "Law & Legal Studies",
        "Urban Studies & Geography", "Communication Studies",
        "Criminology", "Psychology",
    ],
    "Humanities": [
        "History", "Philosophy & Ethics", "Religion & Theology",
        "Literature & Writing", "Linguistics", "Cultural Studies",
        "Classics", "Government",
    ],
    "Arts & Creative": [
        "Design & UX/UI", "Graphic Design", "Visual Art & Illustration",
        "Photography", "Film & Video Production", "Music & Audio",
        "Architecture", "Fashion & Style", "Creative Writing",
        "Content Creation", "Poetry", "Sculpture",
    ],
    "Education": [
        "Learning Resources & Courses", "Research Papers & Journals",
        "Tutorials & How-Tos", "Study Materials",
        "Certifications & Exams", "Documentation",
        "Flashcards & Notes", "Academic Journals",
    ],
    "Trades & Practical Skills": [
        "Automotive & Mechanics", "Construction & Carpentry",
        "Electrical Work & HVAC", "Welding & Fabrication",
        "Home Improvement & DIY", "Plumbing", "Appliance Repair",
    ],
    "Entertainment & Media": [
        "Gaming", "Movies & Film", "TV & Streaming",
        "Anime & Manga", "Books & Comics", "Podcasts",
        "Sports & Esports", "Board Games & TCGs", "Music & Concerts",
    ],
    "Lifestyle": [
        "Cooking & Food", "Travel & Adventure",
        "Fitness & Wellness", "Outdoor & Hiking",
        "Pets & Animals", "Home & Living",
        "Personal Growth & Mindset", "Coffee & Tea",
        "Gardening & Plants", "Fashion & Lifestyle",
        "Watches & Luxury", "Survival & Prepping",
        "Martial Arts & Combat Sports",
    ],
    "General": [
        "News & Media", "Tools & Apps",
        "Ideas & Inspiration", "Projects & Planning",
        "Shopping & Product Research", "Read Later",
    ],
}

# Flat list of all categories (for local fallback and AI validation)
CATEGORIES: list[str] = [cat for cats in CATEGORY_TAXONOMY.values() for cat in cats]
CATEGORIES.append("Other")

# Keywords that indicate a category is technical — used for tag sanitization
_TECH_DOMAIN_KEYWORDS = frozenset({
    "programming", "web development", "machine learning", "deep learning",
    "natural language", "computer vision", "data science",
    "cybersecurity", "devops", "cloud computing", "networking",
    "linux", "system admin", "embedded systems", "iot", "robotics",
    "hardware", "game development", "computer graphics", "distributed systems",
    "algorithms", "databases", "reverse engineering", "homelabs",
    "mobile development", "api development", "compilers", "computer architecture",
    "operating systems", "system design", "artificial intelligence",
    # Old category names for backward compat
    "development", "ai & ml", "cloud & devops", "design",
})

def _is_tech_category(category: str) -> bool:
    """Return True if a category string is technology-related."""
    cat = category.lower()
    return any(kw in cat for kw in _TECH_DOMAIN_KEYWORDS)


# Tags that are only plausible if the content is genuinely technical
_TECH_ONLY_TAGS = frozenset({
    "ai", "llm", "machine-learning", "deep-learning", "neural-network",
    "python", "javascript", "typescript", "react", "nodejs", "api",
    "docker", "kubernetes", "devops", "cloud", "aws", "azure",
    "robotics", "embedded", "firmware", "arduino", "esp32",
    "security", "cybersecurity", "hacking", "pentest",
    "database", "sql", "backend", "frontend", "developer-tools",
})

# ── Tag normalization ──────────────────────────────────────────────────────────

_TAG_ALIASES: dict[str, str] = {
    # AI / ML variants
    "a.i.": "ai", "a.i": "ai", "artificial intelligence": "ai",
    "artificial-intelligence": "ai",
    "llm": "llm", "large language model": "llm", "large-language-model": "llm",
    "ml": "machine-learning", "machine learning": "machine-learning",
    "deep learning": "deep-learning", "dl": "deep-learning",
    "neural network": "neural-networks", "neural networks": "neural-networks",
    "nlp": "nlp", "natural language processing": "nlp",
    "generative ai": "generative-ai", "gen ai": "generative-ai",
    # Programming languages
    "js": "javascript", "javascript": "javascript",
    "ts": "typescript",
    "py": "python", "python3": "python",
    "react.js": "react", "reactjs": "react",
    "node.js": "nodejs", "node": "nodejs",
    "next.js": "nextjs",
    "vue.js": "vue", "vuejs": "vue",
    "c++": "cpp", "c plus plus": "cpp",
    "golang": "go", "go lang": "go",
    "rust lang": "rust",
    # Dev concepts
    "rest api": "api", "rest-api": "api", "apis": "api",
    "open source": "open-source", "oss": "open-source",
    "developer tools": "developer-tools", "dev tools": "developer-tools",
    # Security
    "cyber security": "cybersecurity", "infosec": "cybersecurity",
    "pentesting": "pentest", "penetration testing": "pentest",
    # Cloud
    "amazon web services": "aws",
    "google cloud platform": "gcp", "google cloud": "gcp",
    "microsoft azure": "azure",
    # Business
    "startup": "startups", "start up": "startups", "start-up": "startups",
    # Design
    "ux design": "ux", "ui design": "ui", "ux/ui": "ui-ux", "ui/ux": "ui-ux",
    # Food
    "recipes": "recipe",
    # Misc
    "cryptocurrency": "crypto", "cryptocurrencies": "crypto",
    "open ai": "openai",
}


def normalize_tag(tag: str) -> str:
    """Return the canonical lowercase-hyphenated form of a tag."""
    cleaned = tag.lower().strip()
    if cleaned in _TAG_ALIASES:
        return _TAG_ALIASES[cleaned]
    normalized = re.sub(r"[^\w\s\-]", "", cleaned)
    normalized = re.sub(r"\s+", "-", normalized.strip())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or cleaned


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize a list of tags and deduplicate while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        norm = normalize_tag(tag)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


# ── Local fallback analysis ────────────────────────────────────────────────────

# Non-tech domain patterns checked FIRST to prevent false tech assignments
_DOMAIN_CATEGORY: list[tuple[set[str], str]] = [
    # Gaming — unambiguous, must come before general entertainment
    ({"steampowered.com", "epicgames.com", "gog.com", "itch.io",
      "xbox.com", "playstation.com", "nintendo.com",
      "gamespot.com", "ign.com", "polygon.com", "kotaku.com",
      "pcgamer.com", "rockpapershotgun.com", "eurogamer.net",
      "newgrounds.com", "gamefaqs.gamespot.com"}, "Gaming"),
    # Food & Cooking
    ({"allrecipes", "foodnetwork", "epicurious", "seriouseats", "bonappetit",
      "tasty.co", "delish.", "yummly", "simplyrecipes", "thekitchn", "skinnytaste",
      "food.", "recipe", "cooking.", "cuisine", "baking", "bbq.", "eater.com",
      "sallybakingaddiction", "budgetbytes", "halfbakedharvest",
      "pinchofyum", "damndelicious", "cafedelites"}, "Food & Cooking"),
    # Home & Living
    ({"ikea.com", "wayfair.com", "westelm.com", "crateandbarrel.com",
      "cb2.com", "potterybarn.com", "homedepot.com", "lowes.com",
      "overstock.com", "apartmenttherapy.com", "architecturaldigest.com",
      "houzz.com", "article.com", "burrow.com", "zgallerie.com",
      "roomandboard.com", "rh.com", "restoration hardware"}, "Home & Living"),
    # Outdoor & Sports
    ({"rei.com", "backcountry.com", "alltrails.com", "strava.com",
      "patagonia.com", "thenorthface.com", "moosejaw.com", "trailforks.com",
      "outsideonline.com", "backpacker.com", "hikingproject.com",
      "summitpost.org", "peakbagger.com", "komoot.com"}, "Outdoor & Sports"),
    # Pets
    ({"petfinder.com", "chewy.com", "petsmart.com", "petco.com",
      "akc.org", "catster.com", "dogster.com", "hillspet.com",
      "rover.com", "petmd.com", "vetstreet.com", "iheartdogs.com"}, "Pets"),
    # Travel
    ({"airbnb.com", "booking.com", "expedia.com", "tripadvisor.com",
      "kayak.com", "skyscanner.com", "lonelyplanet.com", "hotels.com",
      "vrbo.com", "travelocity.com", "momondo.com", "fodors.com",
      "frommers.com", "nomadicmatt.com", "travelandleisure.com"}, "Travel"),
    # News & Media
    ({"cnn.com", "bbc.", "reuters.", "nytimes", "washingtonpost", "theguardian",
      "apnews", "npr.org", "bloomberg.", "foxnews", "nbcnews", "abc7", "cbsnews",
      "usatoday", "theatlantic", "politico", "axios", "vox.com",
      "slate.com", "huffpost", "thedailybeast"}, "News & Media"),
    # Health & Wellness
    ({"webmd", "healthline", "mayoclinic", "nih.gov", "pubmed", "medicalnewstoday",
      "everydayhealth", "health.", "wellness", "nutrition.", "drugs.com",
      "verywellhealth", "medlineplus", "clevelandclinic"}, "Health & Wellness"),
    # Entertainment (music, film, streaming — not gaming)
    ({"imdb.com", "rottentomatoes", "metacritic", "netflix", "hulu", "disney",
      "spotify.com", "soundcloud", "twitch.tv", "youtube.com", "vimeo",
      "letterboxd.com", "goodreads.com", "audible.com"}, "Entertainment"),
    # Business & Finance
    ({"forbes", "investopedia", "marketwatch", "cnbc.com", "businessinsider",
      "hbr.org", "wsj.com", "ft.com", "economist",
      "morningstar.com", "seekingalpha.com", "kiplinger.com"}, "Business & Finance"),
    # Sports (→ Entertainment as general catch-all)
    ({"espn.com", "bleacherreport", "nba.com", "nfl.com", "mlb.com",
      "goal.com", "skysports", "theathletic"}, "Entertainment"),
    # Science (non-CS)
    ({"nature.com", "science.org", "sciencedaily", "newscientist", "scientificamerican",
      "nasa.gov", "space.com", "phys.org"}, "Science"),
    # Shopping — general retail (placed before tech to catch ebay/etsy/walmart)
    # Note: amazon.com excluded here — aws.amazon.com must match Cloud & DevOps instead
    ({"ebay.com", "etsy.com", "walmart.com", "target.com", "bestbuy.com",
      "newegg.com", "wirecutter.com", "rtings.com",
      "camelcamelcamel.com", "slickdeals.net", "dealnews.com"}, "Shopping"),
    # Tech domains (after all non-tech domains)
    ({"github.com", "gitlab.com", "bitbucket.org", "codeberg.org"}, "Development"),
    ({"stackoverflow.com", "stackexchange.com"}, "Development"),
    ({"devdocs.io", "developer.mozilla", "developer.apple", "developer.android"}, "Development"),
    ({"arxiv.org", "scholar.google", "semanticscholar.org", "researchgate.net"}, "Research"),
    ({"figma.com", "dribbble.com", "behance.net", "sketch.com"}, "Design"),
    ({"kaggle.com", "huggingface.co", "openai.com", "anthropic.com"}, "AI & ML"),
    ({"coursera.org", "udemy.com", "edx.org", "khanacademy.org", "pluralsight.com"}, "Education"),
    ({"notion.so", "obsidian.md", "roamresearch.com", "logseq.com"}, "Productivity"),
    ({"aws.amazon.com", "cloud.google.com", "azure.microsoft.com", "digitalocean.com"}, "Cloud & DevOps"),
    ({"arduino.cc", "raspberrypi.org", "adafruit.com", "sparkfun.com"}, "Hardware"),
    ({"ros.org", "robotics."}, "Robotics"),
]

# Tags with their trigger keywords — multi-word and long keywords use substring
# matching; short (≤3 char) single words use word-boundary matching via _kw_match
_KEYWORD_TAGS: list[tuple[list[str], str]] = [
    (["python", "pytorch", "pandas", "numpy", "flask", "django", "fastapi"], "python"),
    (["javascript", "node.js", "nodejs", "express.js", "deno.js"], "javascript"),
    (["typescript"], "typescript"),
    (["react", "reactjs", "next.js", "nextjs", "gatsby", "remix.run"], "react"),
    (["tailwindcss", "tailwind css"], "tailwind"),
    (["machine learning", "deep learning", "neural network", "bert", "transformers model"], "machine-learning"),
    (["large language model", "gpt-4", "gpt-3", "chatgpt", "openai api", "claude api", "gemini api", "llama model"], "llm"),
    (["artificial intelligence", "generative ai", "ai agent", "ai model"], "ai"),
    (["robotics", "robot arm", "autonomous robot", "ros framework"], "robotics"),
    (["arduino", "esp32", "raspberry pi", "microcontroller", "firmware", "fpga"], "embedded"),
    (["linux", "ubuntu", "debian", "fedora", "bash script", "shell script"], "linux"),
    (["docker", "kubernetes", "k8s", "devops", "ci/cd", "github actions", "gitlab ci"], "devops"),
    (["postgresql", "mysql", "mongodb", "redis", "sqlite", "nosql", "database"], "database"),
    (["rest api", "graphql", "grpc", "openapi", "swagger", "webhook"], "api"),
    (["resume", "portfolio", "job interview", "career", "hiring"], "career"),
    (["figma", "sketch app", "user interface design", "prototyping", "wireframe"], "design"),
    (["tutorial", "step-by-step", "how-to guide", "getting started guide"], "tutorial"),
    (["online course", "lecture", "bootcamp", "certification"], "learning"),
    (["workflow automation", "zapier", "make.com"], "productivity"),
    (["cybersecurity", "penetration testing", "pentest", "vulnerability", "exploit", "ctf", "firewall"], "security"),
    (["data science", "data analysis", "jupyter notebook", "matplotlib", "seaborn"], "data-science"),
    (["aws", "azure cloud", "google cloud", "serverless", "lambda function", "vercel", "netlify"], "cloud"),
    (["pcb design", "circuit board", "electronics project", "oscilloscope", "soldering"], "hardware"),
    (["research paper", "academic study", "journal article", "arxiv", "peer review"], "research"),
    (["game development", "unity engine", "unreal engine", "godot engine", "pygame"], "game-dev"),
    (["ios app", "android app", "swift", "kotlin", "react native", "flutter"], "mobile"),
    # Non-tech tags (original)
    (["recipe", "ingredients", "cooking", "baking", "cuisine"], "recipe"),
    (["health tips", "symptoms", "treatment", "wellness", "nutrition"], "health"),
    (["news", "breaking news", "journalist", "headline", "editorial"], "news"),
    # Gaming
    (["video game", "pc gaming", "game review", "gameplay", "multiplayer", "esports",
      "open world", "indie game", "game trailer", "early access", "battle royale",
      "mmorpg", "rpg game", "fps game", "gaming pc", "patch notes"], "gaming"),
    (["steam store", "epic games store", "gog games", "game pass",
      "nintendo eshop", "psn store", "xbox store"], "game-store"),
    # Home & Living
    (["furniture", "sofa", "couch", "bookshelf", "dining table", "wardrobe",
      "dresser", "office chair", "standing desk", "home office setup"], "furniture"),
    (["home decor", "interior design", "living room design", "bedroom design",
      "kitchen renovation", "home improvement", "room makeover"], "interior-design"),
    # Shopping
    (["add to cart", "buy now", "free shipping", "product review", "buyer's guide",
      "best price", "discount code", "in stock", "compare prices", "price drop",
      "top picks", "best overall"], "shopping"),
    # Outdoor & Sports
    (["hiking trail", "camping gear", "outdoor adventure", "backpacking",
      "rock climbing", "kayaking", "mountain biking", "trail running",
      "skiing", "snowboarding", "outdoor gear", "trekking"], "hiking"),
    (["national park", "campsite", "wilderness", "summit", "sleeping bag",
      "tent review", "camping trip"], "camping"),
    # Pets
    (["dog breed", "cat breed", "puppy training", "kitten care", "pet adoption",
      "pet health", "dog food", "cat food", "pet grooming", "veterinary",
      "dog walking", "cat owner", "pet store"], "pets"),
    # Travel
    (["travel destination", "hotel review", "flight deal", "vacation planning",
      "travel itinerary", "sightseeing", "tourist attraction", "travel guide",
      "travel tips", "travel blog", "best places to visit"], "travel"),
    (["hostel", "hotel booking", "resort review", "cruise ship"], "accommodation"),
]

_KEYWORD_CATEGORY: list[tuple[list[str], str]] = [
    # Non-tech categories checked first
    (["recipe", "ingredients", "tablespoon", "teaspoon", "cooking time", "serves", "prep time",
      "bake at", "roast", "simmer", "sauté", "chopped", "minced"], "Food & Cooking"),
    (["symptoms", "treatment", "diagnosis", "medication", "therapy", "disease", "patient",
      "clinical trial", "vaccine", "health tips", "nutrition facts"], "Health & Wellness"),
    (["breaking news", "journalist", "editorial board", "press release", "correspondent",
      "news report", "latest news", "top stories"], "News & Media"),
    (["species", "ecosystem", "climate change", "biology", "chemistry", "physics experiment",
      "quantum", "genomics", "neuroscience", "telescope", "nasa"], "Science"),
    (["quarterly earnings", "stock market", "investor", "startup funding", "venture capital",
      "business strategy", "revenue", "ceo", "acquisition"], "Business & Finance"),
    # Lifestyle / consumer categories
    (["video game", "pc gaming", "console game", "game review", "gameplay",
      "multiplayer", "esports", "indie game", "open world", "mmorpg",
      "game trailer", "steam game", "gaming pc", "game download",
      "game pass", "game release", "dlc"], "Gaming"),
    (["furniture", "sofa", "couch", "bookshelf", "home office", "interior design",
      "home decor", "living room", "bedroom", "dining table", "home improvement",
      "wardrobe", "office chair", "standing desk", "room design",
      "home setup", "desk setup"], "Home & Living"),
    (["add to cart", "buy now", "free shipping", "product review", "buyer's guide",
      "best price", "discount", "in stock", "compare prices",
      "customer reviews", "return policy", "top picks", "best overall",
      "where to buy", "price comparison"], "Shopping"),
    (["hiking trail", "camping", "outdoor adventure", "backpacking", "rock climbing",
      "kayaking", "mountain biking", "trail running", "skiing", "snowboarding",
      "outdoor gear", "national park", "trekking", "summit", "gear review"], "Outdoor & Sports"),
    (["dog breed", "cat breed", "puppy training", "kitten care", "pet adoption",
      "pet care", "pet health", "dog training", "cat care", "dog food",
      "cat food", "veterinary", "pet grooming", "pet store", "fish tank",
      "aquarium", "bird care"], "Pets"),
    (["travel destination", "hotel review", "flight deal", "vacation planning",
      "travel itinerary", "sightseeing", "tourist attraction", "travel guide",
      "travel tips", "trip planning", "travel blog", "best places to visit",
      "hostel", "resort", "cruise"], "Travel"),
    # Tech categories
    (["machine learning", "deep learning", "large language model", "gpt-4", "transformer model",
      "neural network", "ai agent", "generative ai", "openai", "anthropic", "hugging face"], "AI & ML"),
    (["robotics", "robot arm", "autonomous vehicle", "servo motor", "ros framework", "manipulator"], "Robotics"),
    (["arduino", "esp32", "microcontroller", "raspberry pi", "embedded system", "firmware", "fpga",
      "circuit board", "pcb design"], "Embedded Systems"),
    (["figma design", "ui design", "ux research", "user experience design", "dribbble",
      "typography", "color palette", "wireframe", "prototype"], "Design"),
    (["penetration testing", "cybersecurity", "hacking", "vulnerability assessment", "exploit",
      "ctf challenge", "firewall", "malware"], "Cybersecurity"),
    (["data science", "data analysis", "machine learning pipeline", "kaggle", "spark",
      "tableau", "power bi", "data visualization"], "Data Science"),
    (["aws", "azure", "google cloud", "kubernetes", "docker", "devops", "terraform",
      "cloud infrastructure", "serverless"], "Cloud & DevOps"),
    (["electronics", "pcb", "soldering", "oscilloscope", "power supply", "sensor module"], "Hardware"),
    (["research paper", "academic", "arxiv", "journal", "scholarly", "peer-reviewed"], "Research"),
    (["workflow", "notion", "obsidian", "task management", "time tracking", "productivity system"], "Productivity"),
    (["python", "javascript", "typescript", "react", "framework", "library", "developer docs",
      "programming", "coding", "software engineer", "backend", "frontend"], "Development"),
]


def _kw_match(keyword: str, text: str) -> bool:
    """Match a keyword against text with word-boundary safety for short terms."""
    if ' ' in keyword:
        # Multi-word phrase: substring is already specific enough
        return keyword in text
    if len(keyword) <= 4:
        # Short tokens: require word boundary to prevent "ts" matching "nutrients"
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', text))
    return keyword in text


def _local_analyze_site(url: str, title: str, description: str = "", raw_content: str = "") -> dict:
    """Rule-based analysis — always produces a useful result without an API key."""
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.lower().replace("www.", "")

    # Keyword matching uses only title + description + short content excerpt.
    # URL is deliberately excluded — path segments like /api/v2/... cause false positives.
    keyword_text = f"{title} {description} {raw_content[:500]}".lower()

    # ── Category inference ────────────────────────────────
    category = "Other"
    for domains_set, cat in _DOMAIN_CATEGORY:
        if any(d in domain for d in domains_set):
            category = cat
            break
    if category == "Other":
        for keywords, cat in _KEYWORD_CATEGORY:
            if any(_kw_match(kw, keyword_text) for kw in keywords):
                category = cat
                break

    # ── Tag extraction ────────────────────────────────────
    found_tags: list[str] = []
    for keywords, tag in _KEYWORD_TAGS:
        if any(_kw_match(kw, keyword_text) for kw in keywords):
            found_tags.append(tag)
        if len(found_tags) >= 5:
            break

    # Strip tech-only tags when category is clearly non-technical
    if category not in _TECH_CATEGORIES:
        found_tags = [t for t in found_tags if t not in _TECH_ONLY_TAGS]

    # Only add a fallback category tag when we genuinely know the category
    if not found_tags and category not in ("Other",):
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
            "Food & Cooking": "recipe",
            "Health & Wellness": "health",
            "News & Media": "news",
            "Education": "education",
            "Science": "science",
            "Business & Finance": "business",
            "Gaming": "gaming",
            "Home & Living": "furniture",
            "Shopping": "shopping",
            "Outdoor & Sports": "hiking",
            "Pets": "pets",
            "Travel": "travel",
            "Entertainment": "entertainment",
        }
        tag = cat_tag_map.get(category)
        if tag:
            found_tags = [tag]

    # ── Summary ───────────────────────────────────────────
    if description and len(description) > 40:
        summary = description
    elif raw_content:
        sentences = re.split(r'(?<=[.!?])\s+', raw_content[:600].strip())
        usable = [s.strip() for s in sentences if len(s.strip()) > 30]
        summary = " ".join(usable[:2]) if usable else f"{title} — saved to your NEXUS library."
    else:
        summary = f"{title} — saved to your NEXUS library."

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
        "Food & Cooking": "When looking for recipes, cooking techniques, or food inspiration.",
        "Health & Wellness": "When researching health topics, symptoms, treatments, or wellness advice.",
        "News & Media": "When staying current on news, events, or media coverage.",
        "Science": "When exploring scientific research, discoveries, or explanations.",
        "Business & Finance": "When researching business strategy, markets, or financial topics.",
        "Education": "When learning or teaching a subject in depth.",
        "Entertainment": "For leisure, entertainment, or cultural reference.",
        "Gaming": "When looking for games to play, game reviews, or gaming communities.",
        "Home & Living": "When furnishing, decorating, or setting up a living or work space.",
        "Shopping": "When researching a product, comparing options, or looking for the best deal.",
        "Outdoor & Sports": "When planning outdoor activities, gear purchases, or fitness routes.",
        "Pets": "When caring for, adopting, or learning about pets.",
        "Travel": "When planning a trip, finding accommodations, or exploring destinations.",
    }
    use_case = use_case_map.get(category, "A reference saved to your NEXUS library.")

    return {
        "summary":          summary[:500],
        "primary_category": category,
        "categories":       [category] if category != "Other" else [],
        "category":         category,  # backward compat
        "tags":             found_tags[:5],
        "technologies":     [],
        "topics":           [category] if category != "Other" else [],
        "use_case":         use_case,
        "learning_value":   "intermediate",
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


def _sanitize_analysis(result: dict) -> dict:
    """Post-process analysis: normalize tags, ensure multi-category fields, strip tech contamination."""
    # Normalize and deduplicate tags
    result["tags"] = normalize_tags(result.get("tags") or [])[:5]

    # Ensure both category fields are populated consistently
    primary = result.get("primary_category") or result.get("category") or "Other"
    categories = result.get("categories") or []
    if not categories:
        categories = [primary]
    if categories[0] != primary:
        categories = [primary] + [c for c in categories if c != primary]
    result["primary_category"] = primary
    result["categories"]       = categories[:3]
    result["category"]         = primary  # backward compat

    # Strip tech-only tags when none of the assigned categories are technical
    if not any(_is_tech_category(c) for c in categories):
        result["tags"] = [t for t in result["tags"] if t not in _TECH_ONLY_TAGS]

    return result


_TAXONOMY_PROMPT = """TAXONOMY — use these as specific category names (or generate a more specific subcategory):
Technology: Programming, Web Development, Machine Learning, Deep Learning, NLP, Computer Vision, Data Science, Cybersecurity, DevOps & Cloud, Networking, Linux & System Administration, Embedded Systems, IoT, Robotics, Hardware & Electronics, Game Development, Computer Graphics, Distributed Systems, Algorithms & Data Structures, Databases, Reverse Engineering, Homelabs & Self-Hosting, Mobile Development, API Development, System Design
Science: Physics, Chemistry, Biology, Neuroscience, Astronomy & Space, Genetics & Genomics, Environmental Science, Scientific Research
Mathematics: Calculus & Analysis, Linear Algebra, Statistics & Probability, Discrete Mathematics, Applied Mathematics
Engineering: Mechanical Engineering, Electrical Engineering, Aerospace Engineering, Chemical Engineering, Biomedical Engineering, Materials Science, Renewable Energy, Electronics & Circuits
Medicine: Medicine & Healthcare, Mental Health & Psychology, Nutrition & Dietetics, Fitness & Exercise Science, Pharmacology, Public Health, Medical Research
Business: Startups & Entrepreneurship, Marketing & Growth, Finance & Investing, Cryptocurrency & Web3, Economics, eCommerce & SaaS, Management & Leadership, Productivity & Systems, Personal Finance, Real Estate, Sales, Trading & Markets
Social Sciences: Sociology & Anthropology, Political Science, Law & Legal Studies, International Relations
Humanities: History, Philosophy & Ethics, Religion & Theology, Literature & Writing, Linguistics, Cultural Studies
Arts: Design & UX/UI, Graphic Design, Photography, Music & Audio, Film & Video Production, Architecture, Creative Writing, Content Creation
Education: Learning Resources & Courses, Research Papers & Journals, Tutorials & How-Tos, Study Materials, Certifications & Exams
Trades: Automotive & Mechanics, Construction & Carpentry, Electrical Work & HVAC, Home Improvement & DIY
Entertainment: Gaming, Movies & Film, TV & Streaming, Anime & Manga, Books & Comics, Sports & Esports, Podcasts, Board Games & TCGs
Lifestyle: Cooking & Food, Travel & Adventure, Fitness & Wellness, Outdoor & Hiking, Pets & Animals, Home & Living, Personal Growth & Mindset, Coffee & Tea, Gardening & Plants, Fashion & Lifestyle, Watches & Luxury, Martial Arts
General: News & Media, Tools & Apps, Ideas & Inspiration, Shopping & Product Research, Projects & Planning, Read Later"""


async def analyze_site(url: str, title: str, description: str = "", raw_content: str = "") -> dict:
    content_preview = raw_content[:3000] if raw_content else ""
    prompt = f"""You are NEXUS, an intelligent knowledge curator. Analyze this content and return rich structured metadata.

URL: {url}
TITLE: {title}
DESCRIPTION: {description}
CONTENT (excerpt): {content_preview}

{_TAXONOMY_PROMPT}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "primary_category": "the single most specific category for this content (e.g. 'Machine Learning', 'Neuroscience', 'Cooking & Food', 'Mechanical Engineering')",
  "categories": ["primary_category", "up to 2 more only if content genuinely spans multiple domains"],
  "summary": "2-3 sentences: what this is, who it's for, why it matters",
  "tags": ["3-5 specific lowercase tags that directly describe THIS content — not the field in general"],
  "technologies": ["only if explicitly technical: programming languages, frameworks, tools mentioned"],
  "topics": ["specific concepts or subtopics this content covers"],
  "use_case": "one sentence: when would someone return to this?",
  "learning_value": "beginner or intermediate or advanced",
  "content_type": "article or video or tool or paper or docs or course or repository or news or product or recipe or forum or other"
}}

CRITICAL RULES:
- primary_category must be SPECIFIC (e.g. 'Machine Learning' not 'Technology', 'Neuroscience' not 'Science')
- categories: 1 is ideal, 2-3 only if the content truly spans domains
- tags must describe THIS page, not the general field — fewer accurate tags beat many generic ones
- NEVER assign tech categories to non-technical content:
  - food/recipe → "Cooking & Food", tags: ["recipe","cooking"]
  - gaming/Steam → "Gaming", tags: ["gaming"]
  - furniture/IKEA → "Home & Living", tags: ["furniture"]
  - hiking/REI/camping → "Outdoor & Hiking", tags: ["hiking"]
  - pets/adoption → "Pets & Animals", tags: ["pets"]
  - travel/hotels → "Travel & Adventure", tags: ["travel"]
  - news/journalism → "News & Media", tags: ["news"]
  - health/medical → "Medicine & Healthcare" or "Fitness & Wellness"
- technologies = [] unless this page is explicitly about code or technical tools
- If genuinely unclear, use "Other" with no tags"""

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
        result = _sanitize_analysis(result)
        logger.info(f"AI analysis complete for: {url}")
        return result
    except anthropic.AuthenticationError:
        logger.warning("Anthropic API key invalid — using local fallback analysis")
        return _sanitize_analysis(_local_analyze_site(url, title, description, raw_content))
    except Exception as e:
        logger.error(f"AI analysis failed for {url}: {e} — using local fallback")
        return _sanitize_analysis(_local_analyze_site(url, title, description, raw_content))


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

GOOD examples:
- Tech: "React Frontend", "AI Agents & LLMs", "Arduino & ESP32", "Academic Research", "Resume & Job Tools"
- Non-tech: "Cooking & Recipes", "Home Office Setup", "PC Gaming", "Hiking & Outdoor Gear", "Pet Care", "Travel Planning", "Home Furniture"
The library may be entirely non-technical — that is completely valid. Group by THEME, not by tech-bias.

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
