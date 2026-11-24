# Cerveza Turia — Brand Sentiment Demo

> 🍺 Live brand-sentiment monitoring for **Cerveza Turia** (Valencian toasted/Märzen beer) and its 7 competitors.
> Built as the live demo for the talk **«Análisis de sentimiento de marca con IA por menos de 20€ al mes»** at **GDG DevFest Valencia 2026**.

**ES:** monitorización de sentimiento de marca en tiempo real para *Cerveza Turia* (marca **no cliente**, elegida por ser una cerveza tostada/Märzen valenciana) y 7 competidores, montada como demo pública para la charla del DevFest Valencia 2026.

---

## What it does

The pipeline continuously ingests public mentions from multiple sources, classifies each one, runs sentiment analysis with an LLM, and renders the result in a live Grafana dashboard.

Each mention is classified into one of three buckets:

| Type | Meaning |
|---|---|
| `brand` | Content that directly mentions Turia |
| `competitor` | Content about a competitor (without mentioning Turia) |
| `opportunity` | Generic category content ("cerveza tostada", "Märzen") with no brand |

Sentiment (`positive` / `neutral` / `negative`, scored -1..1) is produced by **Claude Haiku 4.5**.

## Demo results (as of 2026-11-18)

- **388 mentions** indexed, 0 parse errors.
- Sources: Bluesky 156 · YouTube 123 · X 100 · Birrapedia 5 · Google News 2 · Arctic Shift 1 · NewsAPI 1.
- **7 competitors**: Amstel Oro · 1906 · Mahou Maestra · Alhambra 1925 · San Miguel Selecta · Cruzcampo Gran Reserva · Moritz Epidor. Turia **Share of Voice ≈ 31%**.
- **Key insight from the talk:** Turia wins in mention volume but *loses in sentiment* (+0.39) vs. Alhambra (+0.50), 1906 (+0.43) and Mahou (+0.43). *"More conversation ≠ better perception."*
- **Cost:** the one-off demo cost **~$1.30** in LLM calls (≈ 1,600 requests across the pipeline); recurring runs are cents/month in LLM — the recurring cost is dominated by the ~€10-15 VPS, not the AI.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Compose                     │
│                                                     │
│  ┌──────────┐    ┌─────────────────────────────┐   │
│  │ pipeline │───▶│        PostgreSQL 16          │   │
│  │(scheduler│    │  table: sentiment_mentions   │   │
│  │ + NLP)   │    └──────────────┬──────────────┘   │
│  └──────────┘                   │                   │
│                                 ▼                   │
│  ┌──────────┐         Grafana 10.4.5               │
│  │   api    │    ┌────────────────────────────┐    │
│  │(Flask CSV│◀───│  Dashboard: Turia          │    │
│  │ export)  │    └────────────────────────────┘    │
│  └──────────┘                                      │
└─────────────────────────────────────────────────────┘
```

## Data sources

| Source | Frequency | Auth |
|---|---|---|
| Reddit (public JSON API) | 24 h | No |
| Google News RSS | 24 h | No |
| Bing News RSS | 24 h | No |
| Arctic Shift (Reddit archive) | 12 h | No |
| GDELT Project API v2 | 24 h | No |
| NewsAPI | 24 h | `NEWSAPI_KEY` |
| YouTube Data API v3 | 24 h | `YOUTUBE_API_KEY` |
| X / Reddit web / Bluesky / Birrapedia | 12 h | ControlTab (real browser) |

Sentiment analysis requires `ANTHROPIC_API_KEY` (Claude Haiku 4.5).

## Getting started

### 1. Configure

```bash
cp .env.example .env
# fill in the keys you have (ANTHROPIC_API_KEY is required for sentiment)
```

### 2. Run

```bash
docker compose up -d --build
```

- Grafana: http://localhost:3001 (default `admin` / `admin` — change in `.env`)
- CSV export API: http://localhost:8081
- PostgreSQL: localhost:5433

The dashboard `Turia` is provisioned automatically from `grafana/provisioning/dashboards/turia.json`.

### 3. Backfill a source (optional)

One-off scripts to populate the DB before a demo:

```bash
python scripts/populate_turia_bluesky.py
python scripts/populate_turia_x.py
python scripts/populate_turia_youtube.py
python scripts/populate_turia_birrapedia.py
```

## Repository structure

```
├── config.py                 # Turia segment, brand/competitor/generic regex, keywords
├── scheduler/scheduler.py    # ingestion orchestration (APScheduler)
├── ingestion/                # one scraper per source
├── processing/
│   ├── entity_matcher.py     # brand | competitor | opportunity
│   ├── sentiment_analyzer.py # Claude Haiku 4.5 wrapper
│   └── sentiment_prompt.txt  # system prompt
├── storage/
│   ├── postgres_client.py    # insert / dedup / retention
│   └── schema.sql
├── api/export.py             # Flask CSV export
├── grafana/provisioning/     # datasource + Turia dashboard
└── scripts/                  # one-off backfill scripts (demo prep)
```

## Notes & known limitations

- This is a **demo**, not production software. It was written to be shown live at a conference, so some shortcuts were taken (e.g. inconsistent `timestamp` semantics across sources — see the dashboard's aggregated panels, which intentionally drop the time filter for that reason).
- **False positives** are the hardest problem in this kind of tool. Examples handled here: "1906" (the year) vs. 1906 the beer, "San Miguel" (place name) vs. the beer, "Mahou" (Japanese 魔法, anime) vs. the beer. The regexes in `config.py` encode those disambiguations.
- **Reddit in Spanish** is nearly empty for this niche; Arctic Shift (Reddit archive) covers it but contributes ~0 mentions for beer in ES.
- **YouTube quota** is the main cost risk on the free tier (100 `search.list` queries/day).

## License

MIT — see [LICENSE](LICENSE).
