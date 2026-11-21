"""Command-Line Interface (CLI) for batch clinical summarization of FHIR R4 Bundles.

Usage:
    python -m app.ai.cli --input ./data/fhir_bundles --output ./data/summaries
    python -m app.ai.summarizer --input ./data/fhir_bundles/bundle.json --output ./data/summaries
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

from app.ai.providers.factory import get_llm_provider
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.models.database import get_session_factory, init_db
from app.services.clinical_summarization_service import ClinicalSummarizationService

logger = get_logger(__name__)


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for clinical summarization."""
    parser = argparse.ArgumentParser(
        description="EHR Intelligence Platform - AI Clinical Summarization Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to a single FHIR Bundle JSON file or directory containing FHIR Bundle JSON files",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Directory to save generated clinical summary JSON files",
    )
    parser.add_argument(
        "--provider",
        "-p",
        choices=["ollama", "anthropic", "openai", "mock"],
        default=None,
        help="Override active LLM provider (defaults to LLM_PROVIDER in settings)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="Override active LLM model name",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass cached summaries and force fresh LLM inference",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console logging level",
    )
    return parser.parse_args(args)


async def run_cli_async(args: argparse.Namespace) -> int:
    """Execute asynchronous CLI clinical summarization workflow."""
    setup_logging(args.log_level)
    settings = get_settings()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        logger.error("Input path does not exist: %s", input_path)
        return 1

    # Locate bundle files
    bundle_files: List[Path] = []
    if input_path.is_file():
        bundle_files.append(input_path)
    elif input_path.is_dir():
        for f in input_path.rglob("*.json"):
            if not f.name.endswith("_summary.json"):
                bundle_files.append(f)

    if not bundle_files:
        logger.warning("No JSON files found in input path: %s", input_path)
        return 0

    logger.info("Found %d FHIR Bundle file(s) to process", len(bundle_files))

    # Initialize database
    await init_db(database_path=settings.DATABASE_PATH)
    session_factory = get_session_factory(settings.sqlite_url)

    provider_override = args.provider or settings.LLM_PROVIDER
    provider = get_llm_provider(
        settings,
        provider_name=provider_override,
        model_name=args.model,
    )

    logger.info("Using LLM Provider: [%s], Model: [%s]", provider.provider_name, provider.model_name)

    # Health check
    health = await provider.check_health()
    if not health.get("available") and provider_override != "mock":
        logger.warning(
            "Provider health check reported: %s (Details: %s)",
            health.get("status"),
            health.get("details"),
        )

    processed_count = 0
    cached_count = 0
    failed_count = 0
    consolidated_summaries: List[Dict[str, Any]] = []

    async with session_factory() as session:
        service = ClinicalSummarizationService(
            session=session,
            settings=settings,
            provider=provider,
        )

        for b_file in bundle_files:
            try:
                with open(b_file, "r", encoding="utf-8") as f:
                    bundle_data = json.load(f)

                if bundle_data.get("resourceType") != "Bundle":
                    logger.debug("Skipping non-bundle file: %s", b_file.name)
                    continue

                summary, was_cached, lat_ms = await service.summarize_bundle(
                    bundle_data=bundle_data,
                    force_refresh=args.force_refresh,
                )

                processed_count += 1
                if was_cached:
                    cached_count += 1

                summary_dict = summary.model_dump()
                consolidated_summaries.append(summary_dict)

                # Save individual summary file
                out_file = output_dir / f"{summary.patient_id}_summary.json"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(summary_dict, f, indent=2, ensure_ascii=False)

                status_str = "CACHE_HIT" if was_cached else "INFERRED"
                print(
                    f"[{status_str}] Patient: {summary.patient_id:<16} | "
                    f"Words: {summary.word_count:<3} | "
                    f"Conf: {summary.confidence.level.value:<8} | "
                    f"Time: {lat_ms:6.1f}ms | Output: {out_file.name}"
                )

            except Exception as exc:
                failed_count += 1
                logger.error("Failed to summarize bundle %s: %s", b_file.name, exc)

        await session.commit()

    if hasattr(provider, "aclose"):
        await provider.aclose()

    # Save consolidated batch report
    consolidated_file = output_dir / "consolidated_batch_summary.json"
    with open(consolidated_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_processed": processed_count,
                "cache_hits": cached_count,
                "failed": failed_count,
                "provider": provider.provider_name,
                "model": provider.model_name,
                "summaries": consolidated_summaries,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print("\n" + "=" * 60)
    print(f"Batch Processing Complete: {processed_count} succeeded ({cached_count} from cache), {failed_count} failed")
    print(f"Consolidated summary output saved to: {consolidated_file}")
    print("=" * 60)

    return 0 if failed_count == 0 else 1


def main() -> None:
    """CLI synchronous entry point."""
    args = parse_args()
    exit_code = asyncio.run(run_cli_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
