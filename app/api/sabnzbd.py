"""API SABnzbd émulée pour Radarr/Sonarr/Lidarr"""

import asyncio
import base64
import json
import re
import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import get_settings
from app.services.downloads import get_download_manager
from app.services.jdownloader import get_jdownloader_client

router = APIRouter(tags=["SABnzbd"])


@router.get("/sabnzbd/api")
@router.post("/sabnzbd/api")
async def sabnzbd_api(
    request: Request,
    mode: str = Query(default="", description="Mode SABnzbd"),
    apikey: str = Query(default="", description="Clé API"),
    output: str = Query(default="json", description="Format de sortie"),
    cat: str = Query(default="", alias="category", description="Catégorie"),
    name: str = Query(default="", description="Nom/ID"),
    value: str = Query(default="", description="Valeur"),
    start: int = Query(default=0, description="Offset"),
    limit: int = Query(default=100, description="Limite"),
):
    """
    Émule l'API SABnzbd pour le suivi des téléchargements
    
    Modes supportés:
    - version: Version SABnzbd
    - queue: File d'attente des téléchargements
    - history: Historique des téléchargements
    - addurl: Ajouter un téléchargement
    - delete: Supprimer un téléchargement
    - config: Configuration
    - fullstatus: Statut complet
    """
    settings = get_settings()
    
    # Vérifier l'API key (sauf pour version)
    if mode != "version" and apikey != settings.api_key:
        logger.warning(f"⚠️ API key invalide: {apikey}")
        return JSONResponse({"status": False, "error": "API Key Incorrect"})
    
    logger.debug(f"📥 SABnzbd: mode={mode}, cat={cat}, name={name}")
    
    manager = get_download_manager()
    
    # === VERSION ===
    if mode == "version":
        return JSONResponse({"version": "4.2.1"})
    
    # === DELETE (doit être vérifié AVANT queue/history) ===
    if name == "delete" and mode in ["queue", "history"]:
        nzo_id = value
        
        # Supprimer tous les téléchargements
        if nzo_id == "all":
            manager.clear_all()
            logger.info("🗑️ Tous les téléchargements supprimés")
            return JSONResponse({"status": True})
        
        # Supprimer un téléchargement spécifique
        if manager.delete_download(nzo_id):
            logger.info(f"🗑️ Supprimé: {nzo_id}")
        else:
            logger.warning(f"⚠️ Non trouvé pour suppression: {nzo_id}")
        
        return JSONResponse({"status": True})
    
    # === QUEUE ===
    if mode == "queue":
        # Mettre à jour les progressions
        await manager.update_all_progress()
        
        # Récupérer les téléchargements actifs
        downloads = manager.get_active_downloads(cat if cat else None)
        
        slots = [dl.to_sabnzbd_slot() for dl in downloads]
        
        # Calculer les totaux
        total_size = sum(dl.size_total for dl in downloads)
        total_left = sum(dl.size_total - dl.size_downloaded for dl in downloads)
        total_speed = sum(dl.speed for dl in downloads)
        
        logger.info(f"📊 Queue: {len(slots)} téléchargements actifs")
        
        return JSONResponse({
            "queue": {
                "status": "Downloading" if any(dl.status.value == "downloading" for dl in downloads) else "Idle",
                "paused": False,
                "speedlimit": "0",
                "speedlimit_abs": "0",
                "speed": f"{total_speed / (1024*1024):.2f} MB/s" if total_speed else "0 B/s",
                "kbpersec": f"{total_speed / 1024:.2f}" if total_speed else "0",
                "mb": f"{total_size / (1024*1024):.2f}",
                "mbleft": f"{total_left / (1024*1024):.2f}",
                "sizeleft": f"{total_left / (1024*1024*1024):.2f} GB",
                "noofslots_total": len(slots),
                "noofslots": len(slots),
                "start": start,
                "limit": limit,
                "slots": slots,
            }
        })
    
    # === HISTORY ===
    if mode == "history":
        # Nettoyer les téléchargements obsolètes (fichiers importés ou supprimés de JD)
        # Exécuter en arrière-plan pour ne pas bloquer la réponse
        asyncio.create_task(manager.cleanup_stale_downloads())
        
        downloads = manager.get_completed_downloads(cat if cat else None)
        
        slots = [dl.to_sabnzbd_history() for dl in downloads]
        
        logger.info(f"📊 History: {len(slots)} téléchargements terminés")
        
        return JSONResponse({
            "history": {
                "noofslots": len(slots),
                "slots": slots,
            }
        })
    
    # === ADDFILE (POST avec NZB dans le body) ===
    if mode == "addfile":
        logger.info(f"➕ Ajout fichier NZB (POST)...")
        
        try:
            # Lire le contenu multipart/form-data
            form = await request.form()
            nzb_file = form.get("name")
            
            if nzb_file:
                nzb_content = (await nzb_file.read()).decode("utf-8")
            else:
                # Fallback: lire le body brut
                nzb_content = (await request.body()).decode("utf-8")
            
            # Extraire les données encodées depuis le NZB
            data_match = re.search(r'<meta type="link_data">([^<]+)</meta>', nzb_content)
            if not data_match:
                logger.error("❌ Pas de link_data dans le NZB")
                return JSONResponse({"status": False, "error": "No link_data in NZB"})
            
            encoded_data = data_match.group(1)
            
            # Décoder les données base64
            link_data = json.loads(base64.urlsafe_b64decode(encoded_data).decode())
            download_url = link_data.get("url")
            title = link_data.get("title", cat)
            clean_title = link_data.get("clean_title", title)  # Titre sans hébergeur
            link_id = link_data.get("link_id")
            
            logger.info(f"📦 NZB décodé: {clean_title[:50]}... (link_id={link_id})")
            
            if not download_url:
                logger.error("❌ Pas d'URL dans le NZB")
                return JSONResponse({"status": False, "error": "No URL in NZB"})
            
            logger.info(f"🔗 URL: {download_url[:80]}...")
            
            # Créer le téléchargement avec clean_title (sans hébergeur)
            download = manager.create_download(
                title=clean_title or f"download-{link_id}",
                category=cat,
                links=[download_url],
                source_url=f"darkiworld://link/{link_id}" if link_id else download_url
            )
            
            # Envoyer à JDownloader avec le clean_title (sans hébergeur)
            jd_client = get_jdownloader_client()
            
            # Créer un sous-dossier par téléchargement (comme SABnzbd)
            # Sonarr/Radarr s'attendent à ce que le fichier soit dans un sous-dossier
            base_folder = f"{settings.output_path}/{cat}" if cat else settings.output_path
            download_title = clean_title or f"download-{link_id}"
            output_folder = f"{base_folder}/{download_title}"
            
            # Préfixer avec le service *arr pour identification
            package_prefix = f"[{cat.upper()}] " if cat else ""
            package_name = f"{package_prefix}{download_title}"
            
            package_id = await jd_client.add_links(
                links=[download_url],
                package_name=package_name,
                output_folder=output_folder
            )
            
            if package_id:
                download.jd_uuid = package_id
                download.jd_package_name = package_name  # Stocker le nom pour recherche
                download.output_path = output_folder  # Sauvegarder le chemin avec sous-dossier
                manager._save_downloads()
                logger.success(f"✅ Envoyé à JDownloader: {download_url[:60]}...")
            
            return JSONResponse({
                "status": True,
                "nzo_ids": [download.nzo_id],
            })
            
        except Exception as e:
            logger.error(f"❌ Erreur addfile: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse({"status": False, "error": str(e)})
    
    # === ADDURL ===
    if mode == "addurl":
        # Radarr envoie l'URL du NZB: http://ddl-indexarr:9117/nzb?id=BASE64_DATA&apikey=xxx
        
        logger.info(f"➕ Ajout URL: {name[:80]}...")
        
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(name)
            params = parse_qs(parsed.query)
            
            category = cat
            encoded_data = None
            download_url = None
            title = None
            
            # Extraire les données encodées de l'URL (paramètre 'id')
            if "id" in params:
                encoded_data = params["id"][0]
            
            # Si pas dans l'URL, télécharger le NZB et extraire
            if not encoded_data:
                logger.info("📥 Téléchargement du NZB...")
                
                nzb_url = name.replace("ddl-indexarr:9117", "127.0.0.1:9117")
                
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.get(nzb_url, follow_redirects=True)
                    nzb_content = response.text
                
                # Extraire les données depuis le NZB
                data_match = re.search(r'<meta type="link_data">([^<]+)</meta>', nzb_content)
                if data_match:
                    encoded_data = data_match.group(1)
            
            if not encoded_data:
                logger.error(f"❌ Impossible d'extraire les données de {name}")
                return JSONResponse({"status": False, "error": "No link data found"})
            
            # Décoder les données base64 - contient l'URL réelle !
            try:
                link_data = json.loads(base64.urlsafe_b64decode(encoded_data).decode())
                download_url = link_data.get("url")
                title = link_data.get("title", category)
                clean_title = link_data.get("clean_title", title)  # Titre sans hébergeur
                link_id = link_data.get("link_id")
                logger.info(f"📦 Décodé: {clean_title[:50]}... (link_id={link_id})")
            except Exception as e:
                logger.error(f"❌ Erreur décodage base64: {e}")
                return JSONResponse({"status": False, "error": "Invalid link data"})
            
            if not download_url:
                logger.error("❌ Pas d'URL dans les données")
                return JSONResponse({"status": False, "error": "No download URL in data"})
            
            logger.info(f"🔗 URL de téléchargement: {download_url[:80]}...")
            
            # Créer le téléchargement avec clean_title (sans hébergeur)
            download = manager.create_download(
                title=clean_title or f"download-{link_id}",
                category=category,
                links=[download_url],
                source_url=f"darkiworld://link/{link_id}" if link_id else download_url
            )
            
            # Envoyer à JDownloader avec le clean_title (sans hébergeur)
            jd_client = get_jdownloader_client()
            
            # Créer un sous-dossier par téléchargement (comme SABnzbd)
            # Sonarr/Radarr s'attendent à ce que le fichier soit dans un sous-dossier
            base_folder = f"{settings.output_path}/{category}" if category else settings.output_path
            download_title = clean_title or f"download-{link_id}"
            output_folder = f"{base_folder}/{download_title}"
            
            # Préfixer avec le service *arr pour identification
            package_prefix = f"[{category.upper()}] " if category else ""
            package_name = f"{package_prefix}{download_title}"
            
            package_id = await jd_client.add_links(
                links=[download_url],
                package_name=package_name,
                output_folder=output_folder
            )
            
            if package_id:
                download.jd_uuid = package_id
                download.jd_package_name = package_name  # Stocker le nom pour recherche
                download.output_path = output_folder  # Sauvegarder le chemin avec sous-dossier
                manager._save_downloads()
                logger.success(f"✅ Envoyé à JDownloader: {download_url[:60]}...")
            
            return JSONResponse({
                "status": True,
                "nzo_ids": [download.nzo_id],
            })
            
        except Exception as e:
            logger.error(f"❌ Erreur ajout téléchargement: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse({"status": False, "error": str(e)})
    
    # === CONFIG ===
    if mode == "config":
        return JSONResponse({
            "config": {
                "misc": {
                    "complete_dir": settings.output_path,
                    "download_dir": "/incomplete",
                },
                "categories": [
                    {"name": "*", "order": 0, "pp": "", "script": "None", "dir": "", "priority": -100},
                    {"name": "radarr", "order": 1, "pp": "", "script": "None", "dir": "radarr", "priority": -100},
                    {"name": "sonarr", "order": 2, "pp": "", "script": "None", "dir": "sonarr", "priority": -100},
                    {"name": "lidarr", "order": 3, "pp": "", "script": "None", "dir": "lidarr", "priority": -100},
                    {"name": "radarr-anime", "order": 4, "pp": "", "script": "None", "dir": "radarr-anime", "priority": -100},
                    {"name": "sonarr-anime", "order": 5, "pp": "", "script": "None", "dir": "sonarr-anime", "priority": -100},
                ]
            }
        })
    
    # === FULLSTATUS ===
    if mode == "fullstatus":
        return JSONResponse({
            "status": {
                "paused": False,
                "diskspace1": "100.00",
                "diskspace2": "100.00",
                "speedlimit": "0",
                "speed": "0 B/s",
            }
        })
    
    # === GET_CONFIG ===
    if mode == "get_config":
        return JSONResponse({
            "config": {
                "misc": {
                    "complete_dir": settings.output_path,
                },
                "categories": [
                    {"name": "*", "order": 0, "pp": "", "script": "None", "dir": "", "priority": -100},
                    {"name": "radarr", "order": 1, "pp": "", "script": "None", "dir": "radarr", "priority": -100},
                    {"name": "sonarr", "order": 2, "pp": "", "script": "None", "dir": "sonarr", "priority": -100},
                    {"name": "lidarr", "order": 3, "pp": "", "script": "None", "dir": "lidarr", "priority": -100},
                    {"name": "radarr-anime", "order": 4, "pp": "", "script": "None", "dir": "radarr-anime", "priority": -100},
                    {"name": "sonarr-anime", "order": 5, "pp": "", "script": "None", "dir": "sonarr-anime", "priority": -100},
                ]
            }
        })
    
    # Mode non supporté
    logger.warning(f"⚠️ Mode SABnzbd non supporté: {mode}")
    return JSONResponse({"status": True})
