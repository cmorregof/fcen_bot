"""Configuración del bot. Todo lo secreto llega por variables de entorno."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[2]


def _es_verdadero(valor: object) -> bool:
    return str(valor).strip().lower() in ("1", "true", "yes", "on")


def _ids(valor: str) -> frozenset[int]:
    """Ids de Telegram separados por comas (o punto y coma)."""
    partes = valor.replace(";", ",").split(",")
    return frozenset(int(i) for i in (x.strip() for x in partes) if i.isdigit())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Servicio actual del bot (actas, admision, calidad)
    bot_servicio: Literal["actas", "admision", "calidad"] = "actas"

    # Entorno de práctica (capacitaciones): base propia en <DATA_DIR>/practica/,
    # sin envíos a Telegram y con datos ficticios. Ver docs/entorno-practica.md.
    memoria_practica: bool = False

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    # Código que una administrativa envía con /start para registrarse.
    invite_code: str = ""
    max_users: int = 4

    # Rutas internas (cron de GitHub Actions)
    internal_cron_secret: str = ""

    # Decanatura (Decana y vicedecanos): ids de Telegram, separados por comas.
    # Solo ellos reciben /resumen y el resumen semanal.
    decanatura_telegram_ids: str = ""
    # El cron del lunes no envía nada si esto es false.
    resumen_semanal_activo: bool = True
    # Días sin movimiento a partir de los cuales un caso sale como alerta.
    resumen_dias_sin_movimiento: int = 7
    # Secreto compartido por los tres servicios para /internal/cifras; con él,
    # actas pide a calidad y admisión sus conteos agregados (nunca su base).
    resumen_secret: str = ""
    # URL pública de los servicios de calidad y admisión (solo en actas).
    resumen_calidad_url: str = ""
    resumen_admision_url: str = ""
    # Administradores en Telegram: ids separados por comas. Pueden usar
    # /indicadores, igual que la decanatura.
    admin_telegram_ids: str = ""
    # Vicedecanatura Académica: ids de Telegram que reciben el consolidado del
    # reporte mensual de indicadores.
    vicedecanatura_telegram_ids: str = ""
    # El cron del día 1 no envía el reporte mensual si esto es false.
    reporte_mensual_activo: bool = True
    # Columnas del Excel de indicadores (mientras llega la plantilla oficial de
    # Calidad; ver docs/indicadores.md).
    indicadores_path: Path = RAIZ / "config" / "indicadores.yaml"
    # Al confirmar una decisión del acta del Consejo, avisar por Telegram a las
    # personas del área del caso. Apagado por defecto.
    aviso_consejo_telegram: bool = False

    # Claude
    anthropic_api_key: str = ""
    # Solo si la API key no pertenece a un workspace de la Console: el ID del
    # workspace al que se cobra (wrkspc_...).
    anthropic_workspace_id: str = ""
    extraction_model: str = "claude-sonnet-5-5"
    correction_model: str = "claude-sonnet-5-5"
    extraction_max_tokens: int = 8000
    # El acta del Consejo trae muchas decisiones: salida más larga.
    acta_consejo_max_tokens: int = 16000
    # Tope del texto del acta que se envía al modelo (unas 40 páginas).
    acta_consejo_max_caracteres: int = 150_000
    extraction_timeout_seconds: float = 90.0
    # Lado mayor de las imágenes antes de enviarlas al modelo (controla tokens).
    max_image_side: int = 1568
    # Precios en USD por millón de tokens, para el comando /costo.
    precio_input_mtok: float = 2.0
    precio_output_mtok: float = 10.0

    # Periodo académico: con la fecha de inicio de clases se calcula la semana
    # en la que llegó cada solicitud (Acuerdo 027 de 2024).
    periodo_actual: str = "2026-2S"
    periodo_inicio: date | None = None

    # Jurados de Trabajo de Grado que se presentan como mínimo. No es norma:
    # es instrucción del Consejo de Facultad (reunión del 28-oct-2026). El
    # valor por defecto está en config/solicitudes.yaml; si JURADOS_MINIMO se
    # define, tiene prioridad.
    jurados_minimo: int | None = None

    # Rutas de decisión y umbrales de las solicitudes (lo edita la
    # Vicedecanatura Académica; ver docs/solicitudes.md).
    solicitudes_path: Path = RAIZ / "config" / "solicitudes.yaml"

    # Almacenamiento. Si DB_PATH, MEDIA_DIR u OUTPUT_DIR no se definen, se
    # derivan de DATA_DIR por servicio: <DATA_DIR>/<servicio>/... En Docker,
    # DATA_DIR=/data (el volumen).
    data_dir: Path = Path("data")
    db_path: Path = Path("data/actas/fcen.db")
    media_dir: Path = Path("data/actas/media")
    output_dir: Path = Path("data/actas/out")

    # Conversión a PDF
    soffice_bin: str = "soffice"
    pdf_timeout_seconds: float = 120.0

    timezone: str = "America/Bogota"
    log_level: str = "INFO"

    @property
    def ids_decanatura(self) -> frozenset[int]:
        return _ids(self.decanatura_telegram_ids)

    @property
    def ids_admin(self) -> frozenset[int]:
        return _ids(self.admin_telegram_ids)

    @property
    def ids_vicedecanatura(self) -> frozenset[int]:
        return _ids(self.vicedecanatura_telegram_ids)

    @field_validator("periodo_inicio", mode="before")
    @classmethod
    def _fecha_vacia(cls, valor: object) -> object:
        # En .env.example la variable viene vacía: eso es "sin configurar".
        return None if valor == "" else valor

    @field_validator("jurados_minimo", mode="before")
    @classmethod
    def _entero_vacio(cls, valor: object) -> object:
        return None if valor == "" else valor

    @model_validator(mode="before")
    @classmethod
    def _rutas_por_defecto(cls, datos: Any) -> Any:
        if not isinstance(datos, dict):
            return datos
        datos = dict(datos)
        servicio = str(datos.get("bot_servicio") or "actas")
        data_dir = Path(str(datos.get("data_dir") or "data"))
        practica = _es_verdadero(datos.get("memoria_practica"))
        base = data_dir / "practica" / servicio if practica else data_dir / servicio
        # Actas ya desplegado guardaba todo en <DATA_DIR>/fcen.db, media y out.
        # Si esa base existe y la nueva no, se sigue usando: así un despliegue
        # no deja huérfanos los casos ni los usuarios registrados.
        if (
            not practica
            and servicio == "actas"
            and not datos.get("db_path")
            and (data_dir / "fcen.db").exists()
            and not (base / "fcen.db").exists()
        ):
            base = data_dir
        for campo, nombre in (
            ("db_path", "fcen.db"),
            ("media_dir", "media"),
            ("output_dir", "out"),
        ):
            if not datos.get(campo):  # ausente o vacío en el .env
                datos[campo] = base / nombre
        return datos

    @model_validator(mode="after")
    def _aislamiento(self) -> Self:
        if self.memoria_practica:
            # La práctica nunca toca la base de producción ni escribe a Telegram.
            for ruta in (self.db_path, self.media_dir, self.output_dir):
                if "practica" not in ruta.parts:
                    raise ValueError(
                        f"MEMORIA_PRACTICA=true exige rutas dentro de una carpeta "
                        f"«practica»; recibió {ruta}."
                    )
            self.telegram_bot_token = ""
            self.telegram_webhook_secret = ""
        # Un servicio nunca usa la base de actas (AGENTS.md).
        if self.bot_servicio != "actas":
            legado = {
                self.data_dir / "fcen.db",
                Path("data/fcen.db"),
                Path("/data/fcen.db"),
            }
            if self.db_path in legado or "actas" in self.db_path.parts:
                raise ValueError(
                    f"DB_PATH={self.db_path} es la base de actas; "
                    f"el servicio {self.bot_servicio} necesita la suya."
                )
        return self


settings = Settings()
