# Prefer the docker/ folder for builds (EDITO / Visual Port layout):
#
#   cd docker
#   build.bat
#
# This root Dockerfile remains as a short alias with the same image recipe.

FROM node:22-bookworm-slim AS ui

WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_BASE_URL= \
    VITE_ASSET_BASE_URL=/data \
    VITE_BUILDINGS_TILESET_URL= \
    VITE_APP_MODE=hub
RUN npm run build

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    OPENBLAS_NUM_THREADS=1 \
    HDF5_USE_FILE_LOCKING=FALSE \
    DATA_SOURCE=s3 \
    DATA_ROOT=/app/data \
    S3_CACHE_DIR=/app/data/cache/s3/model \
    HGRID_LL=/app/data/hgrid.ll \
    SCHISM_DIR=/app/data/schism \
    S3_ENDPOINT=https://minio.dive.edito.eu \
    S3_BUCKET=project-foccus \
    S3_MODEL_PREFIX=DigitalTwinTest/model \
    S3_ZARR_PREFIX=DigitalTwinTest/zarr/schism.zarr \
    S3_BUILDINGS_PREFIX=DigitalTwinTest/Buildings/hamburg/area1 \
    CORS_ORIGINS=* \
    MESH_CRS=EPSG:25832 \
    APP_MODE=hub \
    SCENARIOS_FILE=/app/config/scenarios.json

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libexpat1 libgomp1 libfreetype6 libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY backend /app/backend
COPY preprocessing/model /app/preprocessing/model
COPY config /app/config
COPY --from=ui /ui/dist /app/frontend/dist
RUN mkdir -p /app/data/cache/s3/model /app/data/models

WORKDIR /app/backend
# Kubernetes / EDITO Visual Port typically route to 8080. Vite 5173 is local-only.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD sh -c "curl --fail http://127.0.0.1:${PORT:-8080}/health || exit 1"

ENTRYPOINT ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
