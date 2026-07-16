"""Servicio de limpieza automática del proyecto.

Este módulo se encarga de:
- eliminar notas con más de 7 días de antigüedad
- eliminar el archivo de audio asociado cuando exista
- registrar logs del proceso
- devolver estadísticas del ciclo de limpieza
- ejecutarse manualmente o en modo scheduler

No contiene lógica de Telegram ni reglas de negocio de la interfaz.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Protocol

from database import Note, NoteRepository


class AudioPathProvider(Protocol):
    """Contrato para obtener la ruta del audio asociado a una nota."""

    def __call__(self, note: Note) -> str | Path | None:
        """Devuelve la ruta del audio asociado o None si no existe."""


class CleanupRepository(Protocol):
    """Contrato mínimo que necesita el servicio de limpieza."""

    def list_all(self, limit: int | None = None) -> list[Note]:
        """Devuelve todas las notas disponibles ordenadas por fecha descendente."""

    def delete(self, note_id: int) -> bool:
        """Elimina una nota por identificador."""


@dataclass(frozen=True)
class CleanupStatistics:
    """Resumen del resultado de una ejecución de limpieza."""

    started_at: datetime
    finished_at: datetime
    cutoff_at: datetime
    scanned_notes: int
    deleted_notes: int
    deleted_audio_files: int
    missing_audio_files: int
    audio_delete_errors: int
    repository_delete_errors: int

    @property
    def duration_seconds(self) -> float:
        """Devuelve la duración de la ejecución en segundos."""

        return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class CleanupResult:
    """Resultado completo de una ejecución de limpieza."""

    statistics: CleanupStatistics
    deleted_note_ids: tuple[int, ...]
    deleted_audio_paths: tuple[str, ...]
    failed_audio_paths: tuple[str, ...]
    errors: tuple[str, ...]


class CleanupService:
    """Servicio responsable de borrar notas antiguas y sus audios asociados."""

    def __init__(
        self,
        repository: CleanupRepository,
        audio_path_provider: AudioPathProvider | None = None,
        logger: logging.Logger | None = None,
        max_age_days: int = 7,
    ) -> None:
        """Inicializa el servicio de limpieza.

        Args:
            repository: repositorio de notas con operaciones de listado y borrado.
            audio_path_provider: función opcional para resolver la ruta del audio.
            logger: logger opcional; si no se pasa, se usa uno del módulo.
            max_age_days: antigüedad máxima permitida para conservar una nota.
        """

        self._repository = repository
        self._audio_path_provider = audio_path_provider
        self._logger = logger or logging.getLogger(__name__)
        self._max_age_days = max_age_days

    @property
    def max_age_days(self) -> int:
        """Devuelve la antigüedad máxima configurada para conservar notas."""

        return self._max_age_days

    def run_once(self) -> CleanupResult:
        """Ejecuta un ciclo único de limpieza y devuelve sus estadísticas."""

        started_at = datetime.now(UTC)
        cutoff_at = started_at - timedelta(days=self._max_age_days)

        self._logger.info(
            "Iniciando limpieza automática: cutoff=%s, max_age_days=%s",
            cutoff_at.isoformat(),
            self._max_age_days,
        )

        notes = self._repository.list_all()
        scanned_notes = len(notes)
        deleted_note_ids: list[int] = []
        deleted_audio_paths: list[str] = []
        failed_audio_paths: list[str] = []
        errors: list[str] = []
        deleted_audio_files = 0
        missing_audio_files = 0
        audio_delete_errors = 0
        repository_delete_errors = 0

        for note in self._iter_expired_notes(notes, cutoff_at):
            audio_path = self._resolve_audio_path(note)
            if audio_path is not None:
                try:
                    removed = self._delete_audio_file(audio_path)
                    if removed:
                        deleted_audio_files += 1
                        deleted_audio_paths.append(str(audio_path))
                        self._logger.info("Audio eliminado para nota %s: %s", note.id, audio_path)
                    else:
                        missing_audio_files += 1
                        self._logger.warning("No se encontró audio para nota %s: %s", note.id, audio_path)
                except Exception as exc:  # pragma: no cover - se registra y se continúa.
                    audio_delete_errors += 1
                    failed_audio_paths.append(str(audio_path))
                    error_message = f"Error eliminando audio de la nota {note.id}: {exc}"
                    errors.append(error_message)
                    self._logger.exception(error_message)
            else:
                missing_audio_files += 1
                self._logger.info("La nota %s no tiene audio asociado resoluble.", note.id)

            try:
                deleted = self._repository.delete(note.id)
                if deleted:
                    deleted_note_ids.append(note.id)
                    self._logger.info("Nota eliminada correctamente: id=%s", note.id)
                else:
                    error_message = f"La nota {note.id} no pudo eliminarse o ya no existía"
                    errors.append(error_message)
                    self._logger.warning(error_message)
            except Exception as exc:  # pragma: no cover - se registra y se continúa.
                repository_delete_errors += 1
                error_message = f"Error eliminando nota {note.id}: {exc}"
                errors.append(error_message)
                self._logger.exception(error_message)

        finished_at = datetime.now(UTC)
        statistics = CleanupStatistics(
            started_at=started_at,
            finished_at=finished_at,
            cutoff_at=cutoff_at,
            scanned_notes=scanned_notes,
            deleted_notes=len(deleted_note_ids),
            deleted_audio_files=deleted_audio_files,
            missing_audio_files=missing_audio_files,
            audio_delete_errors=audio_delete_errors,
            repository_delete_errors=repository_delete_errors,
        )

        self._logger.info(
            "Limpieza finalizada: deleted_notes=%s, deleted_audio_files=%s, duration=%.2fs",
            statistics.deleted_notes,
            statistics.deleted_audio_files,
            statistics.duration_seconds,
        )

        return CleanupResult(
            statistics=statistics,
            deleted_note_ids=tuple(deleted_note_ids),
            deleted_audio_paths=tuple(deleted_audio_paths),
            failed_audio_paths=tuple(failed_audio_paths),
            errors=tuple(errors),
        )

    def run_forever(
        self,
        interval_seconds: int,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Ejecuta el servicio en un bucle útil para scheduler o tareas de fondo.

        Args:
            interval_seconds: tiempo de espera entre ejecuciones.
            stop_event: evento opcional para detener el bucle de forma limpia.
        """

        event = stop_event or threading.Event()
        self._logger.info("Scheduler de limpieza iniciado: interval_seconds=%s", interval_seconds)

        while not event.is_set():
            self.run_once()
            event.wait(interval_seconds)

        self._logger.info("Scheduler de limpieza detenido.")

    def start_scheduler(self, interval_seconds: int) -> tuple[threading.Thread, threading.Event]:
        """Lanza la limpieza en un hilo daemon para integrarla con un scheduler simple.

        Returns:
            Una tupla con el hilo arrancado y el evento de parada.
        """

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.run_forever,
            kwargs={"interval_seconds": interval_seconds, "stop_event": stop_event},
            daemon=True,
            name="cleanup-scheduler",
        )
        thread.start()
        return thread, stop_event

    def _iter_expired_notes(self, notes: Iterable[Note], cutoff_at: datetime) -> Iterable[Note]:
        """Filtra las notas que superan la antigüedad permitida."""

        for note in notes:
            note_created_at = note.created_at
            if note_created_at.tzinfo is None:
                note_created_at = note_created_at.replace(tzinfo=UTC)
            else:
                note_created_at = note_created_at.astimezone(UTC)

            if note_created_at < cutoff_at:
                yield note

    def _resolve_audio_path(self, note: Note) -> Path | None:
        """Resuelve la ruta del audio asociado a una nota, si existe."""

        if self._audio_path_provider is not None:
            resolved = self._audio_path_provider(note)
            if resolved is None:
                return None
            return Path(resolved)

        candidate = getattr(note, "audio_path", None)
        if candidate:
            return Path(candidate)

        source_message_id = getattr(note, "source_message_id", None)
        if source_message_id:
            audios_dir = Path("audios")
            for extension in (".ogg", ".mp3", ".wav", ".m4a", ".opus"):
                candidate_path = audios_dir / f"{source_message_id}{extension}"
                if candidate_path.exists():
                    return candidate_path
        return None

    def _delete_audio_file(self, audio_path: Path) -> bool:
        """Elimina el archivo de audio si existe y devuelve si fue borrado."""

        if not audio_path.exists():
            return False

        audio_path.unlink()
        return True


def create_cleanup_service(
    repository: NoteRepository,
    audio_path_provider: AudioPathProvider | None = None,
    logger: logging.Logger | None = None,
    max_age_days: int = 7,
) -> CleanupService:
    """Factory de conveniencia para crear el servicio de limpieza."""

    return CleanupService(
        repository=repository,
        audio_path_provider=audio_path_provider,
        logger=logger,
        max_age_days=max_age_days,
    )


__all__ = [
    "AudioPathProvider",
    "CleanupResult",
    "CleanupService",
    "CleanupStatistics",
    "create_cleanup_service",
]
