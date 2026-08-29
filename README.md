# Letterboxd AI Recommender

A username-first film recommender: give it a public Letterboxd username, it
analyses recent watched films and ranks that user's own watchlist with a
**TF-IDF + LLM hybrid** recommender.

```
username → direct scrape → enrich (TMDb) → similarity rank → LLM rerank → recommendations
```

TMDb and OpenAI are optional. Without TMDb, enrichment is skipped; without an
OpenAI key, the final step falls back to local similarity ordering.

## The four layers

| Layer | File | What it does |
|-------|------|--------------|
| 1. Scraper | `app/scraper.py` | Fetches public watched/watchlist HTML and diary RSS |
| 2. Enrichment | `app/enrich.py` | Adds TMDb metadata: overview, genres, director, keywords |
| 3. Recommender | `app/recommender.py` | Builds a rating-aware taste vector and ranks the watchlist |
| 4. LLM ranking | `app/llm.py` | Curates the candidate pool and writes the reasons |

`app/main.py` wires them together behind a FastAPI endpoint.

## Setup

Requires Python 3.10+.

```bash
cd letterboxd-recommender
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then optionally add your API keys
```

### Run the server

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Shows which integrations are configured |
| `POST /api/recommend` | Taste analysis and personalized watchlist ranking |
| `POST /api/random` | Three random picks from the user's watchlist |
| `POST /api/blend` | Two-user taste compatibility and common films |
| `DELETE /api/data` | Deletes one username's profile and recommendation caches |

```bash
curl -X POST localhost:8000/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{"username": "your-letterboxd-name"}'
```

## API keys (optional)

- **TMDb** — free at <https://www.themoviedb.org/settings/api>. Enables the
  enrichment layer (much better recommendations).
- **OpenAI** — <https://platform.openai.com/api-keys>. Enables LLM reranking
  with taste-aware explanations.
- **Supabase** — persists user film and recommendation caches across deploys.

Put them in `.env`. The ranking model is configured with `OPENAI_MODEL`.

## Notes & caveats

- **Letterboxd's official API access is restricted and currently unavailable for
  recommendation projects.** The scraper therefore parses public HTML, and the
  selectors in `app/scraper.py` can break if Letterboxd changes its markup.
  It also respects a polite delay between requests (`SCRAPE_DELAY`) and uses
  no proxy or paid scraping service. Check Letterboxd's terms of service before
  using this at any scale.
- User profiles use stale-while-revalidate caching. An unchanged first-page
  fingerprint skips the full crawl; a full crawl still runs at least weekly.
- Identical concurrent scrapes are coalesced and TMDb uses a shared bounded pool.
- TMDb metadata uses a local SQLite L1 and a batched Supabase L2, so deploys can
  reuse enrichment results without turning every film into a separate DB request.
- Taste, Random and Blend share an anonymous per-IP budget of five heavy requests
  per ten minutes, with at most two starting inside fifteen seconds. Health checks
  do not consume this budget. The limiter is process-local and intended for the
  single-instance deployment.
- “Verimi Sil” removes username-scoped profile, refresh, recommendation and user
  tracking rows. It is anonymous and separately IP-limited until account login is
  added; shared TMDb film metadata is not user-specific and remains cached.
- Blend returns a calibrated 0–100 similarity score plus an independent low,
  medium or high data-confidence indicator. The score is shown before the two
  watchlists finish loading; common watchlist titles arrive lazily.
- Recommendation ranking uses rating-aware negative signals and MMR diversity.
  LLM context includes explicit 3.5+ ratings (with their scores); unrated history
  is used only when the profile has no rating data.
- Without Supabase, caches live in `data/cache.sqlite3` and are ephemeral on hosts
  without persistent disks.

## Project layout

```
letterboxd-recommender/
├── app/
│   ├── config.py        settings / .env loading
│   ├── cache.py         layered SQLite/Supabase key-value cache
│   ├── scraper.py       layer 1 — watchlist scraping
│   ├── enrich.py        layer 2 — TMDb enrichment
│   ├── recommender.py   layer 3 — rating-aware similarity ranking
│   ├── llm.py           layer 4 — LLM reranking
│   └── main.py          FastAPI app
├── scripts/
│   ├── check_scraper.py direct scraper canary
│   ├── check_profiles.py isolated real-profile pipeline check
│   └── warm_cache.py    profile cache warmer
├── static/
│   └── index.html       frontend
├── requirements.txt
└── .env.example
```
