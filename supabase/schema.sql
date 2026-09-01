-- Supabase şeması — Supabase Studio > SQL Editor'da çalıştırın.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Kullanıcı takibi: her Letterboxd kullanıcı adı için bir satır.
CREATE TABLE IF NOT EXISTS public.users (
  id            BIGSERIAL    PRIMARY KEY,
  username      TEXT         UNIQUE NOT NULL,
  created_at    TIMESTAMPTZ  DEFAULT now(),
  last_seen_at  TIMESTAMPTZ  DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON public.users (username);

-- Account migration: existing anonymous tracking rows remain valid and can be
-- claimed after Letterboxd ownership verification.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS auth_user_id UUID UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT 'anonymous';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS profile_sync_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS ownership_verified_at TIMESTAMPTZ;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS profile_synced_at TIMESTAMPTZ;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS letterboxd_stats JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
-- User-curated "top 10 films" (ordered list of watched film slugs). Empty =
-- fall back to the highest-rated watched films.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS top_films JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_auth_user_id
  ON public.users (auth_user_id) WHERE auth_user_id IS NOT NULL;

DO $$ BEGIN
  ALTER TABLE public.users ADD CONSTRAINT users_account_status_check
    CHECK (account_status IN ('anonymous', 'pending_verification', 'active', 'disabled'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE public.users ADD CONSTRAINT users_profile_sync_status_check
    CHECK (profile_sync_status IN ('pending', 'syncing', 'ready', 'stale', 'failed'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.taste_profiles (
  user_id             BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  summary             TEXT NOT NULL DEFAULT '',
  favorite_director   TEXT NOT NULL DEFAULT '',
  top_directors       JSONB NOT NULL DEFAULT '[]'::jsonb,
  top_directors_detail JSONB NOT NULL DEFAULT '[]'::jsonb,
  top_genres          JSONB NOT NULL DEFAULT '[]'::jsonb,
  top_keywords        JSONB NOT NULL DEFAULT '[]'::jsonb,
  analysis            JSONB NOT NULL DEFAULT '[]'::jsonb,
  personality         TEXT NOT NULL DEFAULT '',
  sample_size         INTEGER NOT NULL DEFAULT 0,
  rated_count         INTEGER NOT NULL DEFAULT 0,
  metadata_coverage   INTEGER NOT NULL DEFAULT 0 CHECK (metadata_coverage BETWEEN 0 AND 100),
  confidence_level    TEXT NOT NULL DEFAULT 'low' CHECK (confidence_level IN ('low', 'medium', 'high')),
  confidence_score    INTEGER NOT NULL DEFAULT 0 CHECK (confidence_score BETWEEN 0 AND 100),
  algorithm_version   TEXT NOT NULL,
  source_fingerprint  TEXT NOT NULL DEFAULT '',
  generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.taste_profiles
  ADD COLUMN IF NOT EXISTS source_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE public.taste_profiles
  ADD COLUMN IF NOT EXISTS top_directors JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.taste_profiles
  ADD COLUMN IF NOT EXISTS top_directors_detail JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.taste_profiles
  ADD COLUMN IF NOT EXISTS analysis JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.taste_profiles
  ADD COLUMN IF NOT EXISTS personality TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS public.profile_favorites (
  user_id       BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  position      SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 4),
  slug          TEXT NOT NULL,
  title         TEXT NOT NULL,
  release_year  INTEGER,
  tmdb_id       INTEGER,
  poster_url    TEXT,
  PRIMARY KEY (user_id, position)
);

-- Full watched-history store: one row per film the user has logged. This is the
-- source of truth the taste analysis aggregates over, so an incremental sync
-- only has to upsert the delta instead of re-scraping the whole history.
CREATE TABLE IF NOT EXISTS public.user_watched_films (
  user_id        BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  film_slug      TEXT NOT NULL,
  title          TEXT NOT NULL DEFAULT '',
  release_year   INTEGER,
  tmdb_id        INTEGER,
  director       TEXT NOT NULL DEFAULT '',
  genres         JSONB NOT NULL DEFAULT '[]'::jsonb,
  keywords       JSONB NOT NULL DEFAULT '[]'::jsonb,
  user_rating    REAL,
  rating_observed BOOLEAN NOT NULL DEFAULT FALSE,
  poster_url     TEXT,
  poster_resolver_url TEXT,
  watched_rank   INTEGER,          -- diary position; 0 = most recent (chronological proxy)
  details_loaded BOOLEAN NOT NULL DEFAULT FALSE,
  last_seen_run_id UUID,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, film_slug)
);

ALTER TABLE public.user_watched_films
  ADD COLUMN IF NOT EXISTS poster_url TEXT;
ALTER TABLE public.user_watched_films
  ADD COLUMN IF NOT EXISTS poster_resolver_url TEXT;
ALTER TABLE public.user_watched_films
  ADD COLUMN IF NOT EXISTS rating_observed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.user_watched_films
  ADD COLUMN IF NOT EXISTS last_seen_run_id UUID;
ALTER TABLE public.user_watched_films
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_user_watched_films_rank
  ON public.user_watched_films (user_id, watched_rank);
CREATE INDEX IF NOT EXISTS idx_user_watched_films_director
  ON public.user_watched_films (user_id, director);

-- Shared, account-independent film catalog. Filled by every scrape/enrichment
-- path across all users. Public film metadata deliberately survives account
-- deletion so the application gets faster as its catalog grows.
CREATE TABLE IF NOT EXISTS public.film_posters (
  film_slug     TEXT PRIMARY KEY,
  poster_url    TEXT,
  poster_resolver_url TEXT,
  tmdb_id       INTEGER,
  title         TEXT NOT NULL DEFAULT '',
  release_year  INTEGER,
  overview      TEXT NOT NULL DEFAULT '',
  director      TEXT NOT NULL DEFAULT '',
  genres        JSONB NOT NULL DEFAULT '[]'::jsonb,
  keywords      JSONB NOT NULL DEFAULT '[]'::jsonb,
  vote_average  REAL NOT NULL DEFAULT 0,
  matched       BOOLEAN NOT NULL DEFAULT FALSE,
  details_loaded BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent upgrade from the former poster-only pool.
ALTER TABLE public.film_posters ALTER COLUMN poster_url DROP NOT NULL;
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS poster_resolver_url TEXT;
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS overview TEXT NOT NULL DEFAULT '';
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS director TEXT NOT NULL DEFAULT '';
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS genres JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS keywords JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS vote_average REAL NOT NULL DEFAULT 0;
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS matched BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.film_posters ADD COLUMN IF NOT EXISTS details_loaded BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_film_posters_tmdb_id
  ON public.film_posters (tmdb_id)
  WHERE tmdb_id IS NOT NULL;

-- Successful director portraits are durable shared assets. Empty/failed lookups
-- are intentionally not stored here, so a transient TMDb miss can heal later.
CREATE TABLE IF NOT EXISTS public.director_images (
  normalized_name TEXT PRIMARY KEY,
  display_name    TEXT NOT NULL,
  photo_url       TEXT NOT NULL,
  tmdb_person_id  INTEGER,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.upsert_director_images(p_directors JSONB)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  INSERT INTO public.director_images (
    normalized_name, display_name, photo_url, tmdb_person_id, updated_at
  )
  SELECT
    lower(trim(item->>'name')),
    trim(item->>'name'),
    item->>'photo_url',
    NULLIF(item->>'tmdb_person_id', '')::INTEGER,
    now()
  FROM jsonb_array_elements(COALESCE(p_directors, '[]'::jsonb)) AS item
  WHERE COALESCE(trim(item->>'name'), '') <> ''
    AND COALESCE(item->>'photo_url', '') <> ''
  ON CONFLICT (normalized_name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    photo_url = EXCLUDED.photo_url,
    tmdb_person_id = COALESCE(EXCLUDED.tmdb_person_id, public.director_images.tmdb_person_id),
    updated_at = now();
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_director_images(JSONB)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_director_images(JSONB) TO service_role;

CREATE OR REPLACE FUNCTION public.upsert_film_posters(p_films JSONB)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  INSERT INTO public.film_posters (
    film_slug, poster_url, poster_resolver_url, tmdb_id, title, release_year, overview, director,
    genres, keywords, vote_average, matched, details_loaded, updated_at
  )
  SELECT
    item->>'slug',
    NULLIF(item->>'poster_url', ''),
    NULLIF(item->>'poster_resolver_url', ''),
    NULLIF(item->>'tmdb_id', '')::INTEGER,
    COALESCE(item->>'title', ''),
    NULLIF(item->>'release_year', '')::INTEGER,
    COALESCE(item->>'overview', ''),
    COALESCE(item->>'director', ''),
    COALESCE(item->'genres', '[]'::jsonb),
    COALESCE(item->'keywords', '[]'::jsonb),
    COALESCE(NULLIF(item->>'vote_average', '')::REAL, 0),
    COALESCE((item->>'matched')::BOOLEAN, FALSE),
    COALESCE((item->>'details_loaded')::BOOLEAN, FALSE),
    now()
  FROM jsonb_array_elements(COALESCE(p_films, '[]'::jsonb)) AS item
  WHERE COALESCE(item->>'slug', '') <> ''
  ON CONFLICT (film_slug) DO UPDATE SET
    poster_url = COALESCE(EXCLUDED.poster_url, public.film_posters.poster_url),
    poster_resolver_url = COALESCE(EXCLUDED.poster_resolver_url, public.film_posters.poster_resolver_url),
    tmdb_id = COALESCE(EXCLUDED.tmdb_id, public.film_posters.tmdb_id),
    title = CASE WHEN EXCLUDED.title <> '' THEN EXCLUDED.title ELSE public.film_posters.title END,
    release_year = COALESCE(EXCLUDED.release_year, public.film_posters.release_year),
    overview = CASE WHEN EXCLUDED.overview <> '' THEN EXCLUDED.overview ELSE public.film_posters.overview END,
    director = CASE WHEN EXCLUDED.director <> '' THEN EXCLUDED.director ELSE public.film_posters.director END,
    genres = CASE WHEN EXCLUDED.genres <> '[]'::jsonb THEN EXCLUDED.genres ELSE public.film_posters.genres END,
    keywords = CASE WHEN EXCLUDED.keywords <> '[]'::jsonb THEN EXCLUDED.keywords ELSE public.film_posters.keywords END,
    vote_average = CASE WHEN EXCLUDED.vote_average > 0 THEN EXCLUDED.vote_average ELSE public.film_posters.vote_average END,
    matched = public.film_posters.matched OR EXCLUDED.matched,
    details_loaded = public.film_posters.details_loaded OR EXCLUDED.details_loaded,
    updated_at = now();
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_film_posters(JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_film_posters(JSONB) TO service_role;

-- Checkpointed background crawl for the one-time full history sweep. One row per
-- user; a run advances cursor_page under a per-run time budget and can be resumed
-- (in-process on the next visit) if the instance restarts mid-crawl.
CREATE TABLE IF NOT EXISTS public.profile_sync_jobs (
  user_id         BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  state           TEXT NOT NULL DEFAULT 'queued'
                  CHECK (state IN ('queued', 'running', 'done', 'failed')),
  phase           TEXT NOT NULL DEFAULT 'diary'
                  CHECK (phase IN ('diary', 'enrich', 'aggregate', 'done')),
  scope           TEXT NOT NULL DEFAULT 'full'
                  CHECK (scope IN ('full', 'incremental')),
  cursor_page     INTEGER NOT NULL DEFAULT 1,
  films_total     INTEGER NOT NULL DEFAULT 0,
  films_processed INTEGER NOT NULL DEFAULT 0,
  attempts        SMALLINT NOT NULL DEFAULT 0,
  heartbeat_at    TIMESTAMPTZ,
  backoff_until   TIMESTAMPTZ,
  last_error      TEXT NOT NULL DEFAULT '',
  sync_run_id     UUID,
  lease_token     UUID,
  lease_expires_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.profile_sync_jobs ADD COLUMN IF NOT EXISTS sync_run_id UUID;
ALTER TABLE public.profile_sync_jobs ADD COLUMN IF NOT EXISTS lease_token UUID;
ALTER TABLE public.profile_sync_jobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_profile_sync_jobs_resumable
  ON public.profile_sync_jobs (state, heartbeat_at)
  WHERE state IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS public.auth_challenges (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN ('register', 'password_reset')),
  code_hash     TEXT NOT NULL,
  attempts      SMALLINT NOT NULL DEFAULT 0,
  expires_at    TIMESTAMPTZ NOT NULL,
  consumed_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_challenges_active
  ON public.auth_challenges (user_id, kind, created_at DESC)
  WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS public.blend_requests (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  requester_user_id   BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  recipient_user_id   BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  status              TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled', 'expired')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at          TIMESTAMPTZ,
  expires_at          TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '14 days'),
  CHECK (requester_user_id <> recipient_user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_blend_requests_pending_pair
  ON public.blend_requests (requester_user_id, recipient_user_id)
  WHERE status = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS idx_blend_requests_pending_unordered_pair
  ON public.blend_requests (
    LEAST(requester_user_id, recipient_user_id),
    GREATEST(requester_user_id, recipient_user_id)
  ) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_blend_inbox
  ON public.blend_requests (recipient_user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blend_sent
  ON public.blend_requests (requester_user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.blend_results (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id          UUID NOT NULL UNIQUE REFERENCES public.blend_requests(id) ON DELETE CASCADE,
  score               INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
  confidence          JSONB NOT NULL DEFAULT '{}'::jsonb,
  result              JSONB NOT NULL DEFAULT '{}'::jsonb,
  algorithm_version   TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.user_blocks (
  blocker_user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  blocked_user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (blocker_user_id, blocked_user_id),
  CHECK (blocker_user_id <> blocked_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked
  ON public.user_blocks (blocked_user_id, blocker_user_id);

CREATE TABLE IF NOT EXISTS public.user_reports (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reporter_user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  reported_user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  category         TEXT NOT NULL CHECK (category IN ('spam', 'harassment', 'impersonation', 'other')),
  detail           TEXT NOT NULL DEFAULT '' CHECK (char_length(detail) <= 500),
  status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'dismissed')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (reporter_user_id <> reported_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_reports_status_time
  ON public.user_reports (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_reports_reporter_time
  ON public.user_reports (reporter_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.auth_audit_log (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
  event         TEXT NOT NULL,
  ip_hash       TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_user_time
  ON public.auth_audit_log (user_id, created_at DESC);

-- A profile refresh must become visible as one coherent snapshot. The backend
-- invokes this function only with the service_role key; browser roles cannot
-- execute it directly.
CREATE OR REPLACE FUNCTION public.save_profile_snapshot(
  p_user_id BIGINT,
  p_profile JSONB,
  p_taste JSONB,
  p_favorites JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.users
    WHERE id = p_user_id AND account_status = 'active'
  ) THEN
    RAISE EXCEPTION 'active account not found';
  END IF;

  INSERT INTO public.taste_profiles (
    user_id, summary, favorite_director, top_directors, top_directors_detail,
    top_genres, top_keywords, analysis, personality,
    sample_size, rated_count, metadata_coverage, confidence_level,
    confidence_score, algorithm_version, source_fingerprint, generated_at, updated_at
  ) VALUES (
    p_user_id,
    COALESCE(p_taste->>'summary', ''),
    COALESCE(p_taste->>'favorite_director', ''),
    COALESCE(p_taste->'top_directors', '[]'::jsonb),
    COALESCE(p_taste->'top_directors_detail', '[]'::jsonb),
    COALESCE(p_taste->'top_genres', '[]'::jsonb),
    COALESCE(p_taste->'top_keywords', '[]'::jsonb),
    COALESCE(p_taste->'analysis', '[]'::jsonb),
    COALESCE(p_taste->>'personality', ''),
    COALESCE((p_taste->>'sample_size')::INTEGER, 0),
    COALESCE((p_taste->>'rated_count')::INTEGER, 0),
    COALESCE((p_taste->>'metadata_coverage')::INTEGER, 0),
    COALESCE(p_taste->>'confidence_level', 'low'),
    COALESCE((p_taste->>'confidence_score')::INTEGER, 0),
    COALESCE(p_taste->>'algorithm_version', 'taste-v3'),
    COALESCE(p_taste->>'source_fingerprint', ''),
    now(),
    now()
  )
  ON CONFLICT (user_id) DO UPDATE SET
    summary = EXCLUDED.summary,
    favorite_director = EXCLUDED.favorite_director,
    top_directors = EXCLUDED.top_directors,
    top_directors_detail = EXCLUDED.top_directors_detail,
    top_genres = EXCLUDED.top_genres,
    top_keywords = EXCLUDED.top_keywords,
    analysis = EXCLUDED.analysis,
    personality = EXCLUDED.personality,
    sample_size = EXCLUDED.sample_size,
    rated_count = EXCLUDED.rated_count,
    metadata_coverage = EXCLUDED.metadata_coverage,
    confidence_level = EXCLUDED.confidence_level,
    confidence_score = EXCLUDED.confidence_score,
    algorithm_version = EXCLUDED.algorithm_version,
    source_fingerprint = EXCLUDED.source_fingerprint,
    generated_at = EXCLUDED.generated_at,
    updated_at = EXCLUDED.updated_at;

  DELETE FROM public.profile_favorites WHERE user_id = p_user_id;
  INSERT INTO public.profile_favorites (
    user_id, position, slug, title, release_year, tmdb_id, poster_url
  )
  SELECT
    p_user_id,
    (item->>'position')::SMALLINT,
    item->>'slug',
    item->>'title',
    NULLIF(item->>'release_year', '')::INTEGER,
    NULLIF(item->>'tmdb_id', '')::INTEGER,
    NULLIF(item->>'poster_url', '')
  FROM jsonb_array_elements(COALESCE(p_favorites, '[]'::jsonb)) AS item
  WHERE (item->>'position')::INTEGER BETWEEN 1 AND 4
    AND COALESCE(item->>'slug', '') <> ''
    AND COALESCE(item->>'title', '') <> '';

  UPDATE public.users SET
    display_name = COALESCE(NULLIF(p_profile->>'display_name', ''), display_name),
    avatar_url = COALESCE(NULLIF(p_profile->>'avatar_url', ''), avatar_url),
    letterboxd_stats = CASE
      WHEN p_profile ? 'stats' THEN COALESCE(p_profile->'stats', '{}'::jsonb)
      ELSE letterboxd_stats
    END,
    profile_sync_status = 'ready',
    profile_synced_at = now(),
    updated_at = now(),
    last_seen_at = now()
  WHERE id = p_user_id;
END;
$$;

REVOKE ALL ON FUNCTION public.save_profile_snapshot(BIGINT, JSONB, JSONB, JSONB)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.save_profile_snapshot(BIGINT, JSONB, JSONB, JSONB)
  TO service_role;

-- Atomic batch upsert for the crawl/enrich pipeline. Metadata (director, genres,
-- keywords, tmdb_id) is only overwritten when the incoming batch actually carries
-- it, so a search-only pass never clobbers details a later enrich pass filled in.
CREATE OR REPLACE FUNCTION public.upsert_watched_films(
  p_user_id BIGINT,
  p_films JSONB
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.users WHERE id = p_user_id AND account_status = 'active'
  ) THEN
    RAISE EXCEPTION 'active account not found';
  END IF;

  INSERT INTO public.user_watched_films (
    user_id, film_slug, title, release_year, tmdb_id, director, genres, keywords,
    user_rating, rating_observed, poster_url, poster_resolver_url, watched_rank, details_loaded,
    last_seen_run_id, is_active, updated_at
  )
  SELECT
    p_user_id,
    item->>'slug',
    COALESCE(item->>'title', ''),
    NULLIF(item->>'release_year', '')::INTEGER,
    NULLIF(item->>'tmdb_id', '')::INTEGER,
    COALESCE(item->>'director', ''),
    COALESCE(item->'genres', '[]'::jsonb),
    COALESCE(item->'keywords', '[]'::jsonb),
    NULLIF(item->>'user_rating', '')::REAL,
    COALESCE((item->>'rating_observed')::BOOLEAN, FALSE),
    NULLIF(item->>'poster_url', ''),
    NULLIF(item->>'poster_resolver_url', ''),
    NULLIF(item->>'watched_rank', '')::INTEGER,
    COALESCE((item->>'details_loaded')::BOOLEAN, FALSE),
    NULLIF(item->>'last_seen_run_id', '')::UUID,
    COALESCE((item->>'is_active')::BOOLEAN, TRUE),
    now()
  FROM jsonb_array_elements(COALESCE(p_films, '[]'::jsonb)) AS item
  WHERE COALESCE(item->>'slug', '') <> ''
  ON CONFLICT (user_id, film_slug) DO UPDATE SET
    title = CASE WHEN EXCLUDED.title <> '' THEN EXCLUDED.title ELSE public.user_watched_films.title END,
    release_year = COALESCE(EXCLUDED.release_year, public.user_watched_films.release_year),
    tmdb_id = COALESCE(EXCLUDED.tmdb_id, public.user_watched_films.tmdb_id),
    director = CASE WHEN EXCLUDED.director <> '' THEN EXCLUDED.director ELSE public.user_watched_films.director END,
    genres = CASE WHEN EXCLUDED.genres <> '[]'::jsonb THEN EXCLUDED.genres ELSE public.user_watched_films.genres END,
    keywords = CASE WHEN EXCLUDED.keywords <> '[]'::jsonb THEN EXCLUDED.keywords ELSE public.user_watched_films.keywords END,
    user_rating = CASE
      WHEN EXCLUDED.rating_observed THEN EXCLUDED.user_rating
      ELSE public.user_watched_films.user_rating
    END,
    rating_observed = public.user_watched_films.rating_observed OR EXCLUDED.rating_observed,
    poster_url = COALESCE(EXCLUDED.poster_url, public.user_watched_films.poster_url),
    poster_resolver_url = COALESCE(EXCLUDED.poster_resolver_url, public.user_watched_films.poster_resolver_url),
    watched_rank = COALESCE(EXCLUDED.watched_rank, public.user_watched_films.watched_rank),
    details_loaded = public.user_watched_films.details_loaded OR EXCLUDED.details_loaded,
    last_seen_run_id = COALESCE(EXCLUDED.last_seen_run_id, public.user_watched_films.last_seen_run_id),
    is_active = CASE
      WHEN EXCLUDED.last_seen_run_id IS NOT NULL THEN TRUE
      ELSE public.user_watched_films.is_active
    END,
    updated_at = now();

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_watched_films(BIGINT, JSONB)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_watched_films(BIGINT, JSONB)
  TO service_role;

-- Cross-process ownership for Render/background workers. Only one valid lease
-- can own a user's sync job at a time; stale leases may be reclaimed.
CREATE OR REPLACE FUNCTION public.claim_profile_sync_job(
  p_user_id BIGINT,
  p_lease_token UUID,
  p_lease_seconds INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_claimed BIGINT;
BEGIN
  UPDATE public.profile_sync_jobs
  SET lease_token = p_lease_token,
      lease_expires_at = now() + make_interval(secs => GREATEST(60, p_lease_seconds)),
      heartbeat_at = now(),
      updated_at = now()
  WHERE user_id = p_user_id
    AND state IN ('queued', 'running', 'failed')
    AND (
      lease_token = p_lease_token
      OR lease_expires_at IS NULL
      OR lease_expires_at <= now()
    )
  RETURNING user_id INTO v_claimed;
  RETURN v_claimed IS NOT NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_profile_sync_run(
  p_user_id BIGINT,
  p_sync_run_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  UPDATE public.user_watched_films
  SET is_active = COALESCE(last_seen_run_id = p_sync_run_id, FALSE),
      updated_at = CASE
        WHEN is_active IS DISTINCT FROM COALESCE(last_seen_run_id = p_sync_run_id, FALSE) THEN now()
        ELSE updated_at
      END
  WHERE user_id = p_user_id;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_profile_sync_job(BIGINT, UUID, INTEGER)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finalize_profile_sync_run(BIGINT, UUID)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_profile_sync_job(BIGINT, UUID, INTEGER)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.finalize_profile_sync_run(BIGINT, UUID)
  TO service_role;

CREATE OR REPLACE FUNCTION public.create_blend_request(
  p_requester_user_id BIGINT,
  p_recipient_username TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_recipient_user_id BIGINT;
  v_request_id UUID;
BEGIN
  SELECT id INTO v_recipient_user_id
  FROM public.users
  WHERE username = lower(trim(leading '@' FROM p_recipient_username))
    AND account_status = 'active';

  IF v_recipient_user_id IS NULL THEN
    RAISE EXCEPTION 'recipient_not_found';
  END IF;
  IF v_recipient_user_id = p_requester_user_id THEN
    RAISE EXCEPTION 'self_request';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.user_blocks
    WHERE (blocker_user_id = p_requester_user_id AND blocked_user_id = v_recipient_user_id)
       OR (blocker_user_id = v_recipient_user_id AND blocked_user_id = p_requester_user_id)
  ) THEN
    RAISE EXCEPTION 'blend_user_blocked';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended(
      LEAST(p_requester_user_id, v_recipient_user_id)::TEXT || ':' ||
      GREATEST(p_requester_user_id, v_recipient_user_id)::TEXT,
      0
    )
  );

  UPDATE public.blend_requests
  SET status = 'expired', decided_at = now()
  WHERE status = 'pending' AND expires_at <= now()
    AND (
      (requester_user_id = p_requester_user_id AND recipient_user_id = v_recipient_user_id)
      OR
      (requester_user_id = v_recipient_user_id AND recipient_user_id = p_requester_user_id)
    );

  IF EXISTS (
    SELECT 1 FROM public.blend_requests
    WHERE status = 'accepted'
      AND (
        (requester_user_id = p_requester_user_id AND recipient_user_id = v_recipient_user_id)
        OR
        (requester_user_id = v_recipient_user_id AND recipient_user_id = p_requester_user_id)
      )
  ) THEN
    RAISE EXCEPTION 'blend_already_accepted';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.blend_requests
    WHERE status = 'pending'
      AND (
        (requester_user_id = p_requester_user_id AND recipient_user_id = v_recipient_user_id)
        OR
        (requester_user_id = v_recipient_user_id AND recipient_user_id = p_requester_user_id)
      )
  ) THEN
    RAISE EXCEPTION 'blend_request_exists';
  END IF;

  IF (
    SELECT count(*) FROM public.blend_requests
    WHERE requester_user_id = p_requester_user_id
      AND status = 'pending' AND expires_at > now()
  ) >= 10 THEN
    RAISE EXCEPTION 'pending_quota_reached';
  END IF;

  INSERT INTO public.blend_requests (requester_user_id, recipient_user_id)
  VALUES (p_requester_user_id, v_recipient_user_id)
  RETURNING id INTO v_request_id;
  RETURN v_request_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.decide_blend_request(
  p_request_id UUID,
  p_recipient_user_id BIGINT,
  p_decision TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_request public.blend_requests%ROWTYPE;
BEGIN
  IF p_decision NOT IN ('accepted', 'rejected') THEN
    RAISE EXCEPTION 'invalid_decision';
  END IF;

  SELECT * INTO v_request FROM public.blend_requests
  WHERE id = p_request_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'request_not_found';
  END IF;
  IF v_request.recipient_user_id <> p_recipient_user_id THEN
    RAISE EXCEPTION 'forbidden';
  END IF;
  IF v_request.status = 'pending' AND v_request.expires_at <= now() THEN
    UPDATE public.blend_requests
    SET status = 'expired', decided_at = now()
    WHERE id = p_request_id;
    RETURN jsonb_build_object('id', p_request_id, 'status', 'expired');
  END IF;
  IF v_request.status = p_decision THEN
    RETURN to_jsonb(v_request);
  END IF;
  IF v_request.status <> 'pending' THEN
    RAISE EXCEPTION 'request_already_decided';
  END IF;

  UPDATE public.blend_requests
  SET status = p_decision, decided_at = now()
  WHERE id = p_request_id
  RETURNING * INTO v_request;
  RETURN to_jsonb(v_request);
END;
$$;

CREATE OR REPLACE FUNCTION public.cancel_blend_request(
  p_request_id UUID,
  p_requester_user_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.blend_requests
  SET status = 'cancelled', decided_at = now()
  WHERE id = p_request_id
    AND requester_user_id = p_requester_user_id
    AND status = 'pending';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'request_not_cancellable';
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.save_blend_result(
  p_request_id UUID,
  p_actor_user_id BIGINT,
  p_score INTEGER,
  p_confidence JSONB,
  p_result JSONB,
  p_algorithm_version TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_result_id UUID;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.blend_requests
    WHERE id = p_request_id AND status = 'accepted'
      AND p_actor_user_id IN (requester_user_id, recipient_user_id)
  ) THEN
    RAISE EXCEPTION 'accepted_request_not_found';
  END IF;

  INSERT INTO public.blend_results (
    request_id, score, confidence, result, algorithm_version
  ) VALUES (
    p_request_id, p_score, p_confidence, p_result, p_algorithm_version
  )
  ON CONFLICT (request_id) DO UPDATE SET
    score = EXCLUDED.score,
    confidence = EXCLUDED.confidence,
    result = EXCLUDED.result,
    algorithm_version = EXCLUDED.algorithm_version
  RETURNING id INTO v_result_id;
  RETURN v_result_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.block_user(
  p_blocker_user_id BIGINT,
  p_blocked_username TEXT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_blocked_user_id BIGINT;
BEGIN
  SELECT id INTO v_blocked_user_id FROM public.users
  WHERE username = lower(trim(leading '@' FROM p_blocked_username))
    AND account_status = 'active';
  IF v_blocked_user_id IS NULL THEN RAISE EXCEPTION 'user_not_found'; END IF;
  IF v_blocked_user_id = p_blocker_user_id THEN RAISE EXCEPTION 'self_block'; END IF;

  INSERT INTO public.user_blocks (blocker_user_id, blocked_user_id)
  VALUES (p_blocker_user_id, v_blocked_user_id)
  ON CONFLICT DO NOTHING;

  UPDATE public.blend_requests
  SET status = 'cancelled', decided_at = now()
  WHERE status = 'pending'
    AND (
      (requester_user_id = p_blocker_user_id AND recipient_user_id = v_blocked_user_id)
      OR
      (requester_user_id = v_blocked_user_id AND recipient_user_id = p_blocker_user_id)
    );
  RETURN v_blocked_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.unblock_user(
  p_blocker_user_id BIGINT,
  p_blocked_username TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  DELETE FROM public.user_blocks b
  USING public.users u
  WHERE b.blocker_user_id = p_blocker_user_id
    AND b.blocked_user_id = u.id
    AND u.username = lower(trim(leading '@' FROM p_blocked_username));
END;
$$;

CREATE OR REPLACE FUNCTION public.report_user(
  p_reporter_user_id BIGINT,
  p_reported_username TEXT,
  p_category TEXT,
  p_detail TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_reported_user_id BIGINT;
  v_report_id UUID;
BEGIN
  IF p_category NOT IN ('spam', 'harassment', 'impersonation', 'other') THEN
    RAISE EXCEPTION 'invalid_report_category';
  END IF;
  SELECT id INTO v_reported_user_id FROM public.users
  WHERE username = lower(trim(leading '@' FROM p_reported_username))
    AND account_status = 'active';
  IF v_reported_user_id IS NULL THEN RAISE EXCEPTION 'user_not_found'; END IF;
  IF v_reported_user_id = p_reporter_user_id THEN RAISE EXCEPTION 'self_report'; END IF;
  IF (
    SELECT count(*) FROM public.user_reports
    WHERE reporter_user_id = p_reporter_user_id
      AND created_at >= now() - interval '24 hours'
  ) >= 5 THEN
    RAISE EXCEPTION 'report_quota_reached';
  END IF;

  INSERT INTO public.user_reports (
    reporter_user_id, reported_user_id, category, detail
  ) VALUES (
    p_reporter_user_id, v_reported_user_id, p_category, left(COALESCE(p_detail, ''), 500)
  ) RETURNING id INTO v_report_id;
  RETURN v_report_id;
END;
$$;

REVOKE ALL ON FUNCTION public.create_blend_request(BIGINT, TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.decide_blend_request(UUID, BIGINT, TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cancel_blend_request(UUID, BIGINT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.save_blend_result(UUID, BIGINT, INTEGER, JSONB, JSONB, TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.block_user(BIGINT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.unblock_user(BIGINT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.report_user(BIGINT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_blend_request(BIGINT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.decide_blend_request(UUID, BIGINT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.cancel_blend_request(UUID, BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION public.save_blend_result(UUID, BIGINT, INTEGER, JSONB, JSONB, TEXT)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.block_user(BIGINT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.unblock_user(BIGINT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.report_user(BIGINT, TEXT, TEXT, TEXT) TO service_role;

-- TMDb API önbelleği: SQLite'ın üretim ortamındaki yedeği.
CREATE TABLE IF NOT EXISTS public.tmdb_cache (
  namespace   TEXT         NOT NULL,
  key         TEXT         NOT NULL,
  value       JSONB        NOT NULL,
  created_at  TIMESTAMPTZ  DEFAULT now(),
  PRIMARY KEY (namespace, key)
);

-- Row Level Security — backend yalnızca service_role secret ile bağlanır.
-- anon/authenticated rolleri browser veya ele geçirilmiş public key üzerinden bu
-- tablolardaki kullanıcı adlarını ve cache verisini okuyamaz/değiştiremez.
ALTER TABLE public.users     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tmdb_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.film_posters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.director_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.taste_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_favorites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_watched_films ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_sync_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blend_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blend_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_all_users" ON public.users;
DROP POLICY IF EXISTS "service_all_tmdb_cache" ON public.tmdb_cache;

REVOKE ALL ON TABLE public.users FROM anon, authenticated;
REVOKE ALL ON TABLE public.tmdb_cache FROM anon, authenticated;
REVOKE ALL ON TABLE public.film_posters FROM anon, authenticated;
REVOKE ALL ON TABLE public.director_images FROM anon, authenticated;
REVOKE ALL ON TABLE public.taste_profiles FROM anon, authenticated;
REVOKE ALL ON TABLE public.profile_favorites FROM anon, authenticated;
REVOKE ALL ON TABLE public.user_watched_films FROM anon, authenticated;
REVOKE ALL ON TABLE public.profile_sync_jobs FROM anon, authenticated;
REVOKE ALL ON TABLE public.auth_challenges FROM anon, authenticated;
REVOKE ALL ON TABLE public.blend_requests FROM anon, authenticated;
REVOKE ALL ON TABLE public.blend_results FROM anon, authenticated;
REVOKE ALL ON TABLE public.user_blocks FROM anon, authenticated;
REVOKE ALL ON TABLE public.user_reports FROM anon, authenticated;
REVOKE ALL ON TABLE public.auth_audit_log FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.users_id_seq FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.auth_audit_log_id_seq FROM anon, authenticated;

GRANT ALL ON TABLE public.users TO service_role;
GRANT ALL ON TABLE public.tmdb_cache TO service_role;
GRANT ALL ON TABLE public.film_posters TO service_role;
GRANT ALL ON TABLE public.director_images TO service_role;
GRANT ALL ON TABLE public.taste_profiles TO service_role;
GRANT ALL ON TABLE public.profile_favorites TO service_role;
GRANT ALL ON TABLE public.user_watched_films TO service_role;
GRANT ALL ON TABLE public.profile_sync_jobs TO service_role;
GRANT ALL ON TABLE public.auth_challenges TO service_role;
GRANT ALL ON TABLE public.blend_requests TO service_role;
GRANT ALL ON TABLE public.blend_results TO service_role;
GRANT ALL ON TABLE public.user_blocks TO service_role;
GRANT ALL ON TABLE public.user_reports TO service_role;
GRANT ALL ON TABLE public.auth_audit_log TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.users_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.auth_audit_log_id_seq TO service_role;
