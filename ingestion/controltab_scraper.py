"""
ControlTab — scraping de Reddit y X/Twitter vía navegador real.

En vez de la API oficial (X v2 de pago, Reddit OAuth bloqueado) pilotamos el
navegador real del usuario a través del MCP de ControlTab (streamable-http).
El navegador navega a la búsqueda, devuelve el HTML renderizado y lo parseamos.

Fuentes cubiertas:
  - X / Twitter  → búsqueda `x.com/search?q="<termo>"`  (source="x")
  - Reddit (web) → búsqueda `reddit.com/search/?q="<termo>"` (source="reddit_web")

Requisito: navegador abierto + logueado + extensión ControlTab conectada al
workspace. Si no hay sesión activa, el MCP devuelve error -32002 y la función
devuelve [] (no rompe el pipeline).

Variables en .env:
  CONTROLTAB_MCP_URL        (por defecto: workspace de Turia)
  CONTROLTAB_REQUEST_DELAY  (segundos entre navegaciones, default 2.0)
"""
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

from config import SegmentConfig, BIRRAPEDIA_BEERS

logger = logging.getLogger(__name__)

MCP_URL = os.getenv("CONTROLTAB_MCP_URL", "")
REQUEST_DELAY = float(os.getenv("CONTROLTAB_REQUEST_DELAY", "2.0"))
RENDER_DELAY = float(os.getenv("CONTROLTAB_RENDER_DELAY", "5.0"))
NAV_TIMEOUT = 30

# Contador JSON-RPC (monotónico por proceso)
_rpc_id = 0


# ─────────────────────────────────────────────────────────────────────────────
# Cliente MCP mínimo (streamable-http)
# ─────────────────────────────────────────────────────────────────────────────
def _rpc(method: str, params: dict) -> dict:
    global _rpc_id
    _rpc_id += 1
    payload = {"jsonrpc": "2.0", "id": _rpc_id, "method": method, "params": params}
    resp = requests.post(
        MCP_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=NAV_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        code = data["error"].get("code")
        msg = data["error"].get("message", "")
        raise RuntimeError(f"MCP error {code}: {msg}")
    return data.get("result", {})


def _call_tool(name: str, arguments: dict) -> str:
    """Ejecuta una tool del MCP y devuelve el texto del primer bloque content."""
    result = _rpc("tools/call", {"name": name, "arguments": arguments})
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    return text


def _navigate(url: str) -> str:
    return _call_tool("browser_navigate", {"url": url})


def _get_html() -> str:
    """Obtiene el HTML renderizado de la pestaña activa."""
    raw = _call_tool("browser_get_html", {})
    try:
        obj = json.loads(raw)
        return obj.get("html", raw)
    except Exception:
        return raw


def _wait_render(selector: str | None = None, timeout_ms: int = 8000) -> None:
    """Espera a que el contenido dinámico se renderice (selector) o duerme fijo."""
    if selector:
        try:
            _call_tool("browser_wait_for", {"selector": selector, "timeout": timeout_ms})
            return
        except Exception:
            pass
    time.sleep(RENDER_DELAY)


def _has_session() -> bool:
    try:
        _call_tool("browser_get_title", {})
        return True
    except Exception as exc:
        logger.warning("[ControlTab] Sin sesión de navegador activa: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Normalización común
# ─────────────────────────────────────────────────────────────────────────────
def _doc_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Bluesky: el rkey de un post (app.bsky.feed.post) es un TID base32-sortable.
# Los 53 bits altos son microsegundos desde el UNIX epoch; los 10 bajos, clock id.
# Así recuperamos la fecha REAL de publicación sin depender del <time> del HTML.
# ─────────────────────────────────────────────────────────────────────────────
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_TID_RE = re.compile(r"^[234567abcdefghijklmnopqrstuvwxyz]{13}$")


def _tid_to_iso(rkey: str) -> str | None:
    """Decodifica un rkey/TID de Bluesky a ISO8601, o None si no es un TID válido."""
    if not rkey or not _TID_RE.match(rkey):
        return None
    try:
        n = 0
        for ch in rkey:
            n = n * 32 + _TID_ALPHABET.index(ch)
    except ValueError:
        return None
    micros = n >> 10
    seconds, micro_remainder = divmod(micros, 1_000_000)
    dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=seconds, microseconds=micro_remainder
    )
    return dt.isoformat()


def _clean(text: str) -> str:
    """Quita etiquetas HTML y colapsa espacios."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_item(
    *,
    item_id: str,
    title: str,
    text: str,
    url: str,
    subreddit: str,
    author: str,
    timestamp: str,
    source: str,
) -> dict:
    return {
        "id": item_id,
        "title": title,
        "text": text,
        "url": url,
        "subreddit": subreddit,
        "author": author,
        "score": 0,
        "num_comments": 0,
        "timestamp": timestamp,
        "source": source,
        "doc_id": _doc_id(url),
    }


# ─────────────────────────────────────────────────────────────────────────────
# X / Twitter
# ─────────────────────────────────────────────────────────────────────────────
_TWEET_RE = re.compile(r"<article\b.*?</article>", re.S)
_TWEETTEXT_RE = re.compile(r'data-testid="tweetText"[^>]*>(.*?)</div>', re.S)
_STATUS_RE = re.compile(r'href="/([A-Za-z0-9_]+)/status/(\d+)"')
_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')


def _parse_x(html: str) -> list[dict]:
    posts: list[dict] = []
    seen: set[str] = set()

    for art in _TWEET_RE.findall(html):
        text_m = _TWEETTEXT_RE.search(art)
        if not text_m:
            continue
        text = _clean(text_m.group(1))
        if not text:
            continue

        status_m = _STATUS_RE.search(art)
        if not status_m:
            continue
        author, tweet_id = status_m.group(1), status_m.group(2)
        url = f"https://x.com/{author}/status/{tweet_id}"

        time_m = _TIME_RE.search(art)
        timestamp = time_m.group(1) if time_m else _now_iso()

        if url in seen:
            continue
        seen.add(url)

        posts.append(
            _normalize_item(
                item_id=tweet_id,
                title=text,
                text=text,
                url=url,
                subreddit="",
                author=author,
                timestamp=timestamp,
                source="x",
            )
        )
    return posts


def fetch_x(segment: SegmentConfig) -> list[dict]:
    """Busca en X/Twitter cada término del segmento y devuelve tweets normalizados."""
    if not segment.base_search_terms:
        return []
    if not _has_session():
        return []

    seen: set[str] = set()
    posts: list[dict] = []

    for term in segment.base_search_terms:
        q = quote(f'"{term}"')
        url = f"https://x.com/search?q={q}&src=typed_query&f=top"
        try:
            _navigate(url)
            _wait_render("article")
            html = _get_html()
            for p in _parse_x(html):
                if p["doc_id"] in seen:
                    continue
                seen.add(p["doc_id"])
                posts.append(p)
        except Exception as exc:
            logger.error("[ControlTab/X] Error en '%s': %s", term, exc)
        time.sleep(REQUEST_DELAY)

    logger.info(
        "[ControlTab/X] %s/%s/%s → %d tweets únicos de %d términos",
        segment.brand, segment.market, segment.segment, len(posts), len(segment.base_search_terms),
    )
    return posts


# ─────────────────────────────────────────────────────────────────────────────
# Reddit (web)
# ─────────────────────────────────────────────────────────────────────────────
_POST_TITLE_RE = re.compile(
    r'id="search-post-title-t3_([A-Za-z0-9]+)"[^>]*href="(/r/[^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
_USER_RE = re.compile(r'href="/user/([^/"]+)/"')


def _parse_reddit(html: str) -> list[dict]:
    posts: list[dict] = []
    seen: set[str] = set()

    for m in _POST_TITLE_RE.finditer(html):
        post_id = m.group(1)
        permalink = m.group(2)
        title = _clean(m.group(3))
        if not title:
            continue

        url = f"https://www.reddit.com{permalink}"
        if url in seen:
            continue
        seen.add(url)

        sub_m = re.match(r"/r/([^/]+)/", permalink)
        subreddit = sub_m.group(1) if sub_m else ""

        # Autor: buscar en un bloque acotado tras el título (mejor esfuerzo)
        author = ""
        user_m = _USER_RE.search(html[m.end(): m.end() + 4000])
        if user_m:
            author = user_m.group(1)

        # Fecha real del post: created-timestamp del <shreddit-post> (unix seconds).
        timestamp = _now_iso()
        window = html[max(0, m.start() - 3000): m.end() + 1000]
        ts_m = re.search(r'created-timestamp="(\d+)"', window)
        if ts_m:
            timestamp = datetime.fromtimestamp(int(ts_m.group(1)), tz=timezone.utc).isoformat()

        posts.append(
            _normalize_item(
                item_id=post_id,
                title=title,
                text=title,
                url=url,
                subreddit=subreddit,
                author=author,
                timestamp=timestamp,
                source="reddit_web",
            )
        )
    return posts


def fetch_reddit_web(segment: SegmentConfig) -> list[dict]:
    """Busca en Reddit (web, vía navegador) cada término y devuelve posts."""
    if not segment.base_search_terms:
        return []
    if not _has_session():
        return []

    seen: set[str] = set()
    posts: list[dict] = []

    for term in segment.base_search_terms:
        q = quote(f'"{term}"')
        url = f"https://www.reddit.com/search/?q={q}&sort=relevance"
        try:
            _navigate(url)
            _wait_render("shreddit-post")
            html = _get_html()
            for p in _parse_reddit(html):
                if p["doc_id"] in seen:
                    continue
                seen.add(p["doc_id"])
                posts.append(p)
        except Exception as exc:
            logger.error("[ControlTab/Reddit] Error en '%s': %s", term, exc)
        time.sleep(REQUEST_DELAY)

    logger.info(
        "[ControlTab/Reddit] %s/%s/%s → %d posts únicos de %d términos",
        segment.brand, segment.market, segment.segment, len(posts), len(segment.base_search_terms),
    )
    return posts


# ─────────────────────────────────────────────────────────────────────────────
# Bluesky (bsky.app)
# ─────────────────────────────────────────────────────────────────────────────
_BSKY_POST_LINK_RE = re.compile(r'href="(/profile/([^"]+)/post/([^"]+))"')
_BSKY_TEXT_RE = re.compile(r'data-testid="postText"[^>]*>(.*?)</div>', re.S)


def _parse_bluesky(html: str) -> list[dict]:
    posts: list[dict] = []
    links = _BSKY_POST_LINK_RE.findall(html)   # (path, handle, rkey)
    texts = _BSKY_TEXT_RE.findall(html)
    seen: set[str] = set()

    for i, text_html in enumerate(texts):
        text = _clean(text_html)
        if not text:
            continue
        handle = ""
        rkey = f"unknown{i}"
        if i < len(links):
            _, handle, rkey = links[i]
        # Fecha REAL de publicación, decodificada del TID (rkey) del post.
        # Si el rkey no es un TID válido (p.ej. post de una PDS custom), caemos a now().
        timestamp = _tid_to_iso(rkey) or _now_iso()
        url = f"https://bsky.app/profile/{handle}/post/{rkey}"
        if url in seen:
            continue
        seen.add(url)
        posts.append(
            _normalize_item(
                item_id=rkey,
                title=text,
                text=text,
                url=url,
                subreddit="",
                author=handle,
                timestamp=timestamp,
                source="bluesky",
            )
        )
    return posts


def fetch_bluesky(segment: SegmentConfig) -> list[dict]:
    """Busca en Bluesky (bsky.app) cada término y devuelve posts normalizados."""
    if not segment.base_search_terms:
        return []
    if not _has_session():
        return []

    seen: set[str] = set()
    posts: list[dict] = []

    for term in segment.base_search_terms:
        q = quote(f'"{term}"')
        url = f"https://bsky.app/search?q={q}"
        try:
            _navigate(url)
            time.sleep(RENDER_DELAY)
            html = _get_html()
            for p in _parse_bluesky(html):
                if p["doc_id"] in seen:
                    continue
                seen.add(p["doc_id"])
                posts.append(p)
        except Exception as exc:
            logger.error("[ControlTab/Bluesky] Error en '%s': %s", term, exc)
        time.sleep(REQUEST_DELAY)

    logger.info(
        "[ControlTab/Bluesky] %s/%s/%s → %d posts únicos de %d términos",
        segment.brand, segment.market, segment.segment, len(posts), len(segment.base_search_terms),
    )
    return posts


# ─────────────────────────────────────────────────────────────────────────────
# Birrapedia (ratings de cerveza)
# ─────────────────────────────────────────────────────────────────────────────
_BIRRA_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _parse_birrapedia_jsonld(html: str) -> dict | None:
    """Extrae nombre, descripción, rating (0-5) y nº de valoraciones del JSON-LD."""
    m = _BIRRA_LD_RE.search(html)
    if not m:
        return None
    try:
        ld = json.loads(m.group(1).replace("\\/", "/"))
    except Exception:
        return None
    ar = ld.get("aggregateRating", {}) or {}
    try:
        rating = float(ar.get("ratingValue", 0) or 0)
    except (TypeError, ValueError):
        rating = 0.0
    try:
        count = int(ar.get("reviewCount", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    return {
        "name": ld.get("name", ""),
        "description": ld.get("description", ""),
        "rating": rating,
        "rating_count": count,
    }


def fetch_birrapedia(segment: SegmentConfig) -> list[dict]:
    """Lee la ficha de cada cerveza en Birrapedia y devuelve rating + valoraciones."""
    beers = BIRRAPEDIA_BEERS.get(segment.brand, [])
    if not beers:
        return []
    if not _has_session():
        return []

    out: list[dict] = []
    for slug, bid, fallback_name in beers:
        url = f"https://birrapedia.com/{slug}/f-{bid}"
        try:
            _navigate(url)
            time.sleep(RENDER_DELAY)
            html = _get_html()
            info = _parse_birrapedia_jsonld(html)
            if not info:
                continue
            name = info["name"] or fallback_name
            text = info["description"] or name
            out.append({
                "id": bid,
                "title": name,
                "text": text,
                "url": url,
                "subreddit": "",
                "author": "Birrapedia",
                "score": 0,
                "num_comments": 0,
                "timestamp": _now_iso(),
                "source": "birrapedia",
                "doc_id": _doc_id(url),
                "rating": info["rating"],
                "rating_count": info["rating_count"],
            })
        except Exception as exc:
            logger.error("[ControlTab/Birrapedia] Error en '%s': %s", slug, exc)
        time.sleep(REQUEST_DELAY)

    logger.info("[ControlTab/Birrapedia] %s → %d cervezas", segment.brand, len(out))
    return out
