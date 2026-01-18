"""DDL-Indexarr - Point d'entrée principal"""

import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import sys

from app.config import get_settings
from app.api import newznab_router, sabnzbd_router
from app.services.darkiworld import get_darkiworld_client
from app.services.jdownloader import get_jdownloader_client
from app.services.downloads import get_download_manager

# Configuration du logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="DEBUG" if get_settings().debug else "INFO",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application"""
    settings = get_settings()
    
    logger.info("=" * 50)
    logger.info("🚀 DDL-Indexarr v2.0 - Démarrage")
    logger.info("=" * 50)
    logger.info(f"📍 DarkiWorld: {settings.darkiworld_base_url}")
    logger.info(f"📍 JDownloader: {settings.jdownloader_device_name}")
    logger.info(f"📍 Newznab: http://0.0.0.0:{settings.torznab_port}/api")
    logger.info(f"📍 SABnzbd: http://0.0.0.0:{settings.torznab_port}/api (même endpoint)")
    logger.info("=" * 50)
    
    # Initialiser les services
    darkiworld = get_darkiworld_client()
    jdownloader = get_jdownloader_client()
    downloads = get_download_manager()
    
    # Tester les connexions
    logger.info("🔌 Test des connexions...")
    
    if settings.darkiworld_remember_cookie_name and settings.darkiworld_remember_cookie_value:
        auth_ok = await darkiworld.ensure_authenticated()
        if auth_ok:
            logger.success("✅ DarkiWorld: connecté")
        else:
            logger.warning("⚠️ DarkiWorld: non connecté (vérifiez le cookie)")
    else:
        logger.warning("⚠️ DarkiWorld: cookie non configuré")
    
    if settings.jdownloader_email and settings.jdownloader_password:
        jd_ok = await jdownloader.connect()
        if jd_ok:
            logger.success("✅ JDownloader: connecté")
        else:
            logger.warning("⚠️ JDownloader: non connecté")
    else:
        logger.warning("⚠️ JDownloader: non configuré")
    
    # Démarrer la boucle de mise à jour en arrière-plan
    update_task = asyncio.create_task(background_update_loop())
    
    yield
    
    # Arrêt
    logger.info("🛑 Arrêt de DDL-Indexarr...")
    update_task.cancel()
    
    try:
        await update_task
    except asyncio.CancelledError:
        pass
    
    await darkiworld.close()
    jdownloader.disconnect()


async def background_update_loop():
    """Boucle de mise à jour des téléchargements en arrière-plan"""
    manager = get_download_manager()
    
    while True:
        try:
            await asyncio.sleep(30)  # Mise à jour toutes les 30 secondes
            await manager.update_all_progress()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur mise à jour: {e}")


# Créer l'application FastAPI
app = FastAPI(
    title="DDL-Indexarr",
    description="Indexer et client de téléchargement DDL pour Radarr/Sonarr/Lidarr",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monter les routers
app.include_router(newznab_router)
app.include_router(sabnzbd_router)


@app.get("/")
async def root():
    """Page d'accueil"""
    return {
        "name": "DDL-Indexarr",
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "newznab": "/api?t=caps",
            "sabnzbd": "/api?mode=version",
        }
    }


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok"}


if __name__ == "__main__":
    settings = get_settings()
    
    # Lancer le serveur
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.torznab_port,
        reload=settings.debug,
    )
