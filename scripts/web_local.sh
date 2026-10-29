#!/usr/bin/env bash
# Levanta los tres backends en local con datos ficticios y entrada sin Google.
# actas → :8001, calidad → :8002, admision → :8003. Ctrl+C los detiene.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA_DIR="${DATA_DIR:-data/web-local}"
export DATA_DIR WEB_AUTH_DEV=true WEB_SESSION_SECRET="${WEB_SESSION_SECRET:-solo-local}"
export WEB_ORIGINS="${WEB_ORIGINS:-http://localhost:3000}"
export ADMISION_INSUMOS_DIR="${ADMISION_INSUMOS_DIR:-tests/fixtures/admision}"
puerto=8001
for servicio in actas calidad admision; do
  BOT_SERVICIO=$servicio uv run python scripts/datos_web_ficticios.py
  BOT_SERVICIO=$servicio uv run uvicorn app.main:app --port $puerto &
  puerto=$((puerto + 1))
done
trap 'kill 0' INT TERM
wait
