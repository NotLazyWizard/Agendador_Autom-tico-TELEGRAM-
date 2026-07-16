"""Servicio de transcripción de voz usando Groq Whisper.

Este módulo se limita a:
- recibir un archivo .ogg
- enviarlo a Groq Whisper
- recibir y devolver la transcripción como texto
- manejar errores
- registrar tiempos de ejecución

No guarda nada en SQLite, no responde Telegram y no usa LLM.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SpeechServiceError(RuntimeError):
    """Error base para fallos en la transcripción de audio."""


class InvalidAudioFileError(SpeechServiceError):
    """Error lanzado cuando el archivo de entrada no es válido."""


class SpeechTranscriptionError(SpeechServiceError):
    """Error lanzado cuando Groq Whisper no devuelve una transcripción válida."""


@dataclass(frozen=True)
class SpeechServiceConfig:
    """Configuración necesaria para llamar a Groq Whisper."""

    api_key: str
    model: str = "whisper-large-v3"
    base_url: str = "https://api.groq.com/openai/v1"
    timeout_seconds: float = 60.0
    max_retries: int = 3
    language: str = "es"


class SpeechService:
    """Servicio responsable de transcribir audios .ogg mediante Groq Whisper."""

    def __init__(self, config: SpeechServiceConfig, logger: logging.Logger | None = None) -> None:
        """Inicializa el servicio con configuración y logger opcional.

        Args:
            config: credenciales y parámetros de conexión a Groq.
            logger: logger opcional; si no se proporciona, se usa el del módulo.
        """

        self._config = config
        self._logger = logger or logging.getLogger(__name__)

    def transcribe(self, audio_path: str | Path) -> str:
        """Transcribe un archivo .ogg y devuelve únicamente el texto resultante.

        Args:
            audio_path: ruta del archivo .ogg a transcribir.

        Returns:
            La transcripción devuelta por Groq Whisper.

        Raises:
            InvalidAudioFileError: si el archivo no existe o no es .ogg.
            SpeechTranscriptionError: si la API devuelve un error o una respuesta inválida.
        """

        path = Path(audio_path).expanduser().resolve()
        self._validate_audio_file(path)

        started_at = time.perf_counter()
        self._logger.info("Iniciando transcripción: file=%s", path)

        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 1):
            try:
                transcription = self._request_transcription(path)
                elapsed_seconds = time.perf_counter() - started_at
                self._logger.info(
                    "Transcripción completada: file=%s, attempt=%s, elapsed=%.2fs",
                    path,
                    attempt,
                    elapsed_seconds,
                )
                return transcription
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, SpeechTranscriptionError) as exc:
                last_error = exc
                elapsed_seconds = time.perf_counter() - started_at
                self._logger.warning(
                    "Fallo de transcripción: file=%s, attempt=%s, elapsed=%.2fs, error=%s",
                    path,
                    attempt,
                    elapsed_seconds,
                    exc,
                )
                if attempt >= self._config.max_retries:
                    break

        raise SpeechTranscriptionError(
            f"No fue posible transcribir el audio {path.name} después de {self._config.max_retries} intentos"
        ) from last_error

    def _validate_audio_file(self, path: Path) -> None:
        """Valida que el archivo exista y sea un .ogg legible."""

        if not path.exists():
            raise InvalidAudioFileError(f"El archivo no existe: {path}")

        if not path.is_file():
            raise InvalidAudioFileError(f"La ruta no corresponde a un archivo: {path}")

        if path.suffix.lower() != ".ogg":
            raise InvalidAudioFileError(f"El archivo debe tener extensión .ogg: {path.name}")

        if path.stat().st_size <= 0:
            raise InvalidAudioFileError(f"El archivo está vacío: {path}")

    def _request_transcription(self, audio_path: Path) -> str:
        """Realiza la petición HTTP a Groq Whisper y devuelve el texto transcrito."""

        url = f"{self._config.base_url.rstrip('/')}/audio/transcriptions"
        boundary = f"----speechservice{secrets.token_hex(16)}"
        payload = self._build_multipart_body(audio_path, boundary)

        request = urllib.request.Request(
            url=url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
        )

        start_request = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise SpeechTranscriptionError(
                f"Groq devolvió un error HTTP {exc.code}: {error_body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SpeechTranscriptionError(f"No fue posible conectar con Groq: {exc.reason}") from exc

        elapsed_seconds = time.perf_counter() - start_request
        self._logger.debug(
            "Respuesta de Groq recibida: file=%s, elapsed=%.2fs, bytes=%s",
            audio_path.name,
            elapsed_seconds,
            len(raw_response),
        )

        return self._parse_response(raw_response)

    def _build_multipart_body(self, audio_path: Path, boundary: str) -> bytes:
        """Construye el cuerpo multipart/form-data requerido por la API de Groq."""

        mime_type = mimetypes.guess_type(audio_path.name)[0] or "audio/ogg"
        audio_bytes = audio_path.read_bytes()

        parts: list[bytes] = []
        newline = b"\r\n"

        def add_field(name: str, value: str) -> None:
            parts.append(f"--{boundary}".encode())
            parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            parts.append(b"")
            parts.append(value.encode("utf-8"))

        def add_file(name: str, filename: str, content_type: str, content: bytes) -> None:
            parts.append(f"--{boundary}".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode()
            )
            parts.append(f"Content-Type: {content_type}".encode())
            parts.append(b"")
            parts.append(content)

        add_field("model", self._config.model)
        add_field("language", self._config.language)
        add_field("response_format", "json")
        add_file("file", audio_path.name, mime_type, audio_bytes)
        parts.append(f"--{boundary}--".encode())
        parts.append(b"")

        body = newline.join(parts)
        return body

    def _parse_response(self, raw_response: str) -> str:
        """Extrae la transcripción del JSON retornado por Groq."""

        try:
            data: dict[str, Any] = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise SpeechTranscriptionError("Groq devolvió una respuesta no JSON") from exc

        transcription = data.get("text")
        if not isinstance(transcription, str) or not transcription.strip():
            raise SpeechTranscriptionError("Groq no devolvió una transcripción válida")

        return transcription.strip()


def create_speech_service(
    api_key: str,
    model: str = "whisper-large-v3",
    base_url: str = "https://api.groq.com/openai/v1",
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
    language: str = "es",
    logger: logging.Logger | None = None,
) -> SpeechService:
    """Factory de conveniencia para crear el servicio de transcripción."""

    config = SpeechServiceConfig(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        language=language,
    )
    return SpeechService(config=config, logger=logger)


__all__ = [
    "SpeechServiceConfig",
    "SpeechService",
    "InvalidAudioFileError",
    "SpeechServiceError",
    "SpeechTranscriptionError",
    "create_speech_service",
]