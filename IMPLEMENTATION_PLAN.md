# Implementation Plan — Screening Bulletin & Letterboxd Data Import

Scope: the two directions approved from [REKABET_ANALIZI.md](REKABET_ANALIZI.md) / [OZELLIK_TASARIMI.md](OZELLIK_TASARIMI.md).

- **Workstream A — Screening Bulletin.** A weekly, city-aware card of films playing in Turkish cinemas, matched against the user's watchlist and rated history. Replaces the commodity "where to stream" feature.
- **Workstream B — Letterboxd data import + official API.** Let a signed-in user upload their own Letterboxd export instead of waiting for a full crawl, and prepare a credible API access application.

Conventions used below: `[ ]` open, `[x]` done, **MANUAL** = a step a human performs outside the codebase (SQL Editor, Letterboxd application form).

---

## Workstream A — Screening Bulletin

### A0 · Foundations (no scraping yet)

- [x] Add `BULLETIN_ENABLED` and `BULLETIN_CITIES` settings to `app/config.py`, defaulting to disabled so the feature ships dark.
- [x] Create `app/screenings.py` as the module boundary: ingest, title matching, and per-user digest building live here; `app/main.py` only exposes endpoints.
- [x] Add schema objects to `supabase/schema.sql` (idempotent, RLS on, `service_role` only, browser roles revoked — follow the existing table pattern):
  - [x] `venues(id, slug UNIQUE, name, city, kind, source_url, config JSONB, active BOOL, last_ok_at, last_error, created_at, updated_at)`
  - [x] `screenings(id, venue_id FK, title_raw, year, tmdb_id, film_slug, starts_at, url, match_status, source_run_id, first_seen_at, updated_at)` with `UNIQUE (venue_id, title_raw, starts_at)`
  - [x] Indexes: `(starts_at)` for the week window, `(tmdb_id) WHERE tmdb_id IS NOT NULL` for user matching, `(match_status) WHERE match_status <> 'matched'` for the resolve queue
  - [x] `upsert_screenings(p_rows JSONB)` RPC mirroring `upsert_film_posters` semantics: never let an empty incoming value overwrite a resolved `tmdb_id`/`film_slug`
  - [x] `bulletin_digests(user_id FK CASCADE, week_start DATE, payload JSONB, created_at, PRIMARY KEY (user_id, week_start))` so a week's card is generated once and is idempotent
- [ ] **MANUAL:** apply the updated `supabase/schema.sql` in the Supabase SQL Editor.

**Acceptance:** schema applies cleanly twice in a row; `/api/readiness` still reports ready.

### A1 · Release layer (TMDb `now_playing`, unbreakable baseline)

- [x] Add `fetch_now_playing(region="TR")` to `app/enrich.py`, cached through the existing layered cache with a 12-hour TTL.
- [x] Write results into `screenings` with a synthetic venue (`slug='tr-vizyon'`, `kind='release'`, no showtimes) so the digest builder has one uniform source.
- [x] Reuse the shared catalog: resolve posters/metadata from `film_posters` first, call TMDb only for unresolved ids.
- [x] Unit tests with a recorded TMDb payload: ingest is idempotent, re-running the same day writes no duplicates.

**Acceptance:** with only this layer enabled, a digest can already be produced for any user.

### A2 · Title matching (TR distribution titles)

- [x] Implement `resolve_screening_title(title_raw, year)`:
  - [x] exact match against `film_posters.title` / `user_watched_films.title`
  - [x] TMDb search with `language=tr-TR` plus the year
  - [x] fall back to `alternative_titles` for the TR title of an original-language film (e.g. *Autumn Sonata* → *Sonbahar Sonatı*)
  - [x] normalize before comparing: casefold with Turkish `İ/ı` handling, strip punctuation and the trailing year
- [x] Persist the outcome as `match_status` in `('matched', 'ambiguous', 'unresolved')`; never guess silently.
- [x] Add `scripts/resolve_screenings.py`: list unresolved rows and accept a manual `title_raw → tmdb_id` mapping (local, service-role, same shape as `scripts/admin_users.py`).
- [x] Golden tests over a fixture list of real TR distribution titles, including at least one Turkish-character case and one re-release.

**Acceptance:** ≥90% of the release layer resolves automatically; the rest is visible in the queue rather than wrong.

### A3 · Repertory venues (the differentiating layer)

> **Durum (4 Eylül 2026):** dört mekân canlı — Paribu Cineverse, Başka Sinema,
> Atlas 1948 ve Kadıköy Sineması. Her birinin `robots.txt`'si tek tek kontrol
> edildi ve karar `venues.config.robots` içine yazıldı. Parser üç stratejiyi
> destekliyor (`attr` / `css` / `link`); selector'lar config'te, kodda değil.
>
> Eklenmeyenler ve sebepleri: **Cinemaximum** artık ayrı bir marka değil —
> Paribu Cineverse olarak yeniden adlandırıldı ve alan adı çözülmüyor.
> **Pera Müzesi** ve **İKSV/Filmekimi** programları bugün doğrulanabilir bir
> uçtan sunulmuyor (Pera'nın etkinlik yolu 404, İKSV film listesi sunucuda
> render edilmiyor); festival programı sezonluk yayımlandığı için boşken
> selector yazmak tahmin olurdu.

- [x] Write venue parsers as **data, not code**: each venue's CSS selectors and date format live in `venues.config`, so a broken site is a config change.
- [x] Start with 4 venues (Başka Sinema program pages, Kadıköy Sineması, Beyoğlu/Atlas 1948, Pera & İKSV, current festival programmes).
- [x] One polite request per venue per ingest, at most twice a day (lease + `BULLETIN_INGEST_INTERVAL_HOURS`). **Deviation:** the Letterboxd budget is not reused — it exists to protect one host we hammer, whereas each venue gets a single GET.
- [x] Check `robots.txt` and terms per venue before enabling it; record the decision in `venues.config` so it is auditable.
- [x] Per-venue health: write `last_ok_at` / `last_error` on every run. **A failed venue must never fail the bulletin** — the digest ships with the venues that succeeded.
- [ ] Add `scripts/check_venues.py` canary in the shape of `scripts/check_scraper.py`, and a scheduled GitHub workflow next to `scraper-canary.yml`.
- [x] Attribution in the payload: venue name, source link and "buy tickets" pointing at the venue, never at us.

**Acceptance:** one venue's markup can be broken in a test and the digest still renders with the others.

### A4 · Digest builder

- [x] `build_user_digest(user_id, week_start, city)` returns three ordered sections:
  - [x] **On your watchlist and in cinemas** — strongest signal, direct action
  - [x] **Back on screen** — from `user_watched_films` where `rating_observed AND user_rating >= 4`, carrying the original rating and year ("you gave it 4.5 in 2021")
  - [x] **New releases that fit your taste** — scored with the existing taste vector, excluding watchlist and watched films
- [x] Cap each section (3 items) and the whole card; empty sections collapse rather than render placeholders.
- [x] Persist to `bulletin_digests` keyed by `(user_id, week_start)`; regeneration is idempotent.
- [x] Generate lazily: the first member to open the bulletin nudges a background ingest under a DB lease. **Deviation from the plan:** Render runs one web service and no worker, so a scheduled job would need a second service; the lease makes the lazy trigger safe across processes and the caller never waits.

**Acceptance:** a user with an empty watchlist still gets a useful card from sections 2 and 3.

### A5 · Delivery surface

- [x] `GET /api/bulletin?city=` — authenticated, CSRF-checked, cheap read of the stored digest.
- [x] **Deviation:** a card between "Ne izlesen?" and "Favori dört film" instead of a tab, at the product owner's request; it loads after the profile paints, so nothing new blocks the first render.
- [x] City selector persisted on the user row (`bulletin_city`), defaulting to unset = nationwide release layer only.
- [ ] Optional opt-in web push (not started); **no email is collected or sent** — that constraint is a product principle, not an oversight.
- [ ] Share card (not started): a "Bu hafta perdede" variant in `static/js/share-cards.js` reusing the 1080×1350 renderer.
- [x] Record `bulletin_viewed` in `user_activity_events` (bounded metadata only).

**Acceptance:** the tab renders from one request; no new blocking call on profile load.

### A6 · Blend intersection (the payoff)

- [ ] For an accepted Blend, intersect both users' digests: films on both watchlists that are playing this week.
- [ ] Surface it in the Blend result as a single line: *"İkinizin de listesinde — Cuma 21:30, Kadıköy Sineması."*
- [ ] Feed the same intersection into the "tonight" pick when that ships, as its highest-priority bucket.

**Acceptance:** the line appears only when a real showtime exists; never a speculative match.

### A7 · Rollout

- [x] Ship dark, enable for the owner account first, then a small cohort.
- [ ] Watch: ingest duration, venue success rate, auto-match rate, digest open rate, repeat-visit rate week over week.
- [x] Kill switches: `BULLETIN_ENABLED` globally and `venues.active` per venue.

---

## Workstream B — Letterboxd data import

### B1 · Onboarding choice

- [ ] After the first login, while the full crawl is being queued, present two options:
  - [ ] **Fast path** — open `letterboxd.com/data/export` in a new tab, drop the ZIP here, results in seconds
  - [ ] **Wait** — we crawl in the background; show the estimate derived from `profile_sync_jobs.films_total` progress
- [ ] The choice must be skippable and re-offerable later from the profile menu; never a hard gate.
- [ ] Record `import_offered` / `import_chosen` / `crawl_chosen` in `user_activity_events`.

### B2 · Parser

- [ ] Add `app/letterboxd_import.py`, parsing in memory only — nothing is written to disk at any point.
- [ ] Map the export files onto the existing model:
  - [ ] `ratings.csv` → `film_slug` from the `Letterboxd URI` column, `user_rating`, `rating_observed = true`
  - [ ] `watched.csv` → the full active set
  - [ ] `diary.csv` → chronological order for `watched_rank`, rewatch flag
  - [ ] `watchlist.csv` → recommendation candidate pool
  - [ ] `likes/films.csv` → positive signal
- [ ] Derive the slug from the `Letterboxd URI` column — this is what makes the export line up with `user_watched_films.film_slug` with no fuzzy matching.
- [ ] Verify the export belongs to this account (profile name vs. account username); warn on mismatch instead of importing silently.

### B3 · Pipeline integration

- [ ] Feed parsed rows through the existing `upsert_watched_films` RPC in batches; do not add a second write path.
- [ ] Treat an import as a sync run: allocate a `sync_run_id`, then call `finalize_profile_sync_run` so films removed on Letterboxd are deactivated exactly as after a crawl.
- [ ] Add `'import'` to the `profile_sync_jobs.scope` CHECK constraint and set `phase='enrich'` on completion.
- [ ] **The import skips the diary phase, not the enrich phase** — director/genre/keyword metadata still comes from TMDb, resolved through the shared catalog first.
- [ ] Cancel or supersede any queued full crawl for that user once an import succeeds.
- [ ] Run the taste snapshot exactly as the crawl path does, so both routes produce the same `algorithm_version` and fingerprint.

### B4 · Upload safety

- [ ] `POST /api/profile/import` — authenticated, CSRF-checked, its own rate-limit bucket (a few attempts per hour).
- [ ] Reject before reading: request size cap (~20 MB), and a cap on both entry count and **total uncompressed size** (zip-bomb protection).
- [ ] Allow-list expected entry names only; reject absolute paths, `..` segments and symlinks.
- [ ] Cap CSV rows (~100k) and validate the header schema; unknown columns are ignored, missing required columns are a clear error.
- [ ] Error messages never echo file contents.
- [ ] Tests: zip bomb, path traversal, wrong-account export, truncated CSV, missing files, oversized upload, and a valid import ending in the same state a crawl produces.

### B5 · Preview reuse (optional, after §1 of the design doc ships)

- [ ] Reuse the same parser client-side so a visitor can analyse a ZIP **without uploading it**, matching our privacy positioning.

### B6 · Official API application

- [ ] Measure and record the current cost: Letterboxd page requests per user for a full crawl and for an incremental refresh. This number is the application's strongest argument.
- [ ] Draft the application around what the platform gains:
  - [ ] "We fetch N pages per user today; with API access that goes to zero."
  - [ ] Traffic returned: film and profile links out to Letterboxd; OAuth watchlist writes on the user's behalf.
  - [ ] No competition: we host no catalog, no reviews, no lists, no alternative social feed.
  - [ ] Data hygiene, all already true: full account deletion (`DELETE /api/data`), letters only the two participants can read, RLS with no browser access, documented rate limits and caching.
  - [ ] Attribution: "not affiliated with Letterboxd", no logo use.
- [ ] Prepare the package: live demo link, user count and growth, a one-page architecture summary, privacy policy and terms pages, a domain-based contact address.
- [ ] Decide consciously on the naming risk: a product name ending in "boxd" may draw a trademark objection. Toolboxd and Blendboxd surviving suggests tolerance, not permission.
- [ ] **MANUAL:** submit the application and log the date and response.
- [ ] Keep the import path as the permanent Plan B regardless of the outcome — the application is an option, not a bet.

---

## Sequencing

| Order | Item | Why first |
|---|---|---|
| 1 | B1–B4 (import) | Shortest path to a visibly faster product; removes the most fragile scraping work |
| 2 | A0–A2 (schema + release layer) | Ships a real bulletin with zero scraping risk |
| 3 | A4–A5 (digest + tab) | Turns the data into the weekly habit the product currently lacks |
| 4 | A3 (repertory venues) | The differentiator, once the surface around it exists |
| 5 | A6 (Blend intersection) | Needs both a bulletin and an accepted Blend |
| 6 | B6 (API application) | Argument is strongest once import has measurably cut our request volume |

## Definition of done

- [ ] Both workstreams ship behind flags and can be disabled without a deploy.
- [ ] No new blocking call on profile load; every new surface is lazy or cached.
- [ ] Every new table has RLS enabled and browser roles revoked, matching the existing schema.
- [ ] `pytest` covers ingest idempotency, title matching, digest shaping, and every upload-safety case.
- [ ] `README.md` documents the new endpoints and settings when they land.
