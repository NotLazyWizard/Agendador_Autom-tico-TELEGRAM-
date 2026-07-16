"""Comandos de Telegram del proyecto.

Este módulo se limita a:
- /start
- /help
- /hoy
- /ayer
- /semana
- /mes
- /buscar
- /ultimas
- /estadisticas

Cada comando delega el trabajo al repositorio o a servicios inyectados.
No contiene SQL, no conoce Whisper y no usa LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Protocol

from database import Note, NoteRepository, NoteStatistics

try:  # pragma: no cover - dependencia opcional en tiempo de edición.
    from telegram import Update
    from telegram.ext import CallbackContext
except ImportError:  # pragma: no cover - se evalúa solo si la dependencia no está instalada.
    Update = Any  # type: ignore[assignment]
    CallbackContext = Any  # type: ignore[assignment]


class TelegramCommandError(RuntimeError):
    """Error base para fallos en los comandos de Telegram."""


class TelegramCommandCallback(Protocol):
    """Contrato del callback compatible con el adaptador de Telegram."""

    def __call__(self, update: Update, context: CallbackContext) -> Awaitable[str | None] | str | None:
        """Devuelve el texto que el bot debe responder o None si no corresponde."""


@dataclass(frozen=True)
class TelegramCommandConfig:
    """Configuración de presentación para los comandos de Telegram."""

    recent_notes_limit: int = 10
    search_limit: int = 10
    date_format: str = "%d/%m/%Y"
    datetime_format: str = "%d/%m/%Y %H:%M"
    max_preview_length: int = 120


class TelegramCommands:
    """Implementa los callbacks de comandos delegando en el repositorio."""

    def __init__(
        self,
        note_repository: NoteRepository,
        config: TelegramCommandConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Inicializa los comandos con el repositorio y configuración de salida."""

        self._note_repository = note_repository
        self._config = config or TelegramCommandConfig()
        self._logger = logger or logging.getLogger(__name__)

    async def start(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /start."""

        self._logger.info("Comando /start recibido")
        return (
            "Hola. Envíame una nota de voz para guardarla.\n"
            "También puedes consultar /hoy, /ayer, /semana, /mes, /buscar, /ultimas y /estadisticas."
        )

    async def help(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /help."""

        self._logger.info("Comando /help recibido")
        return (
            "Comandos disponibles:\n"
            "/start - iniciar\n"
            "/help - ayuda\n"
            "/hoy - notas de hoy\n"
            "/ayer - notas de ayer\n"
            "/semana - notas de los últimos 7 días\n"
            "/mes - notas de los últimos 30 días\n"
            "/buscar <texto> - buscar notas por texto\n"
            "/ultimas - últimas notas\n"
            "/estadisticas - resumen de métricas"
        )

    async def hoy(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /hoy usando búsqueda por fecha del repositorio."""

        self._logger.info("Comando /hoy recibido")
        today = datetime.now(UTC).date()
        notes = await self._load_notes_by_date(start_date=today, end_date=today)
        return self._format_notes_response("Notas de hoy", notes)

    async def ayer(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /ayer usando búsqueda por fecha del repositorio."""

        self._logger.info("Comando /ayer recibido")
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        notes = await self._load_notes_by_date(start_date=yesterday, end_date=yesterday)
        return self._format_notes_response("Notas de ayer", notes)

    async def semana(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /semana usando búsqueda por fecha del repositorio."""

        self._logger.info("Comando /semana recibido")
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=6)
        notes = await self._load_notes_by_date(start_date=start_date, end_date=end_date)
        return self._format_notes_response("Notas de la última semana", notes)

    async def mes(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /mes usando búsqueda por fecha del repositorio."""

        self._logger.info("Comando /mes recibido")
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=29)
        notes = await self._load_notes_by_date(start_date=start_date, end_date=end_date)
        return self._format_notes_response("Notas del último mes", notes)

    async def buscar(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /buscar usando búsqueda textual del repositorio."""

        query = self._extract_search_query(update, context)
        self._logger.info("Comando /buscar recibido: query=%s", query)

        if not query:
            return "Debes escribir un texto para buscar. Ejemplo: /buscar reunión"

        notes = await self._run_blocking(self._note_repository.search_by_text, query, self._config.search_limit)
        return self._format_notes_response(f"Resultados para: {query}", notes)

    async def ultimas(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /ultimas con las notas más recientes."""

        self._logger.info("Comando /ultimas recibido")
        notes = await self._run_blocking(self._note_repository.latest_notes, self._config.recent_notes_limit)
        return self._format_notes_response("Últimas notas", notes)

    async def estadisticas(self, update: Update, context: CallbackContext) -> str:
        """Responde al comando /estadisticas con métricas agregadas del repositorio."""

        self._logger.info("Comando /estadisticas recibido")
        statistics = await self._run_blocking(self._note_repository.statistics)
        return self._format_statistics(statistics)

    async def _load_notes_by_date(self, start_date: date, end_date: date) -> list[Note]:
        """Carga notas por rango de fechas sin exponer SQL en la capa de comandos."""

        return await self._run_blocking(self._note_repository.search_by_date, start_date, end_date, self._config.search_limit)

    async def _run_blocking(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Ejecuta una llamada bloqueante fuera del event loop."""

        import asyncio

        return await asyncio.to_thread(func, *args, **kwargs)

    def _extract_search_query(self, update: Update, context: CallbackContext) -> str:
        """Extrae el texto de búsqueda desde argumentos del comando o del mensaje."""

        args = getattr(context, "args", None)
        if isinstance(args, list) and args:
            return " ".join(str(item).strip() for item in args if str(item).strip()).strip()

        message = getattr(update, "message", None)
        text = getattr(message, "text", None)
        if isinstance(text, str):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                return parts[1].strip()
        return ""

    def _format_notes_response(self, title: str, notes: list[Note]) -> str:
        """Formatea una lista de notas para su envío al usuario."""

        if not notes:
            return f"{title}: no hay resultados."

        lines = [f"{title} ({len(notes)}):"]
        for note in notes:
            lines.append(self._format_note_item(note))
        return "\n".join(lines)

    def _format_note_item(self, note: Note) -> str:
        """Formatea una nota individual para una respuesta legible."""

        created_at = note.created_at.astimezone(UTC).strftime(self._config.datetime_format)
        preview = self._build_preview(note.content)
        return f"- [{created_at}] {note.title}: {preview}"

    def _build_preview(self, content: str) -> str:
        """Recorta el contenido de una nota para evitar respuestas demasiado largas."""

        normalized = " ".join(content.split())
        if len(normalized) <= self._config.max_preview_length:
            return normalized
        return normalized[: self._config.max_preview_length].rstrip() + "..."

    def _format_statistics(self, statistics: NoteStatistics) -> str:
        """Formatea las estadísticas devueltas por el repositorio."""

        first_note_at = (
            statistics.first_note_at.astimezone(UTC).strftime(self._config.datetime_format)
            if statistics.first_note_at is not None
            else "-"
        )
        last_note_at = (
            statistics.last_note_at.astimezone(UTC).strftime(self._config.datetime_format)
            if statistics.last_note_at is not None
            else "-"
        )
        return (
            "Estadísticas:\n"
            f"- Total notas: {statistics.total_notes}\n"
            f"- Notas hoy: {statistics.notes_today}\n"
            f"- Notas últimos 7 días: {statistics.notes_last_7_days}\n"
            f"- Notas últimos 30 días: {statistics.notes_last_30_days}\n"
            f"- Promedio de contenido: {statistics.average_content_length:.2f} caracteres\n"
            f"- Primera nota: {first_note_at}\n"
            f"- Última nota: {last_note_at}"
        )


def create_telegram_commands(
    note_repository: NoteRepository,
    config: TelegramCommandConfig | None = None,
    logger: logging.Logger | None = None,
) -> TelegramCommands:
    """Factory de conveniencia para crear los comandos de Telegram."""

    return TelegramCommands(note_repository=note_repository, config=config, logger=logger)


__all__ = [
    "TelegramCommandCallback",
    "TelegramCommandConfig",
    "TelegramCommandError",
    "TelegramCommands",
    "create_telegram_commands",
]
