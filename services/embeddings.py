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
            " ".join(site_data.get("tags") or []),
            " ".join(site_data.get("topics") or []),
            " ".join(site_data.get("technologies") or []),
            site_data.get("category", ""),
            site_data.get("use_case", ""),
            site_data.get("notes", ""),
        ]
        text = " | ".join(p for p in parts if p).strip()
        metadata_richness = sum(len(p) for p in parts[1:] if p)
        raw = (site_data.get("raw_content") or "")[:800]
        if raw and metadata_richness < 60:
            text = f"{text} | {raw}"
        return text

    def embed_text(self, text: str) -> List[float]:
        return self._get_model().encode(text, normalize_embeddings=True).tolist()

    def upsert(self, site_id: str, site_data: dict, user_id: Optional[str] = None) -> str:
        text = self._build_text(site_data)
        vector = self.embed_text(text)
        collection = self._get_collection()
        chroma_id = f"site_{site_id}"
        metadata: dict = {
            "site_id":  site_id,
            "title":    site_data.get("title", ""),
            "url":      site_data.get("url", ""),
            "category": site_data.get("category", ""),
        }
        if user_id:
            metadata["user_id"] = user_id
        collection.upsert(
            ids=[chroma_id],
            embeddings=[vector],
            metadatas=[metadata],
            documents=[text],
        )
        logger.info(f"Upserted vector for site {site_id} (user={user_id})")
        return chroma_id

    def search(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict] = None,
        user_id: Optional[str] = None,
    ) -> List[dict]:
        query_vector = self.embed_text(query)
        collection   = self._get_collection()
        count        = collection.count()
        if count == 0:
            return []
        n_results = min(n_results, count)

        # Build where clause
        where_clause: Optional[dict] = None
        if user_id and where:
            where_clause = {"$and": [{"user_id": user_id}, where]}
        elif user_id:
            where_clause = {"user_id": user_id}
        elif where:
            where_clause = where

        kwargs: dict = {
            "query_embeddings": [query_vector],
            "n_results":        n_results,
            "include":          ["metadatas", "distances", "documents"],
        }
        if where_clause:
            kwargs["where"] = where_clause

        try:
            results = collection.query(**kwargs)
        except Exception as e:
            # ChromaDB can error if where filter matches nothing — fall back without filter
            logger.warning(f"ChromaDB query error (falling back without filter): {e}")
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=n_results,
                include=["metadatas", "distances", "documents"],
            )

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

    def stats(self, user_id: Optional[str] = None) -> dict:
        collection = self._get_collection()
        if user_id:
            try:
                result = collection.get(where={"user_id": user_id}, include=[])
                return {"total_vectors": len(result["ids"])}
            except Exception:
                pass
        return {"total_vectors": collection.count()}


embedding_service = EmbeddingService()
