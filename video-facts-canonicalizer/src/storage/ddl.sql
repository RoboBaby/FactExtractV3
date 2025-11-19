-- Enable pgvector for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Core entities table (either QID or local_id must be present)
CREATE TABLE IF NOT EXISTS entities (
  entity_key TEXT PRIMARY KEY,             -- "wikidata:Qxxx" or "local:hash"
  qid TEXT,                                -- e.g., Q42
  local_id TEXT,                           -- e.g., ent:sha1:...
  surface TEXT,
  link_conf REAL,
  meta JSONB
);

-- Videos (for anchoring publish time)
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  publish_time TIMESTAMPTZ
);

-- Facts
CREATE TABLE IF NOT EXISTS facts (
  fact_id TEXT PRIMARY KEY,                -- sha1 of canonical string
  video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
  channel_id TEXT NOT NULL,
  subject_key TEXT NOT NULL REFERENCES entities(entity_key),
  predicate_frame TEXT NOT NULL,           -- e.g., Assemble, Apply_heat
  predicate_pid TEXT,                      -- optional Wikidata PID
  object_key TEXT,                         -- null if literal object
  object_literal JSONB,                    -- for string/quantity literal objects
  qualifiers JSONB,                        -- normalized (units/time)
  evidence JSONB,                          -- blob/sentence/time/frame anchors
  conf JSONB,                              -- el/srl/verify_support
  t_start DOUBLE PRECISION,
  t_end DOUBLE PRECISION,
  canonical_string TEXT NOT NULL,
  canonical_embedding vector(384)          -- MiniLM
);

-- MinHash bands for LSH
CREATE TABLE IF NOT EXISTS fact_minhash (
  fact_id TEXT NOT NULL REFERENCES facts(fact_id) ON DELETE CASCADE,
  band_index SMALLINT NOT NULL,
  band_hash TEXT NOT NULL,
  PRIMARY KEY (band_index, band_hash, fact_id)
);

-- Clusters (optional but useful for analytics)
CREATE TABLE IF NOT EXISTS clusters (
  cluster_id BIGSERIAL PRIMARY KEY,
  rep_fact_id TEXT REFERENCES facts(fact_id),
  global_df INT DEFAULT 0,
  per_channel_df JSONB DEFAULT '{}',
  first_seen_ts TIMESTAMPTZ DEFAULT now(),
  avg_support REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cluster_members (
  cluster_id BIGINT REFERENCES clusters(cluster_id) ON DELETE CASCADE,
  fact_id TEXT REFERENCES facts(fact_id) ON DELETE CASCADE,
  added_ts TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (cluster_id, fact_id)
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_key);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts(object_key);
CREATE INDEX IF NOT EXISTS idx_facts_channel ON facts(channel_id);
CREATE INDEX IF NOT EXISTS idx_facts_embedding ON facts USING hnsw (canonical_embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_facts_qualifiers_gin ON facts USING GIN (qualifiers);
CREATE INDEX IF NOT EXISTS idx_entities_qid ON entities(qid);
CREATE INDEX IF NOT EXISTS idx_entities_local_id ON entities(local_id);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
