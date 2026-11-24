"""
Endpoint de exportación CSV.

GET /export/csv
  Parámetros:
    brand          TKE | CSS | LLADRO
    mention_type   brand | opportunity | competitor
    market         código de mercado plano: NL | ES | FR | UK | USA | EU | JP | * (todos)
    segment        nombre de segmento plano: traplift | salvaescaleras | ...  | * (todos)
    city           código de ciudad plano: london | new_york | ... | * (todas)
    source         fuente(s) separadas por coma: boamp,tenderned | reddit | ...
    from           epoch ms o fecha ISO (rango inicio, defecto now-30d)
    to             epoch ms o fecha ISO (rango fin, defecto now)
"""
import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
from flask import Flask, Response, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from storage.postgres_client import TABLE_NAME

app = Flask(__name__)
logger = logging.getLogger(__name__)

# ── CORS ──────────────────────────────────────────────────────────────────────
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
CORS(app, origins=_cors_origins)

# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute"],
    storage_uri="memory://",
)

# ── Sanitización ──────────────────────────────────────────────────────────────
_RE_SAFE = re.compile(r"[^A-Za-z0-9 \-_\*]")


def _safe(val: str) -> str:
    return _RE_SAFE.sub("", val).strip()


EXPORT_FIELDS = [
    "timestamp", "title", "entity", "sentiment", "sentiment_score",
    "market", "segment", "product_type", "city", "source", "url",
    "mention_type", "brand", "language", "author", "deadline", "budget", "cpv",
]


def _get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "sentiment"),
        user=os.getenv("POSTGRES_USER", "sentiment"),
        password=os.getenv("POSTGRES_PASSWORD", "sentiment"),
    )


def _parse_date(val: str) -> datetime:
    """Convierte epoch ms de Grafana o fecha ISO a datetime UTC."""
    try:
        ms = int(val)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(val).astimezone(timezone.utc)
    except Exception:
        pass
    # Fallback: now-30d / now
    if "now" in str(val):
        return datetime.now(timezone.utc) - timedelta(days=30)
    return datetime.now(timezone.utc)


@app.route("/export/csv")
@limiter.limit("10 per minute")
def export_csv():
    brand        = _safe(request.args.get("brand", ""))
    mention_type = _safe(request.args.get("mention_type", ""))
    market       = _safe(request.args.get("market", ""))
    segment      = _safe(request.args.get("segment", ""))
    city         = _safe(request.args.get("city", ""))
    source_param = _safe(request.args.get("source", ""))
    from_date    = request.args.get("from", "now-30d")
    to_date      = request.args.get("to", "now")

    from_dt = _parse_date(from_date)
    to_dt   = _parse_date(to_date)

    # Construir WHERE dinámico
    conditions: list[str] = [
        "timestamp >= %s",
        "timestamp <= %s",
        "parse_error = false",
    ]
    params: list = [from_dt, to_dt]

    if brand:
        conditions.append("brand = %s")
        params.append(brand.upper())

    if mention_type and mention_type not in ("*", ""):
        conditions.append("mention_type = %s")
        params.append(mention_type)

    if market and market not in ("*", ""):
        conditions.append("market = %s")
        params.append(market)

    if segment and segment not in ("*", ""):
        conditions.append("segment = %s")
        params.append(segment)

    if city and city not in ("*", ""):
        conditions.append("city = %s")
        params.append(city)

    if source_param:
        sources = [s.strip() for s in source_param.split(",") if s.strip()]
        if sources:
            placeholders = ", ".join(["%s"] * len(sources))
            conditions.append(f"source IN ({placeholders})")
            params.extend(sources)

    where_clause = " AND ".join(conditions)
    cols = ", ".join(EXPORT_FIELDS)
    sql = f"SELECT {cols} FROM {TABLE_NAME} WHERE {where_clause} ORDER BY timestamp DESC LIMIT 10000"

    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.error("Error consultando PostgreSQL: %s", exc)
        return Response("Error interno: no se pueden recuperar los datos.", status=500, mimetype="text/plain")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row[f] if row[f] is not None else "" for f in EXPORT_FIELDS})

    brand_label   = brand or "export"
    mention_label = mention_type or "all"
    filename = (
        f"{brand_label}_{mention_label}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 0.0.0.0 (no 127.0.0.1): dentro de Docker el port-mapping conecta a la
    # interfaz de red del contenedor, no al loopback. Con 127.0.0.1 el puerto
    # mapeado (8081/8080) quedaba inaccesible desde el host.
    app.run(host="0.0.0.0", port=8080)
