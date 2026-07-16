# Imagen base oficial de Python, compatible con amd64 y arm64, incluyendo Raspberry Pi 5.
FROM python:3.12-slim-bookworm

# Evita la generacion de archivos .pyc y fuerza salida inmediata en consola para logs correctos.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

# Instala utilidades minimas para una app de voz: ffmpeg para manejo de audio y tini para señales limpias.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Define el directorio de trabajo principal dentro del contenedor.
WORKDIR /app

# Crea un usuario no root para ejecutar la aplicacion con menor privilegio.
RUN useradd --create-home --shell /bin/bash appuser

# Copia todo el contexto del proyecto; .dockerignore se encarga de excluir artefactos innecesarios.
COPY . /app

# Crea los directorios de datos persistentes y asigna permisos al usuario de ejecucion.
RUN mkdir -p /app/database /app/logs /app/audios \
    && chown -R appuser:appuser /app \
    && if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Cambia al usuario sin privilegios para la ejecucion final del proceso.
USER appuser

# Usa tini como init para manejar correctamente zombies y señales de parada.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Deja preparado el arranque de la aplicacion Python cuando exista el modulo principal.
CMD ["python", "-m", "app.main"]