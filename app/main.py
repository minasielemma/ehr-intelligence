"""FastAPI application entry point for the EHR Intelligence Platform.

Configures application lifespan, centralized settings, CORS, exception handling,
and API routing.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import api_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle events."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    logger.info("Starting %s v%s in [%s] mode", settings.APP_NAME, __version__, settings.APP_ENV)
    logger.info("Structured storage target: %s", settings.DATABASE_PATH)
    logger.info("Vector database target: %s", settings.chroma_url)
    logger.info("API prefix: %s", settings.API_V1_PREFIX)

    try:
        from app.models.database import init_db
        await init_db(database_path=settings.DATABASE_PATH)
    except Exception as exc:
        logger.error("Failed to initialize database tables: %s", exc)

    try:
        from app.search.embeddings import get_embedding_generator
        from app.search.vector_store import get_vector_store
        v_store = get_vector_store(settings)
        emb_gen = get_embedding_generator(settings.EMBEDDING_MODEL)
        emb_gen.warmup()
        logger.info("Semantic search vector store initialized (active vectors: %d)", v_store.count())
    except Exception as exc:
        logger.warning("Semantic search warmup encountered issue: %s", exc)

    yield

    logger.info("Shutting down %s gracefully...", settings.APP_NAME)


def create_application() -> FastAPI:
    """Application factory for FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        description="Modular Monolith AI-Powered EHR Intelligence Platform",
        debug=settings.DEBUG,
        lifespan=lifespan,
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    app.include_router(health_router, prefix="", tags=["System Health"])
    from app.api.routes.search import router as search_router
    app.include_router(search_router, prefix="", tags=["Semantic Search"])

    @app.get("/", status_code=status.HTTP_200_OK, tags=["Root"])
    async def root_index() -> Dict[str, str]:
        """Root API metadata endpoint."""
        return {
            "name": settings.APP_NAME,
            "version": __version__,
            "environment": settings.APP_ENV,
            "status": "online",
            "docs_url": f"{settings.API_V1_PREFIX}/docs",
            "health_url": "/health",
        }

    return app


app = create_application()
