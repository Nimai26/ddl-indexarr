"""Modèles pour les téléchargements"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class DownloadStatus(str, Enum):
    """Statuts possibles d'un téléchargement"""
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    EXTRACTING = "extracting"


class Download(BaseModel):
    """Représente un téléchargement en cours"""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    
    # Identifiants
    nzo_id: str = ""  # ID SABnzbd (pour compatibilité)
    title: str
    category: str = "default"  # radarr, sonarr, lidarr
    
    # Source
    source_url: str = ""  # URL DarkiWorld
    download_links: list[str] = Field(default_factory=list)
    
    # JDownloader
    jd_package_id: Optional[int] = None
    jd_uuid: Optional[str] = None
    jd_package_name: Optional[str] = None  # Nom du package pour recherche
    
    # Progression
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0  # 0-100
    size_total: int = 0  # bytes
    size_downloaded: int = 0  # bytes
    speed: int = 0  # bytes/sec
    eta: int = 0  # secondes restantes
    
    # Fichiers
    output_path: Optional[str] = None
    files: list[str] = Field(default_factory=list)
    
    # Métadonnées
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def to_sabnzbd_slot(self) -> dict:
        """Convertit en format SABnzbd queue slot"""
        
        # Mapping statut → SABnzbd
        status_map = {
            DownloadStatus.QUEUED: "Queued",
            DownloadStatus.DOWNLOADING: "Downloading",
            DownloadStatus.PAUSED: "Paused",
            DownloadStatus.COMPLETED: "Completed",
            DownloadStatus.FAILED: "Failed",
            DownloadStatus.EXTRACTING: "Extracting",
        }
        
        mb_total = self.size_total / (1024 * 1024)
        mb_left = (self.size_total - self.size_downloaded) / (1024 * 1024)
        
        return {
            "nzo_id": self.nzo_id or self.id,
            "filename": self.title,
            "cat": self.category,
            "status": status_map.get(self.status, "Downloading"),
            "percentage": str(int(self.progress)),
            "mb": f"{mb_total:.2f}",
            "mbleft": f"{mb_left:.2f}",
            "size": self._format_size(self.size_total),
            "sizeleft": self._format_size(self.size_total - self.size_downloaded),
            "timeleft": self._format_time(self.eta),
            "eta": self._format_time(self.eta),
        }
    
    def to_sabnzbd_history(self) -> dict:
        """Convertit en format SABnzbd history slot"""
        
        status = "Completed" if self.status == DownloadStatus.COMPLETED else "Failed"
        
        return {
            "nzo_id": self.nzo_id or self.id,
            "name": self.title,
            "category": self.category,
            "status": status,
            "bytes": self.size_total,
            "size": self._format_size(self.size_total),
            "completed": int(self.completed_at.timestamp()) if self.completed_at else 0,
            "storage": self.output_path or "",
            "fail_message": self.error_message or "",
        }
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Formate une taille en bytes vers une chaîne lisible"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    
    @staticmethod
    def _format_time(seconds: int) -> str:
        """Formate des secondes en HH:MM:SS"""
        if seconds <= 0:
            return "0:00:00"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"
