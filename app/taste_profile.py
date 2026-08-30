"""Deterministic, persistable taste-profile snapshots.

The snapshot is available immediately after enrichment and does not require an
LLM call. A later LLM pass may improve the prose without changing the measured
favorite director, feature coverage or confidence fields.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from .enrich import EnrichedFilm


@dataclass
class TasteProfileSnapshot:
    summary: str
    favorite_director: str = ""
    top_genres: list[str] = field(default_factory=list)
    top_keywords: list[str] = field(default_factory=list)
    sample_size: int = 0
    rated_count: int = 0
    metadata_coverage: int = 0
    confidence_level: str = "low"
    confidence_score: int = 0
    algorithm_version: str = "taste-v1"
    source_fingerprint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _positive_weight(film: EnrichedFilm, index: int, total: int) -> float:
    """Weight explicit likes strongly and unrated watches as a weaker signal."""
    recency = 1.0 if total <= 1 else 1.0 - (0.25 * index / (total - 1))
    if film.user_rating is None:
        return 0.35 * recency
    rating = float(film.user_rating)
    if rating < 3.0:
        return 0.0
    return max(0.1, (rating - 2.5) / 2.5) * recency


def _top_weighted(values: dict[str, float], limit: int) -> list[str]:
    return [
        value
        for value, _score in sorted(
            values.items(), key=lambda item: (-item[1], item[0].lower())
        )[:limit]
    ]


def build_taste_profile(watched: list[EnrichedFilm]) -> TasteProfileSnapshot:
    """Build a stable taste summary and rating-aware favorite director."""
    if not watched:
        return TasteProfileSnapshot(
            summary="Zevk analizi için henüz yeterli izleme verisi bulunmuyor."
        )

    director_scores: dict[str, float] = defaultdict(float)
    genre_scores: dict[str, float] = defaultdict(float)
    keyword_scores: dict[str, float] = defaultdict(float)
    metadata_points = 0.0
    rated_count = 0

    for index, film in enumerate(watched):
        weight = _positive_weight(film, index, len(watched))
        if film.user_rating is not None:
            rated_count += 1
        if film.director:
            metadata_points += 0.40
            if weight > 0:
                director_scores[film.director] += weight
        if film.genres:
            metadata_points += 0.35
            for genre in set(film.genres):
                if weight > 0:
                    genre_scores[genre] += weight
        if film.keywords:
            metadata_points += 0.25
            for keyword in set(film.keywords):
                if weight > 0:
                    keyword_scores[keyword] += weight

    # A profile with only low ratings still needs a neutral frequency fallback;
    # disliked films are never promoted when any positive signal exists.
    if not director_scores:
        for index, film in enumerate(watched):
            if film.director:
                recency = 1.0 if len(watched) <= 1 else 1.0 - (0.25 * index / (len(watched) - 1))
                director_scores[film.director] += recency

    favorite_director = _top_weighted(director_scores, 1)
    top_genres = _top_weighted(genre_scores, 3)
    top_keywords = _top_weighted(keyword_scores, 5)
    metadata_coverage = round(metadata_points / len(watched) * 100)
    rating_coverage = rated_count / len(watched)
    confidence = (
        min(len(watched) / 50.0, 1.0) * 0.50
        + (metadata_coverage / 100.0) * 0.35
        + rating_coverage * 0.15
    )
    confidence_score = round(min(confidence, 1.0) * 100)
    confidence_level = (
        "high" if confidence_score >= 75 else "medium" if confidence_score >= 45 else "low"
    )

    genre_phrase = ", ".join(top_genres[:2])
    director = favorite_director[0] if favorite_director else ""
    if genre_phrase and director:
        summary = (
            f"{genre_phrase} ağırlıklı; {director} filmlerine belirgin yakınlık "
            "gösteren bir zevk profili."
        )
    elif genre_phrase:
        summary = f"{genre_phrase} ağırlıklı bir izleme zevki öne çıkıyor."
    elif director:
        summary = f"{director} filmlerine yakınlık gösteren bir zevk profili."
    else:
        summary = (
            "İzleme geçmişi kaydedildi; metadata kapsamı arttıkça zevk analizi "
            "daha ayrıntılı hale gelecek."
        )

    return TasteProfileSnapshot(
        summary=summary,
        favorite_director=director,
        top_genres=top_genres,
        top_keywords=top_keywords,
        sample_size=len(watched),
        rated_count=rated_count,
        metadata_coverage=metadata_coverage,
        confidence_level=confidence_level,
        confidence_score=confidence_score,
    )


def taste_source_fingerprint(profile, watched: list[EnrichedFilm]) -> str:
    """Hash only public inputs whose change should invalidate a taste snapshot."""
    payload = {
        "version": "taste-source-v1",
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url or "",
        "favorites": [film.slug for film in profile.favorite_films[:4]],
        "watched": [(film.slug, film.user_rating) for film in watched],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
