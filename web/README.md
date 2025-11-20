# Fact Extraction Review Web Frontend

A comprehensive web interface for reviewing and analyzing extracted facts from video content.

## Features

### Dashboard
- **Key Metrics**: Total facts, entities, videos, clusters, and quality metrics
- **Time Series Charts**: Facts extracted over time
- **Distribution Charts**: Top predicates, entities, and channels

### Fact Browser
- **List View**: Paginated table with filtering and search
- **Filters**: Channel, predicate, quality thresholds
- **Detail View**: Full fact information including:
  - Subject/object entities with Wikidata links
  - Predicate, qualifiers, evidence
  - Confidence scores
  - Cluster membership
  - Similar facts (semantic search)

### Entity Browser
- **List View**: All entities with QID/local ID, link confidence, fact counts
- **Detail View**: Entity information and all facts where entity appears as subject or object

### Video Browser
- **List View**: All videos with fact counts
- **Detail View**: Video metadata, all extracted facts, quality metrics

### Cluster Viewer
- **List View**: All duplicate fact clusters
- **Detail View**: All facts in a cluster showing duplicates

### Quality Analytics
- **Subject/Object Quality**: Word count distribution, fragment detection
- **Predicate Quality**: Unique predicates, top predicates
- **Entity Linking Quality**: QID ratio, link confidence
- **Verification Quality**: Support scores, below-threshold facts
- **Deduplication Quality**: Cluster statistics

### Semantic Search
- Natural language search for facts using Qdrant vector similarity
- Configurable score threshold
- Results show similarity scores

## Running the Web Frontend

### Using Docker Compose

The web frontend is integrated into the Docker Compose setup:

```bash
# Start all services including web
docker compose -f docker/docker-compose.yml up -d

# Access the web interface at:
# http://localhost:8003
```

### Manual Setup

1. Install dependencies (same as main project):
   ```bash
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```bash
   export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/facts
   export QDRANT_URL=http://localhost:6333
   ```

3. Run the web API:
   ```bash
   uvicorn web.api:app --host 0.0.0.0 --port 8003
   ```

4. Open browser to `http://localhost:8003`

## API Endpoints

All API endpoints are prefixed with `/api`:

- `GET /api/stats` - Dashboard statistics
- `GET /api/facts` - List facts (with pagination, filters)
- `GET /api/facts/{fact_id}` - Fact detail
- `GET /api/entities` - List entities
- `GET /api/entities/{entity_key}` - Entity detail
- `GET /api/videos` - List videos
- `GET /api/videos/{video_id}` - Video detail
- `GET /api/clusters` - List clusters
- `GET /api/clusters/{cluster_id}` - Cluster detail
- `GET /api/analytics/quality` - Quality metrics
- `GET /api/analytics/timeline` - Time series data
- `GET /api/analytics/predicates` - Predicate distribution
- `GET /api/analytics/entities` - Entity distribution
- `GET /api/analytics/channels` - Channel distribution
- `GET /api/search/semantic` - Semantic search

## Architecture

- **Backend**: FastAPI (`web/api.py`)
- **Frontend**: Vanilla JavaScript with Bootstrap 5 and Chart.js
- **Database**: PostgreSQL (existing)
- **Vector Search**: Qdrant (existing)

## File Structure

```
web/
├── api.py              # FastAPI backend
├── static/
│   ├── index.html     # Main HTML page
│   ├── css/
│   │   └── style.css  # Custom styles
│   └── js/
│       ├── app.js     # Main app logic
│       ├── dashboard.js
│       ├── facts.js
│       ├── entities.js
│       ├── videos.js
│       ├── clusters.js
│       ├── analytics.js
│       └── search.js
└── README.md
```

## Notes

- The web frontend requires the database to be populated with facts first
- Semantic search requires Qdrant to be running and embeddings to be stored
- All charts use Chart.js and are responsive
- The interface is mobile-friendly with Bootstrap's responsive design

