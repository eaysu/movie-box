"""Layer 3 — turn film text into vectors.

Two interchangeable backends:

  * "tfidf"                 — lightweight, no heavy dependencies. The
                              vectorizer must be *fitted* on the catalog and
                              then *reused* (saved/loaded) for the watchlist,
                              so the two live in the same vector space.
  * "sentence-transformers" — semantic embeddings, far better quality, but
                              needs `pip install sentence-transformers`.
                              Stateless: no fitting required.

All vectors are L2-normalised, so a dot product equals cosine similarity.
"""

import pickle
from pathlib import Path

import numpy as np

_ST_MODEL_CACHE: dict = {}  # process-wide cache for the heavy ST model


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class Embedder:
    """Pluggable text -> vector encoder."""

    def __init__(self, provider: str = "tfidf", st_model: str = "all-MiniLM-L6-v2"):
        self.provider = provider
        self.st_model = st_model
        self._vectorizer = None  # TfidfVectorizer, when provider == "tfidf"
        self._fitted = False

    # --- fitting (only the tfidf backend needs it) ---
    def fit(self, corpus: list[str]) -> "Embedder":
        if self.provider == "tfidf":
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(
                stop_words="english",
                max_features=8000,
                ngram_range=(1, 2),
                sublinear_tf=True,
            )
            self._vectorizer.fit(corpus or ["placeholder"])
        self._fitted = True
        return self

    # --- encoding ---
    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)

        if self.provider == "tfidf":
            if self._vectorizer is None:
                raise RuntimeError(
                    "tfidf embedder used before fit(). Build the catalog first."
                )
            matrix = self._vectorizer.transform(texts).toarray().astype(np.float32)
            return _l2_normalize(matrix)

        if self.provider == "sentence-transformers":
            model = self._get_st_model()
            matrix = model.encode(
                texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True
            ).astype(np.float32)
            return _l2_normalize(matrix)

        raise ValueError(f"Unknown embedding provider: {self.provider!r}")

    def _get_st_model(self):
        if self.st_model not in _ST_MODEL_CACHE:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "EMBEDDING_PROVIDER=sentence-transformers but the package "
                    "is not installed. Run: pip install sentence-transformers"
                ) from exc
            _ST_MODEL_CACHE[self.st_model] = SentenceTransformer(self.st_model)
        return _ST_MODEL_CACHE[self.st_model]

    # --- persistence ---
    def save(self, path: Path) -> None:
        """Persist the fitted state so the catalog and watchlist share a space."""
        with open(path, "wb") as fh:
            pickle.dump(
                {
                    "provider": self.provider,
                    "st_model": self.st_model,
                    "vectorizer": self._vectorizer,
                },
                fh,
            )

    @classmethod
    def load(cls, path: Path) -> "Embedder":
        with open(path, "rb") as fh:
            state = pickle.load(fh)
        emb = cls(provider=state["provider"], st_model=state["st_model"])
        emb._vectorizer = state["vectorizer"]
        emb._fitted = True
        return emb
