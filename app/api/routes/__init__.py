from fastapi import APIRouter
from app.api.routes.fhir import router as fhir_router
from app.api.routes.health import router as health_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.summarization import router as summarization_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(ingestion_router)
api_router.include_router(fhir_router)
api_router.include_router(summarization_router)

__all__ = ["api_router"]
