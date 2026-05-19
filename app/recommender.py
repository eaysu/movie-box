"""Layer 4 — similarity search over the film catalog.

The catalog is a set of films pre-embedded by `scripts/build_catalog.py`.
A user's "taste vector" is the mean of their watchlist film vectors; the
nearest catalog films (cosine similarity) become the candidate pool that
the LLM layer then curates.
"""

import json
from pathlib import Path

import numpy as np

from .config import Settings
from .embeddings import Embedder


def _norm_title(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


class CatalogNotBuilt(Exception):
    """Raised when the recommender is used before the catalog exists."""


class Recommender:
    """Holds the catalog in memory and answers nearest-neighbour queries."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.films: list[dict] = []
        self.vectors: np.ndarray = np.zeros((0, 1), dtype=np.float32)
        self.embedder: Embedder | None = None
        self._load()

    def _load(self) -> None:
        cat_path: Path = self.settings.catalog_path
        vec_path: Path = self.settings.catalog_vectors_path
        emb_path: Path = self.settings.data_path / "embedder.pkl"

        if not (cat_path.exists() and vec_path.exists() and emb_path.exists()):
            raise CatalogNotBuilt(
                "Catalog not found. Build it first:\n"
                "  python -m scripts.build_catalog --source sample"
            )

        self.films = json.loads(cat_path.read_text(encoding="utf-8"))
        self.vectors = np.load(vec_path)
        self.embedder = Embedder.load(emb_path)

    @property
    def size(self) -> int:
        return len(self.films)

    def taste_vector(self, watchlist: list) -> np.ndarray:
        """Average the embeddings of every watchlist film into one vector."""
        blobs = [self._blob(f) for f in watchlist]
        blobs = [b for b in blobs if b]
        if not blobs:
            raise ValueError("Watchlist produced no usable text to embed.")
        vecs = self.embedder.embed(blobs)
        mean = vecs.mean(axis=0, keepdims=True)
        norm = np.linalg.norm(mean)
        return mean / norm if norm else mean

    def recommend(self, watchlist: list, pool_size: int) -> list[dict]:
        """Return the `pool_size` catalog films closest to the user's taste."""
        taste = self.taste_vector(watchlist)
        scores = (self.vectors @ taste.T).ravel()  # cosine, vectors are normalised

        # Exclude anything already on the watchlist.
        seen = {_norm_title(self._title(f)) for f in watchlist}
        seen_ids = {self._tmdb_id(f) for f in watchlist if self._tmdb_id(f)}

        ranked = np.argsort(-scores)
        out: list[dict] = []
        for idx in ranked:
            film = self.films[int(idx)]
            if _norm_title(film.get("title", "")) in seen:
                continue
            if film.get("tmdb_id") and film["tmdb_id"] in seen_ids:
                continue
            out.append({**film, "similarity": round(float(scores[idx]), 4)})
            if len(out) >= pool_size:
                break
        return out

    # --- helpers: accept either dicts or EnrichedFilm objects ---
    @staticmethod
    def _blob(f) -> str:
        if hasattr(f, "text_blob"):
            return f.text_blob
        if isinstance(f, dict):
            return f.get("text_blob") or f.get("title", "")
        return str(f)

    @staticmethod
    def _title(f) -> str:
        return f.title if hasattr(f, "title") else f.get("title", "")

    @staticmethod
    def _tmdb_id(f):
        return f.tmdb_id if hasattr(f, "tmdb_id") else f.get("tmdb_id")
