"""Punto de entrada de la aplicación.

Este módulo compone configuración, logging, repositorio, servicios,
comandos de Telegram, handler de voz y scheduler interno.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from cleanup_service import create_cleanup_service
from config import build_runtime_config
from database import SQLiteDatabase, SQLiteNoteRepository
from logger import get_logger, setup_logging
from scheduler_internal import create_internal_scheduler
from speech_service import create_speech_service
from telegram_bot import TelegramBotCallbacks, create_telegram_bot
from telegram_commands import create_telegram_commands
from voice_note_handler import create_voice_note_handler
from telegram import Update


async def run() -> None:
    """Arranca la aplicación y mantiene vivos el bot y el scheduler."""

    runtime_config = build_runtime_config()
    setup_logging(runtime_config)
    app_logger = get_logger("automatizador")

    database = SQLiteDatabase(runtime_config.sqlite.database_path)
    note_repository = SQLiteNoteRepository(database)

    speech_service = create_speech_service(
        api_key=runtime_config.groq.api_key,
        model=runtime_config.groq.model,
        base_url=runtime_config.groq.base_url,
        timeout_seconds=runtime_config.groq.timeout_seconds,
        max_retries=runtime_config.groq.max_retries,
        language=runtime_config.groq.language,
        logger=app_logger.getChild("speech"),
    )

    commands = create_telegram_commands(
        note_repository=note_repository,
        logger=app_logger.getChild("commands"),
    )

    voice_handler = create_voice_note_handler(
        speech_service=speech_service,
        note_repository=note_repository,
        logger=app_logger.getChild("voice_handler"),
    )

    cleanup_service = create_cleanup_service(
        repository=note_repository,
        logger=app_logger.getChild("cleanup"),
        max_age_days=7,
    )

    scheduler = create_internal_scheduler(
        cleanup_service=cleanup_service,
        interval_seconds=24 * 60 * 60,
        logger=app_logger.getChild("scheduler"),
    )

    telegram_bot = create_telegram_bot(
        config=runtime_config.telegram,
        callbacks=TelegramBotCallbacks(
            on_start=commands.start,
            on_help=commands.help,
            on_text=None,
            on_voice=voice_handler,
        ),
        logger=app_logger.getChild("telegram"),
    )

    application = telegram_bot.build()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, stop_event.set)

    await application.initialize()
    await application.start()
    post_init = getattr(application, "post_init", None)
    if callable(post_init):
        await post_init(application)
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

    scheduler_task = await scheduler.start()
    app_logger.info("Aplicación iniciada correctamente")

    try:
        await stop_event.wait()
    finally:
        app_logger.info("Cerrando aplicación")
        await scheduler.stop()
        if scheduler_task is not None and not scheduler_task.done():
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task

        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    """Wrapper síncrono para ejecutar la aplicación desde Docker o consola."""

    asyncio.run(run())


if __name__ == "__main__":
    main()
