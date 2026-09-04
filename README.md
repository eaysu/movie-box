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

Requires Python 3.12 (see `runtime.txt`).

```bash
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

**Service**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Shows which integrations are configured |
| `GET /api/readiness` | Returns 200 only when auth config and required Supabase tables are usable |
| `GET /api/public/stats` | Returns the cached total of active registered users for the public hero |
| `GET /api/share/image` | Proxies an allow-listed remote image for share-card rendering |

**Auth**

| Endpoint | Purpose |
|----------|---------|
| `POST /api/auth/register/start` | Creates a pending account and bio challenge |
| `POST /api/auth/register/verify` | Verifies Letterboxd ownership |
| `POST /api/auth/login` | Opens an HttpOnly cookie session |
| `GET /api/auth/me` | Returns the signed-in account |
| `POST /api/auth/refresh` | Rotates the session cookie pair |
| `POST /api/auth/logout` | Clears the session |
| `POST /api/auth/password-reset/start` | Issues a bio challenge for recovery |
| `POST /api/auth/password-reset/finish` | Sets a new password after verification |
| `DELETE /api/data` | Deletes the signed-in account and username-scoped caches |

**Profile**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/profile/me` | Returns the stored profile and taste snapshot |
| `GET /api/profile/sync-status` | Lightweight progress poll during a crawl |
| `POST /api/profile/sync` | Refreshes profile, Fav 4 and taste data |
| `POST /api/profile/watchlist/check` | One-page freshness check; full crawl only on change |
| `POST /api/profile/onboarding-complete` | Persists onboarding completion |
| `POST /api/profile/discovery-settings` | Opts the signed-in user into/out of Sinefil Sineması |
| `GET /api/profile/directors/{rank}/films` | Lazy-loads one ranked director's watched films |
| `GET /api/profile/watched` | Searches the stored watched history |
| `GET /api/profile/recent` | Lists recently logged films |
| `GET /api/profile/stats` | Returns aggregate profile counters |
| `GET /api/profile/film-overview` | Lazy-loads one film's overview text |
| `GET/PUT /api/profile/top-films` | Reads/saves the user-curated top ten |

**Recommendations**

| Endpoint | Purpose |
|----------|---------|
| `POST /api/recommend` | Taste analysis and personalized watchlist ranking |
| `POST /api/random` | Three unlimited random picks from films other members watched and this user has not |

**Sinefil Sineması & letters**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/sinefil-alani` | Lists opted-in, safe profile cards ranked by taste overlap |
| `GET /api/sinefil-alani/{username}/personality` | Lazy-loads an opted-in profile's Fav 4 reading |
| `POST /api/letters/receiving` | Opens or closes voluntary letter receiving |
| `GET/POST /api/letters` | Lists the caller's letters or sends one per 24h |
| `GET /api/letters/unread-count` | Badge count for the inbox |
| `GET /api/letters/send-status` | Remaining 24h send allowance |
| `POST /api/letters/{id}/read` | Marks one letter read |
| `GET /api/letters/recipients/{username}` | Confirms a recipient is eligible and returns their card |

**Blend & safety**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/users/search?q=` | Finds active registered Movieboxd users |
| `POST/DELETE /api/users/{username}/block` | Blocks/unblocks a user and cancels pending requests |
| `POST /api/users/{username}/report` | Stores a rate-limited safety report |
| `POST /api/blends/requests` | Sends a consent-based Blend request |
| `GET /api/blends` | Lists inbox, sent requests and history |
| `GET /api/blends/pending-count` | Inbox badge count |
| `DELETE /api/blends/requests/{id}` | Requester cancels a pending request |
| `POST /api/blends/requests/{id}/decision` | Recipient accepts or rejects |
| `POST /api/blends/requests/{id}/result` | Retries an accepted result safely |
| `GET /api/blends/requests/{id}/result` | Lazy-loads a stored Blend result |
| `POST /api/blends/{id}/refresh` | Recomputes an accepted Blend |
| `DELETE /api/blends/{id}` | Removes a Blend from both histories |
| `POST /api/blend` | Legacy anonymous Blend; disabled in account mode |

### Sinefil Mektupları

Mektuplar hesaba bağlıdır: kullanıcı giriş yaptığı her cihazda aynı mektupları
görür. Önceki tasarımda anahtar yalnızca tarayıcının IndexedDB deposunda
durduğu için ikinci bir cihaza girmek hem eski mektupları okunamaz yapıyor hem
de sunucudaki public key'i değiştirerek ilk cihazı bozuyordu; bu yüzden uçtan
uca şifreleme kaldırıldı.

Gizliliği artık erişim kuralları sağlıyor: bir mektubu yalnızca gönderen ve
alıcı listeleyebilir, engelleme iki taraftaki mektupları siler, admin raporu
gövdeyi hiç seçmez. Servis mektupları teknik olarak okuyabilir — bu, ürünün
verdiği sözün sınırıdır. Eski şifreli satırlar veritabanında kalır ama artık
kimse tarafından açılamaz; arayüz bunu açıkça söyler.

Mektup yollamak için kullanıcının kendi mektup kutusunun da açık olması gerekir
(`letter_sender_closed`); kapalıysa arayüz kutuyu açmayı öneren bir modal
gösterir. Gerekçesi: kapalı bir hesaptan gönderilen mektup, alıcının cevap
veremediği tek yönlü bir kanal olur.

## Local admin activity report

The repository includes a local-only, service-role report for aggregate account
usage. It is deliberately not an HTTP admin endpoint and never prints
passwords, tokens, raw event metadata or film rows:

```bash
python -m scripts.admin_users
python -m scripts.admin_users --username enesaysu --json
python -m scripts.admin_users --include-non-active
```

Rows are numbered and ordered by most recent activity (last recorded event,
falling back to last sync, then registration). Each row carries, per account:
Sinefil Sineması visibility
(`online`/`offline`), the letter inbox preference, letter volume as
sent/received/unread, the last send date, scan progress, watched and watchlist
counts, Blend sent/received/completed, recommendation success rate, random
picks, sync requests, logins and last activity. A summary line closes the table
with how many accounts are visible and who has sent letters. Letters are
counted only: the report never selects a body, a film gift or a recipient.

Run the current `supabase/schema.sql` in Supabase SQL Editor before using the
command; an outdated report function makes the letter and visibility columns
print as `-` with a hint. The `user_activity_events` table records bounded
product events such as profile sync lifecycle, recommendation success/failure,
random picks, onboarding completion and Blend lifecycle actions. Event writes
are best-effort and never block the user-facing flow.

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
  is used only when the profile has no rating data. Taste mode returns up to
  `NUM_RECOMMENDATIONS` (default 5) films; the last card offers the random mode
  as a way out instead of a dead end.
- Random mode is watchlist-independent and unlimited. Its pool is what other
  members have watched and this account has not (`community_random_films`,
  low-rated titles excluded), falling back to TMDb Discover when the membership
  has no usable history yet. It never scrapes Letterboxd, so it has its own
  generous rate-limit bucket instead of the shared analysis budget.
- Without Supabase, caches live in `data/cache.sqlite3` and are ephemeral on hosts
  without persistent disks.

## Project layout

```
movie-box/
├── app/
│   ├── config.py        settings / .env loading
│   ├── auth.py          username-first Supabase Auth and ownership challenges
│   ├── database.py      Supabase service client
│   ├── cache.py         layered SQLite/Supabase key-value cache
│   ├── rate_limit.py    per-IP budgets for auth, heavy and delete routes
│   ├── scraper.py       layer 1 — profile/watchlist/diary scraping
│   ├── enrich.py        layer 2 — TMDb enrichment
│   ├── recommender.py   layer 3 — rating-aware similarity ranking
│   ├── taste_profile.py persisted taste summary and confidence
│   ├── profile_sync.py  checkpointed full/incremental history crawl
│   ├── llm.py           layer 4 — LLM reranking and taste prose
│   └── main.py          FastAPI app
├── scripts/
│   ├── check_scraper.py direct scraper canary (also runs in CI daily)
│   ├── check_profiles.py isolated real-profile pipeline check
│   ├── warm_cache.py    profile cache warmer
│   ├── reset_profile.py clears one profile's stored snapshot
│   ├── admin_users.py   local-only aggregate activity report
│   └── generate_og.py   regenerates static/og-image-v3.png
├── static/
│   ├── index.html       semantic frontend shell
│   ├── css/source.css   Tailwind source
│   ├── app.css          generated production Tailwind CSS
│   └── js/              auth/api/profile/recommendation/blend/letters modules
├── frontend/lumina_cinematic/DESIGN.md   design token reference
├── supabase/schema.sql  tables, RPCs, RLS and grants
├── tests/               pytest suite
├── package.json         frontend CSS build and JS syntax checks
├── requirements.txt
└── .env.example
```

## Product documentation

| Document | Contents |
|----------|----------|
| [IMPROVEMENT_CHECKLIST.md](IMPROVEMENT_CHECKLIST.md) | Running engineering checklist (Turkish) |
| [REKABET_ANALIZI.md](REKABET_ANALIZI.md) | Competitive research and feature inventory (Turkish) |
| [OZELLIK_TASARIMI.md](OZELLIK_TASARIMI.md) | Design of the approved next features (Turkish) |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Screening bulletin and Letterboxd import plan |

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
