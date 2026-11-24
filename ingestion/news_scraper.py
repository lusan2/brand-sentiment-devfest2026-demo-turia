"""
Scraper de noticias:
  1. NewsAPI (hasta 100 req/día — se ejecuta cada 6h)
  2. Google News RSS (sin límite — se ejecuta cada 30min)
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from datetime import timedelta

import feedparser
import re
import requests

_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITY = re.compile(r"&[a-zA-Z]+;|&#\d+;")

def _strip_html(text: str) -> str:
    text = _HTML_TAG.sub(" ", text)
    text = _HTML_ENTITY.sub(" ", text)
    return " ".join(text.split())

from config import SegmentConfig, build_batched_queries, generate_variants

logger = logging.getLogger(__name__)

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
NEWSAPI_BASE = "https://newsapi.org/v2/everything"
GNEWS_BASE = "https://news.google.com/rss/search"
BING_BASE = "https://www.bing.com/news/search"

# Filtra artículos más antiguos que este umbral
NEWS_MAX_AGE_DAYS = int(os.getenv("NEWS_MAX_AGE_DAYS", "180"))


# ─────────────────────────────────────────────────────────────────────────────
# NewsAPI
# ─────────────────────────────────────────────────────────────────────────────
def fetch_newsapi(segment: SegmentConfig) -> list[dict]:
    """
    Busca artículos en NewsAPI para un segmento.
    Envía los batches de keywords y deduplica por URL.
    """
    if not NEWSAPI_KEY:
        logger.warning("NEWSAPI_KEY no configurada — saltando NewsAPI.")
        return []

    variants = generate_variants(segment.base_search_terms)
    queries = build_batched_queries(variants, max_len=400)
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for query in queries:
        params = {
            "q": query,
            "language": segment.newsapi_language,
            "sortBy": "publishedAt",
            "pageSize": 100,
            "apiKey": NEWSAPI_KEY,
        }
        try:
            resp = requests.get(NEWSAPI_BASE, params=params, timeout=15)
            data = resp.json()
            if data.get("status") != "ok":
                logger.warning("NewsAPI error: %s", data.get("message", ""))
                continue
            for art in data.get("articles", []):
                url = art.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    articles.append(_normalize_newsapi(art))
        except Exception as exc:
            logger.error("Error NewsAPI query '%s': %s", query[:60], exc)
        time.sleep(1)

    logger.info(
        "[NewsAPI] %s/%s/%s → %d artículos",
        segment.brand, segment.market, segment.segment, len(articles),
    )
    return articles


def _normalize_newsapi(raw: dict) -> dict:
    text = " ".join(filter(None, [raw.get("title"), raw.get("description"), raw.get("content")]))
    text = _strip_html(text)
    url = raw.get("url", "")
    pub = raw.get("publishedAt", datetime.now(timezone.utc).isoformat())
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:16],
        "title": raw.get("title", ""),
        "text": text,
        "url": url,
        "author": raw.get("author", ""),
        "timestamp": pub,
        "source": "newsapi",
        "doc_id": hashlib.sha256(url.encode()).hexdigest()[:32],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Google News RSS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_google_news(segment: SegmentConfig) -> list[dict]:
    """
    Busca artículos en Google News RSS para un segmento.
    Sin autenticación ni límites.
    """
    lang = segment.language
    country = segment.google_news_country or lang.upper()
    ceid = f"{country}:{lang}"

    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    after_str = cutoff.strftime("%Y-%m-%d")

    variants = generate_variants(segment.base_search_terms)
    queries = build_batched_queries(variants, max_len=280)
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for query in queries:
        dated_query = f"{query} after:{after_str}"
        url = f"{GNEWS_BASE}?q={requests.utils.quote(dated_query)}&hl={lang}&gl={country}&ceid={ceid}"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                entry_url = entry.get("link", "")
                if entry_url and entry_url not in seen_urls:
                    article = _normalize_gnews(entry)
                    # Descartar artículos demasiado antiguos (Google News no siempre respeta after:)
                    try:
                        from datetime import datetime as _dt
                        art_ts = _dt.fromisoformat(article["timestamp"].replace("Z", "+00:00"))
                        if art_ts < cutoff:
                            continue
                    except Exception:
                        pass
                    seen_urls.add(entry_url)
                    articles.append(article)
        except Exception as exc:
            logger.error("Error Google News RSS '%s': %s", query[:60], exc)
        time.sleep(1)

    logger.info(
        "[GoogleNews] %s/%s/%s → %d artículos",
        segment.brand, segment.market, segment.segment, len(articles),
    )
    return articles


def _normalize_gnews(entry) -> dict:
    url = entry.get("link", "")
    title = _strip_html(entry.get("title", ""))
    summary = _strip_html(entry.get("summary", ""))
    text = f"{title} {summary}".strip()

    # Parsear fecha
    published = entry.get("published", "")
    try:
        ts = parsedate_to_datetime(published).isoformat()
    except Exception:
        ts = datetime.now(timezone.utc).isoformat()

    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:16],
        "title": title,
        "text": text,
        "url": url,
        "author": "",
        "timestamp": ts,
        "source": "google_news",
        "doc_id": hashlib.sha256(url.encode()).hexdigest()[:32],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bing News RSS (sin key — complementa Google News)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_bing_news(segment: SegmentConfig) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    variants = generate_variants(segment.base_search_terms)
    queries = build_batched_queries(variants, max_len=280)
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for query in queries:
        url = f"{BING_BASE}?q={requests.utils.quote(query)}&format=rss"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                entry_url = entry.get("link", "")
                if entry_url and entry_url not in seen_urls:
                    article = _normalize_bing(entry)
                    try:
                        art_ts = datetime.fromisoformat(article["timestamp"].replace("Z", "+00:00"))
                        if art_ts < cutoff:
                            continue
                    except Exception:
                        pass
                    seen_urls.add(entry_url)
                    articles.append(article)
        except Exception as exc:
            logger.error("Error Bing News RSS '%s': %s", query[:60], exc)
        time.sleep(0.7)

    logger.info(
        "[BingNews] %s/%s/%s → %d artículos",
        segment.brand, segment.market, segment.segment, len(articles),
    )
    return articles


def _normalize_bing(entry) -> dict:
    url = entry.get("link", "")
    title = _strip_html(entry.get("title", ""))
    summary = _strip_html(entry.get("summary", ""))
    text = f"{title} {summary}".strip()
    published = entry.get("published", "")
    try:
        ts = parsedate_to_datetime(published).isoformat()
    except Exception:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:16],
        "title": title,
        "text": text,
        "url": url,
        "author": "",
        "timestamp": ts,
        "source": "bing_news",
        "doc_id": hashlib.sha256(url.encode()).hexdigest()[:32],
    }
