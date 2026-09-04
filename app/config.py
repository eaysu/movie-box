"""Application settings, loaded from the environment / a .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Values come from .env or the environment."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API keys ---
    tmdb_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini-2025-08-07"
    # Zevk/kişilik analizi için ayrı model; boşsa openai_model kullanılır.
    openai_analysis_model: str = "gpt-5.6-terra"
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_anon_key: str = ""
    auth_identity_secret: str = ""
    auth_cookie_secure: bool = True
    auth_session_max_age: int = 60 * 60 * 24 * 7

    # --- Recommender tuning ---
    num_recommendations: int = 5
    recommendation_history_limit: int = 100
    favorite_director_boost: float = 0.08

    # --- Sinema gündemi (bülten) ---
    # Ships dark: the release layer and the venue framework are inert until this
    # is turned on for an account cohort.
    bulletin_enabled: bool = False
    bulletin_region: str = "TR"
    # Kart üzerindeki şehir seçicisi; boş seçim ülke geneli vizyon demektir.
    bulletin_cities: str = "İstanbul,Ankara,İzmir"
    # A venue is re-fetched at most this often, whoever triggers it.
    bulletin_ingest_interval_hours: int = 12

    # --- Scraper ---
    # Letterboxd sayfaları doğrudan, curl-cffi ile okunur. Ücretli veya harici
    # scraping proxy/API servisi kullanılmaz.
    # Agresif mod: hız öncelikli — daha kısa gecikme, daha düşük film tavanı.
    scrape_delay: float = 0.6       # sayfalar arası temel gecikme (jitter eklenir)
    scrape_max_pages: int = 8       # watchlist için max sayfa
    watched_max_pages: int = 8      # izlenen filmler için max sayfa
    watched_film_limit: int = 100   # hard limit — en son izlenen N film (taste profili)
    # Kept for backwards-compatible env parsing; onboarding no longer performs
    # a duplicate watched-list scrape before the checkpointed full sweep.
    provisional_watched_film_limit: int = 0
    watchlist_film_limit: int = 150 # candidate havuzu — en son eklenen N film (varsayılan sıra: en yeni önce)
    scrape_max_retries: int = 3     # 403/429'da sayfa başına tekrar deneme

    # --- Storage ---
    data_dir: str = "data"

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cache_db_path(self) -> Path:
        return self.data_path / "cache.sqlite3"

    @property
    def has_tmdb(self) -> bool:
        return bool(self.tmdb_api_key.strip())

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url.strip() and self.supabase_key.strip())

    @property
    def bulletin_city_list(self) -> list[str]:
        return [city.strip() for city in self.bulletin_cities.split(",") if city.strip()]

    @property
    def has_auth(self) -> bool:
        return bool(
            self.has_supabase
            and self.supabase_anon_key.strip()
            and self.auth_identity_secret.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
