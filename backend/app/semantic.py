"""No-cost latent semantic signals for Movienotes.

This is deliberately not an external embedding API. A compact LSA projection is
fitted over the films already being compared, then cosine distance is measured
in that latent space. It adds theme/overview context to the explicit metadata
signals without storing private viewing text or adding per-film API spend.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize


def film_semantic_text(film) -> str:
    """Natural-language layer only; genres/directors stay explicit signals."""
    overview = str(getattr(film, "overview", "") or "").strip()
    keywords = [str(value).strip() for value in (getattr(film, "keywords", []) or [])]
    # A keyword-only row is useful but gets little semantic authority because
    # the caller receives its coverage score separately.
    return " ".join(part for part in [overview, " ".join(keywords)] if part).strip()


def taste_semantic_text(taste: dict | None) -> str:
    """Small persisted taste document used by Sinefil Sineması.

    Directory cards must not fetch every member's private watch history. Their
    existing persisted top themes provide a safe, bounded document instead.
    """
    taste = taste or {}
    values: list[str] = []
    for key in ("top_keywords", "top_genres", "top_directors"):
        values.extend(str(value).strip() for value in (taste.get(key) or []) if value)
    return " ".join(values).strip()


def _latent_matrix(documents: list[str]) -> np.ndarray | None:
    usable = [document for document in documents if document.strip()]
    if len(usable) < 3:
        return None
    try:
        matrix = TfidfVectorizer(
            ngram_range=(1, 2), max_features=12_000, sublinear_tf=True
        ).fit_transform(documents)
    except ValueError:
        return None
    smallest_axis = min(matrix.shape)
    if smallest_axis < 3:
        return None
    # LSA smooths word-level matches through co-occurring synopsis terms. It is
    # compact enough for the 0.5 CPU Render instance and deterministic here.
    components = min(32, smallest_axis - 1)
    if components < 2:
        return None
    try:
        dense = TruncatedSVD(n_components=components, random_state=17).fit_transform(matrix)
    except ValueError:
        return None
    return normalize(dense)


def weighted_profile_scores(
    liked, candidates, *, positive_weights: Iterable[float], negative_weights: Iterable[float]
) -> tuple[np.ndarray | None, float]:
    """Return candidate semantic affinity and overview coverage (0–1)."""
    source = list(liked)
    targets = list(candidates)
    if not source or not targets:
        return None, 0.0
    texts = [film_semantic_text(film) for film in source + targets]
    coverage = sum(bool(str(getattr(film, "overview", "") or "").strip()) for film in source) / len(source)
    matrix = _latent_matrix(texts)
    if matrix is None:
        return None, coverage
    source_matrix = matrix[:len(source)]
    target_matrix = matrix[len(source):]
    positive = np.asarray(list(positive_weights), dtype=float)
    negative = np.asarray(list(negative_weights), dtype=float)
    if positive.sum() <= 0:
        return None, coverage
    positive_profile = (source_matrix * positive[:, None]).sum(axis=0) / positive.sum()
    scores = cosine_similarity(positive_profile.reshape(1, -1), target_matrix)[0]
    if negative.sum() > 0:
        negative_profile = (source_matrix * negative[:, None]).sum(axis=0) / negative.sum()
        scores -= 0.35 * cosine_similarity(negative_profile.reshape(1, -1), target_matrix)[0]
    # Cosine has a -1..1 domain; recommendation blending wants a stable 0..1.
    return np.clip((scores + 1.0) / 2.0, 0.0, 1.0), coverage


def profile_similarity(first, second, *, first_weights, second_weights) -> tuple[float | None, float]:
    """Compare two film histories in one shared latent semantic space."""
    left = list(first)
    right = list(second)
    if not left or not right:
        return None, 0.0
    texts = [film_semantic_text(film) for film in left + right]
    coverage = sum(bool(str(getattr(film, "overview", "") or "").strip()) for film in left + right) / len(texts)
    matrix = _latent_matrix(texts)
    if matrix is None:
        return None, coverage
    left_weights = np.maximum(np.asarray(list(first_weights), dtype=float), 0.0)
    right_weights = np.maximum(np.asarray(list(second_weights), dtype=float), 0.0)
    if left_weights.sum() <= 0 or right_weights.sum() <= 0:
        return None, coverage
    left_profile = (matrix[:len(left)] * left_weights[:, None]).sum(axis=0) / left_weights.sum()
    right_profile = (matrix[len(left):] * right_weights[:, None]).sum(axis=0) / right_weights.sum()
    value = float(cosine_similarity(left_profile.reshape(1, -1), right_profile.reshape(1, -1))[0][0])
    return max(0.0, min(1.0, (value + 1.0) / 2.0)), coverage


def taste_document_scores(viewer_taste: dict, candidate_tastes: list[dict]) -> tuple[list[float], float]:
    """Return lightweight latent affinity for the discovery directory."""
    documents = [taste_semantic_text(viewer_taste)] + [taste_semantic_text(row) for row in candidate_tastes]
    matrix = _latent_matrix(documents)
    if matrix is None:
        return [0.0] * len(candidate_tastes), 0.0
    scores = cosine_similarity(matrix[:1], matrix[1:])[0]
    coverage = sum(bool(document.strip()) for document in documents) / len(documents)
    return [max(0.0, min(1.0, (float(value) + 1.0) / 2.0)) for value in scores], coverage
