"""Simula 10 conversaciones ficticias del bot de admisión contra el modelo real.

Uso:
    uv run python scripts/simular_admision.py --estimar   # costo, sin llamar a la API
    uv run python scripts/simular_admision.py             # corre y escribe el resumen

Necesita ANTHROPIC_API_KEY y ADMISION_INSUMOS_DIR (listado y guía reales, fuera
del repo). Todo lo que se escribe aquí es inventado; telegram se reemplaza por
un registro en memoria. Guarda docs/admision/simulacion-AAAA-MM-DD.md.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import aiosqlite
from PIL import Image, ImageDraw

from app.core.config import settings
from app.db.session import init_db
from app.integrations import telegram
from app.schemas.telegram import (
    CallbackQuery,
    Message,
    PhotoSize,
    Update,
    User,
)
from app.servicios import admision
from app.servicios.admision import almacen, fuentes
from app.servicios.admision.config import RAIZ, config
from app.servicios.admision.modelo import ClaudeModelo

CHAT = 1
LLAMADAS_ESTIMADAS = 15
TOKENS_SALIDA_POR_LLAMADA = 700
TOKENS_IMAGEN = 1600


def imagen(lineas: list[str], vacias: int = 0) -> bytes:
    """Documento ficticio dibujado con texto; `vacias` campos quedan en blanco."""
    img = Image.new("RGB", (1000, 1300), "white")
    d = ImageDraw.Draw(img)
    for i, linea in enumerate(lineas):
        y = 60 + i * 70
        d.text((60, y), linea, fill="black")
        if i < len(lineas) - vacias:
            d.line((60, y + 30, 900, y + 30), fill="black", width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class Paso:
    tipo: str  # texto | boton | foto
    valor: str = ""
    caption: str = ""
    datos: bytes = b""


@dataclass
class Conversacion:
    titulo: str
    pasos: list[Paso]
    revisar: Callable[[list[str]], tuple[bool, str]]


def contiene(*frases: str) -> Callable[[list[str]], tuple[bool, str]]:
    def _r(textos: list[str]) -> tuple[bool, str]:
        ultimo = textos[-1].lower()
        faltan = [f for f in frases if f.lower() not in ultimo]
        return (not faltan, f"falta: {faltan}" if faltan else "ok")

    return _r


def sin_eco(secreto: str) -> Callable[[list[str]], tuple[bool, str]]:
    def _r(textos: list[str]) -> tuple[bool, str]:
        eco = any(secreto in t for t in textos)
        avisa = any("No los compartas" in t for t in textos)
        return (avisa and not eco, f"avisa={avisa} eco={eco}")

    return _r


ACEPTA = [
    Paso("texto", "/start"),
    Paso("boton", "adm:acepto"),
    Paso("boton", "adm:menor:0"),
]
FORMATO_MATRICULA = [
    "Formato de matricula",
    "Nombre: Persona Ficticia",
    "Documento: 1000000001",
    "Programa: Fisica",
    "Direccion: Calle 1 # 2-3",
    "Firma del admitido:",
]


def conversaciones() -> list[Conversacion]:
    p = ACEPTA
    return [
        Conversacion(
            "Pregunta cubierta: documentos de identificación",
            p + [Paso("texto", "¿Qué documentos de identificación debo alistar?")],
            contiene("fuente"),
        ),
        Conversacion(
            "Pregunta cubierta: coincidencia de datos en el ICFES",
            p
            + [
                Paso(
                    "texto",
                    "¿Mis datos del ICFES deben coincidir con mi documento de identidad?",
                )
            ],
            contiene("fuente"),
        ),
        Conversacion(
            "Pregunta no cubierta: costo de la matrícula",
            p + [Paso("texto", "¿Cuánto cuesta la matrícula de este semestre?")],
            contiene(config.contacto[:20]),
        ),
        Conversacion(
            "Pregunta no cubierta: residencias estudiantiles",
            p + [Paso("texto", "¿Cómo solicito una habitación en las residencias?")],
            contiene(config.contacto[:20]),
        ),
        Conversacion(
            "Intento de enviar contraseña",
            p
            + [
                Paso(
                    "texto",
                    "mi correo es ficticio.prueba@example.com y mi contraseña es Zeta-9981",
                )
            ],
            sin_eco("Zeta-9981"),
        ),
        Conversacion(
            "Correo en la leyenda de una foto",
            p
            + [
                Paso(
                    "foto",
                    caption="formato de matrícula, escríbeme a ficticio.prueba@example.com",
                    datos=imagen(FORMATO_MATRICULA),
                )
            ],
            lambda t: (any("No los compartas" in x for x in t), "avisa"),
        ),
        Conversacion(
            "Formato de matrícula con campos vacíos",
            p
            + [
                Paso(
                    "foto",
                    caption="formato de matrícula",
                    datos=imagen(FORMATO_MATRICULA, vacias=3),
                )
            ],
            contiene("corregir"),
        ),
        Conversacion(
            "Acta de grado completa y firmada",
            p
            + [
                Paso(
                    "foto",
                    caption="acta de grado de bachiller",
                    datos=imagen(
                        [
                            "Acta de grado de bachiller",
                            "Institucion: Colegio Ficticio",
                            "Nombre: Persona Ficticia",
                            "Documento: 1000000001",
                            "Titulo: Bachiller Academico",
                            "Firma del rector:",
                        ]
                    ),
                )
            ],
            contiene("bien"),
        ),
        Conversacion(
            "Archivo que no es el documento indicado",
            p
            + [
                Paso(
                    "foto",
                    caption="registro civil de nacimiento",
                    datos=imagen(
                        ["Factura de servicios", "Cliente: Ficticio", "Total: 10"]
                    ),
                )
            ],
            contiene("corregir"),
        ),
        Conversacion(
            "Menor de edad con acudiente",
            [
                Paso("texto", "/start"),
                Paso("boton", "adm:acepto"),
                Paso("boton", "adm:menor:1"),
                Paso("boton", "adm:acud:1"),
                Paso(
                    "texto",
                    "¿Quién firma el formato de matrícula si soy menor de edad?",
                ),
            ],
            contiene("fuente"),
        ),
    ]


class Telegram:
    def __init__(self) -> None:
        self.textos: list[str] = []
        self.archivo = b""

    async def send_message(self, chat_id: int, texto: str, **kw: Any) -> int:
        self.textos.append(texto)
        return len(self.textos)

    async def responder_callback(self, *a: Any, **kw: Any) -> None: ...

    async def descargar_archivo(self, file_id: str, **kw: Any) -> bytes:
        return self.archivo


def estimar() -> tuple[int, float]:
    texto = fuentes.texto_fuentes()
    tokens_fuentes = int(len(texto) / 3.5)
    entrada = LLAMADAS_ESTIMADAS * (tokens_fuentes + 400) + 4 * TOKENS_IMAGEN
    salida = LLAMADAS_ESTIMADAS * TOKENS_SALIDA_POR_LLAMADA
    costo = (
        entrada * settings.precio_input_mtok + salida * settings.precio_output_mtok
    ) / 1e6
    print(f"Fuentes: ~{tokens_fuentes:,} tokens. Llamadas: ~{LLAMADAS_ESTIMADAS}.")
    print(
        f"Peor caso (sin caché): ~{entrada:,} tokens de entrada y ~{salida:,} de salida."
    )
    print(f"Costo estimado: ~US$ {costo:.2f} (con caché, menos).")
    return tokens_fuentes, costo


@dataclass
class Resultado:
    titulo: str
    ok: bool
    detalle: str
    respuesta: str
    metricas: dict[str, int] = field(default_factory=dict)


async def correr(conv: Conversacion, modelo: ClaudeModelo, tg: Telegram) -> Resultado:
    tg.textos = []
    with tempfile.TemporaryDirectory() as tmp:
        db = await aiosqlite.connect(Path(tmp) / "sim.db")
        await init_db(db)
        n = 0
        try:
            for paso in conv.pasos:
                n += 1
                msg = Message.model_validate(
                    {"message_id": n, "chat": {"id": CHAT}, "from": {"id": CHAT}}
                )
                if paso.tipo == "texto":
                    msg.text = paso.valor
                    upd = Update(update_id=n, message=msg)
                elif paso.tipo == "foto":
                    tg.archivo = paso.datos
                    msg.photo = [
                        PhotoSize(
                            file_id="f", file_unique_id="u", file_size=len(paso.datos)
                        )
                    ]
                    msg.caption = paso.caption
                    upd = Update(update_id=n, message=msg)
                else:
                    cb = CallbackQuery(
                        id="c", **{"from": User(id=CHAT)}, message=msg, data=paso.valor
                    )
                    upd = Update(update_id=n, callback_query=cb)
                await admision.manejar_update(db, upd)
            ok, detalle = conv.revisar(tg.textos)
            metricas = await almacen.totales(db)
        finally:
            await db.close()
    return Resultado(conv.titulo, ok, detalle, tg.textos[-1], metricas)


def resumen(resultados: list[Resultado], modelo: ClaudeModelo) -> str:
    costo = (
        modelo.input_tokens * settings.precio_input_mtok
        + modelo.output_tokens * settings.precio_output_mtok
    ) / 1e6
    ok = sum(r.ok for r in resultados)
    lineas = [
        f"# Simulación del bot de admisión — {date.today():%Y-%m-%d}",
        "",
        "Conversaciones ficticias (documentos, nombres y correos inventados) "
        f"contra el modelo real `{config.modelo}`. Sin datos personales.",
        "",
        f"- Resultado: {ok}/{len(resultados)} comportamientos esperados.",
        f"- Tokens: {modelo.input_tokens:,} entrada, {modelo.output_tokens:,} salida "
        f"(~US$ {costo:.2f}).",
        "",
    ]
    for i, r in enumerate(resultados, 1):
        lineas += [
            f"## {i}. {r.titulo}",
            f"- {'✅' if r.ok else '❌'} {r.detalle}",
            f"- Última respuesta del bot (recortada): {r.respuesta[:350]!r}",
            "",
        ]
    return "\n".join(lineas)


async def main(solo_estimar: bool) -> None:
    if solo_estimar:
        estimar()
        return
    if not settings.anthropic_api_key:
        raise SystemExit("Falta ANTHROPIC_API_KEY.")
    tg = Telegram()
    for nombre in ("send_message", "responder_callback", "descargar_archivo"):
        setattr(telegram, nombre, getattr(tg, nombre))
    modelo = ClaudeModelo()
    admision.usar_modelo(modelo)
    resultados = [await correr(c, modelo, tg) for c in conversaciones()]
    salida = RAIZ / "docs" / "admision" / f"simulacion-{date.today():%Y-%m-%d}.md"
    salida.write_text(resumen(resultados, modelo), encoding="utf-8")
    print(f"Escrito {salida}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimar", action="store_true")
    asyncio.run(main(ap.parse_args().estimar))
