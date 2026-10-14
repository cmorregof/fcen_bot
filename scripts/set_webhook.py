"""Registra el webhook en Telegram.

Uso:
    uv run python scripts/set_webhook.py https://tu-app.up.railway.app

Lee TELEGRAM_BOT_TOKEN y TELEGRAM_WEBHOOK_SECRET del entorno (o de .env).
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import settings
from app.integrations.telegram import set_webhook


async def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if not settings.telegram_bot_token or not settings.telegram_webhook_secret:
        raise SystemExit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_WEBHOOK_SECRET.")
    url = sys.argv[1].rstrip("/") + "/webhook"
    print(await set_webhook(url, settings.telegram_webhook_secret))


if __name__ == "__main__":
    asyncio.run(main())
