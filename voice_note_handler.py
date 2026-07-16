"""Handler de Telegram para procesar notas de voz.

Este módulo se limita a:
- recibir una nota de voz ya descargada o materializada como archivo local
- guardar una copia temporal
- transcribir mediante SpeechService
- guardar la nota mediante NoteRepository
- eliminar el audio temporal y, si corresponde, el archivo fuente
- devolver el mensaje de éxito al bot

No utiliza LLM y no contiene reglas de negocio fuera del flujo técnico de la nota de voz.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Protocol

from database import NoteCreate, NoteRepository
from speech_service import SpeechService

try:  # pragma: no cover - dependencia opcional durante edición.
    from telegram import Update
    from telegram.ext import CallbackContext
except ImportError:  # pragma: no cover - se evalúa solo si la dependencia no está instalada.
    Update = Any  # type: ignore[assignment]
    CallbackContext = Any  # type: ignore[assignment]


class VoiceNoteHandlerError(RuntimeError):
    """Error base para fallos en el handler de notas de voz."""


class VoiceAudioError(VoiceNoteHandlerError):
    """Error lanzado cuando el archivo de audio de entrada no es válido."""


class VoicePersistenceError(VoiceNoteHandlerError):
    """Error lanzado cuando falla el guardado de la nota."""


class VoiceNoteCallback(Protocol):
    """Contrato del callback compatible con el adaptador de Telegram."""

    def __call__(self, update: Update, context: CallbackContext, audio_path: Path) -> Awaitable[str | None] | str | None:
        """Procesa una nota de voz y devuelve el texto de respuesta o None."""


@dataclass(frozen=True)
class VoiceNoteHandlerConfig:
    """Configuración del handler de notas de voz."""

    temp_dir: Path = Path(tempfile.gettempdir()) / "automatizador-notas-voz"
    cleanup_source_audio: bool = True
    delete_temporary_copy: bool = True
    title_max_length: int = 72
    default_source: str = "telegram"
    success_message: str = "Nota guardada correctamente."


class VoiceNoteHandler:
    """Handler asíncrono responsable de transcribir y guardar notas de voz."""

    def __init__(
        self,
        speech_service: SpeechService,
        note_repository: NoteRepository,
        config: VoiceNoteHandlerConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Inicializa el handler con sus dependencias explícitas."""

        self._speech_service = speech_service
        self._note_repository = note_repository
        self._config = config or VoiceNoteHandlerConfig()
        self._logger = logger or logging.getLogger(__name__)

    async def __call__(self, update: Update, context: CallbackContext, audio_path: Path) -> str:
        """Procesa una nota de voz y devuelve el texto de éxito.

        Args:
            update: actualización de Telegram asociada a la nota.
            context: contexto de la ejecución de Telegram.
            audio_path: ruta del audio descargado por el adaptador de Telegram.

        Returns:
            Mensaje de confirmación listo para enviar al usuario.

        Raises:
            VoiceAudioError: si el archivo no existe o no es transcribible.
            VoicePersistenceError: si falla la transcripción o el guardado.
        """

        source_path = Path(audio_path).expanduser().resolve()
        self._validate_audio(source_path)

        self._config.temp_dir.mkdir(parents=True, exist_ok=True)
        temp_copy = self._create_temp_copy(source_path)

        started_at = time.perf_counter()
        self._logger.info("Procesando nota de voz: source=%s, temp=%s", source_path, temp_copy)

        try:
            transcription = await asyncio.to_thread(self._speech_service.transcribe, temp_copy)
            transcription_elapsed = time.perf_counter() - started_at
            self._logger.info(
                "Transcripción completada: file=%s, elapsed=%.2fs",
                temp_copy,
                transcription_elapsed,
            )

            title = self._build_title(transcription)
            note_create = self._build_note_create(update, transcription, title)

            await asyncio.to_thread(self._note_repository.create, note_create)
            persistence_elapsed = time.perf_counter() - started_at
            self._logger.info(
                "Nota guardada correctamente: source=%s, elapsed=%.2fs",
                source_path,
                persistence_elapsed,
            )

            return self._config.success_message
        except Exception as exc:
            self._logger.exception("Error procesando nota de voz: %s", exc)
            raise VoicePersistenceError("No fue posible procesar la nota de voz") from exc
        finally:
            if self._config.delete_temporary_copy:
                self._cleanup_file(temp_copy, label="copia temporal")
            if self._config.cleanup_source_audio:
                self._cleanup_file(source_path, label="audio origen")

    def _validate_audio(self, audio_path: Path) -> None:
        """Valida que el archivo de entrada exista y tenga extensión .ogg."""

        if not audio_path.exists():
            raise VoiceAudioError(f"El archivo no existe: {audio_path}")

        if not audio_path.is_file():
            raise VoiceAudioError(f"La ruta no corresponde a un archivo: {audio_path}")

        if audio_path.suffix.lower() != ".ogg":
            raise VoiceAudioError(f"El archivo debe tener extensión .ogg: {audio_path.name}")

        if audio_path.stat().st_size <= 0:
            raise VoiceAudioError(f"El archivo está vacío: {audio_path}")

    def _create_temp_copy(self, source_path: Path) -> Path:
        """Crea una copia temporal del audio para trabajar sin tocar el archivo fuente."""

        temp_file = tempfile.NamedTemporaryFile(
            prefix="voice-note-",
            suffix=".ogg",
            dir=self._config.temp_dir,
            delete=False,
        )
        temp_file_path = Path(temp_file.name)
        temp_file.close()
        shutil.copy2(source_path, temp_file_path)
        return temp_file_path

    def _build_title(self, transcription: str) -> str:
        """Genera un título breve a partir de la transcripción."""

        normalized = " ".join(transcription.split())
        if not normalized:
            return "Nota de voz"

        separator_index = len(normalized)
        for separator in (".", "!", "?"):
            index = normalized.find(separator)
            if index != -1:
                separator_index = min(separator_index, index)

        candidate = normalized[:separator_index].strip() or normalized
        candidate = candidate[: self._config.title_max_length].rstrip(" ,;:-")
        return candidate or "Nota de voz"

    def _build_note_create(self, update: Update, transcription: str, title: str) -> NoteCreate:
        """Construye la entidad de entrada para persistir la nota."""

        source_message_id = self._extract_source_message_id(update)
        return NoteCreate(
            title=title,
            content=transcription.strip(),
            source=self._config.default_source,
            source_message_id=source_message_id,
        )

    def _extract_source_message_id(self, update: Update) -> str | None:
        """Extrae un identificador estable del mensaje origen cuando existe."""

        message = getattr(update, "message", None)
        if message is None:
            return None

        voice = getattr(message, "voice", None)
        if voice is not None:
            unique_id = getattr(voice, "file_unique_id", None)
            if unique_id:
                return str(unique_id)

        message_id = getattr(message, "message_id", None)
        if message_id is not None:
            return str(message_id)

        return None

    def _cleanup_file(self, file_path: Path, label: str) -> None:
        """Elimina un archivo si existe, registrando el resultado sin romper el flujo."""

        try:
            if file_path.exists():
                file_path.unlink()
                self._logger.info("Eliminado %s: %s", label, file_path)
        except Exception as exc:  # pragma: no cover - limpieza defensiva.
            self._logger.warning("No fue posible eliminar %s %s: %s", label, file_path, exc)


def create_voice_note_handler(
    speech_service: SpeechService,
    note_repository: NoteRepository,
    config: VoiceNoteHandlerConfig | None = None,
    logger: logging.Logger | None = None,
) -> VoiceNoteHandler:
    """Factory de conveniencia para crear el handler de notas de voz."""

    return VoiceNoteHandler(
        speech_service=speech_service,
        note_repository=note_repository,
        config=config,
        logger=logger,
    )


__all__ = [
    "VoiceAudioError",
    "VoiceNoteCallback",
    "VoiceNoteHandler",
    "VoiceNoteHandlerConfig",
    "VoiceNoteHandlerError",
    "VoicePersistenceError",
    "create_voice_note_handler",
]
