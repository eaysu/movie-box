# Letterboxd AI Recommender

A working skeleton: give it a Letterboxd username, it scrapes the watchlist,
analyses the user's taste, and recommends films — using an **embedding +
LLM hybrid** recommender.

```
username → scrape → enrich (TMDb) → embed → similarity search → LLM ranking → recommendations
```

Every external dependency is optional. The pipeline **degrades gracefully**:
no TMDb key → enrichment is skipped; no Anthropic key → the LLM step falls
back to plain similarity ordering. You can run the whole thing offline
against the bundled sample catalog.

## The five layers

| Layer | File | What it does |
|-------|------|--------------|
| 1. Scraper | `app/scraper.py` | Fetches and parses the watchlist HTML pages |
| 2. Enrichment | `app/enrich.py` | Adds TMDb metadata: overview, genres, director, keywords |
| 3. Embeddings | `app/embeddings.py` | Turns film text into vectors (tfidf or sentence-transformers) |
| 4. Recommender | `app/recommender.py` | Builds a taste vector, finds nearest catalog films |
| 5. LLM ranking | `app/llm.py` | Curates the candidate pool, writes the reasons |

`app/main.py` wires them together behind a FastAPI endpoint.

## Setup

Requires Python 3.10+.

```bash
cd letterboxd-recommender
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then optionally add your API keys
```

### 1. Build the catalog

The recommender searches against a pool of pre-embedded films. Build it once.

```bash
# Offline — uses the 35 bundled sample films. No API key needed.
python -m scripts.build_catalog --source sample

# Or, for a real catalog of ~300 top-rated films (needs TMDB_API_KEY):
python -m scripts.build_catalog --source tmdb --pages 15
```

### 2. Run the server

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Shows which keys / catalog are configured |
| `GET /api/watchlist/{username}` | Just the scraping step — useful for debugging the parser |
| `POST /api/recommend` | The full pipeline. Body: `{"username": "..."}` |

```bash
curl -X POST localhost:8000/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{"username": "your-letterboxd-name"}'
```

## API keys (both optional)

- **TMDb** — free at <https://www.themoviedb.org/settings/api>. Enables the
  enrichment layer (much better recommendations).
- **Anthropic** — <https://console.anthropic.com/>. Enables the LLM ranking
  layer with written, taste-aware explanations.

Put them in `.env`. The model used for ranking is set by `ANTHROPIC_MODEL`
(default `claude-sonnet-4-6`).

## Better embeddings

The default `tfidf` backend is keyword-based and installs with no heavy
dependencies — fine for getting started. For genuinely *semantic* similarity
(e.g. recognising that Solaris and 2001 are close even with different words):

```bash
pip install sentence-transformers
# then in .env:
EMBEDDING_PROVIDER=sentence-transformers
```

Rebuild the catalog after switching providers — the catalog and the watchlist
must share one vector space.

## Notes & caveats

- **Letterboxd has no public API.** The scraper parses HTML, and the CSS
  selectors in `app/scraper.py` can break if Letterboxd changes its markup.
  It also respects a polite delay between requests (`SCRAPE_DELAY`). Check
  Letterboxd's terms of service before using this at any scale; the most
  robust alternative is to let users upload their watchlist CSV export.
- TMDb lookups and scraped watchlists are cached in `data/cache.sqlite3`.
- This is a skeleton — intended as a starting point, not a finished product.
  Natural next steps: CSV-upload support, weighting watched/rated films,
  a real vector database (FAISS / pgvector) instead of the in-memory matrix.

## Project layout

```
letterboxd-recommender/
├── app/
│   ├── config.py        settings / .env loading
│   ├── cache.py         SQLite key-value cache
│   ├── scraper.py       layer 1 — watchlist scraping
│   ├── enrich.py        layer 2 — TMDb enrichment
│   ├── embeddings.py    layer 3 — pluggable embeddings
│   ├── recommender.py   layer 4 — similarity search
│   ├── llm.py           layer 5 — LLM ranking
│   └── main.py          FastAPI app
├── scripts/
│   └── build_catalog.py one-time catalog builder
├── static/
│   └── index.html       frontend
├── data/
│   └── sample_films.json bundled offline catalog source
├── requirements.txt
└── .env.example
```
