FROM python:3.12-slim

# LibreOffice para convertir los borradores a PDF; poppler para leer los
# formatos de solicitud en PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui poppler-utils fonts-dejavu fonts-crosextra-carlito fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Fuente institucional opcional: copia los .ttf de Ancízar Sans en fonts/
# (no se versionan) y quedarán instalados para el PDF.
COPY fonts/ /usr/share/fonts/truetype/unal/
RUN fc-cache -f

RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ ./app/
RUN uv sync --frozen --no-dev

ENV BOT_SERVICIO=actas DATA_DIR=/data
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
