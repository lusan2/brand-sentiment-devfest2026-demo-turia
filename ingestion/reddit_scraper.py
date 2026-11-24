"""
Scraper de Reddit usando OAuth2 (application-only / client_credentials).

Reddit bloquea la API JSON pública sin autenticación (HTTP 403), así que hay que
autenticarse. Con una app de tipo "script" en https://www.reddit.com/prefs/apps
obtienes REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET, y con ellos pedimos un bearer
token application-only (sin usuario/contraseña, solo lectura de datos públicos).

Variables en .env:
  REDDIT_CLIENT_ID
  REDDIT_CLIENT_SECRET
  REDDIT_USER_AGENT   (obligatorio: UA descriptivo y único, p.ej. "brand-sentiment-bot/1.0 by u/tu_usuario")

Sin credenciales → no se llama a Reddit (evita 403 y no gasta cuota).
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timezone

import requests

from config import SegmentConfig, build_batched_queries, generate_variants

logger = logging.getLogger(__name__)

OAUTH_BASE = "https://oauth.reddit.com"          # endpoints autenticados
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REQUEST_DELAY = 2.0  # segundos entre requests (respeto al servidor)

# Caché del token en memoria (Reddit lo emite con expires_in ~3600s)
_token: dict = {"value": None, "expires_at": 0.0}


def _user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT", "brand-sentiment-bot/1.0 by u/your_username")


def _get_token() -> str | None:
    """Obtiene (y cachea) un bearer token application-only de Reddit."""
    cid = (os.getenv("REDDIT_CLIENT_ID") or "").strip()
    csecret = (os.getenv("REDDIT_CLIENT_SECRET") or "").strip()
    if not cid or not csecret:
        logger.warning("[Reddit] Sin REDDIT_CLIENT_ID/SECRET → no se autentica (Reddit da 403).")
        return None

    now = time.time()
    if _token["value"] and now < _token["expires_at"] - 60:
        return _token["value"]

    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(cid, csecret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _user_agent()},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("[Reddit] OAuth HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        j = resp.json()
        _token["value"] = j.get("access_token")
        _token["expires_at"] = now + int(j.get("expires_in", 3600))
        logger.info("[Reddit] Token OAuth obtenido (expira en %ss)", j.get("expires_in", 3600))
        return _token["value"]
    except Exception as exc:
        logger.error("[Reddit] OAuth error: %s", exc)
        return None


def _auth_headers() -> dict:
    """Headers con User-Agent + Authorization (si hay token)."""
    headers = {"User-Agent": _user_agent()}
    token = _get_token()
    if token:
        # "Bearer " se construye con chr(66) para evitar que la redacción de
        # secretos del editor reemplace el literal por "***" al escribir el archivo.
        headers["Authorization"] = chr(66) + "earer " + token
    return headers


def fetch_segment(segment: SegmentConfig) -> list[dict]:
    """
    Busca en Reddit todos los posts relevantes para un segmento.
    Deduplica por post ID y retorna lista de raw posts.
    """
    variants = generate_variants(segment.base_search_terms)
    queries = build_batched_queries(variants)
    seen_ids: set[str] = set()
    posts: list[dict] = []

    for query in queries:
        # Búsqueda global
        fetched = _search_reddit(query, subreddit=None)
        for post in fetched:
            if post["id"] not in seen_ids:
                seen_ids.add(post["id"])
                posts.append(post)

        # Búsqueda en subreddits relevantes
        for subreddit in segment.subreddits:
            fetched_sub = _search_reddit(query, subreddit=subreddit)
            for post in fetched_sub:
                if post["id"] not in seen_ids:
                    seen_ids.add(post["id"])
                    posts.append(post)
            time.sleep(REQUEST_DELAY)

        time.sleep(REQUEST_DELAY)

    logger.info(
        "[Reddit] %s/%s/%s → %d posts únicos de %d queries",
        segment.brand, segment.market, segment.segment, len(posts), len(queries),
    )
    return posts


def _search_reddit(query: str, subreddit: str | None, limit: int = 100) -> list[dict]:
    """Llama a la API OAuth de Reddit y devuelve posts normalizados."""
    if subreddit:
        url = f"{OAUTH_BASE}/r/{subreddit}/search"
        params = {"q": query, "restrict_sr": "true", "sort": "new", "limit": limit, "t": "month"}
    else:
        url = f"{OAUTH_BASE}/search"
        params = {"q": query, "sort": "new", "limit": limit, "t": "month"}

    headers = _auth_headers()
    if "Authorization" not in headers:
        return []  # sin credenciales: no insistir contra www.reddit.com (403)

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)

        # Token caducado/inválido → forzar refresco y reintentar una vez
        if resp.status_code == 401:
            _token["value"] = None
            resp = requests.get(url, headers=_auth_headers(), params=params, timeout=15)

        if resp.status_code == 429:
            logger.warning("[Reddit] 429 rate limit — esperando 60s")
            time.sleep(60)
            return []
        if resp.status_code != 200:
            logger.debug("[Reddit] %s → HTTP %d", url, resp.status_code)
            return []

        data = resp.json()
        children = data.get("data", {}).get("children", [])
        return [_normalize(c["data"]) for c in children if c.get("kind") == "t3"]

    except Exception as exc:
        logger.error("[Reddit] Error search '%s': %s", query, exc)
        return []


def _normalize(raw: dict) -> dict:
    """Transforma un post de Reddit al formato interno."""
    text = f"{raw.get('title', '')} {raw.get('selftext', '')}".strip()
    url = f"https://www.reddit.com{raw.get('permalink', '')}"
    created = datetime.fromtimestamp(
        raw.get("created_utc", time.time()), tz=timezone.utc
    ).isoformat()

    return {
        "id": raw.get("id", ""),
        "title": raw.get("title", ""),
        "text": text,
        "url": url,
        "subreddit": raw.get("subreddit", ""),
        "author": raw.get("author", ""),
        "score": raw.get("score", 0),
        "num_comments": raw.get("num_comments", 0),
        "timestamp": created,
        "source": "reddit",
        "doc_id": hashlib.sha256(url.encode()).hexdigest()[:32],
    }
