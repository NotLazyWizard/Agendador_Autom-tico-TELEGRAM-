"""Sistema central de logging del proyecto.

Este módulo proporciona:
- configuración de logging con rotación automática diaria
- nivel de logging configurable
- logs separados por fecha
- registro de errores
- registro de tiempos
- registro de consultas
- registro de llamadas a Groq
- registro de eventos de Telegram

No contiene lógica de negocio.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, TypeVar

from config import AppConfig, LoggingConfig, load_config


T = TypeVar("T")


class LoggerError(RuntimeError):
    """Error base para fallos del sistema de logging."""


@dataclass(frozen=True)
class LogEvent:
    """Representa un evento estructurado para logging semántico."""

    category: str
    action: str
    message: str
    duration_seconds: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class LoggerSettings:
    """Configuración concreta del sistema de logging."""

    level: str
    log_dir: Path
    log_file: Path
    date_format: str
    message_format: str
    backup_count: int
    console_enabled: bool
    file_enabled: bool
    daily_rotation: bool
    utc: bool


def _coerce_logging_settings(config: AppConfig | LoggingConfig | None = None) -> LoggerSettings:
    """Normaliza la configuración de logging desde AppConfig o LoggingConfig."""

    if config is None:
        app_config = load_config()
        logging_config = app_config.logging
    elif isinstance(config, AppConfig):
        logging_config = config.logging
    else:
        logging_config = config

    return LoggerSettings(
        level=str(logging_config.level).upper(),
        log_dir=logging_config.log_dir,
        log_file=logging_config.log_file,
        date_format=logging_config.date_format,
        message_format=logging_config.format,
        backup_count=logging_config.rotate_backup_count,
        console_enabled=logging_config.console_enabled,
        file_enabled=logging_config.file_enabled,
        daily_rotation=True,
        utc=True,
    )


def setup_logging(config: AppConfig | LoggingConfig | None = None) -> logging.Logger:
    """Configura el sistema global de logging.

    Crea salidas a consola y archivo diario con rotación automática.

    Args:
        config: configuración del proyecto o de logging.

    Returns:
        El logger raíz ya configurado.
    """

    settings = _coerce_logging_settings(config)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(fmt=settings.message_format, datefmt=settings.date_format)

    handlers: list[logging.Handler] = []

    if settings.console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(settings.level)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    if settings.file_enabled:
        file_handler = TimedRotatingFileHandler(
            filename=str(settings.log_file),
            when="midnight",
            interval=1,
            backupCount=settings.backup_count,
            encoding="utf-8",
            utc=settings.utc,
        )
        file_handler.setLevel(settings.level)
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"
        handlers.append(file_handler)

    if not handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(settings.level)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    for handler in handlers:
        root_logger.addHandler(handler)

    root_logger.info(
        "Logging configurado: level=%s, file=%s, daily_rotation=%s",
        settings.level,
        settings.log_file,
        settings.daily_rotation,
    )
    return root_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Devuelve un logger nominal para el módulo o componente solicitado."""

    return logging.getLogger(name)


def log_error(logger: logging.Logger, message: str, exc: BaseException | None = None, **metadata: Any) -> None:
    """Registra un error con contexto estructurado."""

    payload = {key: value for key, value in metadata.items() if value is not None}
    if exc is not None:
        logger.error(
            "%s | metadata=%s",
            message,
            payload,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return
    logger.error("%s | metadata=%s", message, payload)


def log_query(
    logger: logging.Logger,
    query_name: str,
    duration_seconds: float | None = None,
    rows_affected: int | None = None,
    success: bool = True,
    **metadata: Any,
) -> None:
    """Registra una consulta o acceso a datos sin incrustar SQL en el logger."""

    payload = {key: value for key, value in metadata.items() if value is not None}
    logger.info(
        "Consulta %s | success=%s | duration=%.4fs | rows=%s | metadata=%s",
        query_name,
        success,
        duration_seconds or 0.0,
        rows_affected,
        payload,
    )


def log_groq_call(
    logger: logging.Logger,
    operation: str,
    duration_seconds: float | None = None,
    model: str | None = None,
    success: bool = True,
    **metadata: Any,
) -> None:
    """Registra una llamada a Groq con tiempos y metadatos útiles."""

    payload = {key: value for key, value in metadata.items() if value is not None}
    logger.info(
        "Groq %s | success=%s | model=%s | duration=%.4fs | metadata=%s",
        operation,
        success,
        model,
        duration_seconds or 0.0,
        payload,
    )


def log_telegram_event(
    logger: logging.Logger,
    event_name: str,
    duration_seconds: float | None = None,
    chat_id: int | str | None = None,
    user_id: int | str | None = None,
    success: bool = True,
    **metadata: Any,
) -> None:
    """Registra un evento de Telegram sin acoplar la lógica del bot al logger."""

    payload = {key: value for key, value in metadata.items() if value is not None}
    logger.info(
        "Telegram %s | success=%s | chat_id=%s | user_id=%s | duration=%.4fs | metadata=%s",
        event_name,
        success,
        chat_id,
        user_id,
        duration_seconds or 0.0,
        payload,
    )


@contextmanager
def log_duration(logger: logging.Logger, operation: str, **metadata: Any) -> Iterator[None]:
    """Mide y registra la duración de una operación dada."""

    started_at = datetime.now(UTC)
    logger.debug("Inicio de operación %s | metadata=%s", operation, metadata)
    try:
        yield
    except Exception as exc:
        finished_at = datetime.now(UTC)
        duration = (finished_at - started_at).total_seconds()
        log_error(logger, f"Fallo en operación {operation}", exc, duration_seconds=duration, **metadata)
        raise
    finally:
        finished_at = datetime.now(UTC)
        duration = (finished_at - started_at).total_seconds()
        logger.info("Operación %s finalizada | duration=%.4fs | metadata=%s", operation, duration, metadata)


def timed(logger: logging.Logger, operation: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorador para registrar la duración de funciones síncronas."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            started_at = datetime.now(UTC)
            logger.debug("Inicio %s", operation)
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                duration = (datetime.now(UTC) - started_at).total_seconds()
                log_error(logger, f"Error en {operation}", exc, duration_seconds=duration)
                raise
            finally:
                duration = (datetime.now(UTC) - started_at).total_seconds()
                logger.info("%s completado | duration=%.4fs", operation, duration)

        return wrapper

    return decorator


async def timed_async(logger: logging.Logger, operation: str, coro: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    """Ejecuta y registra la duración de una coroutine o llamada asíncrona."""

    started_at = datetime.now(UTC)
    logger.debug("Inicio %s", operation)
    try:
        return await coro(*args, **kwargs)
    except Exception as exc:
        duration = (datetime.now(UTC) - started_at).total_seconds()
        log_error(logger, f"Error en {operation}", exc, duration_seconds=duration)
        raise
    finally:
        duration = (datetime.now(UTC) - started_at).total_seconds()
        logger.info("%s completado | duration=%.4fs", operation, duration)


def build_logger(name: str | None = None, config: AppConfig | LoggingConfig | None = None) -> logging.Logger:
    """Construye y devuelve un logger listo para usar.

    Si el logging global aún no fue configurado, lo configura automáticamente.
    """

    setup_logging(config or load_config())
    return get_logger(name)


__all__ = [
    "LogEvent",
    "LoggerError",
    "LoggerSettings",
    "build_logger",
    "get_logger",
    "log_duration",
    "log_error",
    "log_groq_call",
    "log_query",
    "log_telegram_event",
    "setup_logging",
    "timed",
    "timed_async",
]
