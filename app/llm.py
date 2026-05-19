"""Layer 4 — LLM ile watchlist sıralaması.

Benzerlik katmanı en iyi N watchlist filmini seçti.
GPT bu filmleri kullanıcının izleme geçmişine göre yeniden sıralar,
her biri için kişiselleştirilmiş gerekçe ve genel zevk analizi üretir.

OpenAI key yoksa benzerlik sıralaması fallback olarak döner.
"""

import json

from .config import Settings
from .enrich import EnrichedFilm


def _film_label(f: EnrichedFilm) -> str:
    label = f.title
    if f.year:
        label += f" ({f.year})"
    if f.director:
        label += f", yön. {f.director}"
    return label


def _build_prompt(
    watched: list[EnrichedFilm],
    candidates: list[EnrichedFilm],
    n: int,
) -> str:
    watched_block = "; ".join(_film_label(f) for f in watched[:120])  # prompt limiti

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
        f"Kullanıcının daha önce izlediği filmler (zevk profili):\n{watched_block}\n\n"
        "Aşağıdaki filmler kullanıcının watchlist'inden seçilmiş adaylardır "
        "(izleme geçmişine benzerliğe göre ön filtrelendi):\n"
        f"{candidate_block}\n\n"
        f"Bu kullanıcıya en uygun {n} filmi seç ve sırala. "
        "Her film için, izleme geçmişindeki SOMUT filmlere atıfla "
        "1-2 cümle gerekçe yaz (Türkçe). "
        "Ayrıca 2-3 cümle genel zevk analizi yaz (Türkçe).\n\n"
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
        response = await client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=1500,
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
