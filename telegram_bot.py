"""Adaptador de Telegram para el proyecto.

Este módulo se limita a:
- conectarse a Telegram
- configurar handlers
- registrar comandos
- manejar errores

No contiene lógica de negocio. Toda la lógica debe delegarse a servicios
o callbacks inyectados desde la capa de aplicación.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from config import TelegramConfig

try:  # pragma: no cover - dependencia opcional en tiempo de edición.
    from telegram import Update
    from telegram.constants import ParseMode
    from telegram.ext import (
        Application,
        ApplicationBuilder,
        CallbackContext,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except ImportError as exc:  # pragma: no cover - se evalúa solo si la dependencia falta.
    Update = Any  # type: ignore[assignment]
    ParseMode = Any  # type: ignore[assignment]
    Application = Any  # type: ignore[assignment]
    ApplicationBuilder = Any  # type: ignore[assignment]
    CallbackContext = Any  # type: ignore[assignment]
    CommandHandler = Any  # type: ignore[assignment]
    ContextTypes = Any  # type: ignore[assignment]
    MessageHandler = Any  # type: ignore[assignment]
    filters = Any  # type: ignore[assignment]
    _TELEGRAM_IMPORT_ERROR = exc
else:
    _TELEGRAM_IMPORT_ERROR = None


class TelegramBotError(RuntimeError):
    """Error base para fallos del adaptador de Telegram."""


class TelegramDependencyError(TelegramBotError):
    """Error lanzado cuando la librería de Telegram no está instalada."""


class TelegramFileProvider(Protocol):
    """Contrato para obtener el archivo asociado a un mensaje de voz."""

    def __call__(self, update: Update, context: CallbackContext) -> str | Path | None:
        """Devuelve la ruta local del archivo de audio o None si no aplica."""


class TelegramTextCallback(Protocol):
    """Contrato para procesar textos o comandos delegando la lógica de negocio."""

    def __call__(self, update: Update, context: CallbackContext) -> Awaitable[str | None] | str | None:
        """Devuelve el texto que el bot debe responder o None si no corresponde."""


class TelegramVoiceCallback(Protocol):
    """Contrato para procesar mensajes de voz delegando la lógica de negocio."""

    def __call__(self, update: Update, context: CallbackContext, audio_path: Path) -> Awaitable[str | None] | str | None:
        """Devuelve el texto que el bot debe responder o None si no corresponde."""


class TelegramCommandCallback(Protocol):
    """Contrato para procesar comandos explícitos."""

    def __call__(self, update: Update, context: CallbackContext) -> Awaitable[str | None] | str | None:
        """Devuelve el texto que el bot debe responder o None si no corresponde."""


@dataclass(frozen=True)
class TelegramBotCallbacks:
    """Conjunto de callbacks inyectables para delegar la lógica del bot."""

    on_start: TelegramCommandCallback | None = None
    on_help: TelegramCommandCallback | None = None
    on_text: TelegramTextCallback | None = None
    on_voice: TelegramVoiceCallback | None = None
    on_unknown_command: TelegramTextCallback | None = None
    on_error: Callable[[Update | None, CallbackContext | None, BaseException], None] | None = None


@dataclass(frozen=True)
class TelegramBotRoutes:
    """Define los comandos y filtros que el bot registrará."""

    start_commands: tuple[str, ...] = ("start",)
    help_commands: tuple[str, ...] = ("help",)
    voice_filters: Any = field(default=None)
    text_filters: Any = field(default=None)


class TelegramBot:
    """Adaptador de Telegram que solo enruta eventos hacia callbacks o servicios."""

    def __init__(
        self,
        config: TelegramConfig,
        callbacks: TelegramBotCallbacks,
        routes: TelegramBotRoutes | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Inicializa el bot con configuración y callbacks delegados.

        Args:
            config: configuración de Telegram cargada desde config.py.
            callbacks: funciones o servicios que contienen la lógica de negocio.
            routes: configuración opcional de comandos y filtros.
            logger: logger opcional; si no se pasa, se usa el del módulo.
        """

        self._config = config
        self._callbacks = callbacks
        self._routes = routes or TelegramBotRoutes()
        self._logger = logger or logging.getLogger(__name__)
        self._application: Application | None = None

    @property
    def application(self) -> Application:
        """Devuelve la aplicación de Telegram construida internamente."""

        if self._application is None:
            raise TelegramBotError("El bot aún no ha sido inicializado")
        return self._application

    def build(self) -> Application:
        """Crea la aplicación de Telegram y registra handlers, comandos y errores."""

        self._ensure_dependency()

        application = ApplicationBuilder().token(self._config.bot_token).build()
        self._register_handlers(application)
        self._register_error_handler(application)
        application.post_init = self._post_init
        self._application = application
        self._logger.info("Bot de Telegram construido correctamente")
        return application

    def run_polling(self) -> None:
        """Inicia el bot en modo polling.

        No contiene lógica de negocio; solo arranque y supervisión.
        """

        application = self._application or self.build()
        self._logger.info("Iniciando polling de Telegram")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    def _ensure_dependency(self) -> None:
        """Verifica que python-telegram-bot esté disponible."""

        if _TELEGRAM_IMPORT_ERROR is not None:
            raise TelegramDependencyError(
                "La dependencia 'python-telegram-bot' no está instalada"
            ) from _TELEGRAM_IMPORT_ERROR

    def _register_handlers(self, application: Application) -> None:
        """Registra los handlers de comandos, mensajes de texto y mensajes de voz."""

        for command in self._routes.start_commands:
            application.add_handler(CommandHandler(command, self._handle_start))

        for command in self._routes.help_commands:
            application.add_handler(CommandHandler(command, self._handle_help))

        if self._callbacks.on_voice is not None:
            voice_filter = self._routes.voice_filters or filters.VOICE
            application.add_handler(MessageHandler(voice_filter, self._handle_voice))

        if self._callbacks.on_text is not None:
            text_filter = self._routes.text_filters or (filters.TEXT & ~filters.COMMAND)
            application.add_handler(MessageHandler(text_filter, self._handle_text))

        if self._callbacks.on_unknown_command is not None:
            application.add_handler(MessageHandler(filters.COMMAND, self._handle_unknown_command))

        self._logger.info("Handlers de Telegram registrados")

    async def _post_init(self, application: Application) -> None:
        """Inicializa comandos visibles para Telegram una vez que la app está activa."""

        commands: list[tuple[str, str]] = []
        commands.extend((command, "Inicia la conversación") for command in self._routes.start_commands)
        commands.extend((command, "Muestra la ayuda disponible") for command in self._routes.help_commands)

        if commands:
            await application.bot.set_my_commands(commands)
            self._logger.info("Comandos de Telegram registrados: %s", ", ".join(name for name, _ in commands))

    def _register_error_handler(self, application: Application) -> None:
        """Registra el manejador centralizado de errores."""

        application.add_error_handler(self._handle_error)

    async def _handle_start(self, update: Update, context: CallbackContext) -> None:
        """Maneja el comando /start delegando la respuesta real a un callback."""

        await self._reply_from_callback(update, context, self._callbacks.on_start)

    async def _handle_help(self, update: Update, context: CallbackContext) -> None:
        """Maneja el comando /help delegando la respuesta real a un callback."""

        await self._reply_from_callback(update, context, self._callbacks.on_help)

    async def _handle_text(self, update: Update, context: CallbackContext) -> None:
        """Maneja mensajes de texto delegando el procesamiento a la capa de aplicación."""

        await self._reply_from_callback(update, context, self._callbacks.on_text)

    async def _handle_unknown_command(self, update: Update, context: CallbackContext) -> None:
        """Maneja comandos desconocidos delegando la respuesta si existe callback."""

        await self._reply_from_callback(update, context, self._callbacks.on_unknown_command)

    async def _handle_voice(self, update: Update, context: CallbackContext) -> None:
        """Maneja mensajes de voz resolviendo primero el archivo local y luego delegando."""

        if update.message is None or update.message.voice is None:
            return

        if self._callbacks.on_voice is None:
            return

        audio_path = await self._download_voice_file(update, context)
        if audio_path is None:
            self._logger.warning("No fue posible descargar el audio de voz")
            return

        response = await self._invoke_callback(self._callbacks.on_voice, update, context, audio_path)
        if response:
            await update.message.reply_text(response)

    async def _handle_error(self, update: object, context: CallbackContext) -> None:
        """Maneja errores no controlados sin introducir lógica de negocio."""

        error = getattr(context, "error", None)
        if isinstance(error, BaseException):
            self._logger.exception("Error no controlado en Telegram", exc_info=error)
            if self._callbacks.on_error is not None:
                self._callbacks.on_error(update if isinstance(update, Update) else None, context, error)

        if isinstance(update, Update) and update.effective_message is not None:
            await update.effective_message.reply_text(
                "Ocurrió un error inesperado. Intenta nuevamente más tarde."
            )

    async def _reply_from_callback(
        self,
        update: Update,
        context: CallbackContext,
        callback: TelegramCommandCallback | TelegramTextCallback | None,
    ) -> None:
        """Ejecuta un callback y responde solo si el callback devuelve texto."""

        if callback is None or update.effective_message is None:
            return

        response = await self._invoke_callback(callback, update, context)
        if response:
            await update.effective_message.reply_text(response)

    async def _download_voice_file(self, update: Update, context: CallbackContext) -> Path | None:
        """Descarga el audio de voz desde Telegram y devuelve una ruta local temporal."""

        if update.message is None or update.message.voice is None:
            return None

        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        target_dir = Path("audios")
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / f"{voice.file_unique_id}.ogg"
        await file.download_to_drive(custom_path=str(target_path))
        self._logger.info("Audio de voz descargado: %s", target_path)
        return target_path

    async def _invoke_callback(
        self,
        callback: TelegramCommandCallback | TelegramTextCallback | TelegramVoiceCallback,
        update: Update,
        context: CallbackContext,
        *args: Any,
    ) -> str | None:
        """Invoca un callback sin acoplar el bot a la naturaleza síncrona o asíncrona."""

        result = callback(update, context, *args)  # type: ignore[misc]
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[assignment]
        if result is None:
            return None
        if not isinstance(result, str):
            raise TelegramBotError("Los callbacks de Telegram deben devolver texto o None")
        return result


def create_telegram_bot(
    config: TelegramConfig,
    callbacks: TelegramBotCallbacks,
    routes: TelegramBotRoutes | None = None,
    logger: logging.Logger | None = None,
) -> TelegramBot:
    """Factory de conveniencia para construir el adaptador de Telegram."""

    return TelegramBot(config=config, callbacks=callbacks, routes=routes, logger=logger)


__all__ = [
    "TelegramBot",
    "TelegramBotCallbacks",
    "TelegramBotError",
    "TelegramBotRoutes",
    "TelegramDependencyError",
    "create_telegram_bot",
]
