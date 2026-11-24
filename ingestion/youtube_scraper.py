"""
Scraper de YouTube Data API v3.

Busca vídeos relevantes por segmento usando los youtube_terms definidos en config.
Presupuesto: 10.000 unidades/día — cada search.list cuesta 100 unidades.
Con 7 segmentos × 2 términos × 100 unidades = 1.400 unidades/ciclo.
Se ejecuta cada YOUTUBE_INTERVAL_MINUTES (default 720 = 12h) → 2.800 unidades/día.
"""
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import SegmentConfig

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
MAX_RESULTS = 50
MAX_AGE_DAYS = int(os.getenv("NEWS_MAX_AGE_DAYS", "180"))

# Escrituras no latinas: si un segmento ES/FR recibe un vídeo en coreano, japonés,
# chino, árabe o cirílico, es un falso positivo de mercado (relevanceLanguage no es
# un filtro estricto en la API de YouTube). Se descartan para esos mercados.
_NON_LATIN_RE = re.compile(r"[\u1100-\u11FF\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF\u0600-\u06FF\u0400-\u04FF]")


def _build_client():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)


def fetch_youtube(segment: SegmentConfig) -> list[dict]:
    """
    Busca vídeos en YouTube para un segmento usando sus youtube_terms.
    Devuelve una lista de raw items normalizados listos para el pipeline.
    """
    if not YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY no configurada — saltando YouTube.")
        return []

    if not segment.youtube_terms:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        youtube = _build_client()
    except Exception as exc:
        logger.error("Error inicializando cliente YouTube: %s", exc)
        return []

    seen_ids: set[str] = set()
    items: list[dict] = []

    for term in segment.youtube_terms:
        try:
            response = (
                youtube.search()
                .list(
                    q=term,
                    part="snippet",
                    type="video",
                    maxResults=MAX_RESULTS,
                    publishedAfter=published_after,
                    relevanceLanguage=segment.language,
                    order="relevance",
                )
                .execute()
            )

            for entry in response.get("items", []):
                video_id = entry["id"].get("videoId", "")
                if not video_id or video_id in seen_ids:
                    continue
                seen_ids.add(video_id)

                snippet = entry.get("snippet", {})
                title = snippet.get("title", "")
                description = snippet.get("description", "")
                channel = snippet.get("channelTitle", "")
                published_at = snippet.get("publishedAt", "")
                url = f"https://www.youtube.com/watch?v={video_id}"

                text = f"{title} {description}".strip()

                # Descarta contenido en escritura no latina para mercados ES/FR
                if segment.language in ("es", "fr") and _NON_LATIN_RE.search(text):
                    continue

                doc_id = hashlib.sha256(url.encode()).hexdigest()[:32]

                items.append({
                    "id":        doc_id[:16],
                    "title":     title,
                    "text":      text,
                    "url":       url,
                    "author":    channel,
                    "timestamp": published_at,
                    "source":    "youtube",
                    "doc_id":    doc_id,
                })

        except HttpError as exc:
            if exc.resp.status == 403:
                logger.warning("YouTube API quota agotada: %s", exc)
                break
            logger.error("Error YouTube search '%s': %s", term, exc)
        except Exception as exc:
            logger.error("Error YouTube search '%s': %s", term, exc)

        time.sleep(1)

    logger.info(
        "[YouTube] %s/%s/%s → %d vídeos",
        segment.brand, segment.market, segment.segment, len(items),
    )
    return items
