"""Dense clinical embeddings generator using Sentence Transformers.

Implements cached singleton lifecycle, L2 vector normalization for cosine similarity,
and thread-safe inference warmup.
"""

from functools import lru_cache
import threading
from typing import List, Optional

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingGenerator:
    """Thread-safe transformer embeddings generator using sentence-transformers.

    Normalized embeddings are guaranteed so that dot product equals cosine similarity.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._model = None
        self._lock = threading.Lock()
        self._load_model()

    def _load_model(self) -> None:
        """Load SentenceTransformer model weights once into memory."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info("Loading SentenceTransformer model [%s]...", self.model_name)
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(self.model_name)
                    logger.info("Successfully loaded SentenceTransformer model [%s]", self.model_name)

    def generate_embeddings(
        self, texts: List[str], batch_size: int = 32
    ) -> List[List[float]]:
        """Generate dense, L2-normalized vector embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.
            batch_size: Batch size for model inference.

        Returns:
            List of 384-dimensional float lists with unit norm.
        """
        if not texts:
            return []

        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def generate_single_embedding(self, text: str) -> List[float]:
        """Generate a single L2-normalized vector embedding."""
        res = self.generate_embeddings([text])
        return res[0] if res else []

    def warmup(self) -> None:
        """Warm up the model weights and CPU cache with a dummy encoding at startup."""
        try:
            _ = self.generate_single_embedding("warmup clinical text")
            logger.info("EmbeddingGenerator [%s] warmup completed successfully.", self.model_name)
        except Exception as exc:
            logger.warning("EmbeddingGenerator warmup encountered warning: %s", exc)


_GLOBAL_EMBEDDING_GENERATOR: Optional[EmbeddingGenerator] = None
_INIT_LOCK = threading.Lock()


def get_embedding_generator(model_name: Optional[str] = None) -> EmbeddingGenerator:
    """Retrieve or initialize the global cached singleton EmbeddingGenerator."""
    global _GLOBAL_EMBEDDING_GENERATOR
    if _GLOBAL_EMBEDDING_GENERATOR is None:
        with _INIT_LOCK:
            if _GLOBAL_EMBEDDING_GENERATOR is None:
                settings = get_settings()
                chosen_model = model_name or settings.EMBEDDING_MODEL
                _GLOBAL_EMBEDDING_GENERATOR = EmbeddingGenerator(model_name=chosen_model)
    return _GLOBAL_EMBEDDING_GENERATOR
