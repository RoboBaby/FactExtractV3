# Video Facts Canonicalizer

A pipeline for extracting, canonicalizing, and deduplicating atomic facts from video transcripts, keyframe captions, and narratives.

## Overview

This system processes text blobs from video content and produces canonical, cross-video facts with:
- Stable fact IDs (SHA1 of canonical string)
- Entity linking to Wikidata QIDs (or deterministic local IDs)
- Predicate mapping to FrameNet/VerbAtlas frames
- Normalized time and quantity qualifiers
- Verification scores against local evidence
- Near-duplicate detection and clustering across videos/channels

## Quick Start

### 1. Build and Start Services

```bash
# Build Docker images
make build

# Start database and microservices
make up

# Run pipeline with toy data
make run-demo
```

### 2. Check Results

```bash
# Connect to database
make psql

# In psql:
SELECT * FROM facts LIMIT 5;
SELECT * FROM clusters;

# View statistics
make stats
```

### 3. Run with Custom Data

```bash
# Place your JSONL file in data/
make run BLOBS=data/my_blobs.jsonl
```

## Input Format

Input blobs should be in JSONL format (one JSON per line):

```json
{
  "blob_id": "uuid",
  "video_id": "vid_123",
  "channel_id": "ch_42",
  "source": "transcript|keyframe|narrative",
  "text": "Alice assembles the drone with a Torx T20 bit.",
  "t_start": 310.12,
  "t_end": 328.48,
  "frames": ["f_12_003", "f_12_007"]
}
```

## Output Format

Canonical facts are stored in PostgreSQL with structure:

```json
{
  "fact_id": "sha1-of-canonical-string",
  "video_id": "vid_123",
  "channel_id": "ch_42",
  "subject": {"qid": "Qxxx", "surface": "Alice", "el_conf": 0.93},
  "predicate": {"frame": "Assemble", "sense": "assemble.01"},
  "object": {"qid": "Qyyy", "surface": "drone", "el_conf": 0.81},
  "qualifiers": {
    "instrument": {"qid": "Qzzz", "surface": "Torx T20 bit"},
    "temperature": {"value": 180, "unit": "celsius"}
  },
  "evidence": {
    "blob_id": "uuid",
    "sent_id": "vid_123:b42:s17",
    "char_span": [215, 278]
  },
  "conf": {"el": 0.93, "srl": 0.88, "verify_support": 0.86},
  "canonical_string": "S:Qxxx|P:Assemble|O:Qyyy|Q:{...}"
}
```

## Architecture

```
blob.jsonl
    │
    ▼
┌─────────────┐
│   Ingest    │  Read & validate blobs
└─────┬───────┘
      │
      ▼
┌─────────────┐
│  Preprocess │  Normalize text, split sentences
└─────┬───────┘
      │
      ▼
┌─────────────┐
│    SRL      │  Extract predicate-argument structures
└─────┬───────┘
      │
      ▼
┌─────────────┐
│ Canonicalize│  Link entities, map predicates, normalize literals
└─────┬───────┘
      │
      ▼
┌─────────────┐
│   Verify    │  Score support with local NLI
└─────┬───────┘
      │
      ▼
┌─────────────┐
│   Dedup     │  MinHash LSH + embedding tie-break
└─────┬───────┘
      │
      ▼
┌─────────────┐
│   Store     │  PostgreSQL + Qdrant
└─────────────┘
```

## Components

### SRL (Semantic Role Labeling)
- **Primary**: AllenNLP transformer-srl
- Runs as microservice on port 8001
- Returns predicate and arguments (A0, A1, A2, etc.)

### Entity Linking
- **Primary**: REL (Radboud Entity Linker)
- **Fallback**: BLINK, Bootleg, or deterministic local IDs
- Links surface forms to Wikidata QIDs

### Time Normalization
- **Primary**: HeidelTime
- Runs as microservice on port 8002
- Normalizes temporal expressions to ISO 8601

### Quantity Normalization
- **Library**: quantulum3 + Pint
- Converts to canonical units (celsius, millimeter, gram, second)

### Verification
- **Method**: FEVER/FActScore style
- Uses sentence-transformers for retrieval
- roberta-large-mnli for NLI scoring

### Deduplication
- **Method**: MinHash LSH + embedding fallback
- datasketch for MinHash
- sentence-transformers for semantic similarity

## Configuration

Edit `configs/app.yaml` to customize:

```yaml
srl:
  endpoint: "http://srl:8001/predict"

entity_linking:
  min_conf_accept: 0.75  # Minimum confidence for QID linking

verification:
  enable: true
  min_support: 0.6  # Minimum NLI support score

dedup:
  minhash:
    n_perm: 128
    bands: 32
    jaccard_equiv: 0.85
  embed_cosine_min: 0.84
```

## Model Artifacts

### Required Downloads

1. **REL Entity Linking Data** (if using REL):
   ```bash
   # Download from https://github.com/informagi/REL
   # Place in /data/rel/
   ```

2. **Sentence Transformers** (auto-downloaded):
   - `sentence-transformers/all-MiniLM-L6-v2`

3. **NLI Model** (auto-downloaded):
   - `roberta-large-mnli`

4. **HeidelTime** (optional):
   - Download from https://github.com/HeidelTime/heideltime
   - Place jar in `resources/heideltime/`

## Development

### Run Tests

```bash
# In Docker
make test

# Locally
make test-local
```

### Local Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set Python path
export PYTHONPATH=.

# Run CLI
python src/cli.py --blobs data/blobs.jsonl --config configs/app.yaml
```

## Troubleshooting

### REL Entity Linker Not Found

If REL data is missing, the system falls back to deterministic local IDs:

```
WARNING: REL not installed, using stub entity linker
```

This is fine for testing. For production, download REL indices.

### HeidelTime Jar Path

If HeidelTime fails:

```
WARNING: HeidelTime request failed: ...
```

Check that the jar is at `resources/heideltime/heideltime-standalone.jar` or set:

```yaml
timex:
  mode: "none"  # Disable HeidelTime
```

### NLI Model OOM

If NLI model runs out of memory:

1. Reduce batch size
2. Use smaller model:
   ```yaml
   verification:
     nli_model: "distilroberta-base"
   ```
3. Disable verification:
   ```yaml
   verification:
     enable: false
   ```

### Database Connection Failed

Ensure PostgreSQL is running:

```bash
docker compose -f docker/docker-compose.yml up -d db
docker compose -f docker/docker-compose.yml logs db
```

### SRL Service Timeout

If SRL is slow to respond:

1. Increase timeout in `src/srl/client.py`
2. Check SRL service logs:
   ```bash
   make logs-srl
   ```

## API Reference

### CLI Options

```bash
python src/cli.py \
  --blobs /path/to/blobs.jsonl \
  --config configs/app.yaml \
  --init-db \
  --log-level DEBUG
```

### Database Schema

See `src/storage/ddl.sql` for complete schema.

Key tables:
- `entities` - Linked entities with QIDs/local IDs
- `videos` - Video metadata
- `facts` - Canonical facts with embeddings
- `fact_minhash` - LSH band hashes
- `clusters` - Deduplicated fact clusters

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests: `make test`
4. Submit a pull request
