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
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

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
  top_genres          JSONB NOT NULL DEFAULT '[]'::jsonb,
  top_keywords        JSONB NOT NULL DEFAULT '[]'::jsonb,
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
    user_id, summary, favorite_director, top_genres, top_keywords,
    sample_size, rated_count, metadata_coverage, confidence_level,
    confidence_score, algorithm_version, source_fingerprint, generated_at, updated_at
  ) VALUES (
    p_user_id,
    COALESCE(p_taste->>'summary', ''),
    COALESCE(p_taste->>'favorite_director', ''),
    COALESCE(p_taste->'top_genres', '[]'::jsonb),
    COALESCE(p_taste->'top_keywords', '[]'::jsonb),
    COALESCE((p_taste->>'sample_size')::INTEGER, 0),
    COALESCE((p_taste->>'rated_count')::INTEGER, 0),
    COALESCE((p_taste->>'metadata_coverage')::INTEGER, 0),
    COALESCE(p_taste->>'confidence_level', 'low'),
    COALESCE((p_taste->>'confidence_score')::INTEGER, 0),
    COALESCE(p_taste->>'algorithm_version', 'taste-v1'),
    COALESCE(p_taste->>'source_fingerprint', ''),
    now(),
    now()
  )
  ON CONFLICT (user_id) DO UPDATE SET
    summary = EXCLUDED.summary,
    favorite_director = EXCLUDED.favorite_director,
    top_genres = EXCLUDED.top_genres,
    top_keywords = EXCLUDED.top_keywords,
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

REVOKE ALL ON FUNCTION public.create_blend_request(BIGINT, TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.decide_blend_request(UUID, BIGINT, TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cancel_blend_request(UUID, BIGINT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.save_blend_result(UUID, BIGINT, INTEGER, JSONB, JSONB, TEXT)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_blend_request(BIGINT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.decide_blend_request(UUID, BIGINT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.cancel_blend_request(UUID, BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION public.save_blend_result(UUID, BIGINT, INTEGER, JSONB, JSONB, TEXT)
  TO service_role;

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
ALTER TABLE public.taste_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_favorites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blend_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blend_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_all_users" ON public.users;
DROP POLICY IF EXISTS "service_all_tmdb_cache" ON public.tmdb_cache;

REVOKE ALL ON TABLE public.users FROM anon, authenticated;
REVOKE ALL ON TABLE public.tmdb_cache FROM anon, authenticated;
REVOKE ALL ON TABLE public.taste_profiles FROM anon, authenticated;
REVOKE ALL ON TABLE public.profile_favorites FROM anon, authenticated;
REVOKE ALL ON TABLE public.auth_challenges FROM anon, authenticated;
REVOKE ALL ON TABLE public.blend_requests FROM anon, authenticated;
REVOKE ALL ON TABLE public.blend_results FROM anon, authenticated;
REVOKE ALL ON TABLE public.auth_audit_log FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.users_id_seq FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.auth_audit_log_id_seq FROM anon, authenticated;

GRANT ALL ON TABLE public.users TO service_role;
GRANT ALL ON TABLE public.tmdb_cache TO service_role;
GRANT ALL ON TABLE public.taste_profiles TO service_role;
GRANT ALL ON TABLE public.profile_favorites TO service_role;
GRANT ALL ON TABLE public.auth_challenges TO service_role;
GRANT ALL ON TABLE public.blend_requests TO service_role;
GRANT ALL ON TABLE public.blend_results TO service_role;
GRANT ALL ON TABLE public.auth_audit_log TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.users_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.auth_audit_log_id_seq TO service_role;
