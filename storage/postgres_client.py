"""
Cliente PostgreSQL: inicialización de tabla e indexado de documentos.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

TABLE_NAME = "sentiment_mentions"
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

_conn: psycopg2.extensions.connection | None = None
_conn_lock = threading.Lock()


def _create_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "sentiment"),
        user=os.getenv("POSTGRES_USER", "sentiment"),
        password=os.getenv("POSTGRES_PASSWORD", "sentiment"),
    )
    conn.autocommit = False
    return conn


def get_connection() -> psycopg2.extensions.connection:
    global _conn
    with _conn_lock:
        if _conn is None or _conn.closed != 0:
            _conn = _create_connection()
        return _conn


def wait_for_postgres(retries: int = 20, delay: int = 5) -> None:
    """Espera a que PostgreSQL esté disponible antes de arrancar."""
    for attempt in range(retries):
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            logger.info("PostgreSQL disponible.")
            return
        except Exception:
            global _conn
            _conn = None
        logger.info("Esperando PostgreSQL... intento %d/%d", attempt + 1, retries)
        time.sleep(delay)
    raise RuntimeError("PostgreSQL no disponible tras %d intentos." % retries)


def ensure_table() -> None:
    """Crea la tabla y los índices si no existen."""
    conn = get_connection()
    with open(_SCHEMA_PATH) as f:
        schema_sql = f.read()
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    logger.info("Tabla '%s' verificada/creada.", TABLE_NAME)


_COLUMNS = [
    "doc_id", "text", "title", "brand", "market", "segment", "category", "product_type",
    "mention_type", "entity", "all_entities", "sentiment", "sentiment_score",
    "confidence", "parse_error", "source", "language", "url", "subreddit",
    "author", "channel_type", "city", "deadline", "budget", "cpv", "rating", "rating_count", "timestamp", "ingested_at",
]
_COLS_STR = ", ".join(_COLUMNS)


def _doc_to_row(doc: dict) -> tuple:
    return (
        doc["doc_id"],
        doc.get("text", ""),
        doc.get("title", ""),
        doc.get("brand", ""),
        doc.get("market", ""),
        doc.get("segment", ""),
        doc.get("category", ""),
        doc.get("product_type", ""),
        doc.get("mention_type", ""),
        doc.get("entity", ""),
        doc.get("all_entities", []),
        doc.get("sentiment", "neutral"),
        doc.get("sentiment_score", 0.0),
        doc.get("confidence", 0.0),
        doc.get("parse_error", False),
        doc.get("source", ""),
        doc.get("language", ""),
        doc.get("url", ""),
        doc.get("subreddit", ""),
        doc.get("author", ""),
        doc.get("channel_type"),
        doc.get("city", ""),
        doc.get("deadline"),
        doc.get("budget"),
        doc.get("cpv", ""),
        doc.get("rating"),
        doc.get("rating_count"),
        doc.get("timestamp"),
        doc.get("ingested_at"),
    )


def index_documents(docs: list[dict]) -> tuple[int, int]:
    """
    Inserta documentos en PostgreSQL.
    Usa ON CONFLICT (doc_id) DO NOTHING para evitar duplicados.
    Retorna (indexados, omitidos).
    """
    if not docs:
        return 0, 0

    conn = get_connection()
    rows = [_doc_to_row(d) for d in docs]

    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                f"INSERT INTO {TABLE_NAME} ({_COLS_STR}) VALUES %s "
                f"ON CONFLICT (doc_id) DO NOTHING RETURNING doc_id",
                rows,
            )
            inserted = len(cur.fetchall())
        conn.commit()
        skipped = len(docs) - inserted
        return inserted, skipped
    except Exception as exc:
        conn.rollback()
        logger.error("Error indexando documentos: %s", exc)
        return 0, len(docs)


def cleanup_old_documents(retention_days: int) -> int:
    """
    Elimina documentos con ingested_at anterior a retention_days.
    Retorna el número de documentos eliminados.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE_NAME} WHERE ingested_at < %s",
                (cutoff,),
            )
            deleted = cur.rowcount
        conn.commit()
        logger.info(
            "Cleanup: %d documentos eliminados (ingested_at < %s)",
            deleted, cutoff,
        )
        return deleted
    except Exception as exc:
        conn.rollback()
        logger.error("Error en cleanup: %s", exc)
        return 0
