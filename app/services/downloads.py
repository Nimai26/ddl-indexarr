"""Gestionnaire de téléchargements - Pont entre Radarr/Sonarr et JDownloader"""

import json
import asyncio
from pathlib import Path
from loguru import logger
from typing import Optional
from datetime import datetime

from app.config import get_settings
from app.models.download import Download, DownloadStatus
from app.services.jdownloader import get_jdownloader_client


class DownloadManager:
    """Gère les téléchargements et leur suivi"""
    
    def __init__(self):
        self.settings = get_settings()
        self._downloads: dict[str, Download] = {}
        self._data_file = Path(self.settings.data_path) / "downloads.json"
        self._load_downloads()
    
    def _load_downloads(self):
        """Charge les téléchargements depuis le fichier"""
        try:
            if self._data_file.exists():
                with open(self._data_file, "r") as f:
                    data = json.load(f)
                    for item in data:
                        dl = Download(**item)
                        self._downloads[dl.id] = dl
                logger.info(f"📂 {len(self._downloads)} téléchargements chargés")
        except Exception as e:
            logger.error(f"❌ Erreur chargement téléchargements: {e}")
    
    def _save_downloads(self):
        """Sauvegarde les téléchargements dans le fichier"""
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._data_file, "w") as f:
                data = [dl.model_dump(mode="json") for dl in self._downloads.values()]
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde téléchargements: {e}")
    
    def create_download(
        self,
        title: str,
        category: str,
        links: list[str],
        source_url: str = ""
    ) -> Download:
        """
        Crée un nouveau téléchargement
        
        Args:
            title: Nom du téléchargement
            category: Catégorie (radarr, sonarr, lidarr)
            links: Liens de téléchargement
            source_url: URL source DarkiWorld
            
        Returns:
            L'objet Download créé
        """
        download = Download(
            title=title,
            category=category,
            download_links=links,
            source_url=source_url,
            nzo_id=f"SABnzbd_nzo_{title[:20].replace(' ', '_')}_{datetime.now().strftime('%H%M%S')}",
        )
        
        self._downloads[download.id] = download
        self._save_downloads()
        
        logger.info(f"➕ Téléchargement créé: {title} [{category}]")
        return download
    
    def get_download(self, download_id: str) -> Optional[Download]:
        """Récupère un téléchargement par ID"""
        # Chercher par ID ou nzo_id
        if download_id in self._downloads:
            return self._downloads[download_id]
        
        for dl in self._downloads.values():
            if dl.nzo_id == download_id:
                return dl
        
        return None
    
    def delete_download(self, download_id: str) -> bool:
        """
        Supprime un téléchargement
        
        Args:
            download_id: ID ou nzo_id du téléchargement
            
        Returns:
            True si supprimé avec succès
        """
        # Chercher par ID direct
        if download_id in self._downloads:
            del self._downloads[download_id]
            self._save_downloads()
            logger.info(f"🗑️ Téléchargement supprimé: {download_id}")
            return True
        
        # Chercher par nzo_id
        for dl_id, dl in list(self._downloads.items()):
            if dl.nzo_id == download_id:
                del self._downloads[dl_id]
                self._save_downloads()
                logger.info(f"🗑️ Téléchargement supprimé: {dl.title}")
                return True
        
        logger.warning(f"⚠️ Téléchargement non trouvé: {download_id}")
        return False
    
    def clear_all(self):
        """Supprime tous les téléchargements"""
        count = len(self._downloads)
        self._downloads.clear()
        self._save_downloads()
        logger.info(f"🗑️ {count} téléchargements supprimés")
    
    async def cleanup_stale_downloads(self) -> int:
        """
        Nettoie les téléchargements obsolètes :
        - Téléchargements complétés dont les fichiers ont été importés (n'existent plus)
        - Téléchargements échoués vieux de plus de 24h
        
        NOTE: On ne supprime PAS les téléchargements en cours basé sur JDownloader
        car l'UUID retourné par add_links est un crawling ID temporaire,
        pas l'UUID final du package.
        
        Returns:
            Nombre de téléchargements supprimés
        """
        import os
        from datetime import datetime, timedelta
        
        to_remove = []
        now = datetime.now()
        
        for dl_id, dl in self._downloads.items():
            should_remove = False
            reason = ""
            
            # Cas 1: Téléchargement complété - vérifier si le fichier existe encore
            if dl.status == DownloadStatus.COMPLETED:
                if dl.output_path:
                    # Vérifier si le dossier/fichier existe
                    if not os.path.exists(dl.output_path):
                        should_remove = True
                        reason = "fichier importé/supprimé"
                    else:
                        # Vérifier si c'est un dossier vide
                        if os.path.isdir(dl.output_path):
                            files = [f for f in os.listdir(dl.output_path) if not f.startswith('.')]
                            if len(files) == 0:
                                should_remove = True
                                reason = "dossier vide (fichier importé)"
            
            # Cas 2: Téléchargement échoué vieux de plus de 24h
            elif dl.status == DownloadStatus.FAILED:
                if dl.created_at:
                    age = now - dl.created_at
                    if age > timedelta(hours=24):
                        should_remove = True
                        reason = "échec depuis plus de 24h"
            
            # NOTE: On ne vérifie PAS JDownloader ici car l'UUID est temporaire
            # Le suivi de progression se fait via update_progress() qui gère ce cas
            
            if should_remove:
                to_remove.append((dl_id, dl.title, reason))
        
        # Supprimer les téléchargements obsolètes
        for dl_id, title, reason in to_remove:
            del self._downloads[dl_id]
            logger.info(f"🧹 Nettoyé: {title} ({reason})")
        
        if to_remove:
            self._save_downloads()
            logger.success(f"✅ {len(to_remove)} téléchargements obsolètes nettoyés")
        
        return len(to_remove)

    def get_downloads_by_category(self, category: str = None) -> list[Download]:
        """Récupère les téléchargements filtrés par catégorie"""
        if category:
            return [dl for dl in self._downloads.values() if dl.category == category]
        return list(self._downloads.values())
    
    def get_active_downloads(self, category: str = None) -> list[Download]:
        """Récupère les téléchargements actifs (non terminés)"""
        active_statuses = {
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSED,
            DownloadStatus.EXTRACTING,
        }
        
        downloads = self.get_downloads_by_category(category)
        return [dl for dl in downloads if dl.status in active_statuses]
    
    def get_completed_downloads(self, category: str = None) -> list[Download]:
        """Récupère les téléchargements terminés"""
        completed_statuses = {
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
        }
        
        downloads = self.get_downloads_by_category(category)
        return [dl for dl in downloads if dl.status in completed_statuses]
    
    async def start_download(self, download: Download) -> bool:
        """
        Démarre un téléchargement via JDownloader
        
        Args:
            download: Le téléchargement à démarrer
            
        Returns:
            True si le démarrage a réussi
        """
        if not download.download_links:
            logger.error(f"❌ Pas de liens pour: {download.title}")
            download.status = DownloadStatus.FAILED
            download.error_message = "Aucun lien de téléchargement"
            self._save_downloads()
            return False
        
        jd = get_jdownloader_client()
        
        # Déterminer le dossier de sortie - créer un sous-dossier par téléchargement
        # SABnzbd crée normalement un sous-dossier par téléchargement, Sonarr s'y attend
        base_folder = f"{self.settings.output_path}/{download.category}"
        output_folder = f"{base_folder}/{download.title}"
        
        # Ajouter les liens à JDownloader avec le sous-dossier spécifique
        uuid = await jd.add_links(
            links=download.download_links,
            package_name=download.title,
            output_folder=output_folder
        )
        
        if uuid:
            download.jd_uuid = uuid
            download.status = DownloadStatus.DOWNLOADING
            download.output_path = output_folder
            self._save_downloads()
            logger.success(f"✅ Téléchargement démarré: {download.title}")
            return True
        else:
            download.status = DownloadStatus.FAILED
            download.error_message = "Échec ajout à JDownloader"
            self._save_downloads()
            return False
    
    async def update_progress(self, download: Download) -> Download:
        """
        Met à jour la progression d'un téléchargement depuis JDownloader
        
        Args:
            download: Le téléchargement à mettre à jour
            
        Returns:
            Le téléchargement mis à jour
        """
        jd = get_jdownloader_client()
        status = None
        
        # Essayer par UUID d'abord
        if download.jd_uuid:
            status = await jd.get_package_status(uuid=download.jd_uuid)
        
        # Si pas trouvé par UUID, chercher par nom de package exact
        # La fonction normalize_jd_name() dans jdownloader.py gère les remplacements de caractères
        if not status and download.jd_package_name:
            status = await jd.get_package_status(name=download.jd_package_name)
            # Mettre à jour l'UUID si trouvé
            if status:
                download.jd_uuid = status.get("uuid")
                logger.debug(f"🔄 UUID mis à jour pour {download.title}: {download.jd_uuid}")
        
        if status:
            download.size_total = status.get("bytes_total", 0)
            download.size_downloaded = status.get("bytes_loaded", 0)
            download.speed = status.get("speed", 0)
            download.eta = status.get("eta", 0) if status.get("eta", -1) > 0 else 0
            
            # Mettre à jour le chemin de sortie (dossier)
            save_to = status.get("save_to")
            if save_to:
                download.output_path = save_to
            
            # Calculer le pourcentage
            if download.size_total > 0:
                download.progress = (download.size_downloaded / download.size_total) * 100
            
            # Déterminer le statut
            if status.get("finished"):
                download.status = DownloadStatus.COMPLETED
                download.completed_at = datetime.now()
                download.progress = 100
                
                # Récupérer les fichiers du package pour avoir le chemin complet
                # SABnzbd attend un chemin vers le dossier contenant le fichier
                if download.jd_uuid and save_to:
                    files = await jd.get_package_files(download.jd_uuid)
                    if files and len(files) > 0:
                        # Utiliser le nom du premier fichier pour construire le chemin complet
                        filename = files[0].get("name", "")
                        if filename:
                            # output_path pointe vers le dossier qui contient le fichier
                            # C'est ce que Sonarr attend pour faire l'import
                            download.output_path = save_to
                            logger.debug(f"📁 Fichier téléchargé: {save_to}/{filename}")
                
                logger.success(f"✅ Téléchargement terminé: {download.title} -> {download.output_path}")
            elif status.get("running"):
                download.status = DownloadStatus.DOWNLOADING
            else:
                # Vérifier le statut textuel
                jd_status = status.get("status", "").lower()
                if "extract" in jd_status:
                    download.status = DownloadStatus.EXTRACTING
                elif "queue" in jd_status or "wait" in jd_status:
                    download.status = DownloadStatus.QUEUED
            
            self._save_downloads()
        
        return download
    
    async def update_all_progress(self):
        """Met à jour la progression de tous les téléchargements actifs"""
        active = self.get_active_downloads()
        
        for download in active:
            await self.update_progress(download)
    
    def remove_download(self, download_id: str) -> bool:
        """Supprime un téléchargement du suivi"""
        download = self.get_download(download_id)
        
        if download:
            del self._downloads[download.id]
            self._save_downloads()
            logger.info(f"🗑️ Téléchargement supprimé: {download.title}")
            return True
        
        return False
    
    def mark_completed(self, download_id: str) -> bool:
        """Marque un téléchargement comme terminé"""
        download = self.get_download(download_id)
        
        if download:
            download.status = DownloadStatus.COMPLETED
            download.completed_at = datetime.now()
            download.progress = 100
            self._save_downloads()
            return True
        
        return False
    
    def mark_failed(self, download_id: str, error: str = "") -> bool:
        """Marque un téléchargement comme échoué"""
        download = self.get_download(download_id)
        
        if download:
            download.status = DownloadStatus.FAILED
            download.error_message = error
            self._save_downloads()
            return True
        
        return False


# Instance singleton
_manager: Optional[DownloadManager] = None


def get_download_manager() -> DownloadManager:
    """Récupère l'instance singleton du gestionnaire"""
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager
