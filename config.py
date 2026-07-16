"""Configuracion central del proyecto.

Este modulo solo resuelve configuracion transversal:
- carga de variables desde .env
- validacion de variables obligatorias
- logging
- SQLite
- Groq
- Telegram
- limpieza automatica
- configuracion Docker

No contiene logica del bot ni reglas de negocio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from logging.config import dictConfig
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - soporte defensivo si la dependencia aun no esta instalada.
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:  # type: ignore[override]
        return False


class ConfigError(RuntimeError):
    """Se lanza cuando falta una variable obligatoria o un valor es invalido."""


def _load_environment() -> None:
    """Carga variables desde .env si existe, sin sobrescribir el entorno real."""

    load_dotenv(override=False)


def _env(name: str, default: str | None = None) -> str | None:
    """Lee una variable de entorno con valor por defecto opcional."""

    from os import getenv

    value = getenv(name)
    if value is None or value == "":
        return default
    return value


def _required_env(name: str) -> str:
    """Lee una variable obligatoria y falla con un error explicito si no existe."""

    value = _env(name)
    if value is None:
        raise ConfigError(f"Falta la variable obligatoria: {name}")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    """Convierte una variable de entorno a booleano."""

    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "si", "sí"}


def _int_env(name: str, default: int) -> int:
    """Convierte una variable de entorno a entero con valor por defecto."""

    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"La variable {name} debe ser un entero valido") from exc


def _float_env(name: str, default: float) -> float:
    """Convierte una variable de entorno a decimal con valor por defecto."""

    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"La variable {name} debe ser un numero valido") from exc


def _csv_int_env(name: str) -> list[int]:
    """Convierte una lista separada por comas en enteros."""

    raw = _env(name, "")
    if not raw:
        return []

    values: list[int] = []
    for item in raw.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        try:
            values.append(int(cleaned))
        except ValueError as exc:
            raise ConfigError(
                f"La variable {name} debe contener solo enteros separados por coma"
            ) from exc
    return values


def _path_env(name: str, default: str) -> Path:
    """Convierte una ruta de entorno en Path."""

    raw = _env(name, default)
    if raw is None:
        return Path(default)
    return Path(raw)


def _project_root() -> Path:
    """Resuelve la raiz del proyecto desde la ubicacion de este archivo."""

    return Path(__file__).resolve().parent


@dataclass(frozen=True)
class DockerConfig:
    """Configuracion relevante para ejecutar el proyecto en Docker."""

    project_name: str
    container_name: str
    restart_policy: str
    timezone: str
    app_user: str
    app_group: str
    workdir: Path
    database_dir: Path
    logs_dir: Path
    audios_dir: Path
    use_bind_mounts: bool


@dataclass(frozen=True)
class LoggingConfig:
    """Configuracion de logging de la aplicacion."""

    level: str
    format: str
    date_format: str
    log_dir: Path
    log_file: Path
    rotate_max_bytes: int
    rotate_backup_count: int
    console_enabled: bool
    file_enabled: bool


@dataclass(frozen=True)
class SQLiteConfig:
    """Configuracion de SQLite."""

    database_path: Path
    timeout_seconds: float
    journal_mode: str
    foreign_keys_enabled: bool
    busy_timeout_ms: int
    backup_enabled: bool
    backup_dir: Path


@dataclass(frozen=True)
class GroqConfig:
    """Configuracion del servicio Groq."""

    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    temperature: float
    language: str


@dataclass(frozen=True)
class TelegramConfig:
    """Configuracion de Telegram."""

    bot_token: str
    allowed_user_ids: list[int]
    polling_timeout_seconds: int
    webhook_enabled: bool
    webhook_path: str
    webhook_secret_token: str
    max_message_length: int


@dataclass(frozen=True)
class CleanupConfig:
    """Configuracion de limpieza automatica de archivos temporales y registros."""

    enabled: bool
    interval_seconds: int
    max_audio_age_hours: int
    max_log_age_days: int
    max_temp_age_hours: int
    dry_run: bool


@dataclass(frozen=True)
class AppConfig:
    """Agrupa toda la configuracion transversal de la aplicacion."""

    app_name: str
    app_env: str
    debug: bool
    project_root: Path
    docker: DockerConfig
    logging: LoggingConfig
    sqlite: SQLiteConfig
    groq: GroqConfig
    telegram: TelegramConfig
    cleanup: CleanupConfig


def _build_docker_config(project_root: Path) -> DockerConfig:
    workdir = _path_env("DOCKER_WORKDIR", str(project_root))
    database_dir = _path_env("DATABASE_DIR", str(project_root / "database"))
    logs_dir = _path_env("LOG_DIR", str(project_root / "logs"))
    audios_dir = _path_env("AUDIO_DIR", str(project_root / "audios"))

    return DockerConfig(
        project_name=_env("DOCKER_PROJECT_NAME", _env("APP_NAME", "automatizador-notas-voz")) or "automatizador-notas-voz",
        container_name=_env("DOCKER_CONTAINER_NAME", "automatizador-notas-voz") or "automatizador-notas-voz",
        restart_policy=_env("DOCKER_RESTART_POLICY", "unless-stopped") or "unless-stopped",
        timezone=_env("TIMEZONE", "UTC") or "UTC",
        app_user=_env("DOCKER_APP_USER", "appuser") or "appuser",
        app_group=_env("DOCKER_APP_GROUP", "appuser") or "appuser",
        workdir=workdir,
        database_dir=database_dir,
        logs_dir=logs_dir,
        audios_dir=audios_dir,
        use_bind_mounts=_bool_env("DOCKER_USE_BIND_MOUNTS", True),
    )


def _build_logging_config(project_root: Path) -> LoggingConfig:
    log_dir = _path_env("LOG_DIR", str(project_root / "logs"))
    return LoggingConfig(
        level=_env("LOG_LEVEL", "INFO") or "INFO",
        format=_env(
            "LOG_FORMAT",
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        or "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        date_format=_env("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S") or "%Y-%m-%d %H:%M:%S",
        log_dir=log_dir,
        log_file=_path_env("LOG_FILE", str(log_dir / "app.log")),
        rotate_max_bytes=_int_env("LOG_ROTATE_MAX_BYTES", 5 * 1024 * 1024),
        rotate_backup_count=_int_env("LOG_ROTATE_BACKUP_COUNT", 5),
        console_enabled=_bool_env("LOG_TO_CONSOLE", True),
        file_enabled=_bool_env("LOG_TO_FILE", True),
    )


def _build_sqlite_config(project_root: Path) -> SQLiteConfig:
    database_path = _path_env("DATABASE_PATH", str(project_root / "database" / "app.db"))
    return SQLiteConfig(
        database_path=database_path,
        timeout_seconds=_float_env("SQLITE_TIMEOUT_SECONDS", 30.0),
        journal_mode=_env("SQLITE_JOURNAL_MODE", "WAL") or "WAL",
        foreign_keys_enabled=_bool_env("SQLITE_FOREIGN_KEYS", True),
        busy_timeout_ms=_int_env("SQLITE_BUSY_TIMEOUT_MS", 5000),
        backup_enabled=_bool_env("SQLITE_BACKUP_ENABLED", False),
        backup_dir=_path_env("SQLITE_BACKUP_DIR", str(project_root / "database" / "backups")),
    )


def _build_groq_config() -> GroqConfig:
    return GroqConfig(
        api_key=_required_env("GROQ_API_KEY"),
        model=_env("GROQ_MODEL", "whisper-large-v3") or "whisper-large-v3",
        base_url=_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        or "https://api.groq.com/openai/v1",
        timeout_seconds=_float_env("GROQ_TIMEOUT_SECONDS", 60.0),
        max_retries=_int_env("GROQ_MAX_RETRIES", 3),
        temperature=_float_env("GROQ_TEMPERATURE", 0.0),
        language=_env("GROQ_LANGUAGE", "es") or "es",
    )


def _build_telegram_config() -> TelegramConfig:
    return TelegramConfig(
        bot_token=_required_env("BOT_TOKEN"),
        allowed_user_ids=_csv_int_env("TELEGRAM_ALLOWED_USER_IDS"),
        polling_timeout_seconds=_int_env("TELEGRAM_POLLING_TIMEOUT_SECONDS", 20),
        webhook_enabled=_bool_env("TELEGRAM_WEBHOOK_ENABLED", False),
        webhook_path=_env("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook") or "/telegram/webhook",
        webhook_secret_token=_env("TELEGRAM_WEBHOOK_SECRET_TOKEN", "") or "",
        max_message_length=_int_env("TELEGRAM_MAX_MESSAGE_LENGTH", 4096),
    )


def _build_cleanup_config() -> CleanupConfig:
    return CleanupConfig(
        enabled=_bool_env("CLEANUP_ENABLED", True),
        interval_seconds=_int_env("CLEANUP_INTERVAL_SECONDS", 3600),
        max_audio_age_hours=_int_env("CLEANUP_MAX_AUDIO_AGE_HOURS", 24),
        max_log_age_days=_int_env("CLEANUP_MAX_LOG_AGE_DAYS", 7),
        max_temp_age_hours=_int_env("CLEANUP_MAX_TEMP_AGE_HOURS", 12),
        dry_run=_bool_env("CLEANUP_DRY_RUN", False),
    )


def load_config() -> AppConfig:
    """Carga, valida y construye la configuracion completa de la aplicacion."""

    _load_environment()

    project_root = _project_root()
    app_name = _env("APP_NAME", "automatizador-notas-voz") or "automatizador-notas-voz"
    app_env = _env("APP_ENV", "development") or "development"
    debug = _bool_env("DEBUG", app_env.lower() != "production")

    return AppConfig(
        app_name=app_name,
        app_env=app_env,
        debug=debug,
        project_root=project_root,
        docker=_build_docker_config(project_root),
        logging=_build_logging_config(project_root),
        sqlite=_build_sqlite_config(project_root),
        groq=_build_groq_config(),
        telegram=_build_telegram_config(),
        cleanup=_build_cleanup_config(),
    )


def configure_logging(config: LoggingConfig) -> None:
    """Aplica la configuracion de logging al runtime de Python."""

    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.log_file.parent.mkdir(parents=True, exist_ok=True)

    handlers: dict[str, Any] = {}

    if config.console_enabled:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "level": config.level,
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        }

    if config.file_enabled:
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": config.level,
            "formatter": "standard",
            "filename": str(config.log_file),
            "maxBytes": config.rotate_max_bytes,
            "backupCount": config.rotate_backup_count,
            "encoding": "utf-8",
        }

    if not handlers:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "level": config.level,
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        }

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": config.format,
                    "datefmt": config.date_format,
                }
            },
            "handlers": handlers,
            "root": {
                "level": config.level,
                "handlers": list(handlers.keys()) or ["console"],
            },
        }
    )


def get_logger(name: str | None = None) -> logging.Logger:
    """Devuelve un logger listo para usar una vez aplicada la configuracion."""

    return logging.getLogger(name)


def ensure_directories(config: AppConfig) -> None:
    """Crea las carpetas esperadas por la configuracion antes de ejecutar la app."""

    config.docker.database_dir.mkdir(parents=True, exist_ok=True)
    config.docker.logs_dir.mkdir(parents=True, exist_ok=True)
    config.docker.audios_dir.mkdir(parents=True, exist_ok=True)
    config.sqlite.database_path.parent.mkdir(parents=True, exist_ok=True)
    config.sqlite.backup_dir.mkdir(parents=True, exist_ok=True)


def build_runtime_config() -> AppConfig:
    """Conveniencia para cargar, validar y dejar lista la configuracion de ejecucion."""

    config = load_config()
    ensure_directories(config)
    return config
