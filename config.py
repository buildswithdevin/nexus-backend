from pydantic_settings import BaseSettings
from typing import List
import os
import secrets


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./data/nexus.db"
    chroma_path: str = "./data/chroma"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:5173,https://nexus-frontend-five-swart.vercel.app"
    scraper_timeout: int = 15
    max_content_length: int = 8000

    # Auth
    jwt_secret: str = secrets.token_hex(32)   # override via env var in production
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30

    # URLs (used for OAuth callbacks)
    backend_url:  str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # OAuth — set in Render env vars
    google_client_id:      str = ""
    google_client_secret:  str = ""
    microsoft_client_id:   str = ""
    microsoft_client_secret: str = ""
    github_client_id:      str = ""
    github_client_secret:  str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
os.makedirs(settings.chroma_path, exist_ok=True)
os.makedirs("./data", exist_ok=True)
