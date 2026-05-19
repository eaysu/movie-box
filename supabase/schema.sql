-- Supabase şeması — Supabase Studio > SQL Editor'da çalıştırın.

-- Kullanıcı takibi: her Letterboxd kullanıcı adı için bir satır.
CREATE TABLE IF NOT EXISTS public.users (
  id            BIGSERIAL    PRIMARY KEY,
  username      TEXT         UNIQUE NOT NULL,
  created_at    TIMESTAMPTZ  DEFAULT now(),
  last_seen_at  TIMESTAMPTZ  DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON public.users (username);

-- TMDb API önbelleği: SQLite'ın üretim ortamındaki yedeği.
CREATE TABLE IF NOT EXISTS public.tmdb_cache (
  namespace   TEXT         NOT NULL,
  key         TEXT         NOT NULL,
  value       JSONB        NOT NULL,
  created_at  TIMESTAMPTZ  DEFAULT now(),
  PRIMARY KEY (namespace, key)
);

-- Row Level Security — servis anahtarı (SUPABASE_KEY = service_role) her şeyi okuyup yazabilir.
ALTER TABLE public.users     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tmdb_cache ENABLE ROW LEVEL SECURITY;

-- Servis anahtarıyla tüm operasyonlara izin ver.
CREATE POLICY "service_all_users"      ON public.users
  USING (true) WITH CHECK (true);

CREATE POLICY "service_all_tmdb_cache" ON public.tmdb_cache
  USING (true) WITH CHECK (true);
