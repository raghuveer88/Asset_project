from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_default_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    database_url: str | None = None
    allowed_origins: str = "http://localhost:4200,http://127.0.0.1:4200"
    enable_ingest_endpoint: bool = False
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_database: str = "las_assets"
    mysql_user: str = "las_assets_user"
    mysql_password: str = "las_assets_password"
    chroma_persist_dir: str = "./storage/chroma"
    scraped_content_dir: str = "./storage/scraped_sites"
    retrieval_min_similarity: float = 0.18
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "Asset AI project"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return the configured SQLAlchemy URL, preferring DATABASE_URL when set."""
        if self.database_url:
            return self.database_url
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )

    @property
    def allowed_models(self) -> List[str]:
        """Return the chat model allow-list used to validate runtime model selection."""
        return ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o", "gpt-4.1"]

    @property
    def allowed_origin_list(self) -> List[str]:
        """Return comma-separated CORS origins from environment-backed settings."""
        origins = [origin.strip() for origin in self.allowed_origins.split(",")]
        return [origin for origin in origins if origin]

    @property
    def backend_root(self) -> Path:
        """Return the backend directory so relative storage paths resolve consistently."""
        return Path(__file__).resolve().parents[1]

    def resolve_backend_path(self, value: str) -> Path:
        """Resolve a storage path relative to the backend root unless it is absolute."""
        path = Path(value)
        return path if path.is_absolute() else self.backend_root / path


@lru_cache
def get_settings() -> Settings:
    """Load and cache environment-backed settings without exposing secret values."""
    return Settings()
