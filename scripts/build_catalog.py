"""Build the film catalog the recommender searches against.

The catalog is three files in the data directory:
  * catalog.json          — film metadata, each with a `text_blob`
  * catalog_vectors.npy   — one embedding row per film (same order)
  * embedder.pkl          — the fitted embedder, so the watchlist later
                            lands in the *same* vector space

Two sources:
  python -m scripts.build_catalog --source sample        (offline, bundled)
  python -m scripts.build_catalog --source tmdb --pages 15   (needs TMDb key)
"""

import argparse
import asyncio
import json
import sys

import numpy as np

from app.config import get_settings
from app.embeddings import Embedder
from app.enrich import EnrichedFilm

TMDB_BASE = "https://api.themoviedb.org/3"


def load_sample() -> list[EnrichedFilm]:
    settings = get_settings()
    path = settings.data_path / "sample_films.json"
    if not path.exists():
        sys.exit(f"Sample data not found at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        EnrichedFilm(
            title=f["title"],
            year=f.get("year"),
            director=f.get("director", ""),
            genres=f.get("genres", []),
            overview=f.get("overview", ""),
            keywords=f.get("keywords", []),
            matched=True,
        )
        for f in raw
    ]


async def load_from_tmdb(pages: int) -> list[EnrichedFilm]:
    import httpx

    settings = get_settings()
    if not settings.has_tmdb:
        sys.exit("--source tmdb needs TMDB_API_KEY in your .env")

    films: list[EnrichedFilm] = []
    async with httpx.AsyncClient(timeout=20.0) as client:

        async def get(path: str, **params) -> dict:
            params["api_key"] = settings.tmdb_api_key
            r = await client.get(f"{TMDB_BASE}{path}", params=params)
            r.raise_for_status()
            return r.json()

        genres = {g["id"]: g["name"] for g in (await get("/genre/movie/list"))["genres"]}

        for page in range(1, pages + 1):
            data = await get("/movie/top_rated", page=page)
            for movie in data.get("results", []):
                details = await get(
                    f"/movie/{movie['id']}", append_to_response="keywords,credits"
                )
                director = next(
                    (c["name"] for c in details.get("credits", {}).get("crew", [])
                     if c.get("job") == "Director"),
                    "",
                )
                films.append(
                    EnrichedFilm(
                        title=movie.get("title", ""),
                        year=int(movie.get("release_date", "0")[:4] or 0) or None,
                        tmdb_id=movie.get("id"),
                        director=director,
                        genres=[genres.get(g, "") for g in movie.get("genre_ids", [])],
                        overview=movie.get("overview", ""),
                        keywords=[
                            k["name"]
                            for k in details.get("keywords", {}).get("keywords", [])
                        ][:12],
                        vote_average=float(movie.get("vote_average", 0.0)),
                        matched=True,
                    )
                )
            print(f"  fetched page {page}/{pages} ({len(films)} films so far)")
    return films


def build(films: list[EnrichedFilm], provider: str) -> None:
    settings = get_settings()
    records = []
    for f in films:
        d = f.to_dict()
        d["text_blob"] = f.text_blob
        records.append(d)

    blobs = [r["text_blob"] for r in records]
    print(f"Embedding {len(blobs)} films with provider '{provider}'...")

    embedder = Embedder(provider=provider, st_model=settings.st_model)
    embedder.fit(blobs)
    vectors = embedder.embed(blobs)

    settings.catalog_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    np.save(settings.catalog_vectors_path, vectors)
    embedder.save(settings.data_path / "embedder.pkl")

    print(
        f"Done. Catalog: {len(records)} films, vector shape {vectors.shape}\n"
        f"  {settings.catalog_path}\n"
        f"  {settings.catalog_vectors_path}\n"
        f"  {settings.data_path / 'embedder.pkl'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the recommender catalog.")
    parser.add_argument("--source", choices=["sample", "tmdb"], default="sample")
    parser.add_argument("--pages", type=int, default=15, help="TMDb pages (20 films each)")
    parser.add_argument(
        "--provider", default=None, help="override EMBEDDING_PROVIDER for this build"
    )
    args = parser.parse_args()

    provider = args.provider or get_settings().embedding_provider

    if args.source == "sample":
        films = load_sample()
    else:
        films = asyncio.run(load_from_tmdb(args.pages))

    build(films, provider)


if __name__ == "__main__":
    main()
