"""Sentence-transformer embedding generation with version tracking."""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
    return SentenceTransformer(settings.EMBEDDING_MODEL)


def get_embedding_version() -> str:
    """Compute a version string from model name + dimension.

    This serves as a fingerprint — if the model or dimension changes,
    the version changes, and the system can detect incompatible vectors.
    """
    version_input = f"{settings.EMBEDDING_MODEL}:{settings.EMBEDDING_DIMENSION}"
    return hashlib.sha256(version_input.encode()).hexdigest()[:12]


def get_embedding_info() -> dict:
    """Return current embedding model metadata."""
    return {
        "model": settings.EMBEDDING_MODEL,
        "dimension": settings.EMBEDDING_DIMENSION,
        "version": get_embedding_version(),
    }


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def generate_single_embedding(text: str) -> list[float]:
    """Generate embedding for a single text."""
    return generate_embeddings([text])[0]
