"""
One-off: poblar el dashboard TURIA con ratings de Birrapedia vía ControlTab.
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
from ingestion.controltab_scraper import fetch_birrapedia
from scheduler.scheduler import process_raw_items
from storage.postgres_client import wait_for_postgres, ensure_table, index_documents


def main() -> None:
    seg = next(s for s in SEGMENTS if s.brand == "TURIA")

    wait_for_postgres()
    ensure_table()

    print(f"▶ Fetch Birrapedia para {seg.brand} — cervezas", flush=True)
    items = fetch_birrapedia(seg)

    seen: dict[str, dict] = {}
    for it in items:
        seen.setdefault(it["doc_id"], it)
    unique = list(seen.values())
    print(f"  cervezas: {len(unique)}", flush=True)
    for it in unique:
        print(f"    - {it['title']}: rating={it.get('rating')} count={it.get('rating_count')}", flush=True)

    docs = process_raw_items(unique, seg)
    print(f"  docs tras clasificar: {len(docs)}", flush=True)

    if docs:
        indexed, skipped = index_documents(docs)
        print(f"  → indexados {indexed}, ya existían {skipped}", flush=True)
    else:
        print("  (sin docs)", flush=True)


if __name__ == "__main__":
    main()
