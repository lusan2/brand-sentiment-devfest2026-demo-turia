"""
Orquestador principal del pipeline de ingesta y análisis — demo Turia.

Fuentes (keyless + API):
- Reddit (API pública) · Google News RSS · Bing News RSS · Arctic Shift · GDELT
- NewsAPI · YouTube Data API v3 (según disponibilidad de keys)
- X / Reddit web / Bluesky / Birrapedia vía ControlTab (navegador real, opcional)
"""
import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

from config import SEGMENTS
from ingestion.reddit_scraper import fetch_segment as fetch_reddit
from ingestion.news_scraper import fetch_google_news, fetch_newsapi, fetch_bing_news
from ingestion.arctic_shift_scraper import fetch_arctic_shift
from ingestion.controltab_scraper import fetch_x, fetch_reddit_web, fetch_bluesky, fetch_birrapedia
from ingestion.youtube_scraper import fetch_youtube
from ingestion.gdelt_scraper import fetch_gdelt
from processing.entity_matcher import match, classify_channel
from processing.sentiment_analyzer import analyze_batch
from storage.postgres_client import ensure_table, index_documents, wait_for_postgres, cleanup_old_documents


def build_document(raw: dict, segment, match_result: dict, sentiment: dict) -> dict | None:
    """Construye el documento final para indexar en PostgreSQL."""
    if match_result["mention_type"] is None:
        return None  # Falso positivo — no se indexa

    return {
        "doc_id":          raw["doc_id"],
        "text":            raw["text"],
        "title":           raw.get("title", ""),
        "brand":           segment.brand,
        "market":          segment.market,
        "segment":         segment.segment,
        "product_type":    "",
        "mention_type":    match_result["mention_type"],
        "entity":          match_result["entity"],
        "all_entities":    match_result["all_entities"],
        "sentiment":       sentiment["sentiment"],
        "sentiment_score": sentiment["sentiment_score"],
        "confidence":      sentiment["confidence"],
        "parse_error":     sentiment.get("parse_error", False),
        "source":          raw.get("source", "unknown"),
        "rating":          raw.get("rating"),
        "rating_count":    raw.get("rating_count"),
        "language":        segment.language,
        "url":             raw.get("url", ""),
        "subreddit":       raw.get("subreddit", ""),
        "author":          raw.get("author", ""),
        "channel_type":    classify_channel(raw.get("author", ""), segment.market) if raw.get("source") == "youtube" else None,
        "timestamp":       raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "ingested_at":     datetime.now(timezone.utc).isoformat(),
        "city":            "",
    }


def process_raw_items(items: list[dict], segment) -> list[dict]:
    """Clasifica y analiza sentimiento de una lista de raw items."""
    if not items:
        return []

    matches = [match(item["text"], segment) for item in items]

    relevant = [
        (item, m) for item, m in zip(items, matches)
        if m["mention_type"] is not None
    ]

    if not relevant:
        return []

    texts = [item["text"] for item, _ in relevant]
    sentiments = analyze_batch(texts)

    docs = []
    for (item, m), sentiment in zip(relevant, sentiments):
        doc = build_document(item, segment, m, sentiment)
        if doc:
            docs.append(doc)

    return docs


def run_ingest(include_newsapi: bool = False, include_youtube: bool = False, include_arctic_shift: bool = False) -> None:
    """Ejecuta un ciclo de ingesta completo para todos los segmentos."""
    logger.info("▶ Iniciando ciclo de ingesta — %s", datetime.now(timezone.utc).isoformat())

    total_indexed = 0
    total_skipped = 0

    for segment in SEGMENTS:
        all_items: list[dict] = []

        try:
            all_items.extend(fetch_reddit(segment))
        except Exception as exc:
            logger.error("[Reddit] Error en %s/%s: %s", segment.brand, segment.market, exc)

        if include_arctic_shift:
            try:
                all_items.extend(fetch_arctic_shift(segment))
            except Exception as exc:
                logger.error("[ArcticShift] Error en %s/%s: %s", segment.brand, segment.market, exc)

        try:
            all_items.extend(fetch_google_news(segment))
        except Exception as exc:
            logger.error("[GoogleNews] Error en %s/%s: %s", segment.brand, segment.market, exc)

        try:
            all_items.extend(fetch_bing_news(segment))
        except Exception as exc:
            logger.error("[BingNews] Error en %s/%s: %s", segment.brand, segment.market, exc)

        try:
            all_items.extend(fetch_gdelt(segment))
        except Exception as exc:
            logger.error("[GDELT] Error en %s/%s: %s", segment.brand, segment.market, exc)

        if include_newsapi:
            try:
                all_items.extend(fetch_newsapi(segment))
            except Exception as exc:
                logger.error("[NewsAPI] Error en %s/%s: %s", segment.brand, segment.market, exc)

        if include_youtube:
            try:
                all_items.extend(fetch_youtube(segment))
            except Exception as exc:
                logger.error("[YouTube] Error en %s/%s: %s", segment.brand, segment.market, exc)

        # Deduplicar por doc_id antes de procesar
        seen: dict[str, dict] = {}
        for item in all_items:
            seen.setdefault(item["doc_id"], item)
        unique_items = list(seen.values())

        docs = process_raw_items(unique_items, segment)

        if docs:
            parse_errors = sum(1 for d in docs if d.get("parse_error", False))
            error_rate = parse_errors / len(docs)
            threshold = float(os.getenv("PARSE_ERROR_THRESHOLD", "0.5"))
            if error_rate >= threshold:
                logger.critical(
                    "  [%s/%s] ALERTA parse_error: %.0f%% de fallos (%d/%d docs) "
                    "— verificar ANTHROPIC_API_KEY y cuota de la API",
                    segment.brand, segment.market,
                    error_rate * 100, parse_errors, len(docs),
                )

        if docs:
            indexed, skipped = index_documents(docs)
            total_indexed += indexed
            total_skipped += skipped
            logger.info(
                "  [%s/%s/%s] %d docs → indexados: %d, ya existían: %d",
                segment.brand, segment.market, segment.segment,
                len(docs), indexed, skipped,
            )

    logger.info(
        "✔ Ciclo completado — indexados: %d, duplicados omitidos: %d",
        total_indexed, total_skipped,
    )


def run_without_newsapi() -> None:
    run_ingest(include_newsapi=False)


def run_with_newsapi() -> None:
    run_ingest(include_newsapi=True)


def run_with_youtube() -> None:
    run_ingest(include_youtube=True)


def run_with_arctic_shift() -> None:
    run_ingest(include_arctic_shift=True)


def run_controltab() -> None:
    """Ingesta de X/Twitter, Reddit web, Bluesky y Birrapedia vía navegador real (ControlTab).

    Requiere navegador abierto + logueado + extensión ControlTab conectada.
    Sin sesión activa, las funciones devuelven [] y no se indexa nada.
    """
    brands = [
        b.strip().upper()
        for b in os.getenv("CONTROLTAB_BRANDS", "TURIA").split(",")
        if b.strip()
    ]
    logger.info("▶ Ciclo ControlTab (X + Reddit web + Bluesky + Birrapedia) — %s", datetime.now(timezone.utc).isoformat())

    for segment in SEGMENTS:
        if segment.brand not in brands:
            continue
        all_items: list[dict] = []
        try:
            all_items.extend(fetch_x(segment))
        except Exception as exc:
            logger.error("[ControlTab/X] Error en %s/%s: %s", segment.brand, segment.market, exc)
        try:
            all_items.extend(fetch_reddit_web(segment))
        except Exception as exc:
            logger.error("[ControlTab/Reddit] Error en %s/%s: %s", segment.brand, segment.market, exc)
        try:
            all_items.extend(fetch_bluesky(segment))
        except Exception as exc:
            logger.error("[ControlTab/Bluesky] Error en %s/%s: %s", segment.brand, segment.market, exc)
        try:
            all_items.extend(fetch_birrapedia(segment))
        except Exception as exc:
            logger.error("[ControlTab/Birrapedia] Error en %s/%s: %s", segment.brand, segment.market, exc)

        seen: dict[str, dict] = {}
        for item in all_items:
            seen.setdefault(item["doc_id"], item)
        unique_items = list(seen.values())

        docs = process_raw_items(unique_items, segment)
        if docs:
            indexed, skipped = index_documents(docs)
            logger.info(
                "  [ControlTab/%s] %d docs → indexados %d, ya existían %d",
                segment.brand, len(docs), indexed, skipped,
            )
        else:
            logger.info("  [ControlTab/%s] sin documentos nuevos", segment.brand)


def run_cleanup() -> None:
    """Elimina documentos más antiguos que RETENTION_DAYS de la base de datos."""
    retention_days = int(os.getenv("RETENTION_DAYS", "365"))
    logger.info("▶ Limpieza de datos — retención: %d días", retention_days)
    deleted = cleanup_old_documents(retention_days)
    logger.info("✔ Limpieza completada — %d documentos eliminados", deleted)


if __name__ == "__main__":
    reddit_interval      = int(os.getenv("REDDIT_INTERVAL_MINUTES", "30"))
    news_interval        = int(os.getenv("NEWS_INTERVAL_MINUTES", "360"))
    youtube_interval     = int(os.getenv("YOUTUBE_INTERVAL_MINUTES", "720"))

    # Esperar PostgreSQL
    wait_for_postgres()
    ensure_table()

    # Primera ejecución inmediata (con NewsAPI + YouTube + Arctic Shift + GDELT)
    logger.info("Ejecutando primera ingesta inicial...")
    run_ingest(include_newsapi=True, include_youtube=True, include_arctic_shift=True)
    run_controltab()

    scheduler = BlockingScheduler(timezone="UTC")

    # Reddit + Google News RSS + Bing + GDELT: cada N minutos
    scheduler.add_job(
        run_without_newsapi,
        "interval",
        minutes=reddit_interval,
        id="reddit_news_job",
        name="Reddit + Google News RSS + Bing + GDELT",
    )

    # NewsAPI: cada 6h (respetar free tier 100 req/día)
    scheduler.add_job(
        run_with_newsapi,
        "interval",
        minutes=news_interval,
        id="newsapi_job",
        name="NewsAPI full cycle",
    )

    # YouTube: cada 12h (respetar free tier)
    scheduler.add_job(
        run_with_youtube,
        "interval",
        minutes=youtube_interval,
        id="youtube_job",
        name="YouTube full cycle",
    )

    # Arctic Shift (archivo Reddit, sin key): cada 12h
    scheduler.add_job(
        run_with_arctic_shift,
        "interval",
        minutes=youtube_interval,
        id="arctic_shift_job",
        name="Arctic Shift (archivo Reddit)",
    )

    # ControlTab (X + Reddit web + Bluesky + Birrapedia, vía navegador real): cada 12h
    scheduler.add_job(
        run_controltab,
        "interval",
        minutes=int(os.getenv("CONTROLTAB_INTERVAL_MINUTES", "720")),
        id="controltab_job",
        name="ControlTab (X + Reddit web + Bluesky + Birrapedia)",
    )

    # Limpieza de datos antiguos: cada 7 días
    scheduler.add_job(
        run_cleanup,
        "interval",
        days=7,
        id="cleanup_job",
        name="Limpieza de documentos antiguos",
    )

    logger.info(
        "Scheduler iniciado — Reddit/RSS: cada %dmin | NewsAPI: cada %dmin | YouTube/Arctic/ControlTab: cada %dmin",
        reddit_interval, news_interval, youtube_interval,
    )
    scheduler.start()
