CREATE TABLE IF NOT EXISTS sentiment_mentions (
    doc_id          VARCHAR(64) PRIMARY KEY,
    text            TEXT,
    title           TEXT,
    brand           VARCHAR(20),
    market          VARCHAR(10),
    segment         VARCHAR(50),
    category        VARCHAR(30),
    product_type    VARCHAR(100),
    mention_type    VARCHAR(20),
    entity          VARCHAR(100),
    all_entities    TEXT[],
    sentiment       VARCHAR(10),
    sentiment_score FLOAT,
    confidence      FLOAT,
    parse_error     BOOLEAN DEFAULT FALSE,
    source          VARCHAR(30),
    language        VARCHAR(5),
    url             TEXT,
    subreddit       VARCHAR(100),
    author          TEXT,
    channel_type    VARCHAR(20),
    city            VARCHAR(100),
    deadline        TIMESTAMPTZ,
    budget          NUMERIC,
    cpv             VARCHAR(512),
    timestamp       TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sm_brand        ON sentiment_mentions(brand);
CREATE INDEX IF NOT EXISTS idx_sm_market       ON sentiment_mentions(market);
CREATE INDEX IF NOT EXISTS idx_sm_mention_type ON sentiment_mentions(mention_type);
CREATE INDEX IF NOT EXISTS idx_sm_sentiment    ON sentiment_mentions(sentiment);
CREATE INDEX IF NOT EXISTS idx_sm_timestamp    ON sentiment_mentions(timestamp);
CREATE INDEX IF NOT EXISTS idx_sm_ingested_at  ON sentiment_mentions(ingested_at);
CREATE INDEX IF NOT EXISTS idx_sm_brand_market ON sentiment_mentions(brand, market);
CREATE INDEX IF NOT EXISTS idx_sm_parse_error  ON sentiment_mentions(parse_error);
CREATE INDEX IF NOT EXISTS idx_sm_entity       ON sentiment_mentions(entity);
CREATE INDEX IF NOT EXISTS idx_sm_source       ON sentiment_mentions(source);

-- Migraciones (idempotentes) para bases de datos existentes
ALTER TABLE sentiment_mentions ADD COLUMN IF NOT EXISTS category VARCHAR(30);
ALTER TABLE sentiment_mentions ADD COLUMN IF NOT EXISTS channel_type VARCHAR(20);
ALTER TABLE sentiment_mentions ADD COLUMN IF NOT EXISTS rating NUMERIC;
ALTER TABLE sentiment_mentions ADD COLUMN IF NOT EXISTS rating_count INT;

CREATE INDEX IF NOT EXISTS idx_sm_channel_type ON sentiment_mentions(channel_type);
