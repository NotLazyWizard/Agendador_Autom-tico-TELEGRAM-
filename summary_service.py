"""Servicio de resumen de notas usando Groq Chat.

Este módulo se limita a:
- recibir una lista de textos existentes
- construir un prompt de resumen
- enviar la solicitud al modelo Chat de Groq
- recibir y devolver el resumen

No consulta SQLite, no conoce Telegram y no conoce Whisper.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SummaryServiceError(RuntimeError):
    """Error base para fallos en el servicio de resumen."""


class InvalidInputError(SummaryServiceError):
    """Error lanzado cuando la entrada no contiene textos válidos."""


class SummaryGenerationError(SummaryServiceError):
    """Error lanzado cuando Groq no devuelve un resumen válido."""


@dataclass(frozen=True)
class SummaryServiceConfig:
    """Configuración necesaria para llamar al modelo Chat de Groq."""

    api_key: str
    model: str = "llama-3.1-70b-versatile"
    base_url: str = "https://api.groq.com/openai/v1"
    timeout_seconds: float = 60.0
    max_retries: int = 3
    temperature: float = 0.2
    max_tokens: int = 512
    language: str = "es"
    system_prompt: str = (
        "Eres un asistente que resume notas personales. "
        "Devuelve un resumen claro, breve, útil y en español. "
        "No inventes información. "
        "Si hay varias ideas repetidas, unifícalas."
    )


class SummaryService:
    """Servicio responsable de resumir una colección de textos mediante Groq Chat."""

    def __init__(self, config: SummaryServiceConfig, logger: logging.Logger | None = None) -> None:
        """Inicializa el servicio con configuración y logger opcional.

        Args:
            config: credenciales y parámetros de conexión a Groq.
            logger: logger opcional; si no se proporciona, se usa el del módulo.
        """

        self._config = config
        self._logger = logger or logging.getLogger(__name__)

    def summarize(self, texts: list[str]) -> str:
        """Resume una lista de textos y devuelve únicamente el resumen generado.

        Args:
            texts: lista de textos a resumir.

        Returns:
            El resumen generado por Groq Chat.

        Raises:
            InvalidInputError: si la lista está vacía o no contiene textos válidos.
            SummaryGenerationError: si la API devuelve un error o una respuesta inválida.
        """

        normalized_texts = self._normalize_texts(texts)
        prompt = self._build_prompt(normalized_texts)

        started_at = time.perf_counter()
        self._logger.info("Iniciando resumen: texts=%s", len(normalized_texts))

        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 1):
            try:
                summary = self._request_summary(prompt)
                elapsed_seconds = time.perf_counter() - started_at
                self._logger.info(
                    "Resumen completado: attempt=%s, elapsed=%.2fs",
                    attempt,
                    elapsed_seconds,
                )
                return summary
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, SummaryGenerationError) as exc:
                last_error = exc
                elapsed_seconds = time.perf_counter() - started_at
                self._logger.warning(
                    "Fallo de resumen: attempt=%s, elapsed=%.2fs, error=%s",
                    attempt,
                    elapsed_seconds,
                    exc,
                )
                if attempt >= self._config.max_retries:
                    break

        raise SummaryGenerationError(
            f"No fue posible generar el resumen después de {self._config.max_retries} intentos"
        ) from last_error

    def _normalize_texts(self, texts: list[str]) -> list[str]:
        """Limpia la entrada y elimina textos vacíos o espacios únicamente."""

        if not texts:
            raise InvalidInputError("Se requiere al menos un texto para resumir")

        normalized = [text.strip() for text in texts if isinstance(text, str) and text.strip()]
        if not normalized:
            raise InvalidInputError("La lista no contiene textos válidos para resumir")

        return normalized

    def _build_prompt(self, texts: list[str]) -> str:
        """Construye el prompt final a partir de la lista de textos."""

        bullet_list = "\n".join(f"- {text}" for text in texts)
        return (
            f"{self._config.system_prompt}\n\n"
            f"Idioma de salida: {self._config.language}\n\n"
            "Textos a resumir:\n"
            f"{bullet_list}\n\n"
            "Instrucciones:\n"
            "- Resume solo la información presente en los textos.\n"
            "- No añadas información nueva.\n"
            "- Mantén el resultado claro y directo.\n"
            "- Si existen ideas duplicadas, consolídalas."
        )

    def _request_summary(self, prompt: str) -> str:
        """Realiza la petición HTTP a Groq Chat y devuelve el resumen."""

        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        payload = self._build_payload(prompt)
        request = urllib.request.Request(
            url=url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        start_request = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise SummaryGenerationError(
                f"Groq devolvió un error HTTP {exc.code}: {error_body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SummaryGenerationError(f"No fue posible conectar con Groq: {exc.reason}") from exc

        elapsed_seconds = time.perf_counter() - start_request
        self._logger.debug(
            "Respuesta de Groq recibida: elapsed=%.2fs, bytes=%s",
            elapsed_seconds,
            len(raw_response),
        )

        return self._parse_response(raw_response)

    def _build_payload(self, prompt: str) -> bytes:
        """Construye el cuerpo JSON para la API de Groq Chat."""

        payload: dict[str, Any] = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": self._config.system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _parse_response(self, raw_response: str) -> str:
        """Extrae el contenido del resumen desde el JSON retornado por Groq."""

        try:
            data: dict[str, Any] = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise SummaryGenerationError("Groq devolvió una respuesta no JSON") from exc

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise SummaryGenerationError("Groq no devolvió choices válidos")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise SummaryGenerationError("Groq devolvió una estructura de respuesta inválida")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise SummaryGenerationError("Groq no devolvió un mensaje válido")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise SummaryGenerationError("Groq no devolvió un resumen válido")

        return content.strip()


def create_summary_service(
    api_key: str,
    model: str = "llama-3.1-70b-versatile",
    base_url: str = "https://api.groq.com/openai/v1",
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
    temperature: float = 0.2,
    max_tokens: int = 512,
    language: str = "es",
    system_prompt: str | None = None,
    logger: logging.Logger | None = None,
) -> SummaryService:
    """Factory de conveniencia para crear el servicio de resumen."""

    config = SummaryServiceConfig(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        temperature=temperature,
        max_tokens=max_tokens,
        language=language,
        system_prompt=system_prompt
        or (
            "Eres un asistente que resume notas personales. "
            "Devuelve un resumen claro, breve, útil y en español. "
            "No inventes información. "
            "Si hay varias ideas repetidas, unifícalas."
        ),
    )
    return SummaryService(config=config, logger=logger)


__all__ = [
    "InvalidInputError",
    "SummaryGenerationError",
    "SummaryService",
    "SummaryServiceConfig",
    "SummaryServiceError",
    "create_summary_service",
]
