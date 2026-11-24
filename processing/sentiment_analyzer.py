"""
Análisis de sentimiento multilingüe con Claude Haiku 4.5.
Soporta ES, NL, FR, EN y cualquier idioma que maneje Claude.

Contrato de salida:
    {
        "sentiment":       "positive" | "neutral" | "negative",
        "sentiment_score": float,    # -1.0 (muy negativo) a 1.0 (muy positivo)
        "confidence":      float,    # 0.0 a 1.0
        "parse_error":     bool,     # True si el análisis falló y se usó el fallback
    }

El prompt del sistema se carga desde processing/sentiment_prompt.txt.
Edita ese archivo para ajustar los criterios sin tocar el código.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_CHARS = 2000  # truncar textos muy largos antes de enviar
MIN_SECONDS_BETWEEN_CALLS = 1.3  # límite 50 req/min → 1 cada 1.2s, con margen

_client: anthropic.Anthropic | None = None

_PROMPT_FILE = Path(__file__).parent / "sentiment_prompt.txt"


def _load_system_prompt() -> str:
    """Carga el prompt desde el archivo externo. Falla explícitamente si no existe."""
    if not _PROMPT_FILE.exists():
        raise FileNotFoundError(
            f"Prompt de sentimiento no encontrado: {_PROMPT_FILE}. "
            "Crea el archivo processing/sentiment_prompt.txt."
        )
    return _PROMPT_FILE.read_text(encoding="utf-8").strip()


# Cargado una sola vez al importar el módulo, no en cada llamada
_SYSTEM_PROMPT: str = _load_system_prompt()

_FALLBACK = {
    "sentiment": "neutral",
    "sentiment_score": 0.0,
    "confidence": 0.0,
    "parse_error": True,
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no está configurada en el entorno.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _extract_json(text: str) -> str:
    """Elimina bloques markdown si Claude los devuelve (```json ... ```)."""
    text = text.strip()
    # Quitar bloque de código markdown si existe
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text


def _parse_response(text: str) -> dict:
    """Extrae y valida el JSON devuelto por Claude."""
    try:
        data = json.loads(_extract_json(text))
        sentiment = data.get("sentiment", "").lower()
        if sentiment not in ("positive", "neutral", "negative"):
            logger.warning("Sentimiento inválido recibido de Claude: %r", data)
            return _FALLBACK
        score = float(data.get("sentiment_score", 0.0))
        confidence = float(data.get("confidence", 0.0))
        return {
            "sentiment": sentiment,
            "sentiment_score": round(max(-1.0, min(1.0, score)), 4),
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "parse_error": False,
        }
    except Exception as exc:
        logger.warning("No se pudo parsear la respuesta de Claude: %s — raw: %r", exc, text)
        return _FALLBACK


def analyze(text: str) -> dict:
    """Analiza el sentimiento de un texto."""
    if not text or not text.strip():
        logger.warning("Texto vacío recibido en analyze(), devolviendo fallback.")
        return _FALLBACK

    try:
        client = _get_client()
        t0 = time.monotonic()
        message = client.messages.create(
            model=MODEL,
            max_tokens=64,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text[:MAX_CHARS]}],
        )
        # Respetar el rate limit de 50 req/min
        elapsed = time.monotonic() - t0
        remaining = MIN_SECONDS_BETWEEN_CALLS - elapsed
        if remaining > 0:
            time.sleep(remaining)
        return _parse_response(message.content[0].text)
    except Exception as exc:
        logger.error("Error en análisis de sentimiento: %s", exc)
        return _FALLBACK


def analyze_batch(texts: list[str]) -> list[dict]:
    """Analiza una lista de textos secuencialmente."""
    if not texts:
        return []
    return [analyze(t) for t in texts]
