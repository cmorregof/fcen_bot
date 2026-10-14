"""Genera el QR de invitación para que una administrativa abra el bot ya registrada.

Uso:
    uv run python scripts/qr_invitacion.py fcenpregrado_bot

Lee INVITE_CODE del entorno (o de .env) y escribe out/invitacion.png. El QR
abre t.me/<bot>?start=<código>; al tocar "Iniciar", Telegram envía
"/start <código>" y el bot registra a la persona. Quien tenga el QR puede
registrarse (hasta MAX_USERS personas): compártelo solo con ellas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import qrcode

from app.core.config import settings


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if not settings.invite_code:
        raise SystemExit("Falta INVITE_CODE.")
    enlace = f"https://t.me/{sys.argv[1].lstrip('@')}?start={settings.invite_code}"
    destino = Path("out") / "invitacion.png"
    destino.parent.mkdir(exist_ok=True)
    qrcode.make(enlace).save(destino)
    print(f"{enlace}\nQR en {destino}")


if __name__ == "__main__":
    main()
