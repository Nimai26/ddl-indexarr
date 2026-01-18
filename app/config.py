"""Configuration centralisée de DDL-Indexarr"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Configuration de l'application"""
    
    # === API ===
    api_key: str = Field(default="ddl-indexarr", alias="DDL_INDEXARR_API_KEY")
    host: str = Field(default="0.0.0.0")
    torznab_port: int = Field(default=9117)
    download_client_port: int = Field(default=9120)
    
    # === DarkiWorld ===
    darkiworld_base_url: str = Field(default="https://darkiworld.com", alias="DARKIWORLD_BASE_URL")
    darkiworld_remember_cookie_name: str = Field(default="", alias="DARKIWORLD_REMEMBER_COOKIE_NAME")
    darkiworld_remember_cookie_value: str = Field(default="", alias="DARKIWORLD_REMEMBER_COOKIE_VALUE")
    
    # === JDownloader ===
    jdownloader_email: str = Field(default="", alias="JDOWNLOADER_EMAIL")
    jdownloader_password: str = Field(default="", alias="JDOWNLOADER_PASSWORD")
    jdownloader_device_name: str = Field(default="ddl-indexarr", alias="JDOWNLOADER_DEVICE_NAME")
    
    # === Chemins ===
    output_path: str = Field(default="/output", alias="DOWNLOAD_FOLDER")
    data_path: str = Field(default="/data")
    
    # === TMDB ===
    tmdb_api_key: str = Field(default="", alias="TMDB_KEY")
    
    # === Debug ===
    debug: bool = Field(default=False, alias="DEBUG")
    
    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Récupère la configuration (singleton)"""
    return Settings()
