"""
One-off: poblar el dashboard TURIA con vídeos de YouTube (search.list).
Ejecutar DENTRO del contenedor del pipeline (tiene psycopg2/anthropic/dotenv).
"""
import logging
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

from config import SEGMENTS
from ingestion.youtube_scraper import fetch_youtube
from scheduler.scheduler import process_raw_items
from storage.postgres_client import wait_for_postgres, ensure_table, index_documents


def main() -> None:
    seg = next(s for s in SEGMENTS if s.brand == "TURIA")

    wait_for_postgres()
    ensure_table()

    print(
        f"▶ Fetch YouTube para {seg.brand}/{seg.market} — {len(seg.youtube_terms)} términos",
        flush=True,
    )
    items = fetch_youtube(seg)

    seen: dict[str, dict] = {}
    for it in items:
        seen.setdefault(it["doc_id"], it)
    unique = list(seen.values())
    print(f"  items crudos: {len(items)} · únicos: {len(unique)}", flush=True)

    docs = process_raw_items(unique, seg)
    print(f"  documentos tras clasificar: {len(docs)}", flush=True)

    c = Counter(d["mention_type"] for d in docs)
    print(f"  tipos: {dict(c)}", flush=True)

    if docs:
        parse_errors = sum(1 for d in docs if d.get("parse_error", False))
        print(f"  parse_errors: {parse_errors}/{len(docs)}", flush=True)
        indexed, skipped = index_documents(docs)
        print(f"  → indexados {indexed}, ya existían {skipped}", flush=True)
    else:
        print("  (sin docs para indexar)", flush=True)


if __name__ == "__main__":
    main()
