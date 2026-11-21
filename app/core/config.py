"""Centralized application configuration using Pydantic Settings (Pydantic v2).

Provides type validation, default fallback values, and environment variable loading.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Union

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    APP_NAME: str = Field(default="EHR Intelligence Platform", description="Name of the application")
    APP_ENV: str = Field(default="development", description="Application environment: development, staging, production")
    DEBUG: bool = Field(default=True, description="Debug mode flag")
    API_V1_PREFIX: str = Field(default="/api/v1", description="Prefix for API v1 routes")
    LOG_LEVEL: str = Field(default="INFO", description="Standard logging level")

    BACKEND_PORT: int = Field(default=8000, description="Port the FastAPI backend listens on")
    FRONTEND_PORT: int = Field(default=3001, description="Host port the frontend is mapped to")
    CHROMA_HOST_PORT: int = Field(default=8001, description="Host port ChromaDB is mapped to for local access")

    DATABASE_PATH: str = Field(
        default="/app/data/storage/ehr.db",
        description="Filesystem path to the SQLite structured database file",
    )

    VECTOR_DB_HOST: str = Field(default="chromadb", description="Host/service name for ChromaDB")
    VECTOR_DB_PORT: int = Field(default=8000, description="Internal service port for ChromaDB")
    VECTOR_DB_PATH: str = Field(default="/chroma/data", description="Filesystem storage path for ChromaDB")

    LLM_PROVIDER: str = Field(default="ollama", description="Active LLM provider: ollama, anthropic, openai")
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL for local Ollama server (e.g. http://localhost:11434 or http://host.docker.internal:11434)",
    )
    OLLAMA_MODEL: str = Field(
        default="gemma3:12b",
        description="Model name to run on local Ollama server (e.g. gemma3:12b, llama3.1:8b)",
    )
    LLM_TEMPERATURE: float = Field(default=0.1, ge=0.0, le=2.0, description="Sampling temperature for clinical inference")
    LLM_TIMEOUT: int = Field(default=120, ge=5, le=600, description="Request timeout in seconds for LLM generation")
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=1000, ge=100, le=8192, description="Maximum completion tokens")
    LLM_MAX_RETRIES: int = Field(default=3, ge=1, le=10, description="Maximum bounded retry attempts on transient LLM failures")
    LLM_BACKOFF_FACTOR: float = Field(default=1.5, ge=1.0, le=5.0, description="Exponential backoff multiplier")
    LLM_CONCURRENCY_LIMIT: int = Field(
        default=2,
        ge=1,
        le=16,
        description="Max concurrent inference requests to avoid overwhelming local Ollama",
    )
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API authentication key")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini", description="OpenAI model identifier")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API authentication key")
    ANTHROPIC_MODEL: str = Field(default="claude-3-5-sonnet-20241022", description="Anthropic Claude model identifier")

    PROMPT_VERSION: str = Field(default="v1.0.0", description="Version of the clinical summarization prompt")
    SUMMARY_CACHE_TTL_SECONDS: Optional[int] = Field(
        default=None,
        description="Optional time-to-live in seconds for clinical summary cache entries (None = indefinite until invalidated)",
    )
    REDACT_PHI_BEFORE_LLM: bool = Field(
        default=True,
        description="Redact or pseudonymize direct patient identifiers before sending prompt to LLM",
    )

    EMBEDDING_MODEL: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace model identifier for generating dense embeddings",
    )

    CORS_ORIGINS: Union[List[str], str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ],
        description="Allowed CORS origins",
    )

    REQUIRE_AUTH: bool = Field(
        default=False,
        description="Enforce API key verification across protected endpoints",
    )
    API_KEYS: Union[List[str], str] = Field(
        default=["dev-test-key", "prod-default-key"],
        description="List of valid API keys for authentication",
    )
    API_KEY_HEADER_NAME: str = Field(
        default="X-API-Key",
        description="HTTP header name used for API Key authentication",
    )

    MAX_UPLOAD_SIZE_BYTES: int = Field(
        default=100 * 1024 * 1024,  # 100 MB
        description="Maximum permissible upload size in bytes for EHR file ingestion",
    )
    ALLOWED_UPLOAD_EXTENSIONS: List[str] = Field(
        default=[".json", ".csv", ".txt", ".zip", ".tar.gz", ".tgz", ".ndjson"],
        description="Permitted file extensions for ingestion uploads",
    )
    MAX_DECOMPRESSED_SIZE_BYTES: int = Field(
        default=500 * 1024 * 1024,  # 500 MB
        description="Maximum permissible uncompressed size in bytes for package extraction",
    )
    MAX_DECOMPRESSION_RATIO: float = Field(
        default=100.0,
        description="Maximum allowable compression ratio to prevent zip bombs",
    )
    INGESTION_BATCH_SIZE: int = Field(
        default=500,
        description="Batch size for chunked record parsing and database persistence",
    )
    STORAGE_UPLOAD_DIR: str = Field(
        default="/app/data/input",
        description="Filesystem path for temporary raw upload staging",
    )
    STORAGE_PROCESSED_DIR: str = Field(
        default="/app/data/processed",
        description="Filesystem path for archiving processed source files",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Normalize comma-separated strings into a list of valid origins."""
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return []

    @field_validator("API_KEYS", mode="before")
    @classmethod
    def assemble_api_keys(cls, v: Union[str, List[str]]) -> List[str]:
        """Normalize comma-separated strings into a list of valid API keys."""
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return []


    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level string."""
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        upper_v = v.upper()
        if upper_v not in allowed:
            raise ValueError(f"Invalid log level: {v}. Must be one of {allowed}")
        return upper_v

    @field_validator("LLM_PROVIDER")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        """Validate supported LLM provider."""
        allowed = {"ollama", "anthropic", "openai", "mock"}
        lower_v = v.lower()
        if lower_v not in allowed:
            raise ValueError(f"Invalid LLM_PROVIDER: '{v}'. Must be one of {allowed}")
        return lower_v

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Enforce strict fail-closed security standards when running in production."""
        if self.APP_ENV.lower() == "production" and not self.REQUIRE_AUTH:
            raise ValueError("REQUIRE_AUTH must be True when APP_ENV is 'production'")
        return self

    @property
    def is_development(self) -> bool:
        """Return True if running in development mode."""
        return self.APP_ENV.lower() == "development"

    @property
    def chroma_url(self) -> str:
        """Return the base URL for the ChromaDB service."""
        return f"http://{self.VECTOR_DB_HOST}:{self.VECTOR_DB_PORT}"

    @property
    def sqlite_url(self) -> str:
        """Return the SQLAlchemy SQLite connection string."""
        return f"sqlite+aiosqlite:///{self.DATABASE_PATH}"


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
