import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database.db import init_db
from services.embeddings import embedding_service
from routers import sites, ingest, search, export, clusters, insights, discover, profile
from routers.auth import router as auth_router
from routers.oauth import router as oauth_router
from routers.extension import router as extension_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nexus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("━━━ NEXUS BACKEND STARTING ━━━")

    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET is not set. "
            "Local: add JWT_SECRET to your .env file. "
            "Render: set it in Environment Variables (or use render.yaml generateValue). "
            "Generate a value with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

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
    allow_origin_regex=r"(chrome-extension://.*|https://nexus-frontend[^.]*\.vercel\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(extension_router)
app.include_router(sites.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(export.router)
app.include_router(clusters.router)
app.include_router(insights.router)
app.include_router(discover.router)
app.include_router(profile.router)


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
