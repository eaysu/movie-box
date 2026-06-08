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
    scraperapi_key: str = ""
    openai_model: str = "gpt-5-mini-2025-08-07"
    supabase_url: str = ""
    supabase_key: str = ""

    # --- Embeddings ---
    embedding_provider: str = "tfidf"  # "tfidf" | "sentence-transformers"
    st_model: str = "all-MiniLM-L6-v2"

    # --- Recommender tuning ---
    num_recommendations: int = 8

    # --- Scraper ---
    # curl-cffi (retry + parmak izi rotasyonu + humanize) asıl iş gücü;
    # ScraperAPI sadece bloklanan sayfalar için sıkı bütçeli son çare.
    # Agresif mod: hız öncelikli — daha kısa gecikme, daha düşük film tavanı.
    scrape_delay: float = 0.6       # sayfalar arası temel gecikme (jitter eklenir)
    scrape_max_pages: int = 8       # watchlist için max sayfa
    watched_max_pages: int = 8      # izlenen filmler için max sayfa
    watched_film_limit: int = 300   # hard limit — taste/blend için yeterli profil
    watchlist_film_limit: int = 300 # watchlist'ten candidate havuzu
    scrape_max_retries: int = 3     # 403/429'da sayfa başına tekrar deneme
    # ScraperAPI fallback bütçesi (sayfa başına ~10 kredi). 0 = tamamen kapalı.
    # Şu an kapalı: yalnızca kendi curl-cffi scraper'ımız kullanılır, 0 kredi.
    scraperapi_max_pages: int = 0

    # --- Storage ---
    data_dir: str = "data"

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def catalog_path(self) -> Path:
        return self.data_path / "catalog.json"

    @property
    def catalog_vectors_path(self) -> Path:
        return self.data_path / "catalog_vectors.npy"

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


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
