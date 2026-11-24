"""
Arctic Shift — archivo de Reddit (submissions), sin key ni auth.
Sucesor de Pushshift. Búsqueda por subreddit + ventana temporal.
Base: https://arctic-shift.photon-reddit.com/api/submissions/search

El volcado por subreddit es amplio; el entity_matcher filtra después
lo relevante (marca / competidor / oportunidad).
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from config import SegmentConfig

logger = logging.getLogger(__name__)

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
MAX_AGE_DAYS = int(os.getenv("NEWS_MAX_AGE_DAYS", "180"))
REQUEST_DELAY = 2.0
LIMIT = 100


def fetch_arctic_shift(segment: SegmentConfig) -> list[dict]:
    """Vuelca submissions recientes de los subreddits del segmento (sin key)."""
    if not segment.subreddits:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    after = int(cutoff.timestamp())
    seen: set[str] = set()
    posts: list[dict] = []

    for sub in segment.subreddits:
        params = {"subreddit": sub, "after": after, "limit": LIMIT}
        try:
            resp = requests.get(ARCTIC_BASE, params=params, timeout=25)
            if resp.status_code == 429:
                logger.warning("[ArcticShift] r/%s → 429, esperando 5s", sub)
                time.sleep(5)
                continue
            if resp.status_code != 200:
                logger.warning("[ArcticShift] r/%s → HTTP %d", sub, resp.status_code)
                continue
            data = resp.json().get("data", [])
            for raw in data:
                p = _normalize(raw)
                if p["doc_id"] in seen:
                    continue
                seen.add(p["doc_id"])
                posts.append(p)
        except Exception as exc:
            logger.error("[ArcticShift] r/%s error: %s", sub, exc)
        time.sleep(REQUEST_DELAY)

    logger.info(
        "[ArcticShift] %s/%s/%s → %d posts",
        segment.brand, segment.market, segment.segment, len(posts),
    )
    return posts


def _normalize(raw: dict) -> dict:
    title = raw.get("title") or ""
    selftext = raw.get("selftext") or ""
    text = f"{title} {selftext}".strip()
    permalink = raw.get("permalink") or ""
    url = (
        f"https://www.reddit.com{permalink}"
        if permalink
        else f"https://www.reddit.com/comments/{raw.get('id', '')}"
    )
    created = raw.get("created_utc") or int(time.time())
    try:
        ts = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    except Exception:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "id": raw.get("id", ""),
        "title": title,
        "text": text,
        "url": url,
        "subreddit": raw.get("subreddit", ""),
        "author": raw.get("author", ""),
        "score": raw.get("score", 0),
        "num_comments": raw.get("num_comments", 0),
        "timestamp": ts,
        "source": "arctic_shift",
        "doc_id": hashlib.sha256(url.encode()).hexdigest()[:32],
    }
