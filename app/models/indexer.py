"""Modèles pour les indexers et instances *arr"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ArrType(str, Enum):
    """Types d'applications *arr supportées"""
    RADARR = "radarr"
    SONARR = "sonarr"
    LIDARR = "lidarr"


class MediaType(str, Enum):
    """Types de médias"""
    MOVIE = "movie"
    TV = "tv"
    MUSIC = "music"


class IndexerConfig(BaseModel):
    """Configuration d'un indexer pour une instance *arr"""
    
    # Identifiant unique
    id: str
    name: str
    
    # Type d'application
    arr_type: ArrType
    media_type: MediaType
    
    # Catégories Torznab supportées
    torznab_categories: list[int] = Field(default_factory=list)
    
    # Catégories DarkiWorld à rechercher (toutes les variantes)
    darkiworld_categories: list[str] = Field(default_factory=list)
    
    # Type de recherche Torznab
    search_type: str = "search"  # movie, tvsearch, music
    
    # Paramètres de recherche supportés
    supported_params: str = "q"
    
    # Dossier de sortie JDownloader
    output_subfolder: str = ""


# Configuration des 3 indexers principaux
INDEXER_CONFIGS: dict[str, IndexerConfig] = {
    # === RADARR - Tous les films (standard + anime + 4K) ===
    "radarr": IndexerConfig(
        id="radarr",
        name="DDL-Indexarr (Films)",
        arr_type=ArrType.RADARR,
        media_type=MediaType.MOVIE,
        torznab_categories=[2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
        darkiworld_categories=["films", "films-4k", "films-animes"],
        search_type="movie",
        supported_params="q,imdbid,tmdbid",
        output_subfolder="radarr",
    ),
    
    # === SONARR - Toutes les séries (standard + anime + 4K) ===
    "sonarr": IndexerConfig(
        id="sonarr",
        name="DDL-Indexarr (Séries)",
        arr_type=ArrType.SONARR,
        media_type=MediaType.TV,
        torznab_categories=[5000, 5010, 5020, 5030, 5040, 5045, 5050, 5060, 5070],
        darkiworld_categories=["series", "series-4k", "animes"],
        search_type="tvsearch",
        supported_params="q,tvdbid,imdbid,season,ep",
        output_subfolder="sonarr",
    ),
    
    # === LIDARR - Musique ===
    "lidarr": IndexerConfig(
        id="lidarr",
        name="DDL-Indexarr (Musique)",
        arr_type=ArrType.LIDARR,
        media_type=MediaType.MUSIC,
        torznab_categories=[3000, 3010, 3020, 3030, 3040],
        darkiworld_categories=["musique"],
        search_type="music",
        supported_params="q,artist,album",
        output_subfolder="lidarr",
    ),
}


def get_indexer_config(indexer_id: str) -> Optional[IndexerConfig]:
    """Récupère la configuration d'un indexer par son ID"""
    return INDEXER_CONFIGS.get(indexer_id)


def get_indexer_by_search_type(search_type: str, categories: list[int] = None) -> Optional[IndexerConfig]:
    """
    Trouve l'indexer correspondant au type de recherche Torznab.
    
    Args:
        search_type: Type de recherche (movie, tvsearch, music, search)
        categories: Liste des catégories Torznab demandées (pour détecter le type quand t=search)
    """
    # Mapping direct par type de recherche
    type_map = {
        "movie": "radarr",
        "tvsearch": "sonarr", 
        "music": "lidarr",
        "audio": "lidarr",
    }
    
    # Si type explicite, l'utiliser
    if search_type in type_map:
        indexer_id = type_map[search_type]
        return INDEXER_CONFIGS.get(indexer_id)
    
    # Pour "search" générique, détecter le type via les catégories
    if search_type == "search" and categories:
        # Catégories musique: 3000-3999
        music_cats = [c for c in categories if 3000 <= c < 4000]
        if music_cats:
            return INDEXER_CONFIGS.get("lidarr")
        
        # Catégories TV: 5000-5999
        tv_cats = [c for c in categories if 5000 <= c < 6000]
        if tv_cats:
            return INDEXER_CONFIGS.get("sonarr")
        
        # Catégories films: 2000-2999 (ou par défaut)
        return INDEXER_CONFIGS.get("radarr")
    
    # Par défaut: radarr (films)
    return INDEXER_CONFIGS.get("radarr")


def get_all_indexers() -> list[IndexerConfig]:
    """Récupère tous les indexers configurés"""
    return list(INDEXER_CONFIGS.values())
