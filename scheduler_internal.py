"""Scheduler interno asíncrono del proyecto.

Este módulo se limita a ejecutar el servicio de limpieza de forma periódica
sin bloquear el bot y con soporte para asyncio.

No contiene lógica de Telegram ni reglas de negocio.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Coroutine, Protocol

from cleanup_service import CleanupResult, CleanupService


class CleanupRunner(Protocol):
    """Contrato asíncrono para ejecutar la limpieza desde el scheduler."""

    async def __call__(self) -> CleanupResult:
        """Ejecuta una limpieza completa y devuelve su resultado."""


@dataclass(frozen=True)
class SchedulerStatistics:
    """Resumen de una ejecución del scheduler."""

    started_at: datetime
    finished_at: datetime
    runs: int
    last_result: CleanupResult | None

    @property
    def duration_seconds(self) -> float:
        """Devuelve la duración total en segundos."""

        return (self.finished_at - self.started_at).total_seconds()


class InternalScheduler:
    """Scheduler asíncrono que ejecuta la limpieza de forma periódica."""

    def __init__(
        self,
        cleanup_service: CleanupService,
        interval_seconds: int = 24 * 60 * 60,
        logger: logging.Logger | None = None,
    ) -> None:
        """Inicializa el scheduler con el servicio de limpieza y su intervalo.

        Args:
            cleanup_service: servicio encargado de eliminar notas antiguas y audios.
            interval_seconds: intervalo entre ejecuciones, por defecto 24 horas.
            logger: logger opcional; si no se pasa, se usa el del módulo.
        """

        self._cleanup_service = cleanup_service
        self._interval_seconds = interval_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[SchedulerStatistics] | None = None

    @property
    def interval_seconds(self) -> int:
        """Devuelve el intervalo configurado del scheduler."""

        return self._interval_seconds

    @property
    def is_running(self) -> bool:
        """Indica si el scheduler tiene una tarea activa."""

        return self._task is not None and not self._task.done()

    async def start(self) -> asyncio.Task[SchedulerStatistics]:
        """Arranca el scheduler en una tarea asíncrona sin bloquear el bot.

        Returns:
            La tarea creada para poder supervisarla o esperar su finalización.
        """

        if self.is_running:
            self._logger.info("El scheduler ya estaba en ejecución")
            return self._task  # type: ignore[return-value]

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_forever(), name="internal-cleanup-scheduler")
        self._logger.info("Scheduler interno iniciado: intervalo=%s segundos", self._interval_seconds)
        return self._task

    async def stop(self) -> None:
        """Detiene el scheduler de forma limpia."""

        self._stop_event.set()
        if self._task is None:
            self._logger.info("El scheduler no tenía tarea activa")
            return

        if not self._task.done():
            self._logger.info("Esperando la finalización del scheduler interno")
            await self._task

        self._task = None
        self._logger.info("Scheduler interno detenido")

    async def run_once(self) -> CleanupResult:
        """Ejecuta una limpieza puntual sin entrar en modo periódico."""

        self._logger.info("Scheduler interno: ejecución puntual de limpieza")
        return await asyncio.to_thread(self._cleanup_service.run_once)

    async def _run_forever(self) -> SchedulerStatistics:
        """Ejecuta la limpieza en bucle hasta recibir la señal de parada."""

        started_at = datetime.now(timezone.utc)
        runs = 0
        last_result: CleanupResult | None = None

        self._logger.info("Scheduler interno entrando en bucle periódico")

        try:
            while not self._stop_event.is_set():
                cycle_started_at = datetime.now(timezone.utc)
                self._logger.info(
                    "Scheduler interno ejecutando cleanup_service: ciclo=%s, hora=%s",
                    runs + 1,
                    cycle_started_at.isoformat(),
                )

                try:
                    last_result = await asyncio.to_thread(self._cleanup_service.run_once)
                    runs += 1

                    self._logger.info(
                        "Scheduler interno completó cleanup_service: ciclo=%s, notas_eliminadas=%s, audios_eliminados=%s",
                        runs,
                        last_result.statistics.deleted_notes,
                        last_result.statistics.deleted_audio_files,
                    )
                except Exception as exc:  # pragma: no cover - defensa de ejecución continua.
                    self._logger.exception("Error en cleanup_service dentro del scheduler: %s", exc)

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            self._logger.info("Scheduler interno cancelado")
            raise
        finally:
            finished_at = datetime.now(timezone.utc)
            statistics = SchedulerStatistics(
                started_at=started_at,
                finished_at=finished_at,
                runs=runs,
                last_result=last_result,
            )
            self._logger.info(
                "Scheduler interno finalizado: runs=%s, duration=%.2fs",
                statistics.runs,
                statistics.duration_seconds,
            )

        return statistics


def create_internal_scheduler(
    cleanup_service: CleanupService,
    interval_seconds: int = 24 * 60 * 60,
    logger: logging.Logger | None = None,
) -> InternalScheduler:
    """Factory de conveniencia para crear el scheduler interno."""

    return InternalScheduler(
        cleanup_service=cleanup_service,
        interval_seconds=interval_seconds,
        logger=logger,
    )


__all__ = [
    "CleanupRunner",
    "InternalScheduler",
    "SchedulerStatistics",
    "create_internal_scheduler",
]
