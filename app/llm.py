"""Layer 5 — LLM curation of the candidate pool.

The similarity step produces ~25 mathematically-close films. GPT-5-mini then
picks the best handful, ranks them by how well they fit *this* user, and
writes a short reason grounded in specific watchlist films.

If no OpenAI API key is configured, this layer falls back to plain
similarity ordering so the pipeline still returns something useful.
"""

import json

from .config import Settings


def _watchlist_titles(watchlist: list) -> list[str]:
    out = []
    for f in watchlist:
        title = f.title if hasattr(f, "title") else f.get("title", "")
        year = f.year if hasattr(f, "year") else f.get("year")
        director = f.director if hasattr(f, "director") else f.get("director", "")
        label = title
        if year:
            label += f" ({year})"
        if director:
            label += f", dir. {director}"
        out.append(label)
    return out


def _build_prompt(watchlist: list, candidates: list[dict], n: int) -> str:
    wl = "; ".join(_watchlist_titles(watchlist))
    lines = []
    for i, c in enumerate(candidates, start=1):
        overview = (c.get("overview", "") or "")[:240]
        genres = ", ".join(c.get("genres", []) or [])
        lines.append(
            f"[{i}] {c.get('title','')} ({c.get('year','')}) "
            f"— dir. {c.get('director','') or 'unknown'} "
            f"— genres: {genres or 'n/a'}\n    {overview}"
        )
    candidate_block = "\n".join(lines)

    return (
        "You are a thoughtful film recommendation expert.\n\n"
        f"A user's Letterboxd watchlist contains these films:\n{wl}\n\n"
        "Here is a pool of candidate films (pre-filtered for similarity). "
        f"None of them are on the watchlist:\n{candidate_block}\n\n"
        f"Pick the {n} best candidates for this user. For each pick, write a "
        "one-or-two sentence reason that refers to SPECIFIC films on their "
        "watchlist. Also write a 2-3 sentence overall taste analysis.\n\n"
        "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
        '{"taste_summary": "...", '
        '"picks": [{"index": <number from the list above>, "reason": "..."}]}'
    )


def _fallback(candidates: list[dict], n: int) -> dict:
    """Plain similarity ordering when the LLM is unavailable."""
    picks = []
    for c in candidates[:n]:
        picks.append(
            {
                **c,
                "reason": (
                    "Closely matches the overall profile of your watchlist "
                    f"(similarity score {c.get('similarity', 0)})."
                ),
            }
        )
    return {
        "taste_summary": (
            "LLM ranking is disabled (no OPENAI_API_KEY). These are the "
            "films nearest your watchlist by embedding similarity."
        ),
        "recommendations": picks,
        "llm_used": False,
    }


async def rank_candidates(
    settings: Settings, watchlist: list, candidates: list[dict]
) -> dict:
    """Curate the candidate pool into a ranked, explained recommendation set."""
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
            messages=[{"role": "user", "content": _build_prompt(watchlist, candidates, n)}],
        )
        raw = response.choices[0].message.content or ""
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        parsed = json.loads(raw.strip())

        # Map the LLM's chosen indices back onto the candidate metadata.
        recommendations = []
        for pick in parsed.get("picks", []):
            idx = int(pick.get("index", 0)) - 1
            if 0 <= idx < len(candidates):
                recommendations.append(
                    {**candidates[idx], "reason": pick.get("reason", "")}
                )
        return {
            "taste_summary": parsed.get("taste_summary", ""),
            "recommendations": recommendations or _fallback(candidates, n)["recommendations"],
            "llm_used": True,
        }
    except Exception as exc:  # noqa: BLE001 — degrade gracefully on any LLM error
        result = _fallback(candidates, n)
        result["taste_summary"] = (
            f"LLM ranking failed ({type(exc).__name__}); showing similarity "
            "ordering instead."
        )
        return result
