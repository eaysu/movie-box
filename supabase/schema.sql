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

-- Row Level Security — backend yalnızca service_role secret ile bağlanır.
-- anon/authenticated rolleri browser veya ele geçirilmiş public key üzerinden bu
-- tablolardaki kullanıcı adlarını ve cache verisini okuyamaz/değiştiremez.
ALTER TABLE public.users     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tmdb_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_all_users" ON public.users;
DROP POLICY IF EXISTS "service_all_tmdb_cache" ON public.tmdb_cache;

REVOKE ALL ON TABLE public.users FROM anon, authenticated;
REVOKE ALL ON TABLE public.tmdb_cache FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.users_id_seq FROM anon, authenticated;

GRANT ALL ON TABLE public.users TO service_role;
GRANT ALL ON TABLE public.tmdb_cache TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.users_id_seq TO service_role;
