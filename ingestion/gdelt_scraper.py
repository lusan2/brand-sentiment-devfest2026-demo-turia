"""
Scraper de GDELT Project API v2.
Sin autenticación. Prensa internacional (multilingüe).
Rate-limit real ~1 req/5s → throttle 6s + retry en 429.
Activo para LLADRO (lujo) y TURIA (demo cerveza).
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from config import SegmentConfig

logger = logging.getLogger(__name__)

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_AGE_DAYS = int(os.getenv("NEWS_MAX_AGE_DAYS", "180"))
THROTTLE_SECONDS = 6.0  # GDELT pide 1 req / 5s
MAX_TERMS = 4


def fetch_gdelt(segment: SegmentConfig) -> list[dict]:
    """Busca artículos en GDELT para LLADRO y TURIA."""
    if segment.brand not in ("LLADRO", "TURIA"):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    start_dt = cutoff.strftime("%Y%m%d%H%M%S")
    end_dt = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    terms = segment.base_search_terms[:MAX_TERMS]
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for term in terms:
        query = term
        if segment.language == "es":
            query += " sourcelang:Spanish"
        elif segment.language == "ja":
            query += " sourcelang:Japanese"

        params = {
            "query":         query,
            "mode":          "ArtList",
            "maxrecords":    75,
            "format":        "json",
            "startdatetime": start_dt,
            "enddatetime":   end_dt,
            "sort":          "DateDesc",
        }

        for attempt in range(3):
            try:
                resp = requests.get(GDELT_BASE, params=params, timeout=20)
                if resp.status_code == 429:
                    logger.warning(
                        "[GDELT] 429 — esperando %ss (intento %d/3)",
                        THROTTLE_SECONDS, attempt + 1,
                    )
                    time.sleep(THROTTLE_SECONDS)
                    continue
                if resp.status_code != 200:
                    logger.warning("[GDELT] HTTP %d para '%s'", resp.status_code, query[:50])
                    break
                data = resp.json()
                for item in data.get("articles", []):
                    url = item.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    articles.append(_normalize(item))
                break
            except Exception as exc:
                logger.error("[GDELT] error '%s': %s", query[:50], exc)
                break

        time.sleep(THROTTLE_SECONDS)

    logger.info(
        "[GDELT] %s/%s/%s → %d artículos",
        segment.brand, segment.market, segment.segment, len(articles),
    )
    return articles


def _normalize(item: dict) -> dict:
    url = item.get("url", "")
    title = item.get("title", "")
    seendate = item.get("seendate", "")
    try:
        ts = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        ts = datetime.now(timezone.utc).isoformat()
    doc_id = hashlib.sha256(url.encode()).hexdigest()[:32]
    return {
        "id":        doc_id[:16],
        "title":     title,
        "text":      title,  # GDELT no devuelve cuerpo del artículo
        "url":       url,
        "author":    item.get("domain", ""),
        "timestamp": ts,
        "source":    "gdelt",
        "doc_id":    doc_id,
    }
