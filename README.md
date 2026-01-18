# DDL-Indexarr 🎬

[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-nimai24%2Fddl--indexarr-blue?logo=docker)](https://hub.docker.com/r/nimai24/ddl-indexarr)
[![GitHub](https://img.shields.io/badge/GitHub-Nimai26%2Fddl--indexarr-black?logo=github)](https://github.com/Nimai26/ddl-indexarr)

**DDL-Indexarr** est un indexer Newznab/Torznab compatible avec les applications \*arr (Radarr, Sonarr, Lidarr) qui permet de rechercher et télécharger du contenu depuis **DarkiWorld** via **JDownloader**.

## ✨ Fonctionnalités

- 🔍 **Indexer Newznab** compatible Radarr, Sonarr et Lidarr
- 📥 **Client de téléchargement SABnzbd** émulé (même endpoint, ports différents)
- 🌐 **Intégration DarkiWorld** avec authentification par cookie
- ⬇️ **JDownloader** via MyJDownloader API pour les téléchargements DDL
- 🎯 **Vérification des liens** avant de les retourner (liens morts filtrés)
- 🎬 **Support TMDB/IMDB** pour la résolution des titres
- 🔗 **Hardlinks compatibles** avec structure /media unifiée

## 🏗️ Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Radarr    │────▶│                 │────▶│  DarkiWorld │
│   Sonarr    │     │   DDL-Indexarr  │     └─────────────┘
│   Lidarr    │◀────│                 │────▶┌─────────────┐
└─────────────┘     └─────────────────┘     │  JDownloader│
       │                    │               └─────────────┘
       │                    │                      │
       ▼                    ▼                      ▼
┌──────────────────────────────────────────────────────┐
│                /media (mount unifié)                 │
│  ├── downloads/complete/ddl/{radarr,sonarr,lidarr}  │
│  ├── movies/                                         │
│  ├── tv/                                             │
│  └── music/                                          │
└──────────────────────────────────────────────────────┘
```

## 🚀 Installation rapide

### Docker Compose (recommandé)

```yaml
version: '3.8'

services:
  ddl-indexarr:
    image: nimai24/ddl-indexarr:latest
    container_name: ddl-indexarr
    restart: unless-stopped
    ports:
      - "9118:9117"   # API Indexer (Newznab)
      - "9120:9117"   # API Download Client (SABnzbd)
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Paris
      # API
      - DDL_INDEXARR_API_KEY=your-api-key
      # DarkiWorld
      - DARKIWORLD_BASE_URL=https://darkiworld.com
      - DARKIWORLD_REMEMBER_COOKIE_NAME=remember_web_XXXXX
      - DARKIWORLD_REMEMBER_COOKIE_VALUE=your-cookie-value
      # JDownloader
      - JDOWNLOADER_EMAIL=your-myjd-email
      - JDOWNLOADER_PASSWORD=your-myjd-password
      - JDOWNLOADER_DEVICE_NAME=ddl-indexarr
      # TMDB (optionnel, pour résolution titres)
      - TMDB_KEY=your-tmdb-api-key
      # Chemins
      - DOWNLOAD_FOLDER=/media/downloads/complete/ddl
    volumes:
      - ddl-indexarr-data:/data
      - /path/to/media:/media
    networks:
      - media-network

  # JDownloader inclus (optionnel si vous en avez déjà un)
  jdownloader:
    image: jlesage/jdownloader-2:latest
    container_name: ddl-indexarr-jdownloader
    restart: unless-stopped
    ports:
      - "5800:5800"   # WebUI
    environment:
      - USER_ID=1000
      - GROUP_ID=1000
      - TZ=Europe/Paris
      - MYJDOWNLOADER_EMAIL=your-myjd-email
      - MYJDOWNLOADER_PASSWORD=your-myjd-password
      - MYJDOWNLOADER_DEVICE_NAME=ddl-indexarr
    volumes:
      - ddl-indexarr-jd-config:/config
      - /path/to/media:/media
    networks:
      - media-network

volumes:
  ddl-indexarr-data:
  ddl-indexarr-jd-config:

networks:
  media-network:
    external: true
```

### Docker Run

```bash
docker run -d \
  --name ddl-indexarr \
  -p 9118:9117 \
  -p 9120:9117 \
  -e DDL_INDEXARR_API_KEY=your-api-key \
  -e DARKIWORLD_BASE_URL=https://darkiworld.com \
  -e DARKIWORLD_REMEMBER_COOKIE_VALUE=your-cookie \
  -e JDOWNLOADER_EMAIL=your-email \
  -e JDOWNLOADER_PASSWORD=your-password \
  -e JDOWNLOADER_DEVICE_NAME=ddl-indexarr \
  -v ddl-indexarr-data:/data \
  -v /path/to/media:/media \
  nimai24/ddl-indexarr:latest
```

## ⚙️ Configuration

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `PUID` | User ID | `1000` |
| `PGID` | Group ID | `1000` |
| `TZ` | Timezone | `Europe/Paris` |
| `DDL_INDEXARR_API_KEY` | Clé API pour l'authentification | `ddl-indexarr` |
| `DARKIWORLD_BASE_URL` | URL de DarkiWorld | `https://darkiworld.com` |
| `DARKIWORLD_REMEMBER_COOKIE_NAME` | Nom du cookie remember_me | `remember_web_*` |
| `DARKIWORLD_REMEMBER_COOKIE_VALUE` | Valeur du cookie remember_me | **Requis** |
| `JDOWNLOADER_EMAIL` | Email MyJDownloader | **Requis** |
| `JDOWNLOADER_PASSWORD` | Mot de passe MyJDownloader | **Requis** |
| `JDOWNLOADER_DEVICE_NAME` | Nom du device JDownloader | `ddl-indexarr` |
| `TMDB_KEY` | Clé API TMDB (optionnel) | - |
| `DOWNLOAD_FOLDER` | Dossier de téléchargement | `/media/downloads/complete/ddl` |
| `DEBUG` | Mode debug | `false` |

### Obtenir le cookie DarkiWorld

1. Connectez-vous sur DarkiWorld avec "Se souvenir de moi" coché
2. Ouvrez les DevTools (F12) → Application → Cookies
3. Copiez le nom et la valeur du cookie `remember_web_*`

## 🔧 Configuration des applications \*arr

### Radarr / Sonarr / Lidarr - Indexer

1. **Settings** → **Indexers** → **+** → **Newznab**
2. Configurer :
   - **Name**: `DDL-Indexarr`
   - **URL**: `http://ddl-indexarr:9117` (ou IP:9118 si externe)
   - **API Path**: `/api`
   - **API Key**: Votre `DDL_INDEXARR_API_KEY`
   - **Categories**: 
     - Radarr: `2000, 2010, 2020, 2030, 2040, 2045, 2050`
     - Sonarr: `5000, 5010, 5020, 5030, 5040, 5045, 5050`
     - Lidarr: `3000, 3010, 3020, 3030, 3040`

### Radarr / Sonarr / Lidarr - Download Client

1. **Settings** → **Download Clients** → **+** → **SABnzbd**
2. Configurer :
   - **Name**: `DDL-Indexarr`
   - **Host**: `ddl-indexarr` (ou IP)
   - **Port**: `9117` (interne) ou `9120` (externe)
   - **API Key**: Votre `DDL_INDEXARR_API_KEY`
   - **Category**: `radarr`, `sonarr` ou `lidarr`

### Remote Path Mapping (si nécessaire)

Si JDownloader télécharge dans un chemin différent :

| Host | Remote Path | Local Path |
|------|-------------|------------|
| `ddl-indexarr` | `/media/downloads/complete/ddl/` | `/media/downloads/complete/ddl/` |

## 📁 Structure des dossiers recommandée

Pour les **hardlinks** (économiser de l'espace disque) :

```
/media/                          # Mount unique
├── downloads/
│   ├── complete/
│   │   ├── ddl/                # DDL-Indexarr downloads
│   │   │   ├── radarr/
│   │   │   ├── sonarr/
│   │   │   └── lidarr/
│   │   └── torrents/           # Torrents
├── movies/                      # Bibliothèque films
├── tv/                          # Bibliothèque séries
└── music/                       # Bibliothèque musique
```

> ⚠️ **Important**: Pour que les hardlinks fonctionnent, tous les conteneurs (*arr, DDL-Indexarr, JDownloader) doivent avoir le **même mount** `/media`.

## 🔌 API Endpoints

### Newznab API (Port 9117/9118)

| Endpoint | Description |
|----------|-------------|
| `GET /api?t=caps` | Capacités de l'indexer |
| `GET /api?t=search&q=...` | Recherche générale |
| `GET /api?t=movie&imdbid=...` | Recherche film par IMDB |
| `GET /api?t=tvsearch&q=...&season=X&ep=Y` | Recherche série |
| `GET /api?t=music&q=...` | Recherche musique |
| `GET /nzb?id=...` | Télécharger un "NZB" (déclenche JDownloader) |

### SABnzbd API (Port 9117/9120)

| Endpoint | Description |
|----------|-------------|
| `GET /api?mode=queue` | File d'attente |
| `GET /api?mode=history` | Historique |
| `GET /api?mode=addurl&name=...` | Ajouter un téléchargement |

## 🐛 Dépannage

### Les recherches ne retournent rien

1. Vérifiez que le cookie DarkiWorld est valide
2. Consultez les logs : `docker logs ddl-indexarr`
3. Testez l'API directement : `curl "http://localhost:9118/api?t=search&q=test&apikey=YOUR_KEY"`

### JDownloader ne démarre pas les téléchargements

1. Vérifiez la connexion MyJDownloader dans les logs
2. Assurez-vous que le device name correspond
3. Vérifiez que JDownloader est bien connecté à MyJDownloader

### Erreur "Invalid API Key"

- Assurez-vous d'utiliser la même `DDL_INDEXARR_API_KEY` partout
- La clé par défaut est `ddl-indexarr`

## 📊 Catégories supportées

| Catégorie | ID Torznab | Description |
|-----------|------------|-------------|
| Films | 2000-2099 | Movies |
| Films HD | 2040 | Movies HD |
| Films UHD | 2045 | Movies UHD/4K |
| Séries | 5000-5099 | TV Shows |
| Séries HD | 5040 | TV HD |
| Anime | 5070 | TV Anime |
| Musique | 3000-3099 | Audio |
| Musique MP3 | 3010 | Audio MP3 |
| Musique FLAC | 3040 | Audio Lossless |

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.

## 📄 Licence

MIT License - Voir [LICENSE](LICENSE)

## 🙏 Remerciements

- [DarkiWorld](https://darkiworld.com) pour le contenu
- [JDownloader](https://jdownloader.org) pour le téléchargement
- [Radarr](https://radarr.video), [Sonarr](https://sonarr.tv), [Lidarr](https://lidarr.audio) pour l'inspiration de l'API
