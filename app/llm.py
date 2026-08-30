"""Layer 4 — LLM ile watchlist sıralaması.

Benzerlik katmanı en iyi N watchlist filmini seçti.
GPT bu filmleri kullanıcının izleme geçmişine göre yeniden sıralar,
her biri için kişiselleştirilmiş gerekçe ve genel zevk analizi üretir.

OpenAI key yoksa benzerlik sıralaması fallback olarak döner.
"""

import json

from .config import Settings
from .enrich import EnrichedFilm

# Kısa alias → tam model ID eşlemesi
_MODEL_ALIASES: dict[str, str] = {
    "gpt-5-mini": "gpt-5-mini-2025-08-07",
}


def _resolve_model(name: str) -> str:
    return _MODEL_ALIASES.get(name, name)


def _film_label(f: EnrichedFilm) -> str:
    label = f.title
    if f.year:
        label += f" ({f.year})"
    if f.director:
        label += f", yön. {f.director}"
    if f.user_rating is not None:
        label += f", kullanıcı puanı {float(f.user_rating):g}/5"
    return label


def _taste_references(watched: list[EnrichedFilm], limit: int = 40) -> tuple[list[EnrichedFilm], str]:
    """Prefer explicit positive ratings; never describe low-rated films as taste."""
    liked = [
        (index, film)
        for index, film in enumerate(watched)
        if film.user_rating is not None and float(film.user_rating) >= 3.5
    ]
    if liked:
        liked.sort(key=lambda item: (-float(item[1].user_rating), item[0]))
        return [film for _, film in liked[:limit]], "rated_likes"

    if any(film.user_rating is not None for film in watched):
        return [], "no_positive_ratings"

    # Profiles without rating coverage still need a bounded implicit signal. The
    # prompt names this honestly as viewing history, not as a list of favourites.
    return watched[: min(limit, 20)], "unrated_history"


def _build_prompt(
    watched: list[EnrichedFilm],
    candidates: list[EnrichedFilm],
    n: int,
) -> str:
    references, reference_mode = _taste_references(watched)
    watched_block = "; ".join(_film_label(f) for f in references)
    if reference_mode == "rated_likes":
        reference_heading = "Kullanıcının yüksek puan verdiği filmler"
    elif reference_mode == "unrated_history":
        reference_heading = "Puan verisi olmadığı için yakın dönem izleme geçmişi"
    else:
        reference_heading = "Yeterli pozitif puan sinyali bulunamadı"
        watched_block = "(pozitif referans yok)"

    lines = []
    for i, c in enumerate(candidates, start=1):
        overview = (c.overview or "")[:240]
        genres = ", ".join(c.genres or [])
        lines.append(
            f"[{i}] {c.title} ({c.year or '?'}) "
            f"— yön. {c.director or 'bilinmiyor'} "
            f"— türler: {genres or 'n/a'}\n    {overview}"
        )
    candidate_block = "\n".join(lines)

    return (
        "Sen deneyimli bir film öneri uzmanısın.\n\n"
        f"{reference_heading}:\n{watched_block}\n\n"
        "Aşağıdaki filmler kullanıcının watchlist'inden seçilmiş adaylardır "
        "(izleme geçmişine benzerliğe göre ön filtrelendi):\n"
        f"{candidate_block}\n\n"
        f"Bu kullanıcıya en uygun {n} filmi seç ve sırala. "
        "Her film için, izleme geçmişindeki SOMUT filmlere atıfla "
        "1-2 cümle gerekçe yaz (Türkçe). "
        "Ayrıca 2-3 cümle genel zevk analizi yaz (Türkçe). "
        "Önemli: film isimleri, yönetmen adları ve diğer özel isimler orijinal dilinde kalmalı, çevrilmemeli.\n\n"
        "SADECE aşağıdaki JSON formatında yanıt ver, başka hiçbir şey yazma:\n"
        '{"taste_summary": "...", '
        '"picks": [{"index": <yukarıdaki liste numarası>, "reason": "..."}]}'
    )


def _fallback(candidates: list[EnrichedFilm], n: int) -> dict:
    """LLM yokken benzerlik sıralamasını döndür."""
    picks = []
    for c in candidates[:n]:
        picks.append({
            **c.to_dict(),
            "reason": c.reason or (
                f"İzleme geçmişinle benzerlik skoru: {c.similarity:.3f}"
            ),
        })
    return {
        "taste_summary": (
            "LLM sıralaması devre dışı (OPENAI_API_KEY yok). "
            "Sonuçlar watchlist'inizden benzerlik skoruna göre sıralandı."
        ),
        "recommendations": picks,
        "llm_used": False,
    }


async def rank_candidates(
    settings: Settings,
    watched: list[EnrichedFilm],
    candidates: list[EnrichedFilm],
) -> dict:
    """Aday watchlist filmlerini LLM ile sırala ve gerekçelendir."""
    n = settings.num_recommendations
    if not candidates:
        return {"taste_summary": "", "recommendations": [], "llm_used": False}

    if not settings.has_openai:
        return _fallback(candidates, n)

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        model_id = _resolve_model(settings.openai_model)
        # Reasoning modelleri (gpt-5-mini, o-serisi):
        #   max_completion_tokens = reasoning_tokens + output_tokens
        #   Karmaşık prompt için reasoning ~4000+ token tüketebilir;
        #   output JSON ~1500 token → toplam 8000 yeterince güvenli.
        # Eski modeller (gpt-4o-mini vb.) max_tokens kullanır.
        _REASONING_MODELS = {"gpt-5-mini-2025-08-07", "o3-mini", "o4-mini", "o1-mini", "o1", "o3"}
        if model_id in _REASONING_MODELS:
            token_kwargs = {"max_completion_tokens": 8000}
        else:
            token_kwargs = {"max_tokens": 1500}

        response = await client.chat.completions.create(
            model=model_id,
            **token_kwargs,
            messages=[{"role": "user", "content": _build_prompt(watched, candidates, n)}],
        )
        raw = response.choices[0].message.content or ""
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        parsed = json.loads(raw.strip())

        recommendations = []
        for pick in parsed.get("picks", []):
            idx = int(pick.get("index", 0)) - 1
            if 0 <= idx < len(candidates):
                c = candidates[idx]
                c.reason = pick.get("reason", "")
                recommendations.append(c.to_dict())

        return {
            "taste_summary": parsed.get("taste_summary", ""),
            "recommendations": recommendations or _fallback(candidates, n)["recommendations"],
            "llm_used": True,
        }
    except Exception as exc:  # noqa: BLE001
        result = _fallback(candidates, n)
        result["taste_summary"] = (
            f"LLM sıralaması başarısız ({type(exc).__name__}); "
            "benzerlik sıralaması kullanıldı."
        )
        return result


_ANALYSIS_REASONING_MODELS = {
    "gpt-5-mini-2025-08-07", "o3-mini", "o4-mini", "o1-mini", "o1", "o3",
}


def _taste_analysis_prompt(
    watched: list[EnrichedFilm], favorites: list[EnrichedFilm]
) -> str:
    liked, _mode = _taste_references(watched, limit=45)
    sample = liked or watched[:30]
    watched_lines = "\n".join(f"- {_film_label(f)}" for f in sample)
    fav_lines = "\n".join(
        f"- {_film_label(f)}" for f in (favorites or [])[:4] if f.title
    ) or "- (belirtilmemiş)"
    return (
        "Bir sinefilin izleme verisinden ZENGİN, SPESİFİK bir zevk analizi çıkar. "
        "Sadece verilen filmlere dayan; klişe ve genel geçer laf yok. Türkçe yaz.\n\n"
        f"Sevdiği / çok izlediği filmler:\n{watched_lines}\n\n"
        f"Letterboxd Favori 4:\n{fav_lines}\n\n"
        "Şu JSON'u döndür (başka hiçbir şey yazma):\n"
        '{\n'
        '  "analysis": ["3-5 cümle; her biri ayrı bir gözlem: dönem/coğrafya '
        'eğilimi, tonal tercih, tekrar eden temalar, türler arası gerilim, neyden '
        'kaçındığı, yönetmen-oyuncu örüntüleri"],\n'
        '  "personality": "Favori 4 filmden yola çıkarak kişiliği hakkında 2-3 '
        'cümlelik, iddialı ama filmlere dayanan bir okuma"\n'
        '}'
    )


async def analyze_taste(
    settings: Settings,
    watched: list[EnrichedFilm],
    favorites: list[EnrichedFilm] | None = None,
) -> dict:
    """LLM ile ayrıntılı zevk analizi + Fav 4 kişilik okuması.

    LLM yoksa veya hata olursa {} döner; çağıran deterministik metni korur.
    """
    if not settings.has_openai or not watched:
        return {}
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        model_id = _resolve_model(settings.openai_model)
        if model_id in _ANALYSIS_REASONING_MODELS:
            token_kwargs = {"max_completion_tokens": 4000}
        else:
            token_kwargs = {"max_tokens": 800}
        response = await client.chat.completions.create(
            model=model_id,
            **token_kwargs,
            messages=[
                {
                    "role": "user",
                    "content": _taste_analysis_prompt(watched, favorites or []),
                }
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        analysis = [
            line.strip()
            for line in parsed.get("analysis", [])
            if isinstance(line, str) and line.strip()
        ][:5]
        personality = str(parsed.get("personality", "")).strip()
        return {"analysis": analysis, "personality": personality}
    except Exception:  # noqa: BLE001 — deterministic fallback stays in place
        return {}
