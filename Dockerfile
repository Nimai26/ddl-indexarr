FROM python:3.11-slim

# Arguments de build
ARG PUID=1000
ARG PGID=1000

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Créer utilisateur non-root (ou réutiliser si existe)
RUN groupadd -g ${PGID} appgroup 2>/dev/null || true && \
    useradd -u ${PUID} -g ${PGID} -m appuser 2>/dev/null || true

WORKDIR /app

# Installer les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY app/ ./app/

# Créer les dossiers nécessaires
RUN mkdir -p /config /data /output && \
    chown -R ${PUID}:${PGID} /app /config /data /output

# Utiliser l'utilisateur non-root
USER ${PUID}

# Exposer les ports
EXPOSE 9117 9120

# Démarrer l'application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9117"]
