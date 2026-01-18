"""Client JDownloader via MyJDownloader API"""

import myjdapi
from loguru import logger
from typing import Optional
from datetime import datetime, timedelta

from app.config import get_settings


# Caractères remplacés par JDownloader pour compatibilité système de fichiers
# https://support.jdownloader.org/Knowledgebase/Article/View/invalid-characters-in-filenames
JD_CHAR_REPLACEMENTS = {
    ':': ';',      # Deux-points → point-virgule
    '/': '⁄',      # Slash → fraction slash (U+2044)
    '\\': '',      # Backslash → supprimé
    '*': '',       # Astérisque → supprimé
    '?': '',       # Point d'interrogation → supprimé
    '"': "'",      # Guillemet double → simple
    '<': '(',      # Inférieur → parenthèse ouvrante
    '>': ')',      # Supérieur → parenthèse fermante
    '|': '-',      # Pipe → tiret
}


def normalize_jd_name(name: str) -> str:
    """
    Normalise un nom pour correspondre au format JDownloader.
    Applique les mêmes remplacements de caractères que JDownloader.
    
    Args:
        name: Nom original
        
    Returns:
        Nom normalisé compatible JDownloader
    """
    for char, replacement in JD_CHAR_REPLACEMENTS.items():
        name = name.replace(char, replacement)
    return name


class JDownloaderClient:
    """Client pour interagir avec JDownloader via MyJDownloader"""
    
    def __init__(self):
        self.settings = get_settings()
        self._jd: Optional[myjdapi.Myjdapi] = None
        self._device: Optional[myjdapi.Jddevice] = None
        self._connected_until: Optional[datetime] = None
    
    async def connect(self) -> bool:
        """Établit la connexion à MyJDownloader"""
        
        # Vérifier si déjà connecté
        if self._connected_until and datetime.now() < self._connected_until:
            return True
        
        email = self.settings.jdownloader_email
        password = self.settings.jdownloader_password
        device_name = self.settings.jdownloader_device_name
        
        if not email or not password:
            logger.error("❌ JDOWNLOADER_EMAIL ou JDOWNLOADER_PASSWORD non configuré")
            return False
        
        logger.info(f"🔌 Connexion MyJDownloader ({device_name})...")
        
        try:
            self._jd = myjdapi.Myjdapi()
            self._jd.set_app_key("ddl-indexarr")
            self._jd.connect(email, password)
            
            # Récupérer la liste des devices
            self._jd.update_devices()
            devices = self._jd.list_devices()
            
            if not devices:
                logger.error("❌ Aucun device JDownloader trouvé")
                return False
            
            # Trouver le device par nom
            self._device = None
            for device in devices:
                if device.get("name") == device_name:
                    self._device = self._jd.get_device(device_name)
                    break
            
            if not self._device:
                # Utiliser le premier device disponible
                self._device = self._jd.get_device(devices[0].get("name"))
                logger.warning(f"⚠️ Device '{device_name}' non trouvé, utilisation de '{devices[0].get('name')}'")
            
            self._connected_until = datetime.now() + timedelta(minutes=30)
            logger.success(f"✅ Connecté à JDownloader: {self._device.name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur connexion JDownloader: {e}")
            self._jd = None
            self._device = None
            return False
    
    async def add_links(self, links: list[str], package_name: str, output_folder: str = None) -> Optional[str]:
        """
        Ajoute des liens à JDownloader
        
        Args:
            links: Liste des URLs à télécharger
            package_name: Nom du package
            output_folder: Dossier de destination (optionnel)
            
        Returns:
            UUID du package créé ou None si erreur
        """
        if not await self.connect():
            return None
        
        logger.info(f"➕ Ajout de {len(links)} liens: {package_name}")
        logger.debug(f"📝 Liens: {links}")
        logger.debug(f"📁 Dossier de sortie: {output_folder}")
        
        try:
            # L'API myjdapi attend un tableau avec un seul élément (le dict des params)
            params = [{
                "autostart": True,
                "links": "\n".join(links),
                "packageName": package_name,
                "overwritePackagizerRules": True,
            }]
            
            if output_folder:
                params[0]["destinationFolder"] = output_folder
            
            # Ajouter les liens via linkgrabber
            result = self._device.linkgrabber.add_links(params)
            
            if result:
                logger.success(f"✅ Liens ajoutés, ID: {result.get('id', 'unknown')}")
                return str(result.get("id"))
            
            return None
            
        except myjdapi.exception.MYJDConnectionException:
            # Connexion perdue, invalider le cache et réessayer
            logger.warning("⚠️ Connexion JDownloader perdue, reconnexion...")
            self._connected_until = None
            
            if await self.connect():
                try:
                    params = [{
                        "autostart": True,
                        "links": "\n".join(links),
                        "packageName": package_name,
                        "overwritePackagizerRules": True,
                    }]
                    if output_folder:
                        params[0]["destinationFolder"] = output_folder
                    
                    result = self._device.linkgrabber.add_links(params)
                    if result:
                        logger.success(f"✅ Liens ajoutés après reconnexion, ID: {result.get('id', 'unknown')}")
                        return str(result.get("id"))
                except Exception as e:
                    logger.error(f"❌ Erreur après reconnexion: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Erreur ajout liens: {e}")
            return None
    
    async def get_packages(self) -> list[dict]:
        """Récupère la liste des packages en téléchargement"""
        if not await self.connect():
            return []
        
        try:
            packages = self._device.downloads.query_packages([{
                "bytesLoaded": True,
                "bytesTotal": True,
                "comment": True,
                "enabled": True,
                "eta": True,
                "finished": True,
                "hosts": True,
                "name": True,
                "priority": True,
                "running": True,
                "saveTo": True,
                "speed": True,
                "status": True,
                "uuid": True,
            }])
            
            return packages or []
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération packages: {e}")
            return []
    
    async def get_package_status(self, uuid: str = None, name: str = None) -> Optional[dict]:
        """Récupère le statut d'un package spécifique par UUID ou nom exact
        
        Args:
            uuid: UUID du package (optionnel)
            name: Nom exact du package (sera normalisé pour comparaison JD)
        """
        packages = await self.get_packages()
        
        # Normaliser le nom recherché pour correspondre au format JDownloader
        normalized_search_name = normalize_jd_name(name) if name else None
        
        for pkg in packages:
            # Recherche par UUID
            if uuid and str(pkg.get("uuid")) == uuid:
                return self._package_to_status(pkg)
            
            # Recherche par nom exact (normalisé)
            if normalized_search_name:
                pkg_name = pkg.get("name", "")
                if pkg_name == normalized_search_name:
                    return self._package_to_status(pkg)
        
        return None
    
    def _package_to_status(self, pkg: dict) -> dict:
        """Convertit un package JDownloader en dict de statut"""
        save_to = pkg.get("saveTo", "")
        
        # Si le package est terminé, on peut récupérer le chemin complet du fichier
        # saveTo est juste le dossier, pas le fichier
        
        return {
            "uuid": str(pkg.get("uuid")),
            "name": pkg.get("name", ""),
            "status": pkg.get("status", ""),
            "bytes_loaded": pkg.get("bytesLoaded", 0),
            "bytes_total": pkg.get("bytesTotal", 0),
            "speed": pkg.get("speed", 0),
            "eta": pkg.get("eta", -1),
            "finished": pkg.get("finished", False),
            "running": pkg.get("running", False),
            "save_to": save_to,
        }
    
    async def get_package_files(self, package_uuid: str) -> list[dict]:
        """Récupère les fichiers (liens) d'un package spécifique"""
        if not await self.connect():
            return []
        
        try:
            links = self._device.downloads.query_links([{
                "packageUUIDs": [int(package_uuid)],
                "bytesLoaded": True,
                "bytesTotal": True,
                "name": True,
                "finished": True,
                "host": True,
            }])
            return links or []
        except Exception as e:
            logger.error(f"❌ Erreur récupération fichiers package {package_uuid}: {e}")
            return []
    
    async def get_linkgrabber_packages(self) -> list[dict]:
        """Récupère les packages dans le linkgrabber (en attente)"""
        if not await self.connect():
            return []
        
        try:
            packages = self._device.linkgrabber.query_packages([{
                "bytesTotal": True,
                "comment": True,
                "name": True,
                "saveTo": True,
                "uuid": True,
            }])
            
            return packages or []
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération linkgrabber: {e}")
            return []
    
    async def move_to_downloads(self, uuid: str) -> bool:
        """Déplace un package du linkgrabber vers les téléchargements"""
        if not await self.connect():
            return False
        
        try:
            self._device.linkgrabber.move_to_downloadlist([int(uuid)], [])
            logger.success(f"✅ Package {uuid} déplacé vers téléchargements")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur déplacement package: {e}")
            return False
    
    async def remove_package(self, uuid: str) -> bool:
        """Supprime un package"""
        if not await self.connect():
            return False
        
        try:
            self._device.downloads.remove_links([int(uuid)], [int(uuid)])
            logger.info(f"🗑️ Package {uuid} supprimé")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur suppression package: {e}")
            return False
    
    def disconnect(self):
        """Déconnecte de MyJDownloader"""
        if self._jd:
            try:
                self._jd.disconnect()
            except:
                pass
            self._jd = None
            self._device = None


# Instance singleton
_client: Optional[JDownloaderClient] = None


def get_jdownloader_client() -> JDownloaderClient:
    """Récupère l'instance singleton du client JDownloader"""
    global _client
    if _client is None:
        _client = JDownloaderClient()
    return _client
