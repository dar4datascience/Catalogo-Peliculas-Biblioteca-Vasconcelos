"""
Shared multilingual sentence embedding singleton.

Uses paraphrase-multilingual-MiniLM-L12-v2 (384-dim) which natively supports
Spanish and English — critical for matching Spanish catalog titles against
English TMDB/OMDB titles.

Both TMDBDuckDB and OMDBDuckDBScorer import from here to avoid loading
the model more than once per process.
"""

from __future__ import annotations

from typing import List

_model = None
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384


def get_model():
    """Return the shared SentenceTransformer model, loading it on first call."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts: List[str]) -> List[List[float]]:
    """
    Embed a list of strings and return normalized float vectors.

    Args:
        texts: List of strings to embed.

    Returns:
        List of 384-dimensional float lists (L2-normalized).
    """
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_one(text: str) -> List[float]:
    """Convenience wrapper to embed a single string."""
    results = embed([text])
    return results[0] if results else []
