"""Dense clinical embeddings generator interface.

Architectural placeholder for generating vector representations of medical notes,
diagnoses, and clinical narratives. Model loading and inference to be implemented in Phase 2+.
"""

from typing import List


class EmbeddingGenerator:
    """Interface for generating text embeddings using transformer models."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate dense vector embeddings (placeholder)."""
        raise NotImplementedError("Embedding generation will be implemented in subsequent phases.")
