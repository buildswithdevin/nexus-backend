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
