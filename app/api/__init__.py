"""API endpoints"""

from .newznab import router as newznab_router
from .sabnzbd import router as sabnzbd_router

__all__ = ["newznab_router", "sabnzbd_router"]
