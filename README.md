# Letterboxd AI Recommender

A username-first film recommender with persistent accounts. A user registers
with a public Letterboxd username and password, proves ownership with a temporary
bio code, then gets a stored profile, Fav 4, favorite director and rating-aware
taste analysis. The watchlist is ranked with a **TF-IDF + LLM hybrid** recommender.

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
| `GET /api/readiness` | Returns 200 only when auth config and required Supabase tables are usable |
| `POST /api/auth/register/start` | Creates a pending account and bio challenge |
| `POST /api/auth/register/verify` | Verifies Letterboxd ownership |
| `POST /api/auth/login` | Opens an HttpOnly cookie session |
| `GET /api/profile/me` | Returns the stored profile and taste snapshot |
| `GET /api/profile/directors/{rank}/films` | Lazy-loads one ranked director's watched films |
| `POST /api/profile/sync` | Refreshes profile, Fav 4 and taste data |
| `POST /api/recommendations/feedback` | Saves watch/skip/block feedback for a recommendation |
| `GET /api/recommendations/history` | Lists active recommendation preferences and event history |
| `DELETE /api/recommendations/feedback/{slug}` | Undoes a saved recommendation preference |
| `GET /api/users/search?q=` | Finds active registered Movieboxd users |
| `POST/DELETE /api/users/{username}/block` | Blocks/unblocks a user and cancels pending requests |
| `POST /api/users/{username}/report` | Stores a rate-limited safety report |
| `POST /api/blends/requests` | Sends a consent-based Blend request |
| `GET /api/blends` | Lists inbox, sent requests and history |
| `POST /api/blends/requests/{id}/decision` | Recipient accepts or rejects |
| `POST /api/blends/requests/{id}/result` | Retries an accepted result safely |
| `POST /api/recommend` | Taste analysis and personalized watchlist ranking |
| `POST /api/random` | Three random picks from the user's watchlist |
| `POST /api/blend` | Legacy anonymous Blend; disabled in account mode |
| `DELETE /api/data` | Deletes the signed-in account and username-scoped caches |

The browser client handles the HttpOnly session and CSRF header. If account
environment variables are absent, the legacy username-only endpoints remain
available as a temporary rollout fallback.

## API keys (optional)

- **TMDb** — free at <https://www.themoviedb.org/settings/api>. Enables the
  enrichment layer (much better recommendations).
- **OpenAI** — <https://platform.openai.com/api-keys>. Enables LLM reranking
  with taste-aware explanations.
- **Supabase** — required for accounts and persists profiles/caches across deploys.
  Run `supabase/schema.sql` once in the project SQL Editor before enabling auth.

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
- Resolved posters and director portraits are promoted to shared Supabase asset
  tables. A known film slug/TMDb id skips movie search, and only unresolved assets
  call TMDb. Successful director filmographies are also cached across users.
- All Letterboxd HTML requests share one adaptive process-wide budget. A 403/429
  serializes traffic and opens a cooldown circuit; sustained success recovers
  concurrency gradually. Full profile crawls additionally use a Supabase lease so
  two Render processes cannot own the same user's job.
- When auth is configured, Taste and Random require the signed-in username plus
  a double-submit CSRF token. Blend searches only registered accounts, creates a
  pending inbox request, and computes/persists compatibility only after recipient
  approval. Auth and heavy routes have separate IP budgets.
- “Verimi Sil” removes the signed-in Supabase Auth identity, profile/taste/Fav 4
  rows and username-scoped caches. Shared TMDb metadata is non-personal and remains.
- Blend returns a calibrated 0–100 similarity score plus an independent low,
  medium or high data-coverage indicator. The score is shown before the two
  watchlists finish loading; common watchlist titles arrive lazily.
- Recommendation ranking uses the latest 100 watched films, rating-aware negative
  signals and MMR diversity. The top three favorite directors receive a bounded
  secondary boost; cached TMDb filmographies identify matching watchlist titles
  before shortlist pruning.
  LLM context includes explicit 3.5+ ratings (with their scores); unrated history
  is used only when the profile has no rating data.
- Without Supabase, caches live in `data/cache.sqlite3` and are ephemeral on hosts
  without persistent disks.

## Project layout

```
letterboxd-recommender/
├── app/
│   ├── config.py        settings / .env loading
│   ├── auth.py          username-first Supabase Auth and ownership challenges
│   ├── cache.py         layered SQLite/Supabase key-value cache
│   ├── scraper.py       layer 1 — watchlist scraping
│   ├── enrich.py        layer 2 — TMDb enrichment
│   ├── recommender.py   layer 3 — rating-aware similarity ranking
│   ├── taste_profile.py persisted taste summary and confidence
│   ├── llm.py           layer 4 — LLM reranking
│   └── main.py          FastAPI app
├── scripts/
│   ├── check_scraper.py direct scraper canary
│   ├── check_profiles.py isolated real-profile pipeline check
│   └── warm_cache.py    profile cache warmer
├── static/
│   ├── index.html       semantic frontend shell
│   ├── app.css          generated production Tailwind CSS
│   └── js/              auth/api/profile/recommendation/blend modules
├── package.json         frontend CSS build and JS syntax checks
├── requirements.txt
└── .env.example
```

## Account rollout

1. Run `supabase/schema.sql` in Supabase SQL Editor.
2. Set `SUPABASE_URL`, service-role `SUPABASE_KEY`, `SUPABASE_ANON_KEY` and a
   stable `AUTH_IDENTITY_SECRET` (`openssl rand -hex 32`) in Render.
3. Deploy. `/api/health` must report `auth_enabled: true`.
4. Verify `/api/readiness` reports `status: ready`; a 503 means the current
   `supabase/schema.sql` still needs to be applied or Supabase is unavailable.
5. Register a test username, copy the challenge into its public Letterboxd bio,
   verify, log in, and wait for the first profile sync.

Never rotate `AUTH_IDENTITY_SECRET` without an identity migration: synthetic
Supabase email mappings are derived from it. Never expose `SUPABASE_KEY` to the
browser; only the backend uses it.

When frontend classes or custom styles change, regenerate the committed CSS with
`npm install && npm run build:css`. Render serves the generated file and does not
need Node at runtime.
