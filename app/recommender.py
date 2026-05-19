"""Layer 3 — watchlist'i zevk profiline göre sırala.

Önceki katalog tabanlı yaklaşımın yerini aldı.
Artık harici bir katalog yok — kullanıcının kendi watchlist'i aday havuzu,
izlediği filmler zevk profilinin kaynağı.

Akış:
  watched_films + watchlist_films  →  TF-IDF fit (birleşik korpus)
  watched vektörlerinin ortalaması  →  zevk profili
  her watchlist filmi × zevk profili  →  cosine benzerlik skoru
  en yüksek skorlu N film  →  LLM katmanına geçer
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

if TYPE_CHECKING:
    from .enrich import EnrichedFilm


def rank_watchlist(
    watched: list[EnrichedFilm],
    watchlist: list[EnrichedFilm],
    n: int = 8,
) -> list[EnrichedFilm]:
    """Watchlist filmlerini izleme geçmişine benzerliğe göre sırala.

    Args:
        watched:   Kullanıcının daha önce izlediği filmler (zevk profili kaynağı).
        watchlist: İzlemek istediği filmler (aday havuzu).
        n:         Döndürülecek film sayısı.

    Returns:
        Watchlist'ten seçilmiş, benzerlik skoruna göre sıralanmış n film.
        Her filmin .similarity ve .reason alanları doldurulmuş olur.
    """
    if not watchlist:
        return []

    if not watched:
        # İzleme geçmişi yoksa watchlist'in ilk n filmini döndür
        for f in watchlist[:n]:
            f.similarity = 0.0
            f.reason = "İzleme geçmişi bulunamadı; sıralama yapılamadı."
        return watchlist[:n]

    # Tüm filmlerin metin bloblarını birleştir (TF-IDF birleşik korpusta fit olsun)
    all_films = watched + watchlist
    blobs = [f.text_blob for f in all_films]

    vec = TfidfVectorizer(max_features=10_000, sublinear_tf=True, min_df=1)
    matrix = vec.fit_transform(blobs)  # sparse (n_films × n_features)

    n_watched = len(watched)
    watched_matrix = matrix[:n_watched]
    watchlist_matrix = matrix[n_watched:]

    # Zevk profili: izlenen filmlerin TF-IDF vektörlerinin ortalaması
    taste = np.asarray(watched_matrix.mean(axis=0))  # (1, n_features)

    # Her watchlist filminin zevk profiline cosine benzerliği
    scores = cosine_similarity(taste, watchlist_matrix)[0]  # (n_watchlist,)

    ranked_idx = np.argsort(-scores)[:n]

    results: list[EnrichedFilm] = []
    for idx in ranked_idx:
        film = watchlist[int(idx)]
        film.similarity = round(float(scores[idx]), 4)
        # Kısa fallback reason — LLM varsa zaten üzerine yazar
        film.reason = (
            f"İzleme geçmişinle benzerlik skoru: {film.similarity:.3f}"
        )
        results.append(film)

    return results
