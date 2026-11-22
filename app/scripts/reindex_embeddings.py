"""CLI management script to backfill and re-index vector embeddings for all EHR data.

Usage:
    python -m app.scripts.reindex_embeddings [--reset] [--batch-size 32]
"""

import argparse
import asyncio
import sys
import time

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.models.database import get_session_factory, init_db
from app.search.indexing import IndexingService
from app.search.vector_store import get_vector_store

logger = get_logger("reindex_embeddings")


async def run_reindexing(reset: bool = False, batch_size: int = 32) -> int:
    """Execute backfill re-indexing across all stored FHIR bundles and clinical summaries."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    logger.info("Initializing database connection at [%s]...", settings.DATABASE_PATH)
    await init_db(database_path=settings.DATABASE_PATH)

    vector_store = get_vector_store(settings)
    if reset:
        logger.warning("Reset flag detected: clearing existing vectors from collection...")
        vector_store.reset()

    indexing_service = IndexingService(
        vector_store=vector_store,
        settings=settings,
    )

    session_factory = get_session_factory(settings.sqlite_url)
    async with session_factory() as session:
        metrics = await indexing_service.reindex_all(session=session, batch_size=batch_size)

    print("\n" + "=" * 60)
    print("  Vector Embeddings Re-indexing Backfill Summary")
    print("=" * 60)
    print(f"  FHIR Bundles Indexed:      {metrics.get('bundles', 0)}")
    print(f"  Clinical Summaries Indexed: {metrics.get('summaries', 0)}")
    print(f"  Total Vector Chunks:       {metrics.get('total_vectors', 0)}")
    print(f"  Active Collection Size:    {vector_store.count()} vectors")
    print(f"  Persistence Directory:     {settings.VECTOR_STORE_PATH}")
    print("=" * 60 + "\n")

    return 0


def main() -> None:
    """Parse CLI arguments and run backfill."""
    parser = argparse.ArgumentParser(
        description="Re-index dense embeddings for all FHIR documents and clinical summaries."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset and wipe existing vector store collection before backfilling",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Inference batch size for embedding generation (default: 32)",
    )

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run_reindexing(reset=args.reset, batch_size=args.batch_size))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nReindexing cancelled by user.")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Critical error during vector re-indexing: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
