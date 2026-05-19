"""
Local discovery engine — personalized recommendations without AI or API credits.

Works by:
  1. Profiling the user's library (tags, categories, domains, source count)
  2. Scoring a curated tools database against that profile + user interaction profile
  3. Building "Because you saved X..." anchors from library sources
  4. Building "Based on your recent questions" sections from Ask NEXUS history
  5. Detecting knowledge gaps from category relationships
  6. Producing interest summaries from tag/category frequency
  7. Surfacing curated Learning Paths relevant to the user's interests
"""
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TAG_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was",
    "not", "but", "all", "your", "can", "use", "has", "have",
}


def _tool_url(tool: dict) -> str:
    hints = tool.get("url_hints", [])
    if not hints:
        return ""
    h = hints[0]
    return h if h.startswith("http") else f"https://{h}"

# ── Curated tools database ────────────────────────────────────────────────────

CURATED_TOOLS: list[dict] = [

    # ── AI & ML ───────────────────────────────────────────────────────────────
    {"topic": "Cursor AI",        "description": "AI-first code editor with deep LLM integration, multi-file edits, and inline chat.",            "category": "AI & ML",        "tags": ["ai", "llm", "code editor", "copilot", "cursor", "autocomplete", "developer-tools"],      "url_hints": ["cursor.sh", "cursor.com"],             "search_query": "AI coding tools"},
    {"topic": "Ollama",           "description": "Run large language models locally with a simple CLI. Supports Llama, Mistral, Phi, and more.", "category": "AI & ML",        "tags": ["llm", "local ai", "ollama", "mistral", "llama", "ai", "self-hosted"],                    "url_hints": ["ollama.ai", "ollama.com"],              "search_query": "local LLM tools"},
    {"topic": "LM Studio",        "description": "Desktop app to discover, download, and run local LLMs with an OpenAI-compatible API.",         "category": "AI & ML",        "tags": ["llm", "local ai", "ai model", "desktop", "openai", "api"],                             "url_hints": ["lmstudio.ai"],                          "search_query": "run LLMs locally"},
    {"topic": "LangChain",        "description": "Framework for building LLM-powered applications with chains, agents, and memory.",             "category": "AI & ML",        "tags": ["langchain", "llm", "agent", "rag", "python", "ai", "langchain"],                         "url_hints": ["langchain.com", "python.langchain.com"],"search_query": "LLM application frameworks"},
    {"topic": "LlamaIndex",       "description": "Data framework for connecting LLMs to external data sources — ideal for RAG pipelines.",       "category": "AI & ML",        "tags": ["llamaindex", "rag", "llm", "vector database", "embedding", "ai", "python"],             "url_hints": ["llamaindex.ai"],                        "search_query": "RAG pipeline tools"},
    {"topic": "Hugging Face",     "description": "Hub for ML models, datasets, and spaces. Host and run open-source models in one click.",       "category": "AI & ML",        "tags": ["huggingface", "llm", "machine learning", "model", "dataset", "transformers", "ai"],     "url_hints": ["huggingface.co"],                       "search_query": "open source AI models"},
    {"topic": "Perplexity AI",    "description": "AI-powered search engine that cites sources and answers complex questions in real time.",       "category": "AI & ML",        "tags": ["perplexity", "ai", "search", "llm", "research"],                                         "url_hints": ["perplexity.ai"],                        "search_query": "AI search tools"},
    {"topic": "ComfyUI",          "description": "Node-based UI for Stable Diffusion — build complex image generation pipelines visually.",       "category": "AI & ML",        "tags": ["stable diffusion", "ai", "image generation", "comfyui", "generative ai", "nodes"],     "url_hints": ["comfyanonymous.github.io"],             "search_query": "Stable Diffusion workflows"},
    {"topic": "Groq",             "description": "Ultra-fast LLM inference API — run Llama and Mixtral at thousands of tokens per second.",      "category": "AI & ML",        "tags": ["groq", "llm", "inference", "api", "ai", "fast"],                                         "url_hints": ["groq.com"],                             "search_query": "fast LLM inference"},
    {"topic": "Weights & Biases", "description": "MLOps platform for experiment tracking, model visualization, and dataset versioning.",          "category": "AI & ML",        "tags": ["machine learning", "mlops", "experiment tracking", "pytorch", "deep learning", "ai"],   "url_hints": ["wandb.ai"],                             "search_query": "ML experiment tracking"},
    {"topic": "Together AI",      "description": "Run open-source LLMs via API at low cost — supports fine-tuning and serverless inference.",    "category": "AI & ML",        "tags": ["llm", "ai", "api", "inference", "fine-tuning", "together ai"],                          "url_hints": ["together.ai"],                          "search_query": "LLM API providers"},
    {"topic": "NotebookLM",       "description": "Google's AI notebook that lets you chat with your documents and generate audio overviews.",     "category": "AI & ML",        "tags": ["notebooklm", "ai", "notes", "research", "google", "rag", "documents"],                  "url_hints": ["notebooklm.google"],                    "search_query": "AI document tools"},
    {"topic": "Replicate",        "description": "Run ML models in the cloud via API — thousands of open-source models available instantly.",     "category": "AI & ML",        "tags": ["replicate", "ai", "api", "model", "inference", "image generation"],                     "url_hints": ["replicate.com"],                        "search_query": "cloud ML model APIs"},

    # ── Robotics & Embedded ───────────────────────────────────────────────────
    {"topic": "PlatformIO",       "description": "Professional IDE and ecosystem for embedded development — supports ESP32, Arduino, and 1000+ boards.", "category": "Embedded Systems", "tags": ["platformio", "embedded", "esp32", "arduino", "firmware", "microcontroller", "iot"],   "url_hints": ["platformio.org"],   "search_query": "embedded development tools"},
    {"topic": "ROS2",             "description": "Robot Operating System 2 — middleware for building complex robotic systems with pub/sub messaging.", "category": "Robotics",    "tags": ["ros", "robotics", "robot", "autonomous", "sensor", "actuator", "middleware"],            "url_hints": ["ros.org", "docs.ros.org"], "search_query": "robotics middleware"},
    {"topic": "KiCad",            "description": "Open-source PCB design suite — schematic capture, PCB layout, and 3D viewer included.",           "category": "Hardware",     "tags": ["kicad", "pcb", "hardware", "electronics", "circuit", "schematic", "soldering"],          "url_hints": ["kicad.org"],        "search_query": "PCB design tools"},
    {"topic": "FreeRTOS",         "description": "Real-time operating system for microcontrollers — widely used on ESP32 and ARM Cortex-M devices.", "category": "Embedded Systems", "tags": ["freertos", "rtos", "embedded", "esp32", "firmware", "microcontroller", "real-time"],  "url_hints": ["freertos.org"],     "search_query": "RTOS for microcontrollers"},
    {"topic": "Edge Impulse",     "description": "Platform for building and deploying machine learning models on edge devices and microcontrollers.",  "category": "Embedded Systems", "tags": ["edge impulse", "embedded", "machine learning", "tinyml", "arduino", "sensor", "ai"],  "url_hints": ["edgeimpulse.com"],  "search_query": "edge AI machine learning"},
    {"topic": "ESPHome",          "description": "YAML-based firmware for ESP8266/ESP32 devices — connect to Home Assistant with zero code.",        "category": "Embedded Systems", "tags": ["esphome", "esp32", "home automation", "iot", "firmware", "yaml", "arduino"],         "url_hints": ["esphome.io"],       "search_query": "ESP32 home automation"},
    {"topic": "Gazebo",           "description": "Robot simulation environment — test ROS-based robots in realistic 3D physics simulations.",        "category": "Robotics",     "tags": ["gazebo", "robotics", "simulation", "ros", "robot", "3d", "physics"],                    "url_hints": ["gazebosim.org"],    "search_query": "robot simulation"},
    {"topic": "MoveIt",           "description": "Motion planning framework for ROS — kinematics, trajectory planning, and manipulation.",           "category": "Robotics",     "tags": ["moveit", "robotics", "ros", "motion planning", "manipulation", "kinematics", "arm"],    "url_hints": ["moveit.ros.org"],   "search_query": "robot motion planning"},
    {"topic": "TensorFlow Lite",  "description": "Run TensorFlow ML models on microcontrollers and mobile devices — tiny footprint, fast inference.", "category": "Embedded Systems", "tags": ["tensorflow", "embedded", "machine learning", "tinyml", "ai", "edge", "microcontroller"], "url_hints": ["tensorflow.org/lite"], "search_query": "TinyML on microcontrollers"},
    {"topic": "Node-RED",         "description": "Flow-based programming tool for wiring hardware devices, APIs, and online services together.",      "category": "Embedded Systems", "tags": ["node-red", "iot", "automation", "flow", "raspberry pi", "embedded", "mqtt"],         "url_hints": ["nodered.org"],      "search_query": "IoT flow programming"},
    {"topic": "OpenCV",           "description": "Computer vision library with 2500+ optimized algorithms — used in robotics, medical imaging, and AR.", "category": "Robotics",  "tags": ["opencv", "computer vision", "robotics", "image processing", "python", "c++", "ai"],  "url_hints": ["opencv.org"],       "search_query": "computer vision library"},

    # ── Frontend Development ──────────────────────────────────────────────────
    {"topic": "shadcn/ui",        "description": "Beautiful, accessible React components built on Radix UI and Tailwind — copy-paste into your app.", "category": "Development", "tags": ["shadcn", "react", "tailwind", "component", "ui", "frontend", "radix"],                 "url_hints": ["ui.shadcn.com"],    "search_query": "React UI component libraries"},
    {"topic": "Vite",             "description": "Next-generation frontend build tool — instant hot module replacement, ultra-fast builds.",          "category": "Development", "tags": ["vite", "frontend", "build tool", "javascript", "react", "typescript", "dev server"],   "url_hints": ["vitejs.dev"],       "search_query": "frontend build tools"},
    {"topic": "Framer Motion",    "description": "Production-ready React animation library — declarative animations, gestures, and transitions.",     "category": "Development", "tags": ["framer motion", "animation", "react", "frontend", "ui", "typescript", "css"],          "url_hints": ["framer.com/motion"],"search_query": "React animation libraries"},
    {"topic": "Zustand",          "description": "Minimal, fast global state management for React — no boilerplate, no context providers needed.",    "category": "Development", "tags": ["zustand", "react", "state management", "javascript", "frontend", "typescript"],        "url_hints": ["zustand-demo.pmnd.rs", "docs.pmnd.rs"], "search_query": "React state management"},
    {"topic": "TanStack Query",   "description": "Powerful async state management for React — caching, background refetching, and optimistic updates.", "category": "Development", "tags": ["react query", "tanstack", "react", "api", "caching", "frontend", "typescript"],       "url_hints": ["tanstack.com"],     "search_query": "React data fetching"},
    {"topic": "Astro",            "description": "Web framework for content-driven sites — ships zero JS by default, supports all UI frameworks.",    "category": "Development", "tags": ["astro", "frontend", "ssg", "javascript", "typescript", "react", "vue", "web"],         "url_hints": ["astro.build"],      "search_query": "static site generators"},
    {"topic": "SvelteKit",        "description": "Full-stack web framework built on Svelte — filesystem routing, SSR, and server actions.",           "category": "Development", "tags": ["svelte", "sveltekit", "frontend", "javascript", "typescript", "ssr", "web"],            "url_hints": ["kit.svelte.dev"],   "search_query": "full-stack JavaScript frameworks"},
    {"topic": "Playwright",       "description": "Reliable end-to-end testing for modern web apps — auto-waits, traces, and multi-browser support.", "category": "Development", "tags": ["playwright", "testing", "e2e", "frontend", "automation", "typescript", "ci"],          "url_hints": ["playwright.dev"],   "search_query": "web testing frameworks"},
    {"topic": "Storybook",        "description": "Frontend workshop for building and documenting UI components in isolation.",                         "category": "Development", "tags": ["storybook", "react", "component", "ui", "frontend", "documentation", "design system"],"url_hints": ["storybook.js.org"], "search_query": "UI component documentation"},
    {"topic": "Biome",            "description": "Fast, all-in-one linter and formatter for JavaScript/TypeScript — replaces ESLint + Prettier.",    "category": "Development", "tags": ["biome", "eslint", "prettier", "linting", "javascript", "typescript", "frontend"],      "url_hints": ["biomejs.dev"],      "search_query": "JavaScript linting tools"},

    # ── Backend Development ───────────────────────────────────────────────────
    {"topic": "SQLAlchemy",       "description": "Python SQL toolkit and ORM — powerful async support and migrations with Alembic.",                  "category": "Development", "tags": ["sqlalchemy", "python", "database", "orm", "backend", "postgresql", "async"],            "url_hints": ["sqlalchemy.org"],   "search_query": "Python database ORM"},
    {"topic": "Pydantic",         "description": "Data validation using Python type hints — powers FastAPI's request/response models.",               "category": "Development", "tags": ["pydantic", "python", "backend", "validation", "fastapi", "types", "api"],               "url_hints": ["docs.pydantic.dev"],"search_query": "Python data validation"},
    {"topic": "Hono",             "description": "Ultra-fast, lightweight web framework for the edge — runs on Cloudflare Workers, Deno, and Bun.",  "category": "Development", "tags": ["hono", "backend", "api", "typescript", "edge", "cloudflare", "javascript"],            "url_hints": ["hono.dev"],         "search_query": "lightweight backend frameworks"},
    {"topic": "Prisma",           "description": "Next-generation Node.js ORM — type-safe database client with auto-generated queries.",              "category": "Development", "tags": ["prisma", "orm", "database", "nodejs", "typescript", "backend", "postgresql"],          "url_hints": ["prisma.io"],        "search_query": "Node.js ORM"},
    {"topic": "Supabase",         "description": "Open-source Firebase alternative — Postgres database, auth, realtime, storage, and edge functions.", "category": "Development", "tags": ["supabase", "database", "backend", "auth", "postgresql", "realtime", "api"],           "url_hints": ["supabase.com"],     "search_query": "backend as a service"},
    {"topic": "PocketBase",       "description": "Open-source backend in a single binary — SQLite, auth, realtime subscriptions, S3 file storage.",  "category": "Development", "tags": ["pocketbase", "backend", "database", "auth", "self-hosted", "sqlite", "api"],           "url_hints": ["pocketbase.io"],    "search_query": "self-hosted backend"},
    {"topic": "tRPC",             "description": "End-to-end type-safe APIs for TypeScript — no code generation, no schema, just types.",             "category": "Development", "tags": ["trpc", "typescript", "api", "backend", "frontend", "react", "type-safe"],              "url_hints": ["trpc.io"],          "search_query": "TypeScript API frameworks"},
    {"topic": "Drizzle ORM",      "description": "Lightweight TypeScript ORM with SQL-like query syntax — fast, type-safe, no magic.",                "category": "Development", "tags": ["drizzle", "orm", "database", "typescript", "backend", "postgresql", "sqlite"],         "url_hints": ["orm.drizzle.team"], "search_query": "TypeScript database ORM"},

    # ── DevOps & Cloud ────────────────────────────────────────────────────────
    {"topic": "GitHub Actions",   "description": "Automate CI/CD workflows directly from GitHub — build, test, and deploy on every push.",           "category": "Cloud & DevOps", "tags": ["github actions", "ci", "cd", "devops", "automation", "github", "yaml"],             "url_hints": ["github.com/features/actions"], "search_query": "CI/CD automation"},
    {"topic": "Fly.io",           "description": "Deploy full-stack apps and databases globally in minutes — Dockerfile-based, generous free tier.",  "category": "Cloud & DevOps", "tags": ["fly.io", "deployment", "cloud", "docker", "hosting", "devops", "postgresql"],      "url_hints": ["fly.io"],           "search_query": "app deployment platforms"},
    {"topic": "Cloudflare Workers","description": "Serverless code at the edge — runs in 300+ locations globally with < 1ms cold starts.",           "category": "Cloud & DevOps", "tags": ["cloudflare", "serverless", "edge", "workers", "javascript", "api", "cdn"],          "url_hints": ["workers.cloudflare.com"], "search_query": "edge serverless functions"},
    {"topic": "Pulumi",           "description": "Infrastructure as code using real programming languages (Python, TypeScript, Go) — not YAML.",      "category": "Cloud & DevOps", "tags": ["pulumi", "infrastructure", "iac", "devops", "terraform", "cloud", "kubernetes"],    "url_hints": ["pulumi.com"],       "search_query": "infrastructure as code"},
    {"topic": "Grafana",          "description": "Open-source observability platform — dashboards for metrics, logs, and traces from any data source.", "category": "Cloud & DevOps", "tags": ["grafana", "monitoring", "devops", "metrics", "dashboard", "prometheus", "logging"],"url_hints": ["grafana.com"],      "search_query": "monitoring and observability"},
    {"topic": "Coolify",          "description": "Self-hosted Heroku/Netlify alternative — deploy anything via Docker on your own VPS in one click.",  "category": "Cloud & DevOps", "tags": ["coolify", "self-hosted", "deployment", "docker", "devops", "vps", "cloud"],         "url_hints": ["coolify.io"],       "search_query": "self-hosted deployment"},
    {"topic": "Traefik",          "description": "Modern reverse proxy and load balancer — auto-discovers Docker services, built-in SSL with Let's Encrypt.", "category": "Cloud & DevOps", "tags": ["traefik", "reverse proxy", "docker", "ssl", "devops", "load balancer", "linux"],"url_hints": ["traefik.io"],       "search_query": "reverse proxy tools"},

    # ── Data Science ──────────────────────────────────────────────────────────
    {"topic": "Polars",           "description": "Lightning-fast DataFrame library in Rust — 10–100× faster than pandas, same familiar API.",         "category": "Data Science", "tags": ["polars", "python", "data science", "pandas", "data analysis", "dataframe", "rust"],   "url_hints": ["pola.rs"],          "search_query": "fast Python dataframes"},
    {"topic": "DuckDB",           "description": "In-process analytical database — run complex SQL queries on Parquet, CSV, and JSON in seconds.",     "category": "Data Science", "tags": ["duckdb", "database", "sql", "data science", "analytics", "parquet", "olap"],          "url_hints": ["duckdb.org"],       "search_query": "analytical databases"},
    {"topic": "Streamlit",        "description": "Turn Python scripts into shareable web apps in minutes — no frontend experience needed.",            "category": "Data Science", "tags": ["streamlit", "python", "data science", "dashboard", "visualization", "web app"],       "url_hints": ["streamlit.io"],     "search_query": "Python data dashboards"},
    {"topic": "MLflow",           "description": "Open-source ML lifecycle management — track experiments, package models, and deploy anywhere.",      "category": "Data Science", "tags": ["mlflow", "machine learning", "mlops", "python", "experiment tracking", "model"],     "url_hints": ["mlflow.org"],       "search_query": "MLOps experiment tracking"},
    {"topic": "Gradio",           "description": "Build and share ML demos in Python — create UIs for models in 3 lines of code.",                    "category": "Data Science", "tags": ["gradio", "python", "machine learning", "demo", "ai", "web app", "model"],            "url_hints": ["gradio.app"],       "search_query": "ML model demos"},

    # ── Security ──────────────────────────────────────────────────────────────
    {"topic": "Burp Suite",       "description": "Industry-standard web security testing platform — intercept, analyze, and attack HTTP traffic.",    "category": "Cybersecurity", "tags": ["burp suite", "security", "web security", "pentest", "vulnerability", "hacking", "http"], "url_hints": ["portswigger.net"], "search_query": "web application security testing"},
    {"topic": "Semgrep",          "description": "Static analysis tool for finding bugs and security vulnerabilities in code — fast and customizable.", "category": "Cybersecurity", "tags": ["semgrep", "security", "static analysis", "vulnerability", "code review", "sast"],    "url_hints": ["semgrep.dev"],      "search_query": "code security analysis"},
    {"topic": "Nuclei",           "description": "Fast, template-based vulnerability scanner — community-driven with thousands of detection templates.", "category": "Cybersecurity", "tags": ["nuclei", "security", "vulnerability", "scanner", "pentest", "automation"],          "url_hints": ["projectdiscovery.io"], "search_query": "vulnerability scanning"},
    {"topic": "TruffleHog",       "description": "Find leaked credentials and secrets in git history, S3, and more — CI-friendly secrets scanning.",  "category": "Cybersecurity", "tags": ["trufflehog", "security", "secrets", "credentials", "git", "ci", "scanning"],          "url_hints": ["trufflesecurity.com"], "search_query": "secrets detection tools"},
    {"topic": "CyberChef",        "description": "The 'Cyber Swiss Army Knife' — 300+ operations for encoding, decoding, encryption, and analysis.",   "category": "Cybersecurity", "tags": ["cyberchef", "security", "encoding", "cryptography", "ctf", "analysis", "hacking"],   "url_hints": ["gchq.github.io"],   "search_query": "CTF and security tools"},

    # ── Developer Tools ───────────────────────────────────────────────────────
    {"topic": "Warp Terminal",    "description": "GPU-accelerated terminal built in Rust — AI command suggestions, collaborative sessions, blocks.",   "category": "Development", "tags": ["warp", "terminal", "developer-tools", "cli", "ai", "productivity", "rust"],           "url_hints": ["warp.dev"],         "search_query": "modern terminal apps"},
    {"topic": "Zed Editor",       "description": "High-performance code editor built in Rust — multiplayer collaboration, tree-sitter, and LSP.",     "category": "Development", "tags": ["zed", "code editor", "rust", "developer-tools", "performance", "lsp", "collaboration"],"url_hints": ["zed.dev"],          "search_query": "fast code editors"},
    {"topic": "Raycast",          "description": "Blazing fast macOS launcher — replace Spotlight with extensible commands, scripts, and AI.",        "category": "Productivity", "tags": ["raycast", "productivity", "macos", "launcher", "developer-tools", "automation", "cli"],"url_hints": ["raycast.com"],      "search_query": "developer productivity tools"},
    {"topic": "DevDocs",          "description": "Fast, offline documentation browser with unified search across 100+ programming languages and frameworks.", "category": "Development", "tags": ["devdocs", "documentation", "developer-tools", "api", "reference", "offline"],     "url_hints": ["devdocs.io"],       "search_query": "developer documentation"},
    {"topic": "Excalidraw",       "description": "Virtual whiteboard for diagramming — hand-drawn style, real-time collaboration, zero setup.",       "category": "Productivity", "tags": ["excalidraw", "diagram", "whiteboard", "design", "collaboration", "developer-tools"],  "url_hints": ["excalidraw.com"],   "search_query": "diagramming tools"},
    {"topic": "Linear",           "description": "Fast issue tracker and project management built for modern software teams — keyboard-first UI.",     "category": "Productivity", "tags": ["linear", "project management", "developer-tools", "issue tracking", "agile"],         "url_hints": ["linear.app"],       "search_query": "developer project management"},
    {"topic": "Tauri",            "description": "Build native desktop apps with web tech (HTML/CSS/JS + Rust backend) — smaller than Electron.",     "category": "Development", "tags": ["tauri", "desktop app", "rust", "javascript", "typescript", "developer-tools", "gui"], "url_hints": ["tauri.app"],        "search_query": "desktop app frameworks"},
    {"topic": "Bun",              "description": "All-in-one JavaScript runtime — faster than Node.js, built-in bundler, transpiler, and test runner.", "category": "Development", "tags": ["bun", "javascript", "nodejs", "runtime", "bundler", "typescript", "backend"],         "url_hints": ["bun.sh"],           "search_query": "JavaScript runtimes"},

    # ── Career & Learning ─────────────────────────────────────────────────────
    {"topic": "NeetCode",         "description": "Curated LeetCode problem roadmap with video explanations — DSA for FAANG-level interviews.",        "category": "Development", "tags": ["leetcode", "interview", "career", "algorithms", "data structures", "competitive programming"], "url_hints": ["neetcode.io"], "search_query": "coding interview preparation"},
    {"topic": "roadmap.sh",       "description": "Developer roadmaps for every role — Frontend, Backend, DevOps, AI, and more, with resource links.", "category": "Development", "tags": ["roadmap", "career", "learning", "developer", "guide", "frontend", "backend"],         "url_hints": ["roadmap.sh"],       "search_query": "developer learning roadmaps"},
    {"topic": "The Odin Project", "description": "Free, open-source full-stack web development curriculum — from zero to job-ready.",                 "category": "Development", "tags": ["the odin project", "web development", "learning", "career", "frontend", "backend", "javascript"], "url_hints": ["theodinproject.com"], "search_query": "free web development courses"},
    {"topic": "Exercism",         "description": "Code practice platform with 70+ programming language tracks and mentored code review.",              "category": "Development", "tags": ["exercism", "learning", "programming", "practice", "career", "mentorship"],             "url_hints": ["exercism.org"],     "search_query": "programming practice platforms"},
    {"topic": "System Design Primer","description": "GitHub mega-guide to system design concepts — used by thousands preparing for senior roles.",    "category": "Research",    "tags": ["system design", "career", "interview", "architecture", "backend", "distributed systems"], "url_hints": ["github.com/donnemartin/system-design-primer"], "search_query": "system design interview prep"},

    # ── Writing & Productivity ────────────────────────────────────────────────
    {"topic": "Obsidian",         "description": "Markdown note-taking app with graph view, backlinks, and a thriving plugin ecosystem.",              "category": "Productivity", "tags": ["obsidian", "notes", "knowledge base", "second brain", "markdown", "productivity"],    "url_hints": ["obsidian.md"],      "search_query": "second brain note-taking apps"},
    {"topic": "Logseq",           "description": "Open-source knowledge management with block-based outliner, graph database, and journal mode.",     "category": "Productivity", "tags": ["logseq", "notes", "knowledge base", "productivity", "markdown", "graph", "pkm"],     "url_hints": ["logseq.com"],       "search_query": "PKM tools"},
    {"topic": "Notion",           "description": "All-in-one workspace — databases, wikis, docs, projects, and now AI writing assistance.",           "category": "Productivity", "tags": ["notion", "notes", "productivity", "project management", "database", "wiki"],           "url_hints": ["notion.so"],        "search_query": "all-in-one productivity apps"},
    {"topic": "Typst",            "description": "Modern typesetting system — compile beautiful PDFs from a clean markup language, much faster than LaTeX.", "category": "Research", "tags": ["typst", "writing", "latex", "pdf", "research", "documentation", "academic"],        "url_hints": ["typst.app"],        "search_query": "document typesetting tools"},

    # ── Design ────────────────────────────────────────────────────────────────
    {"topic": "Penpot",           "description": "Open-source design and prototyping tool — self-hostable Figma alternative with SVG-based files.",   "category": "Design",      "tags": ["penpot", "design", "ui", "ux", "figma", "prototyping", "self-hosted", "open-source"], "url_hints": ["penpot.app"],       "search_query": "open source design tools"},
    {"topic": "Lottie Files",     "description": "Lightweight animations for web and mobile — export from After Effects, render as JSON/SVG.",        "category": "Design",      "tags": ["lottie", "animation", "design", "svg", "json", "ui", "frontend", "after effects"],   "url_hints": ["lottiefiles.com"],  "search_query": "web animation libraries"},
    {"topic": "Spline",           "description": "3D design tool for the web — create interactive 3D scenes that embed directly in web pages.",        "category": "Design",      "tags": ["spline", "3d", "design", "web", "animation", "interactive", "frontend", "threejs"],  "url_hints": ["spline.design"],    "search_query": "3D web design tools"},
]

# ── Related category pairs (for knowledge-gap detection) ─────────────────────

_CATEGORY_RELATIONSHIPS: dict[str, list[str]] = {
    "AI & ML":         ["Data Science", "Development", "Research"],
    "Development":     ["Cloud & DevOps", "AI & ML", "Design"],
    "Embedded Systems":["Robotics", "Hardware", "AI & ML"],
    "Robotics":        ["Embedded Systems", "Hardware", "AI & ML"],
    "Hardware":        ["Embedded Systems", "Robotics"],
    "Data Science":    ["AI & ML", "Research", "Development"],
    "Cybersecurity":   ["Development", "Cloud & DevOps"],
    "Cloud & DevOps":  ["Development", "Cybersecurity"],
    "Design":          ["Development", "Productivity"],
    "Research":        ["AI & ML", "Data Science"],
    "Productivity":    ["Development", "Design"],
}

_STARTER_CATEGORIES = ["AI Tools", "Developer Tools", "Learning Resources"]

# ── Learning paths ────────────────────────────────────────────────────────────

LEARNING_PATHS: list[dict] = [
    {
        "name": "Frontend Developer Stack",
        "description": "Essential tools for building modern, production-ready web UIs",
        "category": "Development",
        "tags": ["frontend", "react", "javascript", "typescript", "ui"],
        "tool_names": ["shadcn/ui", "Vite", "Framer Motion", "Zustand", "TanStack Query", "Playwright", "Storybook"],
    },
    {
        "name": "Robotics Starter Stack",
        "description": "Everything you need to go from zero to building real robots",
        "category": "Robotics",
        "tags": ["robotics", "embedded systems", "hardware", "sensors", "firmware"],
        "tool_names": ["PlatformIO", "ROS2", "OpenCV", "FreeRTOS", "Gazebo", "MoveIt", "TensorFlow Lite", "Edge Impulse"],
    },
    {
        "name": "AI/ML Toolkit",
        "description": "Run, fine-tune, and build with LLMs and ML models — local or cloud",
        "category": "AI & ML",
        "tags": ["ai", "llm", "machine learning", "rag", "embedding"],
        "tool_names": ["Ollama", "LangChain", "LlamaIndex", "Hugging Face", "Weights & Biases", "Gradio", "MLflow", "Groq"],
    },
    {
        "name": "Backend API Stack",
        "description": "Build robust, type-safe backend services and databases",
        "category": "Development",
        "tags": ["backend", "api", "database", "python", "node.js"],
        "tool_names": ["Supabase", "Pydantic", "SQLAlchemy", "Hono", "tRPC", "Prisma", "PocketBase", "Drizzle ORM"],
    },
    {
        "name": "DevOps & Cloud Stack",
        "description": "Deploy and monitor your applications confidently at scale",
        "category": "Cloud & DevOps",
        "tags": ["devops", "cloud", "docker", "ci/cd", "deployment"],
        "tool_names": ["GitHub Actions", "Fly.io", "Grafana", "Coolify", "Traefik", "Pulumi", "Cloudflare Workers"],
    },
    {
        "name": "Data Science Pipeline",
        "description": "Analyze data, train models, and share insights with stakeholders",
        "category": "Data Science",
        "tags": ["data science", "python", "machine learning", "analytics"],
        "tool_names": ["Polars", "DuckDB", "Streamlit", "MLflow", "Gradio", "Weights & Biases"],
    },
    {
        "name": "Productivity & Knowledge Stack",
        "description": "Manage knowledge, automate repetitive work, and stay in flow",
        "category": "Productivity",
        "tags": ["productivity", "notes", "automation", "workflow"],
        "tool_names": ["Obsidian", "Notion", "Logseq", "Linear", "Excalidraw", "Raycast"],
    },
]

# ── Library profiling ─────────────────────────────────────────────────────────

def _build_profile(sources: list[dict]) -> dict:
    tag_counts: Counter = Counter()
    cat_counts: Counter = Counter()
    domains: set[str]   = set()
    titles: list[str]   = []
    now = datetime.now(timezone.utc)

    for s in sources:
        # Sources saved recently get more weight in the interest profile
        try:
            raw = s.get("created_at")
            ts  = datetime.fromisoformat(raw) if raw else None
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (now - ts).days if ts else 999
        except Exception:
            age_days = 999

        weight = 2.0 if age_days <= 7 else 1.5 if age_days <= 30 else 1.0

        cat = s.get("category") or "Other"
        cat_counts[cat] += weight
        for tag in (s.get("tags") or []):
            tag_counts[tag.lower()] += weight
        domain = urlparse(s.get("url", "")).netloc.lower().replace("www.", "")
        if domain:
            domains.add(domain)
        if s.get("title"):
            titles.append(s["title"].lower())

    return {
        "tag_counts": dict(tag_counts),
        "cat_counts": dict(cat_counts),
        "domains":    domains,
        "top_tags":   [t for t, _ in tag_counts.most_common(20)],
        "top_cats":   [c for c, _ in cat_counts.most_common(8)],
        "titles":     titles,
        "total":      len(sources),
    }


def _already_saved(tool: dict, sources: list[dict]) -> bool:
    """Return True if this tool's domain is already in the user's library."""
    saved_domains = {
        urlparse(s.get("url", "")).netloc.lower().replace("www.", "")
        for s in sources
    }
    return any(hint.replace("www.", "") in saved_domains for hint in tool.get("url_hints", []))


def _score_tool(tool: dict, profile: dict) -> tuple[float, list[str]]:
    """Score a curated tool against the library profile."""
    score   = 0.0
    reasons: list[str] = []

    tool_tags = {t.lower() for t in tool.get("tags", [])}
    tag_counts = profile["tag_counts"]
    cat_counts = profile["cat_counts"]

    # Category match (strong signal)
    tool_cat = tool.get("category", "")
    cat_weight = cat_counts.get(tool_cat, 0)
    if cat_weight:
        score += 3.0 + min(cat_weight - 1, 4) * 0.4
        reasons.append(f"matches your {tool_cat} interest")

    # Tag overlap (weighted by frequency in library)
    matching = tool_tags & set(tag_counts.keys())
    if matching:
        weighted = sum(tag_counts[t] for t in matching)
        score += min(weighted * 0.6, 5.0)
        top_match = sorted(matching, key=lambda t: tag_counts.get(t, 0), reverse=True)
        reasons.append(f"shares tags: {', '.join(top_match[:3])}")

    # Related category bonus
    for cat, related in _CATEGORY_RELATIONSHIPS.items():
        if cat_counts.get(cat, 0) and tool_cat in related:
            score += 0.5
            break

    # Title keyword overlap
    title_tokens = set(re.split(r'\W+', tool["topic"].lower())) - {"", "ai", "the", "a"}
    title_matches = title_tokens & set(tag_counts.keys())
    if title_matches:
        score += len(title_matches) * 0.3

    return round(score, 2), reasons


# ── "Because you saved X" sections ───────────────────────────────────────────

def _build_because_sections(sources: list[dict], scored_tools: list[tuple]) -> list[dict]:
    """
    For each top anchor source, find curated tools that share tags with it.
    Returns 2-3 because-sections.
    """
    if not sources or not scored_tools:
        return []

    # Score each source by how many curated tools it connects to
    anchor_scores: list[tuple[dict, int]] = []
    for source in sources[:30]:
        src_tags = {t.lower() for t in (source.get("tags") or [])}
        if not src_tags:
            continue
        connections = sum(
            1 for tool, _, _ in scored_tools[:30]
            if src_tags & {t.lower() for t in tool.get("tags", [])}
        )
        anchor_scores.append((source, connections))

    anchor_scores.sort(key=lambda x: x[1], reverse=True)
    top_anchors = [(s, c) for s, c in anchor_scores[:3] if c >= 2]

    sections = []
    for anchor, _ in top_anchors:
        anchor_tags = {t.lower() for t in (anchor.get("tags") or [])}
        related: list[tuple[dict, int, list[str]]] = []

        for tool, _, reasons in scored_tools:
            tool_tags = {t.lower() for t in tool.get("tags", [])}
            overlap = anchor_tags & tool_tags
            if len(overlap) >= 1:
                shared = sorted(overlap, key=lambda t: len(t), reverse=True)[:3]
                rel_reason = f"Shares {', '.join(shared)} with \"{anchor['title']}\""
                related.append((tool, len(overlap), reasons + [rel_reason]))

        related.sort(key=lambda x: x[1], reverse=True)
        top_related = related[:4]

        if top_related:
            sections.append({
                "anchor_title":    anchor["title"],
                "anchor_id":       anchor["id"],
                "anchor_category": anchor.get("category", ""),
                "recommendations": [
                    _make_suggestion(
                        t,
                        [next((r for r in rs if "Shares" in r), rs[-1] if rs else "Related topic")],
                    )
                    for t, _, rs in top_related
                ],
            })

    return sections


# ── Knowledge gap detection ───────────────────────────────────────────────────

def _find_knowledge_gaps(profile: dict) -> list[dict]:
    """Return 3-4 gaps: categories related to user's interests but underrepresented."""
    cat_counts = profile["cat_counts"]
    top_cats   = set(profile["top_cats"][:4])
    gaps: list[dict] = []

    for cat in top_cats:
        related = _CATEGORY_RELATIONSHIPS.get(cat, [])
        for rel_cat in related:
            already_covered = cat_counts.get(rel_cat, 0)
            if already_covered < 2 and rel_cat not in top_cats:
                gaps.append({
                    "area":   rel_cat,
                    "reason": f"Complements your {cat} knowledge — {already_covered or 'no'} sources so far.",
                })
    # Deduplicate and cap
    seen: set[str] = set()
    result: list[dict] = []
    for g in gaps:
        if g["area"] not in seen:
            seen.add(g["area"])
            result.append(g)
        if len(result) >= 4:
            break
    return result


# ── Interest summary ──────────────────────────────────────────────────────────

def _build_interest_summary(profile: dict) -> str:
    top = profile["top_cats"][:3]
    n   = profile["total"]
    tags = profile["top_tags"][:3]

    if not top:
        return f"Library with {n} source{'s' if n != 1 else ''}. Add more sources to build your interest profile."

    primary = top[0]
    if len(top) >= 2:
        secondary = top[1]
        summary = f"Your library focuses on {primary} and {secondary}"
    else:
        summary = f"Your library focuses on {primary}"

    if tags:
        summary += f", with strong interests in {', '.join(tags[:3])}"

    summary += f". {n} source{'s' if n != 1 else ''} saved."
    return summary


# ── Trending topics (local heuristic) ────────────────────────────────────────

def _get_trending(profile: dict, scored_tools: list[tuple]) -> list[str]:
    """Return top library tags by frequency, then fill with adjacent tool topics."""
    tag_counts = profile["tag_counts"]
    seen: set[str] = set()
    trending: list[str] = []

    # Primary: actual tags from the user's library, sorted by frequency
    for tag, _ in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True):
        if len(tag) >= 3 and tag not in _TAG_STOPWORDS and tag not in seen:
            seen.add(tag)
            trending.append(tag)
        if len(trending) >= 8:
            break

    # Fill remainder with high-scoring tool topic names
    for tool, score, _ in scored_tools[:15]:
        if score >= 2.0 and tool["topic"] not in seen:
            seen.add(tool["topic"])
            trending.append(tool["topic"])
        if len(trending) >= 12:
            break

    return trending[:12]


# ── Tool suggestion builder ───────────────────────────────────────────────────

def _make_suggestion(tool: dict, reasons: list[str], default_reason: str = "") -> dict:
    return {
        "topic":        tool["topic"],
        "description":  tool["description"],
        "reason":       "; ".join(reasons[:2]) if reasons else default_reason or "Matches your library interests",
        "category":     tool["category"],
        "search_query": tool.get("search_query", tool["topic"]),
        "url":          _tool_url(tool),
        "tags":         tool.get("tags", []),
    }


# ── Recent question sections (for Discover) ───────────────────────────────────

def _build_recent_query_sections(
    recent_sections: list[dict],
    sources: list[dict],
) -> list[dict]:
    """
    For each recent Ask NEXUS query (from interest_profile.get_recent_query_sections),
    score CURATED_TOOLS by overlap with that query's extracted tags/categories.
    Returns sections each shaped as {query, age_label, decay, recommendations}.
    """
    if not recent_sections:
        return []

    saved_domains = {
        urlparse(s.get("url", "")).netloc.lower().replace("www.", "")
        for s in sources
    }

    result = []
    for section in recent_sections:
        q_tags = {t.lower() for t in section.get("tags", [])}
        q_cats = set(section.get("categories", []))

        scored: list[tuple[dict, float]] = []
        for tool in CURATED_TOOLS:
            # Skip already saved
            if any(h.replace("www.", "") in saved_domains for h in tool.get("url_hints", [])):
                continue
            tool_tags = {t.lower() for t in tool.get("tags", [])}
            tool_cat  = tool.get("category", "")
            tag_match = len(tool_tags & q_tags)
            cat_match = 1.0 if tool_cat in q_cats else 0.0
            score = tag_match * 2.0 + cat_match * 3.0
            if score > 0:
                scored.append((tool, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        if scored:
            result.append({
                "query":           section["query"],
                "age_label":       section.get("age_label", ""),
                "decay":           section.get("decay", 1.0),
                "recommendations": [
                    _make_suggestion(t, [], f"Related to your question about {t['category'].lower()}")
                    for t, _ in scored[:5]
                ],
            })

    return result


# ── Learning paths ────────────────────────────────────────────────────────────

def _build_learning_paths(lib_profile: dict, user_profile=None) -> list[dict]:
    """Return the 2-3 learning paths most relevant to the user's interests."""
    top_tags = set(lib_profile.get("top_tags", [])[:10])
    top_cats = set(lib_profile.get("top_cats", [])[:6])

    # Build a lookup from topic name to full tool dict
    tool_lookup = {t["topic"]: t for t in CURATED_TOOLS}

    # Score each path
    scored_paths: list[tuple[dict, float]] = []
    for path in LEARNING_PATHS:
        path_tags = set(path.get("tags", []))
        path_cat  = path.get("category", "")
        tag_overlap = len(path_tags & top_tags)
        cat_overlap = 1.0 if path_cat in top_cats else 0.0

        # Profile bonus
        profile_bonus = 0.0
        if user_profile:
            liked_cats = getattr(user_profile, "liked_categories", {}) or {}
            if path_cat in liked_cats:
                profile_bonus += liked_cats[path_cat] * 3

        score = tag_overlap * 2.0 + cat_overlap * 3.0 + profile_bonus
        scored_paths.append((path, score))

    scored_paths.sort(key=lambda x: x[1], reverse=True)

    result = []
    for path, score in scored_paths[:3]:
        if score < 1.0:
            break
        tools = []
        for name in path["tool_names"]:
            tool = tool_lookup.get(name)
            if tool:
                tools.append(_make_suggestion(tool, [], f"Part of the {path['name']}"))
        if tools:
            result.append({
                "name":        path["name"],
                "description": path["description"],
                "category":    path["category"],
                "tools":       tools,
            })

    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_local_discover(
    sources: list[dict],
    user_profile=None,
    clusters: list[dict] | None = None,
) -> dict:
    """
    Fully local, AI-free discovery recommendations.
    Returns the same shape as the AI DiscoverResponse + `because_sections`,
    `recent_question_sections`, and `learning_paths`.

    user_profile: optional UserProfile ORM object (from services.interest_profile)
    """
    # Import here to avoid circular imports; interest_profile never imports from this module
    from services.interest_profile import compute_profile_score, get_recent_query_sections

    if not sources:
        return {
            "interest_summary":          "Add your first sources to unlock personalized discovery.",
            "top_interests":             [],
            "suggestions":               _starter_suggestions(),
            "knowledge_gaps":            [],
            "trending_in_your_space":    [],
            "because_sections":          [],
            "recent_question_sections":  [],
            "learning_paths":            [],
            "total_sources":             0,
            "starter_mode":              True,
        }

    lib_profile = _build_profile(sources)

    # Boost profile with signals extracted from user-created collection names
    if clusters:
        for cluster in clusters:
            name_tokens = {
                t for t in re.split(r'\W+', cluster.get("name", "").lower())
                if len(t) >= 3 and t not in _TAG_STOPWORDS
            }
            for token in name_tokens:
                lib_profile["tag_counts"][token] = (
                    lib_profile["tag_counts"].get(token, 0) + 2.0
                )

    # Score every curated tool (skip already saved)
    dismissed = {d.lower() for d in (getattr(user_profile, "dismissed_topics", None) or [])}
    scored: list[tuple[dict, float, list[str]]] = []
    for tool in CURATED_TOOLS:
        if _already_saved(tool, sources):
            continue
        if tool["topic"].lower() in dismissed:
            continue
        base, reasons = _score_tool(tool, lib_profile)
        profile_bonus  = compute_profile_score(tool, user_profile)
        total = base + profile_bonus
        if total > 0:
            scored.append((tool, total, reasons))
    scored.sort(key=lambda x: x[1], reverse=True)

    # Main suggestions
    suggestions = [
        _make_suggestion(tool, reasons)
        for tool, _, reasons in scored[:9]
    ]

    # Pad to at least 4
    if len(suggestions) < 4:
        used = {s["topic"] for s in suggestions}
        for tool in CURATED_TOOLS:
            if tool["topic"] not in used and not _already_saved(tool, sources):
                suggestions.append(_make_suggestion(tool, [], "Popular tool in this space"))
                if len(suggestions) >= 6:
                    break

    because_sections        = _build_because_sections(sources, scored)
    knowledge_gaps          = _find_knowledge_gaps(lib_profile)
    trending                = _get_trending(lib_profile, scored)
    recent_sections_raw     = get_recent_query_sections(user_profile)
    recent_question_sections = _build_recent_query_sections(recent_sections_raw, sources)
    learning_paths          = _build_learning_paths(lib_profile, user_profile)

    return {
        "interest_summary":          _build_interest_summary(lib_profile),
        "top_interests":             lib_profile["top_tags"][:10],
        "suggestions":               suggestions,
        "knowledge_gaps":            knowledge_gaps,
        "trending_in_your_space":    trending,
        "because_sections":          because_sections,
        "recent_question_sections":  recent_question_sections,
        "learning_paths":            learning_paths,
        "total_sources":             len(sources),
        "starter_mode":              len(sources) < 3,
    }


def _starter_suggestions() -> list[dict]:
    """Return a broad starter set when library is empty."""
    starters = [
        "Cursor AI", "shadcn/ui", "Supabase", "GitHub Actions",
        "Obsidian", "roadmap.sh", "PlatformIO", "Hugging Face",
    ]
    result = []
    for name in starters:
        tool = next((t for t in CURATED_TOOLS if t["topic"] == name), None)
        if tool:
            result.append(_make_suggestion(
                tool, [],
                "Popular tool — save sources to get personalized recommendations",
            ))
    return result


def search_discover(query: str, sources: list[dict]) -> dict:
    """
    Search library sources and curated tools by a text query.
    Returns ranked results with reasons.
    """
    q = query.lower().strip()
    if not q:
        return {"library_hits": [], "tool_hits": [], "query": query}

    q_tokens = set(re.split(r'\W+', q)) - {"", "a", "the", "is", "in", "of", "for"}

    # Library hits
    library_hits: list[tuple[dict, int]] = []
    for s in sources:
        text = " ".join([
            s.get("title") or "",
            s.get("category") or "",
            " ".join(s.get("tags") or []),
            s.get("summary") or "",
        ]).lower()
        tokens = set(re.split(r'\W+', text)) - {"", "a", "the"}
        overlap = len(q_tokens & tokens)
        if overlap:
            library_hits.append((s, overlap))
    library_hits.sort(key=lambda x: x[1], reverse=True)

    # Curated tool hits
    tool_hits: list[tuple[dict, int]] = []
    for tool in CURATED_TOOLS:
        text = " ".join([
            tool["topic"],
            tool["description"],
            " ".join(tool.get("tags", [])),
            tool.get("category", ""),
        ]).lower()
        tokens = set(re.split(r'\W+', text)) - {"", "a", "the"}
        overlap = len(q_tokens & tokens)
        if overlap >= 1:
            tool_hits.append((tool, overlap))
    tool_hits.sort(key=lambda x: x[1], reverse=True)

    return {
        "query":       query,
        "library_hits": [s for s, _ in library_hits[:6]],
        "tool_hits": [
            {
                "topic":        t["topic"],
                "description":  t["description"],
                "reason":       f"Matches '{query}'",
                "category":     t["category"],
                "search_query": t.get("search_query", t["topic"]),
            }
            for t, _ in tool_hits[:6]
        ],
    }
