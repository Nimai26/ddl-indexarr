"""API Newznab pour Radarr/Sonarr/Lidarr - DDL via SABnzbd"""

import base64
import json
import re
import httpx
from datetime import datetime as dt
from fastapi import APIRouter, Query, Request, Response
from loguru import logger
from html import escape
from typing import Optional

from app.config import get_settings
from app.services.darkiworld import get_darkiworld_client
from app.models.indexer import MediaType, get_indexer_by_search_type, get_indexer_config

router = APIRouter(tags=["Newznab"])


# =============================================================================
# RÉSOLUTION DES IDS IMDB/TMDB EN TITRES
# =============================================================================

async def resolve_imdb_to_title(imdb_id: str) -> Optional[str]:
    """
    Résout un IMDB ID en titre de film/série via l'API TMDB.
    
    Args:
        imdb_id: ID IMDB (avec ou sans préfixe 'tt')
        
    Returns:
        Titre du film/série ou None si non trouvé
    """
    settings = get_settings()
    tmdb_key = settings.tmdb_api_key
    
    if not tmdb_key:
        logger.warning("⚠️ TMDB API key not configured - cannot resolve IMDB ID to title")
        return None
    
    # Normaliser l'ID IMDB (ajouter 'tt' si absent)
    if not imdb_id.startswith("tt"):
        imdb_id = f"tt{imdb_id}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Utiliser l'endpoint find de TMDB avec IMDB ID
            url = f"https://api.themoviedb.org/3/find/{imdb_id}"
            params = {
                "api_key": tmdb_key,
                "external_source": "imdb_id",
                "language": "fr-FR"
            }
            
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Chercher dans les résultats films
            if data.get("movie_results"):
                movie = data["movie_results"][0]
                title = movie.get("original_title") or movie.get("title")
                logger.info(f"🎬 IMDB {imdb_id} → Film: {title}")
                return title
            
            # Chercher dans les résultats séries
            if data.get("tv_results"):
                show = data["tv_results"][0]
                title = show.get("original_name") or show.get("name")
                logger.info(f"📺 IMDB {imdb_id} → Série: {title}")
                return title
            
            logger.warning(f"⚠️ IMDB {imdb_id} not found in TMDB")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error resolving IMDB {imdb_id}: {e}")
        return None


async def resolve_tmdb_to_title(tmdb_id: str, media_type: str = "movie") -> Optional[str]:
    """
    Résout un TMDB ID en titre de film/série.
    
    Args:
        tmdb_id: ID TMDB
        media_type: "movie" ou "tv"
        
    Returns:
        Titre du film/série ou None si non trouvé
    """
    settings = get_settings()
    tmdb_key = settings.tmdb_api_key
    
    if not tmdb_key:
        logger.warning("⚠️ TMDB API key not configured - cannot resolve TMDB ID to title")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
            params = {
                "api_key": tmdb_key,
                "language": "fr-FR"
            }
            
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if media_type == "movie":
                title = data.get("original_title") or data.get("title")
                logger.info(f"🎬 TMDB {tmdb_id} → Film: {title}")
            else:
                title = data.get("original_name") or data.get("name")
                logger.info(f"📺 TMDB {tmdb_id} → Série: {title}")
            
            return title
            
    except Exception as e:
        logger.error(f"❌ Error resolving TMDB {tmdb_id}: {e}")
        return None


async def resolve_tvdb_to_title(tvdb_id: str) -> Optional[str]:
    """
    Résout un TVDB ID en titre de série via l'API TMDB (external_ids).
    
    Args:
        tvdb_id: ID TVDB
        
    Returns:
        Titre de la série ou None si non trouvé
    """
    settings = get_settings()
    tmdb_key = settings.tmdb_api_key
    
    if not tmdb_key:
        logger.warning("⚠️ TMDB API key not configured - cannot resolve TVDB ID to title")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://api.themoviedb.org/3/find/{tvdb_id}"
            params = {
                "api_key": tmdb_key,
                "external_source": "tvdb_id",
                "language": "fr-FR"
            }
            
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("tv_results"):
                show = data["tv_results"][0]
                title = show.get("original_name") or show.get("name")
                logger.info(f"📺 TVDB {tvdb_id} → Série: {title}")
                return title
            
            logger.warning(f"⚠️ TVDB {tvdb_id} not found in TMDB")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error resolving TVDB {tvdb_id}: {e}")
        return None


# =============================================================================
# MAPPING QUALITÉS DARKIWORLD → RADARR/SONARR
# =============================================================================

QUALITY_MAPPING = {
    # Qualités 2160p/4K/UHD - Noms Sonarr: WEBDL-2160p, Bluray-2160p, Bluray-2160p Remux
    'ULTRA HD (x265)': 'Bluray-2160p',
    'ULTRA HD': 'Bluray-2160p',
    'UHD (x265)': 'Bluray-2160p',
    'UHD': 'Bluray-2160p',
    'Ultra HDLight (x265)': 'WEBDL-2160p',
    'Ultra HDLight': 'WEBDL-2160p',
    'REMUX UHD': 'Bluray-2160p Remux',
    'REMUX 4K': 'Bluray-2160p Remux',
    'REMUX BLURAY 2160p': 'Bluray-2160p Remux',
    '4K': 'WEBDL-2160p',
    '2160p': 'WEBDL-2160p',
    
    # Qualités 1080p - Remux - Nom Sonarr: Bluray-1080p Remux
    'REMUX BLURAY': 'Bluray-1080p Remux',
    'REMUX': 'Bluray-1080p Remux',
    'REMUX 1080p': 'Bluray-1080p Remux',
    
    # Qualités 1080p - Bluray
    'Bluray 1080p': 'Bluray-1080p',
    'Bluray': 'Bluray-1080p',
    'BDRip 1080p': 'Bluray-1080p',
    'BRRip 1080p': 'Bluray-1080p',
    
    # Qualités 1080p - WEB
    'HDLight 1080p (x265)': 'WEBDL-1080p',
    'HDLight 1080p': 'WEBDL-1080p',
    'WEB 1080p': 'WEBDL-1080p',
    'WEB-DL 1080p': 'WEBDL-1080p',
    'WEBDL 1080p': 'WEBDL-1080p',
    'WEBRip 1080p': 'WEBRip-1080p',
    '1080p': 'WEBDL-1080p',
    
    # Qualités 720p
    'Bluray 720p': 'Bluray-720p',
    'HDLight 720p (x265)': 'WEBDL-720p',
    'HDLight 720p': 'WEBDL-720p',
    'WEB-DL 720p': 'WEBDL-720p',
    'WEBRip 720p': 'WEBRip-720p',
    '720p': 'WEBDL-720p',
    
    # Qualités standard
    'DVDRIP': 'DVD',
    'DVDRip': 'DVD',
    'DVD': 'DVD',
    'HDTV 1080p': 'HDTV-1080p',
    'HDTV 720p': 'HDTV-720p',
    'HDTV': 'HDTV-1080p',
    
    # Qualités 3D
    'Blu-Ray 3D': 'Bluray-1080p',
    'REMUX 3D': 'Bluray-1080p Remux',
    
    # Autres
    'ISO': 'BR-DISK',
    'Autre': 'WEBDL-1080p',
}


def extract_size_from_nfo(nfo_data: list) -> Optional[int]:
    """
    Extrait la taille du fichier depuis le NFO.
    Le NFO contient souvent "File size: X.XX GiB" ou "File size: X.XX MiB"
    
    Returns:
        Taille en bytes ou None si non trouvée
    """
    if not nfo_data or len(nfo_data) == 0:
        return None
    
    nfo_text = nfo_data[0].get("nfo", "")
    if not nfo_text:
        return None
    
    # Patterns pour la taille
    # Ex: "File size: 6.75 GiB" ou "File size : 2.54 GB"
    size_patterns = [
        r'File\s*size\s*:\s*([\d.,]+)\s*(GiB|GB|MiB|MB)',
        r'Size\s*:\s*([\d.,]+)\s*(GiB|GB|MiB|MB)',
    ]
    
    for pattern in size_patterns:
        match = re.search(pattern, nfo_text, re.IGNORECASE)
        if match:
            size_str = match.group(1).replace(',', '.')
            unit = match.group(2).upper()
            
            try:
                size_float = float(size_str)
                
                # Convertir en bytes
                if unit in ('GIB', 'GB'):
                    return int(size_float * 1024 * 1024 * 1024)
                elif unit in ('MIB', 'MB'):
                    return int(size_float * 1024 * 1024)
            except ValueError:
                continue
    
    return None


def estimate_file_size(quality: str, media_type: MediaType = None, is_season_pack: bool = False) -> int:
    """
    Estime une taille de fichier réaliste basée sur la qualité et le type de média.
    Utilisé comme fallback quand NFO et API ne fournissent pas de taille valide.
    
    Les tailles sont calibrées pour passer les vérifications de Sonarr/Radarr
    tout en restant réalistes.
    
    Args:
        quality: Qualité DarkiWorld (ex: "ULTRA HD (x265)", "WEB 1080p")
        media_type: Type de média (MOVIE, TV, MUSIC)
        is_season_pack: True si c'est un pack de saison (pour les séries)
    
    Returns:
        Taille estimée en bytes
    """
    quality_upper = (quality or "").upper()
    
    # Définir les tailles de base par qualité (pour un épisode ~45min ou film ~2h)
    # Format: (taille_episode_GB, taille_film_GB)
    size_map = {
        # 4K/UHD
        "REMUX UHD": (50.0, 70.0),      # Remux 4K - très gros
        "REMUX 4K": (50.0, 70.0),
        "ULTRA HD": (7.0, 15.0),         # 4K encodé
        "UHD": (7.0, 15.0),
        "2160": (6.0, 12.0),
        # Remux 1080p
        "REMUX": (25.0, 40.0),           # Remux Bluray 1080p
        # 1080p encodé
        "BLURAY 1080": (4.0, 10.0),
        "1080": (2.0, 5.0),              # WEB/HDTV 1080p
        "HDLIGHT 1080": (1.5, 4.0),      # HDLight
        # 720p
        "720": (1.0, 2.5),
        "HDLIGHT 720": (0.8, 2.0),
        # SD
        "DVD": (0.7, 1.5),
        "480": (0.5, 1.2),
    }
    
    # Trouver la taille correspondante
    episode_size_gb = 1.5  # Défaut
    movie_size_gb = 4.0    # Défaut
    
    for pattern, (ep_size, mov_size) in size_map.items():
        if pattern in quality_upper:
            episode_size_gb = ep_size
            movie_size_gb = mov_size
            break
    
    # Calculer la taille finale
    if media_type == MediaType.TV:
        if is_season_pack:
            # Pack de saison: environ 10 épisodes en moyenne
            size_gb = episode_size_gb * 10
        else:
            # Épisode individuel
            size_gb = episode_size_gb
    elif media_type == MediaType.MUSIC:
        # Album: généralement 300-800 MB
        size_gb = 0.5
    else:
        # Film (défaut)
        size_gb = movie_size_gb
    
    return int(size_gb * 1024 * 1024 * 1024)


def normalize_quality(raw_quality: str) -> str:
    """
    Normalise une qualité DarkiWorld vers le format Sonarr/Radarr
    Ex: "ULTRA HD (x265)" → "Bluray-2160p"
    Ex: "HDLight 1080p" → "WEBDL-1080p"
    Ex: "REMUX BLURAY" → "Bluray-1080p Remux"
    """
    if not raw_quality or raw_quality == 'Unknown':
        return 'WEBDL-1080p'
    
    # Recherche exacte dans le mapping
    if raw_quality in QUALITY_MAPPING:
        return QUALITY_MAPPING[raw_quality]
    
    # Fallback: analyse heuristique
    quality_lower = raw_quality.lower()
    
    # Détection résolution
    if '2160' in quality_lower or '4k' in quality_lower or 'uhd' in quality_lower or 'ultra hd' in quality_lower:
        resolution = '2160p'
    elif '1080' in quality_lower:
        resolution = '1080p'
    elif '720' in quality_lower:
        resolution = '720p'
    elif '480' in quality_lower or 'sd' in quality_lower:
        resolution = '480p'
    else:
        resolution = '1080p'
    
    # Détection type
    if 'remux' in quality_lower:
        quality_type = 'Remux'
    elif 'bluray' in quality_lower or 'bdrip' in quality_lower or 'brrip' in quality_lower:
        quality_type = 'Bluray'
    elif 'webrip' in quality_lower:
        quality_type = 'WEBRip'
    elif 'hdlight' in quality_lower or 'web-dl' in quality_lower or 'webdl' in quality_lower or 'web ' in quality_lower:
        quality_type = 'WEBDL'
    elif 'hdtv' in quality_lower:
        quality_type = 'HDTV'
    elif 'dvd' in quality_lower:
        return 'DVD'
    else:
        quality_type = 'WEBDL'
    
    return f"{quality_type}-{resolution}"


def normalize_language(lang: str) -> str:
    """Normalise un nom de langue vers le format scene"""
    lang_map = {
        'French': 'FRENCH',
        'TrueFrench': 'TRUEFRENCH',
        'VFF': 'VFF',
        'VFQ': 'VFQ',
        'VFI': 'VFI',
        'VF2': 'VF2',
        'English': 'ENGLISH',
        'German': 'GERMAN',
        'Spanish': 'SPANISH',
        'Italian': 'ITALIAN',
        'Portuguese': 'PORTUGUESE',
        'Russian': 'RUSSIAN',
        'Japanese': 'JAPANESE',
        'Korean': 'KOREAN',
        'Chinese': 'CHINESE',
        'Arabic': 'ARABIC',
        'Hindi': 'HINDI',
        'French (Canada)': 'VFQ',
        'MULTI': 'MULTI',
        'MULTi': 'MULTI',
    }
    return lang_map.get(lang, lang.upper().replace(' ', ''))


def extract_edition_from_nfo(nfo_data: list) -> Optional[str]:
    """
    Extrait l'édition du release depuis le NFO (Extended, Theatrical, Unrated, etc.)
    """
    if not nfo_data or len(nfo_data) == 0:
        return None
    
    nfo_text = nfo_data[0].get("nfo", "")
    if not nfo_text:
        return None
    
    # Patterns d'éditions courantes
    edition_patterns = [
        r'\b(EXTENDED)\b',
        r'\b(THEATRICAL)\b', 
        r'\b(UNRATED)\b',
        r'\b(UNCUT)\b',
        r'\b(DIRECTOR\'?S?\.?CUT)\b',
        r'\b(FINAL\.?CUT)\b',
        r'\b(SPECIAL\.?EDITION)\b',
        r'\b(REMASTERED)\b',
        r'\b(ANNIVERSARY)\b',
        r'\b(COLLECTORS?\.?EDITION)\b',
        r'\b(CRITERION)\b',
        r'\b(IMAX)\b',
        r'\b(3D)\b',
        r'\b(DC)\b',  # Director's Cut abrégé
    ]
    
    for pattern in edition_patterns:
        match = re.search(pattern, nfo_text, re.IGNORECASE)
        if match:
            edition = match.group(1).upper().replace('.', ' ').replace("'", '')
            # Normaliser les variantes
            edition = edition.replace('DIRECTORS CUT', "DIRECTOR'S CUT")
            edition = edition.replace('DIRECTORSCUT', "DIRECTOR'S CUT")
            logger.debug(f"📝 Edition trouvée dans NFO: {edition}")
            return edition
    
    return None


def build_release_title(link: dict, nfo_data: list = None, media_type: MediaType = None) -> tuple[str, str]:
    """
    Construit un titre de release optimisé pour Radarr/Sonarr
    
    Toujours basé sur les métadonnées DarkiWorld (titre, année, qualité, langues).
    Le NFO sert uniquement à extraire l'édition (Extended, Theatrical, etc.)
    
    Pour les séries (media_type=TV):
    - Inclut SxxExx si épisode spécifique
    - Inclut Sxx pour pack de saison
    
    Returns:
        Tuple (display_title, clean_title)
        - display_title: Pour affichage (avec hébergeur)
        - clean_title: Pour Radarr/Sonarr/JDownloader (sans hébergeur)
    """
    # Données DarkiWorld (source principale)
    title = link.get("title", "Unknown")
    year = link.get("year")
    quality = link.get("quality", "")
    audio_languages = link.get("audio_languages", [])
    subtitles = link.get("subtitles", [])
    host = link.get("host", "DDL")
    
    # Données spécifiques aux séries
    season = link.get("season")
    episode = link.get("episode")
    
    # Extraire l'édition depuis le NFO (si disponible) - uniquement pour films
    edition = None
    if media_type != MediaType.TV:
        edition = extract_edition_from_nfo(nfo_data) if nfo_data else None
    
    # Normaliser la qualité
    quality_normalized = normalize_quality(quality)
    
    # Normaliser les langues audio
    audio_normalized = []
    for lang in audio_languages[:3]:  # Max 3 langues
        audio_normalized.append(normalize_language(lang))
    
    # Construire le titre
    # Films: "Title (Year) [Edition] AUDIO QUALITY [Subs: SUBS]"
    # Séries: "Title S01E01 AUDIO QUALITY [Subs: SUBS]" ou "Title S01 AUDIO QUALITY" (pack)
    
    parts = [title]
    
    # Pour les séries: ajouter Sxx ou SxxExx
    if media_type == MediaType.TV and season is not None:
        if episode is not None and episode > 0:
            # Épisode individuel: S01E01
            parts.append(f"S{season:02d}E{episode:02d}")
        else:
            # Pack de saison (episode=None ou 0): S01
            parts.append(f"S{season:02d}")
    elif year:
        # Pour les films: ajouter l'année
        parts.append(f"({year})")
    
    # Edition (depuis NFO) - uniquement pour films
    if edition:
        parts.append(edition)
    
    # Langues audio
    if audio_normalized:
        if len(audio_normalized) > 1 or (len(audio_normalized) == 1 and audio_normalized[0] not in ['FRENCH', 'TRUEFRENCH']):
            parts.append("+".join(audio_normalized))
        elif audio_normalized[0] in ['TRUEFRENCH', 'VFF', 'VFQ']:
            parts.append(audio_normalized[0])
        # Si juste FRENCH, on peut l'omettre car c'est courant
    
    # Qualité normalisée
    parts.append(quality_normalized)
    
    # Sous-titres si présents
    if subtitles:
        subs_normalized = [normalize_language(s) for s in subtitles[:2]]
        parts.append(f"[Subs: {'+'.join(subs_normalized)}]")
    
    clean_title = " ".join(parts)
    display_title = f"{clean_title} [{host}]"
    
    return (display_title, clean_title)


# =============================================================================
# CATÉGORIES NEWZNAB
# =============================================================================

MOVIE_CATEGORIES = [
    ("2000", "Movies"),
    ("2010", "Movies/Foreign"),
    ("2020", "Movies/Other"),
    ("2030", "Movies/SD"),
    ("2040", "Movies/HD"),
    ("2045", "Movies/UHD"),
    ("2050", "Movies/BluRay"),
    ("2060", "Movies/3D"),
]

TV_CATEGORIES = [
    ("5000", "TV"),
    ("5010", "TV/WEB-DL"),
    ("5020", "TV/Foreign"),
    ("5030", "TV/SD"),
    ("5040", "TV/HD"),
    ("5045", "TV/UHD"),
    ("5070", "TV/Anime"),
]

MUSIC_CATEGORIES = [
    ("3000", "Audio"),
    ("3010", "Audio/MP3"),
    ("3040", "Audio/Lossless"),
]


def get_category_for_quality(quality: str, media_type: MediaType) -> str:
    """Détermine la catégorie Newznab selon la qualité normalisée"""
    q = quality.lower() if quality else ""
    
    if media_type == MediaType.MOVIE:
        if any(x in q for x in ["2160", "uhd"]):
            return "2045"
        if any(x in q for x in ["remux", "bluray"]):
            return "2050"
        if any(x in q for x in ["1080", "720"]):
            return "2040"
        if any(x in q for x in ["sd", "dvd", "480"]):
            return "2030"
        return "2040"
    
    elif media_type == MediaType.TV:
        if any(x in q for x in ["2160", "uhd"]):
            return "5045"
        if any(x in q for x in ["1080", "720"]):
            return "5040"
        if any(x in q for x in ["web"]):
            return "5010"
        return "5040"
    
    elif media_type == MediaType.MUSIC:
        if any(x in q for x in ["flac", "lossless"]):
            return "3040"
        return "3010"
    
    return "2000"


# =============================================================================
# GÉNÉRATION XML NEWZNAB
# =============================================================================

def create_caps_xml() -> str:
    """Crée le XML des capacités Newznab"""
    categories_xml = ""
    
    # Movies
    categories_xml += '<category id="2000" name="Movies">\n'
    for cat_id, cat_name in MOVIE_CATEGORIES[1:]:
        categories_xml += f'      <subcat id="{cat_id}" name="{cat_name}"/>\n'
    categories_xml += '    </category>\n'
    
    # TV
    categories_xml += '    <category id="5000" name="TV">\n'
    for cat_id, cat_name in TV_CATEGORIES[1:]:
        categories_xml += f'      <subcat id="{cat_id}" name="{cat_name}"/>\n'
    categories_xml += '    </category>\n'
    
    # Music
    categories_xml += '    <category id="3000" name="Audio">\n'
    for cat_id, cat_name in MUSIC_CATEGORIES[1:]:
        categories_xml += f'      <subcat id="{cat_id}" name="{cat_name}"/>\n'
    categories_xml += '    </category>'
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server title="DDL-Indexarr" strapline="DDL Indexer for *arr apps"/>
  <limits default="100" max="500"/>
  <retention days="9999"/>
  <registration available="no" open="no"/>
  <searching>
    <search available="yes" supportedParams="q"/>
    <movie-search available="yes" supportedParams="q,imdbid,tmdbid"/>
    <tv-search available="yes" supportedParams="q,tvdbid,season,ep"/>
    <music-search available="yes" supportedParams="q,artist,album"/>
  </searching>
  <categories>
    {categories_xml}
  </categories>
</caps>"""


def create_response_xml(items: list[dict], indexer_name: str = "DDL-Indexarr") -> str:
    """Crée la réponse XML Newznab avec les résultats"""
    
    items_xml = ""
    for item in items:
        url = item.get("download_url", "").replace("&", "&amp;")
        title = escape(item.get("title", ""))
        guid = escape(item.get("guid", ""))
        size = item.get("size", 0)
        category = item.get("category", "2000")
        pubdate = item.get("pubdate", dt.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))
        
        items_xml += f"""
    <item>
      <title>{title}</title>
      <guid isPermaLink="true">{guid}</guid>
      <link>{url}</link>
      <pubDate>{pubdate}</pubDate>
      <enclosure url="{url}" length="{size}" type="application/x-nzb"/>
      <newznab:attr name="category" value="{category}"/>
      <newznab:attr name="size" value="{size}"/>
      <newznab:attr name="grabs" value="100"/>
    </item>"""
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <title>{escape(indexer_name)}</title>
    <description>DDL-Indexarr Newznab Feed</description>
    <link>http://ddl-indexarr:9117</link>
    <newznab:response offset="0" total="{len(items)}"/>{items_xml}
  </channel>
</rss>"""


def create_test_items(search_type: str) -> list[dict]:
    """Crée des items de test pour la validation de l'indexeur"""
    now = dt.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    if search_type in ("movie", "m"):
        return [
            {"title": "Test Movie (2024) BluRay-1080p TrueFrench", "guid": "test-1", "size": 8589934592, "category": "2040", "pubdate": now},
            {"title": "Test Movie (2024) UHD-2160p TrueFrench", "guid": "test-2", "size": 32212254720, "category": "2045", "pubdate": now},
        ]
    elif search_type in ("tvsearch", "tv"):
        return [
            {"title": "Test Show S01E01 WEBDL-1080p", "guid": "test-tv-1", "size": 2147483648, "category": "5040", "pubdate": now},
        ]
    elif search_type in ("music", "audio"):
        return [
            {"title": "Test Album (2024) FLAC", "guid": "test-music-1", "size": 524288000, "category": "3040", "pubdate": now},
        ]
    return [
        {"title": "Test Result (2024)", "guid": "test-1", "size": 8589934592, "category": "2040", "pubdate": now},
    ]


# =============================================================================
# ENDPOINT PRINCIPAL
# =============================================================================

@router.get("/api")
@router.post("/api")
async def newznab_api(
    request: Request,
    t: str = Query(default="caps", description="Type (caps, search, movie, tvsearch, music)"),
    apikey: str = Query(default="", description="API Key"),
    q: str = Query(default="", description="Search query"),
    cat: str = Query(default="", description="Categories"),
    imdbid: str = Query(default="", description="IMDB ID"),
    tmdbid: str = Query(default="", description="TMDB ID"),
    tvdbid: str = Query(default="", description="TVDB ID"),
    season: Optional[int] = Query(default=None, description="Season number"),
    ep: Optional[int] = Query(default=None, description="Episode number"),
    artist: str = Query(default="", description="Artist (Lidarr)"),
    album: str = Query(default="", description="Album (Lidarr)"),
    offset: int = Query(default=0),
    limit: int = Query(default=100),
    # SABnzbd compatibility
    mode: str = Query(default="", description="SABnzbd mode"),
    output: str = Query(default="", description="SABnzbd output format"),
    name: str = Query(default="", description="SABnzbd name"),
    value: str = Query(default="", description="SABnzbd value"),
):
    """
    Endpoint Newznab unifié - Configure dans *arr comme Newznab indexer.
    
    URL: http://ddl-indexarr:9117/api
    
    Quand Radarr grab une release, il l'envoie au download client SABnzbd
    (qui est aussi DDL-Indexarr), et on transfère à JDownloader.
    """
    settings = get_settings()
    
    # === REDIRECTION SABNZBD ===
    if mode:
        from app.api.sabnzbd import sabnzbd_api
        query_params = dict(request.query_params)
        return await sabnzbd_api(
            request=request,
            mode=mode,
            apikey=apikey,
            output=output,
            cat=query_params.get("category", cat),
            name=name,
            value=value,
            start=int(query_params.get("start", 0)),
            limit=int(query_params.get("limit", 100)),
        )
    
    # === CAPABILITIES ===
    if t == "caps":
        return Response(content=create_caps_xml(), media_type="application/xml")
    
    # === VÉRIFICATION API KEY ===
    if apikey != settings.api_key:
        logger.warning(f"⚠️ Invalid API key: {apikey}")
        return Response(
            content='<?xml version="1.0"?><error code="100" description="Incorrect API Key"/>',
            media_type="application/xml"
        )
    
    # === PARSER LES CATÉGORIES ===
    categories_list = []
    if cat:
        try:
            categories_list = [int(c.strip()) for c in cat.split(",") if c.strip().isdigit()]
        except:
            pass
    
    # === DÉTERMINER LE TYPE DE MÉDIA ===
    indexer = get_indexer_by_search_type(t, categories_list)
    if not indexer:
        indexer = get_indexer_config("radarr")
    
    logger.info(f"📥 Newznab [{indexer.id}]: t={t}, q={q}, cat={cat}, imdbid={imdbid}, tmdbid={tmdbid}, tvdbid={tvdbid}, season={season}, ep={ep}")
    
    # === CONSTRUIRE LA REQUÊTE ===
    # Pour DarkiWorld, on cherche par titre uniquement
    # Il faut résoudre les IDs IMDB/TMDB/TVDB en titres via l'API TMDB
    search_query = q
    
    if not search_query:
        # Déterminer le type de média pour TMDB
        media_type_for_tmdb = "movie" if indexer.media_type == MediaType.MOVIE else "tv"
        
        if imdbid:
            # Résoudre IMDB ID → titre via TMDB API
            resolved_title = await resolve_imdb_to_title(imdbid)
            if resolved_title:
                search_query = resolved_title
            else:
                logger.warning(f"⚠️ Could not resolve IMDB {imdbid} to title, using as-is")
                search_query = imdbid
                
        elif tmdbid:
            # Résoudre TMDB ID → titre via TMDB API
            resolved_title = await resolve_tmdb_to_title(tmdbid, media_type_for_tmdb)
            if resolved_title:
                search_query = resolved_title
            else:
                logger.warning(f"⚠️ Could not resolve TMDB {tmdbid} to title")
                search_query = None
                
        elif tvdbid:
            # Résoudre TVDB ID → titre via TMDB API (pour les séries)
            resolved_title = await resolve_tvdb_to_title(tvdbid)
            if resolved_title:
                search_query = resolved_title
            else:
                logger.warning(f"⚠️ Could not resolve TVDB {tvdbid} to title")
                search_query = None
                
        elif artist:
            search_query = f"{artist} {album}".strip()
    
    # Note: On ne met PAS le season/ep dans la query de recherche
    # On passe ces paramètres directement à search_with_links
    
    # === TEST MODE (pas de query) ===
    if not search_query:
        test_items = create_test_items(t)
        for item in test_items:
            item["download_url"] = f"http://ddl-indexarr:9117/nzb?id={item['guid']}&apikey={apikey}"
        
        logger.info(f"📋 [{indexer.id}] Test mode - {len(test_items)} fake results")
        return Response(
            content=create_response_xml(test_items, indexer.name),
            media_type="application/xml"
        )
    
    # === RECHERCHE DARKIWORLD ===
    client = get_darkiworld_client()
    links = await client.search_with_links(
        query=search_query,
        media_type=indexer.media_type,
        season=season,  # Passer la saison demandée par Sonarr
        episode=ep,     # Passer l'épisode demandé par Sonarr
        limit=10,
        verify_links=True,
        max_links_per_title=15  # Plus de liens pour les séries (plusieurs épisodes)
    )
    
    # === CONVERTIR EN ITEMS NEWZNAB ===
    items = []
    for link in links:
        nfo_data = link.get("nfo", [])
        
        # Construire le titre optimisé pour Radarr/Sonarr avec notre fonction
        display_title, clean_title = build_release_title(link, nfo_data, indexer.media_type)
        
        link_id = link.get("id")
        
        # L'URL réelle est déjà disponible grâce à la vérification
        real_download_url = link.get("download_url", "")
        
        # Encoder les données du lien en base64 pour éviter un 2ème appel à DarkiWorld
        # Inclure le titre clean pour JDownloader
        link_data = {
            "url": real_download_url,
            "title": display_title,
            "clean_title": clean_title,
            "link_id": link_id
        }
        encoded_data = base64.urlsafe_b64encode(json.dumps(link_data).encode()).decode()
        
        pubdate = ""
        if link.get("created_at"):
            try:
                from datetime import datetime
                parsed = datetime.fromisoformat(link["created_at"].replace("Z", "+00:00"))
                pubdate = parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except:
                pass
        
        # Utiliser clean_title pour Newznab (sans hébergeur) pour que Radarr parse correctement
        # L'hébergeur est gardé dans les données encodées pour référence
        
        # === CALCULER LA TAILLE ===
        # Priorité: 1) NFO, 2) API (si > 100MB), 3) Estimation intelligente
        size = extract_size_from_nfo(nfo_data)
        if not size or size < 100_000_000:  # Si pas de NFO ou < 100MB (invalide)
            api_size = link.get("size", 0)
            if api_size > 100_000_000:  # Taille API valide (> 100MB)
                size = api_size
            else:
                # Estimation basée sur qualité et type de média
                size = estimate_file_size(
                    quality=link.get("quality", ""),
                    media_type=indexer.media_type,
                    is_season_pack=(link.get("episode") is None or link.get("episode") == 0)
                )
        
        items.append({
            "title": clean_title,  # Sans hébergeur pour un parsing Radarr correct
            "guid": f"darkiworld-{link.get('title_id', 0)}-{link_id}",
            "download_url": f"http://ddl-indexarr:9117/nzb?id={encoded_data}&apikey={apikey}",
            "size": size,
            "pubdate": pubdate,
            "category": get_category_for_quality(link.get("quality", ""), indexer.media_type),
        })
    
    logger.info(f"📋 [{indexer.id}] {len(items)} results")
    return Response(
        content=create_response_xml(items, indexer.name),
        media_type="application/xml"
    )


# =============================================================================
# ENDPOINT NZB - Retourne un NZB avec le link_id
# =============================================================================

@router.get("/nzb")
async def get_nzb(
    id: str = Query(..., description="Encoded link data (base64)"),
    apikey: str = Query(default="", description="API Key"),
):
    """
    Génère un NZB contenant les données du lien (URL réelle encodée en base64).
    Quand SABnzbd (notre émulateur) reçoit ce NZB, il décode directement l'URL
    et l'envoie à JDownloader - SANS rappeler DarkiWorld.
    """
    settings = get_settings()
    
    if apikey != settings.api_key:
        return Response(status_code=401)
    
    # Décoder pour récupérer le titre (pour le log)
    try:
        link_data = json.loads(base64.urlsafe_b64decode(id).decode())
        title = link_data.get("title", "download")
        logger.info(f"📦 NZB request: {title[:60]}...")
    except:
        logger.info(f"📦 NZB request: id={id[:30]}...")
    
    # Le NZB contient les données encodées - SABnzbd les décodera
    nzb_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <head>
    <meta type="link_data">{id}</meta>
  </head>
  <file poster="ddl-indexarr" date="0" subject="DDL-Indexarr Download">
    <groups><group>ddl.indexarr</group></groups>
    <segments>
      <segment bytes="1" number="1">{id}</segment>
    </segments>
  </file>
</nzb>"""
    
    return Response(
        content=nzb_content,
        media_type="application/x-nzb",
        headers={"Content-Disposition": f'attachment; filename="ddl-download.nzb"'}
    )
