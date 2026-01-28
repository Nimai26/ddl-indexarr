"""Client DarkiWorld avec gestion automatique de l'authentification via API"""

import httpx
import re
import urllib.parse
from loguru import logger
from typing import Optional
from datetime import datetime, timedelta

from app.config import get_settings
from app.models.indexer import MediaType


class DarkiWorldClient:
    """Client pour interagir avec DarkiWorld via son API"""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.darkiworld_base_url.rstrip("/")
        
        # Session HTTP
        self._client: Optional[httpx.AsyncClient] = None
        
        # Cookies et tokens
        self._cookies: dict = {}
        self._xsrf_token: Optional[str] = None
        self._session_valid_until: Optional[datetime] = None
        
        # Cache des métadonnées (qualités, hosts, catégories)
        self._qualities: dict = {}
        self._hosts: dict = {}
        self._categories: dict = {}
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Récupère ou crée le client HTTP"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/html, */*",
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
        return self._client
    
    def _get_api_headers(self) -> dict:
        """Retourne les headers nécessaires pour les appels API"""
        headers = {
            "Accept": "application/json",
            "Referer": f"{self.base_url}/",
            "X-Requested-With": "XMLHttpRequest",
        }
        if self._xsrf_token:
            headers["X-XSRF-TOKEN"] = self._xsrf_token
        return headers
    
    async def ensure_authenticated(self) -> bool:
        """S'assure que la session est authentifiée"""
        
        # Vérifier si la session est encore valide
        if self._session_valid_until and datetime.now() < self._session_valid_until:
            return True
        
        cookie_name = self.settings.darkiworld_remember_cookie_name
        cookie_value = self.settings.darkiworld_remember_cookie_value
        
        if not cookie_name or not cookie_value:
            logger.error("❌ DARKIWORLD_REMEMBER_COOKIE_NAME/VALUE non configuré")
            return False
        
        logger.info("🔐 Authentification DarkiWorld via cookie remember_me...")
        
        try:
            client = await self._get_client()
            
            # Utiliser le cookie remember_me pour obtenir une session
            self._cookies = {
                cookie_name: cookie_value
            }
            
            # Faire une requête pour récupérer les cookies de session et XSRF
            response = await client.get(
                f"{self.base_url}/",
                cookies=self._cookies
            )
            
            # Récupérer les cookies de la réponse
            for resp_cookie_name, resp_cookie_value in response.cookies.items():
                self._cookies[resp_cookie_name] = resp_cookie_value
                if "xsrf" in resp_cookie_name.lower():
                    # Décoder le token XSRF (URL encodé)
                    self._xsrf_token = urllib.parse.unquote(resp_cookie_value)
            
            # Extraire les métadonnées depuis bootstrapData
            await self._extract_metadata(response.text)
            
            # Vérifier si on est connecté
            if response.status_code == 200 and "darkiworld_session" in self._cookies:
                # Session valide pour 1 heure
                self._session_valid_until = datetime.now() + timedelta(hours=1)
                logger.success(f"✅ Authentification réussie ({len(self._cookies)} cookies)")
                return True
            else:
                logger.error(f"❌ Échec authentification: status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erreur authentification: {e}")
            return False
    
    async def _extract_metadata(self, html: str):
        """Extrait les métadonnées (qualités, hosts, catégories) depuis bootstrapData"""
        import json
        
        match = re.search(r'window\.bootstrapData\s*=\s*({.*?});\s*</script>', html, re.DOTALL)
        if not match:
            return
        
        try:
            data = json.loads(match.group(1))
            
            # Qualités
            if "qualities" in data:
                for q in data["qualities"]:
                    self._qualities[q["id"]] = q["name"]
            
            # Hosts
            if "hosts" in data:
                hosts = data["hosts"]
                if isinstance(hosts, dict):
                    for _, h in hosts.items():
                        self._hosts[h["id"]] = h["name"]
                elif isinstance(hosts, list):
                    for h in hosts:
                        self._hosts[h["id"]] = h["name"]
            
            # Catégories
            if "cats" in data:
                for c in data["cats"]:
                    self._categories[c["id"]] = c["name"]
                    
            logger.debug(f"📊 Métadonnées: {len(self._qualities)} qualités, {len(self._hosts)} hosts, {len(self._categories)} catégories")
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur extraction métadonnées: {e}")
    
    async def search(
        self, 
        query: str, 
        categories: list[str] = None,
        media_type: MediaType = None,
        limit: int = 20
    ) -> list[dict]:
        """
        Recherche sur DarkiWorld via l'API
        
        Args:
            query: Terme de recherche
            categories: Liste des catégories à filtrer (non utilisé pour l'instant)
            media_type: Type de média (movie, tv, music)
            limit: Nombre max de résultats
            
        Returns:
            Liste des résultats avec id, title, year, type, etc.
        """
        if not await self.ensure_authenticated():
            return []
        
        logger.info(f"🔍 Recherche DarkiWorld API: '{query}' (type={media_type})")
        
        try:
            client = await self._get_client()
            
            # Appel API de recherche
            response = await client.get(
                f"{self.base_url}/api/v1/search/{query}",
                params={"loader": "searchPage", "limit": limit},
                cookies=self._cookies,
                headers=self._get_api_headers()
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Recherche échouée: {response.status_code}")
                return []
            
            data = response.json()
            api_results = data.get("results", [])
            
            # Filtrer par type si spécifié
            results = []
            for item in api_results:
                item_type = item.get("type", "movie")
                
                # Filtrage par media_type
                if media_type:
                    if media_type == MediaType.MOVIE and item_type != "movie":
                        continue
                    elif media_type == MediaType.TV and item_type not in ["series", "tv", "animes"]:
                        continue
                    elif media_type == MediaType.MUSIC and item_type != "music":
                        continue
                    elif media_type == MediaType.BOOK and item_type != "ebook":
                        continue
                
                # Déterminer le type normalisé
                if item_type == "movie":
                    normalized_type = "movie"
                elif item_type in ["series", "tv", "animes"]:
                    normalized_type = "series"
                elif item_type == "ebook":
                    normalized_type = "ebook"
                else:
                    normalized_type = item_type
                
                # Construire le résultat
                result = {
                    "id": item.get("id"),
                    "title": item.get("name", ""),
                    "original_title": item.get("original_title"),
                    "year": item.get("year"),
                    "type": normalized_type,
                    "category": item.get("category"),
                    "tmdb_id": item.get("tmdb_id"),
                    "imdb_id": item.get("imdb_id"),
                    "poster": item.get("poster"),
                    "description": item.get("description", ""),
                    "have_link": item.get("have_link", 0),
                    "last_link": item.get("last_link"),
                }
                results.append(result)
            
            logger.info(f"📋 {len(results)} résultats trouvés")
            return results
            
        except Exception as e:
            logger.error(f"❌ Erreur recherche: {e}")
            return []
    
    async def get_title_links(self, title_id: int, season: int = 1) -> list[dict]:
        """
        Récupère TOUS les liens disponibles pour un titre (avec pagination)
        
        Args:
            title_id: ID du titre DarkiWorld
            season: Numéro de saison (pour les séries)
            
        Returns:
            Liste des liens avec qualité, langue, host, etc.
        """
        if not await self.ensure_authenticated():
            return []
        
        logger.info(f"📡 Récupération liens pour title_id={title_id}, saison={season}")
        
        try:
            client = await self._get_client()
            all_links = []
            title_info = {}
            page = 1
            
            while True:  # On sort de la boucle quand il n'y a plus de données
                # Appel API des liens avec pagination
                params = {
                    "perPage": "100",  # Max par page pour réduire les appels
                    "page": str(page),
                    "title_id": str(title_id),
                    "loader": "linksdl",
                    "season": str(season),
                    "filters": "",
                    "paginate": "preferLengthAware"
                }
                
                response = await client.get(
                    f"{self.base_url}/api/v1/liens",
                    params=params,
                    cookies=self._cookies,
                    headers=self._get_api_headers()
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ Récupération liens échouée (page {page}): {response.status_code}")
                    break
                
                data = response.json()
                
                if data.get("status") != "success":
                    logger.error(f"❌ API erreur: {data.get('error', 'Unknown')}")
                    break
                
                pagination = data.get("pagination", {})
                links_data = pagination.get("data", [])
                
                # Récupérer les infos de pagination
                if page == 1:
                    title_info = data.get("title", {})
                
                # Si pas de données, on a tout récupéré
                if not links_data:
                    logger.debug(f"  Page {page}: aucun lien, fin de la pagination")
                    break
                
                # Parser les liens de cette page
                for link in links_data:
                    parsed_link = self._parse_link(link, title_id, title_info)
                    if parsed_link:
                        all_links.append(parsed_link)
                
                logger.debug(f"  Page {page}: {len(links_data)} liens")
                
                # L'API limite à 42 liens par page max (même avec perPage=100)
                # Si on a moins de 42, c'est la dernière page
                if len(links_data) < 42:
                    break
                    
                page += 1
                
                # Sécurité: max 50 pages (2100 liens)
                if page > 50:
                    logger.warning("⚠️ Limite de pagination atteinte (50 pages)")
                    break
            
            logger.info(f"✅ {len(all_links)} liens récupérés au total")
            return all_links
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération liens: {e}")
            return []
    
    def _parse_link(self, link: dict, title_id: int, title_info: dict) -> Optional[dict]:
        """Parse un lien brut de l'API en format unifié"""
        try:
            # Extraire les informations
            quality_id = link.get("qualite")
            quality_name = link.get("qual", {}).get("qual", self._qualities.get(quality_id, "Unknown"))
            
            host_id = link.get("id_host")
            host_name = link.get("host", {}).get("name", self._hosts.get(host_id, "Unknown"))
            
            # Langues audio
            audio_langs = []
            if link.get("langues_compact"):
                audio_langs = [l.get("name") for l in link["langues_compact"]]
            
            # Sous-titres
            subtitles = []
            if link.get("subs_compact"):
                subtitles = [s.get("name") for s in link["subs_compact"]]
            
            # Taille depuis NFO si disponible
            size = link.get("taille", 0)
            nfo_data = link.get("nfo", [])
            if nfo_data and len(nfo_data) > 0:
                nfo_text = nfo_data[0].get("nfo", "")
                # Extraire la taille depuis le NFO (format: "1,36 Gio")
                size_match = re.search(r'(\d+[,.]?\d*)\s*(Gio|Mio|GB|MB)', nfo_text, re.IGNORECASE)
                if size_match:
                    size_value = float(size_match.group(1).replace(",", "."))
                    unit = size_match.group(2).lower()
                    if unit in ["gio", "gb"]:
                        size = int(size_value * 1024 * 1024 * 1024)
                    elif unit in ["mio", "mb"]:
                        size = int(size_value * 1024 * 1024)
            
            return {
                "id": link.get("id"),
                "title_id": title_id,
                "title": title_info.get("name", ""),
                "original_title": title_info.get("original_title"),
                "year": title_info.get("year"),
                "quality": quality_name,
                "host": host_name,
                "host_id": host_id,
                "audio_languages": audio_langs,
                "subtitles": subtitles,
                "size": size,
                "season": link.get("saison", 0),
                "episode": link.get("episode"),
                "active": link.get("active", 0) == 1,
                "created_at": link.get("created_at"),
                "tmdb_id": title_info.get("tmdb_id"),
                "imdb_id": title_info.get("imdb_id"),
                "nfo": nfo_data,
            }
        except Exception as e:
            logger.debug(f"Erreur parsing lien: {e}")
            return None
    
    async def verify_link_availability(self, link_id: int) -> tuple[bool, Optional[dict]]:
        """
        Vérifie la disponibilité d'un lien via l'API download
        
        Args:
            link_id: ID du lien DarkiWorld
            
        Returns:
            Tuple (disponible: bool, lien_info: dict ou None)
        """
        if not await self.ensure_authenticated():
            return False, None
        
        try:
            client = await self._get_client()
            
            headers = self._get_api_headers()
            headers["Content-Type"] = "application/json"
            
            response = await client.post(
                f"{self.base_url}/api/v1/liens/{link_id}/download",
                headers=headers,
                cookies=self._cookies,
                json={}
            )
            
            if response.status_code != 200:
                return False, None
            
            data = response.json()
            lien_obj = data.get("lien", {})
            
            # Vérifier si le lien est actif et non supprimé
            if lien_obj.get("deleted_at") is not None:
                logger.debug(f"  Lien {link_id}: supprimé")
                return False, None
            
            if lien_obj.get("active") != 1:
                logger.debug(f"  Lien {link_id}: inactif")
                return False, None
            
            # Vérifier qu'on a une URL
            download_url = lien_obj.get("directDL") or lien_obj.get("lien")
            if not download_url:
                logger.debug(f"  Lien {link_id}: pas d'URL")
                return False, None
            
            return True, lien_obj
            
        except Exception as e:
            logger.debug(f"  Lien {link_id}: erreur vérification - {e}")
            return False, None
    
    async def get_title_links_verified(
        self, 
        title_id: int, 
        season: int = 1,
        max_links: int = 20,
        batch_size: int = 5
    ) -> list[dict]:
        """
        Récupère les liens disponibles pour un titre avec vérification de disponibilité
        
        Args:
            title_id: ID du titre DarkiWorld
            season: Numéro de saison (pour les séries)
            max_links: Nombre max de liens à vérifier
            batch_size: Taille des batchs pour parallélisation
            
        Returns:
            Liste des liens vérifiés et disponibles
        """
        # Récupérer tous les liens
        all_links = await self.get_title_links(title_id, season)
        
        if not all_links:
            return []
        
        # === DIVERSIFIER LES EPISODES ===
        # Trier pour avoir au moins un lien par épisode en priorité
        # Cela évite de ne vérifier que E1 quand il y a E2, E3, etc.
        from collections import defaultdict
        
        links_by_episode = defaultdict(list)
        for link in all_links:
            ep = link.get("episode")
            # Normaliser: None -> 0 (pack de saison)
            if ep is None:
                ep = 0
            links_by_episode[ep].append(link)
        
        # Construire la liste en alternant les épisodes (round-robin)
        diversified_links = []
        episodes = sorted(links_by_episode.keys())  # Maintenant toutes les clés sont des int
        
        # D'abord, prendre un lien de chaque épisode (priorité aux hébergeurs premium)
        # Fonction de score qualité (plus petit = meilleur)
        # Priorité: 4K/2160p > Remux 1080p > 1080p > 720p
        def quality_score(q: str) -> int:
            q_upper = (q or '').upper()
            # 4K/2160p en premier (meilleure résolution)
            if 'ULTRA HD' in q_upper and 'LIGHT' not in q_upper:
                return 0  # ULTRA HD (x265) = Bluray-2160p
            if 'ULTRA' in q_upper or 'UHD' in q_upper or '2160' in q_upper or '4K' in q_upper:
                return 1  # Ultra HDLight (x265) = WEBDL-2160p
            # Ensuite Remux 1080p (meilleure source en 1080p)
            if 'REMUX' in q_upper:
                return 2  # REMUX BLURAY = Bluray-1080p Remux
            # Puis Bluray 1080p
            if 'BLURAY' in q_upper and '1080' in q_upper:
                return 3
            # Puis Web 1080p
            if '1080' in q_upper:
                return 4  # 1080p
            if '720' in q_upper:
                return 5  # 720p
            return 6  # Autres
        
        for ep in episodes:
            ep_links = links_by_episode[ep]
            # Priorité: Meilleure qualité d'abord, puis hébergeur premium
            ep_links_sorted = sorted(ep_links, key=lambda x: (
                quality_score(x.get('quality', '')),  # D'abord par qualité
                0 if '1fichier' in x.get('host', '').lower() else
                1 if 'send' in x.get('host', '').lower() else 2  # Puis par hébergeur
            ))
            if ep_links_sorted:
                diversified_links.append(ep_links_sorted[0])
        
        # Ensuite, compléter avec les liens restants
        seen_ids = {link.get("id") for link in diversified_links}
        for link in all_links:
            if link.get("id") not in seen_ids:
                diversified_links.append(link)
        
        logger.info(f"🔍 Vérification de {min(len(diversified_links), max_links)} liens ({len(episodes)} épisodes différents)...")
        
        # Limiter le nombre de liens à vérifier
        links_to_verify = diversified_links[:max_links]
        
        async def verify_single(link: dict) -> Optional[dict]:
            """Vérifie un lien unique et retourne le lien enrichi ou None"""
            link_id = link.get("id")
            if not link_id:
                return None
            
            is_available, lien_info = await self.verify_link_availability(link_id)
            
            if is_available and lien_info:
                # Enrichir le lien avec l'URL de téléchargement
                download_url = lien_info.get("directDL") or lien_info.get("lien")
                
                # Correction send.cm → send.now
                if download_url and "send.cm/" in download_url:
                    download_url = download_url.replace("send.cm/", "send.now/")
                
                link["download_url"] = download_url
                link["verified"] = True
                return link
            
            return None
        
        # Vérifier par batchs pour éviter de surcharger
        import asyncio
        verified_links = []
        
        for i in range(0, len(links_to_verify), batch_size):
            batch = links_to_verify[i:i + batch_size]
            results = await asyncio.gather(*[verify_single(link) for link in batch])
            verified_links.extend([r for r in results if r is not None])
        
        logger.info(f"✅ {len(verified_links)}/{len(links_to_verify)} liens disponibles")
        return verified_links
    
    async def get_download_url(self, link_id: int) -> Optional[str]:
        """
        Récupère l'URL de téléchargement pour un lien spécifique
        
        Args:
            link_id: ID du lien DarkiWorld
            
        Returns:
            URL de téléchargement directe ou None
        """
        if not await self.ensure_authenticated():
            return None
        
        logger.info(f"📥 Récupération URL téléchargement pour lien {link_id}")
        
        try:
            client = await self._get_client()
            
            # Headers avec XSRF token
            headers = self._get_api_headers()
            headers["Content-Type"] = "application/json"
            
            # Appel API POST pour obtenir l'URL
            response = await client.post(
                f"{self.base_url}/api/v1/liens/{link_id}/download",
                headers=headers,
                cookies=self._cookies,
                json={}  # Body vide mais en JSON
            )
            
            if response.status_code != 200:
                logger.error(f"❌ API download échouée: {response.status_code}")
                return None
            
            data = response.json()
            logger.debug(f"📦 Réponse API: status={data.get('status')}, debrided={data.get('debrided')}")
            
            # Extraction de l'URL
            lien_obj = data.get("lien", {})
            download_url = None
            
            # Priorité: directDL (darkibox) > lien (1fichier, etc.)
            if lien_obj.get("directDL"):
                download_url = lien_obj["directDL"]
                logger.debug(f"  → URL darkibox (directDL)")
            elif lien_obj.get("lien"):
                download_url = lien_obj["lien"]
                logger.debug(f"  → URL standard (lien)")
            
            if download_url:
                # Correction domaine send.cm → send.now
                if "send.cm/" in download_url:
                    download_url = download_url.replace("send.cm/", "send.now/")
                    logger.info(f"🔧 Correction domaine: send.cm → send.now")
                
                logger.info(f"✅ URL obtenue: {download_url[:60]}...")
                return download_url
            
            # Gestion des erreurs
            if data.get("status") == "KO":
                error = data.get("error", "Erreur inconnue")
                logger.warning(f"⚠️ API retourne KO: {error}")
            
            logger.error(f"❌ Pas d'URL dans la réponse")
            return None
            
        except Exception as e:
            logger.error(f"❌ Erreur get_download_url: {e}")
            return None
    
    async def search_with_links(
        self, 
        query: str, 
        media_type: MediaType = None,
        season: int = None,
        episode: int = None,
        limit: int = 10,
        verify_links: bool = True,
        max_links_per_title: int = 10
    ) -> list[dict]:
        """
        Recherche et récupère directement les liens pour chaque résultat
        
        Args:
            query: Terme de recherche
            media_type: Type de média
            season: Numéro de saison (pour les séries)
            episode: Numéro d'épisode (pour les séries)
            limit: Nombre max de titres à traiter
            verify_links: Si True, vérifie la disponibilité des liens
            max_links_per_title: Nombre max de liens à vérifier par titre
            
        Returns:
            Liste aplatie de tous les liens disponibles (vérifiés si verify_links=True)
        """
        # D'abord rechercher les titres
        titles = await self.search(query, media_type=media_type, limit=limit)
        
        if not titles:
            return []
        
        # Pour chaque titre avec des liens, récupérer les liens détaillés
        all_links = []
        for title in titles:
            if not title.get("have_link"):
                continue
            
            title_id = title.get("id")
            if not title_id:
                continue
            
            # Pour les séries, récupérer les liens de la saison demandée
            search_season = season if season is not None else 1
            
            # Récupérer les liens (vérifiés ou non)
            if verify_links:
                links = await self.get_title_links_verified(
                    title_id,
                    season=search_season,
                    max_links=max_links_per_title
                )
            else:
                links = await self.get_title_links(title_id, season=search_season)
            
            # Filtrer par épisode si demandé
            if episode is not None and media_type == MediaType.TV:
                filtered_links = []
                for link in links:
                    link_episode = link.get("episode")
                    # Garder: l'épisode demandé OU les packs de saison (episode=None/0)
                    if link_episode == episode or link_episode is None or link_episode == 0:
                        filtered_links.append(link)
                links = filtered_links
            
            # Enrichir chaque lien avec les infos du titre
            for link in links:
                link["search_title"] = title.get("title")
                link["search_year"] = title.get("year")
                link["search_type"] = title.get("type")
            
            all_links.extend(links)
        
        logger.info(f"🎯 {len(all_links)} liens {'vérifiés' if verify_links else ''} au total pour '{query}' (S{season}E{episode if episode else 'all'})")
        return all_links
    
    async def close(self):
        """Ferme le client HTTP"""
        if self._client:
            await self._client.aclose()
            self._client = None


# Instance singleton
_client: Optional[DarkiWorldClient] = None


def get_darkiworld_client() -> DarkiWorldClient:
    """Récupère l'instance singleton du client DarkiWorld"""
    global _client
    if _client is None:
        _client = DarkiWorldClient()
    return _client
