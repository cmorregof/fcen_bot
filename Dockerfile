FROM python:3.12-slim

# LibreOffice para convertir los borradores a PDF; poppler para leer los
# formatos de solicitud en PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui poppler-utils fonts-dejavu fonts-crosextra-carlito fontconfig \
    && rm -rf /var/lib/apt/lists/*

# OCR para los insumos escaneados de admisión. Solo se instala si el servicio
# define la variable INSTALAR_OCR=1 (Railway la pasa como argumento de build);
# actas y calidad no la necesitan. Sin OCR, el servicio usa la caché
# <nombre>.ocr.txt que se sube junto al PDF.
ARG INSTALAR_OCR=0
RUN if [ "$INSTALAR_OCR" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ocrmypdf tesseract-ocr-spa \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Fuente institucional opcional: copia los .ttf de Ancízar Sans en fonts/
# (no se versionan) y quedarán instalados para el PDF.
COPY fonts/ /usr/share/fonts/truetype/unal/
RUN fc-cache -f

RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ ./app/
# Archivos editables que leen los servicios: listas (admisión, calidad) y el
# aviso de datos de admisión.
COPY config/ ./config/
COPY docs/admision/aviso_datos.md ./docs/admision/aviso_datos.md
RUN uv sync --frozen --no-dev

ENV BOT_SERVICIO=actas DATA_DIR=/data
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
