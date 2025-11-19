"""FastAPI service for video facts extraction."""

import os
import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.ingest.reader import read_blobs
from src.preprocess.normalize import sentence_split, get_sentence_id, get_evidence_window
from src.srl.client import srl_predict, build_proto_fact
from src.canonicalize.entities import EntityCanonicalizer
from src.canonicalize.predicates import map_predicate
from src.canonicalize.literals import normalize_quantities
from src.verify.evidence import claim_from_fact
from src.verify.nli import LocalVerifier
from src.dedup.signature import canonical_string, fact_id_from_canonical, minhash_from_text, band_hashes
from src.dedup.lsh import embed_text, serialize_minhash, compute_jaccard_from_bytes
from src.storage.db import Database
from src.storage.repo import Repo
from src.storage.qdrant_client import get_vector_store
from src.util.logging import setup_logging, get_logger
from src.util.types import SRLFrame

# Setup logging
setup_logging("INFO")
logger = get_logger("api")

# App configuration
app = FastAPI(
    title="Video Facts Canonicalizer API",
    description="Extract and canonicalize facts from video transcripts and narratives",
    version="1.0.0"
)

# Configuration
DEFAULT_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/facts"
)
DEFAULT_QDRANT_URL = os.environ.get(
    "QDRANT_URL",
    "http://localhost:6333"
)


# Request/Response Models
class BlobInput(BaseModel):
    """Input blob for fact extraction."""
    blob_id: str
    video_id: str
    channel_id: str
    source: str = Field(..., pattern="^(transcript|keyframe|narrative)$")
    text: str
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    frames: Optional[List[str]] = None


class EntityRef(BaseModel):
    """Entity reference."""
    qid: Optional[str] = None
    local_id: Optional[str] = None
    surface: str
    el_conf: float


class PredicateRef(BaseModel):
    """Predicate reference."""
    frame: str
    sense: Optional[str] = None
    pid: Optional[str] = None


class Evidence(BaseModel):
    """Evidence linking fact to source."""
    blob_id: str
    sent_id: str
    char_span: List[int]
    frames: Optional[List[str]] = None


class Confidence(BaseModel):
    """Confidence scores."""
    el: float
    srl: float
    verify_support: float


class ExtractedFact(BaseModel):
    """Extracted and canonicalized fact."""
    fact_id: str
    video_id: str
    channel_id: str
    subject: EntityRef
    predicate: PredicateRef
    object: Optional[EntityRef] = None
    object_literal: Optional[str] = None
    qualifiers: dict = {}
    evidence: Evidence
    conf: Confidence
    canonical_string: str
    cluster_id: Optional[int] = None


class ExtractionResponse(BaseModel):
    """Response from extraction endpoint."""
    blob_id: str
    facts: List[ExtractedFact]
    processing_time_ms: float


class BatchExtractionResponse(BaseModel):
    """Response from batch extraction."""
    total_blobs: int
    total_facts: int
    results: List[ExtractionResponse]
    processing_time_ms: float


class StatsResponse(BaseModel):
    """Database statistics."""
    entities: int
    videos: int
    facts: int
    clusters: int
    vectors: int = 0


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    database: str
    qdrant: str
    timestamp: str


class FactResponse(BaseModel):
    """Single fact response."""
    fact_id: str
    video_id: str
    channel_id: str
    subject_key: str
    predicate_frame: str
    object_key: Optional[str] = None
    object_literal: Optional[dict] = None
    qualifiers: Optional[dict] = None
    evidence: Optional[dict] = None
    conf: Optional[dict] = None
    canonical_string: str
    cluster_id: Optional[int] = None


class ClusterResponse(BaseModel):
    """Cluster with member facts."""
    cluster_id: int
    representative_fact_id: str
    member_fact_ids: List[str]


class SearchRequest(BaseModel):
    """Search request for semantic similarity."""
    query: str
    limit: int = 10
    score_threshold: float = 0.5


class SearchResult(BaseModel):
    """Single search result."""
    fact_id: str
    score: float
    canonical_string: str
    video_id: str
    channel_id: str


class SearchResponse(BaseModel):
    """Search response."""
    query: str
    results: List[SearchResult]
    total: int


# Pipeline configuration
class PipelineConfig:
    """Pipeline configuration."""
    def __init__(self):
        self.srl_endpoint = os.environ.get("SRL_ENDPOINT", "http://localhost:8001/predict")
        self.rel_data_dir = os.environ.get("REL_DATA_DIR", "/data/rel")
        self.min_conf_accept = float(os.environ.get("MIN_CONF_ACCEPT", "0.75"))
        self.enable_verification = os.environ.get("ENABLE_VERIFICATION", "false").lower() == "true"
        self.enable_embeddings = os.environ.get("ENABLE_EMBEDDINGS", "false").lower() == "true"
        self.canonical_units = {
            "temperature": "celsius",
            "length": "millimeter",
            "mass": "gram",
            "time": "second"
        }
        self.minhash_config = {
            "n_perm": 128,
            "bands": 32,
            "rows_per_band": 4,
            "shingle_size": 5
        }


config = PipelineConfig()


# Extraction logic
class FactExtractor:
    """Fact extraction engine."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.el = EntityCanonicalizer(config.rel_data_dir, config.min_conf_accept)
        self.verifier = None
        if config.enable_verification:
            self.verifier = LocalVerifier()

    def extract_from_blob(self, blob: dict) -> List[dict]:
        """Extract facts from a single blob."""
        repo = Repo(self.dsn)

        try:
            # Ensure video exists
            repo.ensure_video(blob["video_id"], blob["channel_id"])

            # Split into sentences
            sentences = sentence_split(blob)
            if not sentences:
                return []

            facts = []

            for sent_idx, (sent, span) in enumerate(sentences):
                # Get SRL frames
                try:
                    srl_frames = srl_predict(config.srl_endpoint, sent)
                except Exception:
                    srl_frames = self._simple_extract(sent)

                for frame in srl_frames:
                    proto = build_proto_fact(frame, sent)

                    if not proto.A0:
                        continue

                    # Extract fact
                    fact = self._build_fact(blob, sent, span, sent_idx, proto, sentences, repo)
                    if fact:
                        facts.append(fact)

            return facts

        finally:
            repo.close()

    def _build_fact(self, blob, sent, span, sent_idx, proto, sentences, repo):
        """Build a single fact from proto-fact."""
        # Link entities
        subj = self.el.link_mentions([{"surface": proto.A0}])[0]
        repo.upsert_entity(subj)

        obj = None
        if proto.A1:
            obj = self.el.link_mentions([{"surface": proto.A1}])[0]
            repo.upsert_entity(obj)

        # Qualifiers
        quals = normalize_quantities(sent, config.canonical_units)

        if proto.A2:
            instr = self.el.link_mentions([{"surface": proto.A2}])[0]
            repo.upsert_entity(instr)
            quals["instrument"] = instr

        # Map predicate
        pred = map_predicate(proto.predicate_lemma)

        # Assemble fact
        fact = {
            "video_id": blob["video_id"],
            "channel_id": blob["channel_id"],
            "subject": subj,
            "predicate": pred,
            "object": obj,
            "object_literal": proto.A1 if not obj else None,
            "qualifiers": quals,
            "evidence": {
                "blob_id": blob["blob_id"],
                "sent_id": get_sentence_id(blob, span),
                "char_span": [span.start, span.end],
                "frames": blob.get("frames")
            },
            "conf": {
                "el": subj.get("el_conf", 0.0),
                "srl": 1.0,
                "verify_support": 0.0
            },
            "t_start": blob.get("t_start"),
            "t_end": blob.get("t_end")
        }

        # Verification
        if self.verifier:
            evidence_sents = get_evidence_window(sentences, sent_idx, 2)
            claim = claim_from_fact(fact)
            vs = self.verifier.score(claim, evidence_sents)
            fact["conf"]["verify_support"] = vs

        # Canonical string and ID
        cs = canonical_string(fact)
        fact["canonical_string"] = cs
        fact["fact_id"] = fact_id_from_canonical(cs)

        # MinHash
        mh = minhash_from_text(
            cs,
            config.minhash_config["n_perm"],
            config.minhash_config["shingle_size"]
        )
        bands = band_hashes(
            mh,
            config.minhash_config["bands"],
            config.minhash_config["rows_per_band"]
        )

        # Serialize MinHash for storage
        mh_bytes = serialize_minhash(mh)

        # Embedding
        embedding = None
        if config.enable_embeddings:
            embedding = embed_text(cs)
        fact["canonical_embedding"] = embedding

        # Query for LSH candidates
        candidates = repo.query_lsh_candidates(bands)

        # Filter candidates by Jaccard similarity
        verified_candidates = []
        for cand_id in candidates:
            cand_mh_bytes = repo.get_minhash_signature(cand_id)
            if cand_mh_bytes:
                jaccard = compute_jaccard_from_bytes(mh_bytes, cand_mh_bytes, config.minhash_config["n_perm"])
                if jaccard >= 0.5:  # Jaccard threshold
                    verified_candidates.append(cand_id)

        # Store fact with MinHash signature
        fact_id = repo.insert_fact(fact, bands, mh_bytes)

        # Store embedding in Qdrant if enabled
        if embedding and config.enable_embeddings:
            try:
                vector_store = get_vector_store(DEFAULT_QDRANT_URL)
                vector_store.upsert_vector(
                    fact_id=fact_id,
                    embedding=embedding,
                    payload={
                        "video_id": fact["video_id"],
                        "channel_id": fact["channel_id"],
                        "canonical_string": cs
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to store embedding in Qdrant: {e}")

        # Assign to cluster
        cluster_id = repo.assign_or_create_cluster(fact_id, verified_candidates, embedding)
        fact["cluster_id"] = cluster_id

        return fact

    def _simple_extract(self, sent: str):
        """Simple fallback extraction."""
        words = sent.split()
        frames = []

        common_verbs = ['is', 'are', 'was', 'were', 'have', 'has',
                       'connect', 'use', 'set', 'place', 'turn', 'read',
                       'connecting', 'using', 'setting', 'placing']

        for i, word in enumerate(words):
            word_lower = word.lower().rstrip('.,!?;:')

            if word_lower in common_verbs or word_lower.endswith('ing'):
                args = {}

                if i > 0:
                    subj_words = words[max(0, i-3):i]
                    args["ARG0"] = " ".join(subj_words).strip(".,!?;:")

                if i < len(words) - 1:
                    remaining = " ".join(words[i+1:])
                    for prep in [" with ", " using ", " to "]:
                        if prep in remaining.lower():
                            parts = remaining.lower().split(prep)
                            args["ARG1"] = parts[0].strip(".,!?;:")
                            if len(parts) > 1:
                                args["ARG2"] = " ".join(parts[1].split()[:4]).strip(".,!?;:")
                            break
                    else:
                        obj_words = words[i+1:min(i+5, len(words))]
                        args["ARG1"] = " ".join(obj_words).strip(".,!?;:")

                if args.get("ARG0") and args.get("ARG1"):
                    frame = SRLFrame(
                        predicate=word_lower,
                        predicate_lemma=word_lower.rstrip('ingsed'),
                        arguments=args
                    )
                    frames.append(frame)
                    break

        return frames


# Global extractor
extractor = None


def get_extractor():
    """Get or create the global extractor."""
    global extractor
    if extractor is None:
        extractor = FactExtractor(DEFAULT_DSN)
    return extractor


# API Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    db_status = "unknown"
    qdrant_status = "unknown"

    try:
        db = Database(DEFAULT_DSN)
        db.connect()
        db.execute("SELECT 1")
        db.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    try:
        vector_store = get_vector_store(DEFAULT_QDRANT_URL)
        info = vector_store.get_collection_info()
        if info:
            qdrant_status = f"connected ({info.get('vectors_count', 0)} vectors)"
        else:
            qdrant_status = "connected (no collection)"
    except Exception as e:
        qdrant_status = f"error: {str(e)}"

    all_healthy = db_status == "connected" and "error" not in qdrant_status

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        database=db_status,
        qdrant=qdrant_status,
        timestamp=datetime.utcnow().isoformat()
    )


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get database statistics."""
    try:
        repo = Repo(DEFAULT_DSN)
        stats = repo.get_stats()
        repo.close()

        # Get Qdrant vector count
        vectors_count = 0
        try:
            vector_store = get_vector_store(DEFAULT_QDRANT_URL)
            info = vector_store.get_collection_info()
            if info:
                vectors_count = info.get("vectors_count", 0)
        except Exception:
            pass

        return StatsResponse(
            entities=stats.get("entities", 0),
            videos=stats.get("videos", 0),
            facts=stats.get("facts", 0),
            clusters=stats.get("clusters", 0),
            vectors=vectors_count
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.post("/extract", response_model=ExtractionResponse)
async def extract_facts(blob: BlobInput):
    """
    Extract facts from a single blob.

    Returns extracted and canonicalized facts with cluster assignments.
    """
    import time
    start = time.time()

    try:
        ext = get_extractor()
        blob_dict = blob.model_dump()

        facts = ext.extract_from_blob(blob_dict)

        # Convert to response format
        extracted_facts = []
        for f in facts:
            extracted_facts.append(ExtractedFact(
                fact_id=f["fact_id"],
                video_id=f["video_id"],
                channel_id=f["channel_id"],
                subject=EntityRef(**f["subject"]),
                predicate=PredicateRef(**f["predicate"]),
                object=EntityRef(**f["object"]) if f.get("object") else None,
                object_literal=f.get("object_literal"),
                qualifiers=f.get("qualifiers", {}),
                evidence=Evidence(**f["evidence"]),
                conf=Confidence(**f["conf"]),
                canonical_string=f["canonical_string"],
                cluster_id=f.get("cluster_id")
            ))

        elapsed = (time.time() - start) * 1000

        return ExtractionResponse(
            blob_id=blob.blob_id,
            facts=extracted_facts,
            processing_time_ms=round(elapsed, 2)
        )

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@app.post("/extract/batch", response_model=BatchExtractionResponse)
async def extract_facts_batch(blobs: List[BlobInput]):
    """
    Extract facts from multiple blobs.

    Processes each blob and returns all extracted facts.
    """
    import time
    start = time.time()

    results = []
    total_facts = 0

    for blob in blobs:
        try:
            response = await extract_facts(blob)
            results.append(response)
            total_facts += len(response.facts)
        except HTTPException as e:
            # Include failed blobs with empty facts
            results.append(ExtractionResponse(
                blob_id=blob.blob_id,
                facts=[],
                processing_time_ms=0
            ))

    elapsed = (time.time() - start) * 1000

    return BatchExtractionResponse(
        total_blobs=len(blobs),
        total_facts=total_facts,
        results=results,
        processing_time_ms=round(elapsed, 2)
    )


@app.post("/init")
async def init_database():
    """Initialize database schema and Qdrant collection."""
    try:
        # Initialize PostgreSQL schema
        db = Database(DEFAULT_DSN)
        db.connect()
        db.init_schema()
        db.close()

        # Initialize Qdrant collection
        try:
            vector_store = get_vector_store(DEFAULT_QDRANT_URL)
            vector_store.ensure_collection()
        except Exception as e:
            logger.warning(f"Qdrant init warning: {e}")

        return {"status": "initialized", "database": "ok", "qdrant": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Init failed: {str(e)}")


@app.post("/reset")
async def reset_database():
    """Reset database (truncate all tables) and Qdrant collection."""
    try:
        # Reset PostgreSQL
        db = Database(DEFAULT_DSN)
        db.connect()

        cleanup_sql = """
            TRUNCATE TABLE cluster_members CASCADE;
            TRUNCATE TABLE clusters CASCADE;
            TRUNCATE TABLE fact_minhash CASCADE;
            TRUNCATE TABLE facts CASCADE;
            TRUNCATE TABLE entities CASCADE;
            TRUNCATE TABLE videos CASCADE;
        """

        cur = db.cursor()
        cur.execute(cleanup_sql)
        db.commit()
        db.close()

        # Reset Qdrant
        try:
            vector_store = get_vector_store(DEFAULT_QDRANT_URL)
            vector_store.delete_collection()
            vector_store.ensure_collection()
        except Exception as e:
            logger.warning(f"Qdrant reset warning: {e}")

        return {"status": "reset", "database": "ok", "qdrant": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")


@app.get("/facts/{fact_id}", response_model=FactResponse)
async def get_fact(fact_id: str):
    """Get a single fact by ID."""
    try:
        repo = Repo(DEFAULT_DSN)
        fact = repo.get_fact(fact_id)
        repo.close()

        if not fact:
            raise HTTPException(status_code=404, detail=f"Fact not found: {fact_id}")

        return FactResponse(
            fact_id=fact["fact_id"],
            video_id=fact["video_id"],
            channel_id=fact["channel_id"],
            subject_key=fact["subject_key"],
            predicate_frame=fact["predicate_frame"],
            object_key=fact.get("object_key"),
            object_literal=fact.get("object_literal"),
            qualifiers=fact.get("qualifiers"),
            evidence=fact.get("evidence"),
            conf=fact.get("conf"),
            canonical_string=fact["canonical_string"],
            cluster_id=fact.get("cluster_id")
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving fact: {str(e)}")


@app.get("/clusters/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(cluster_id: int):
    """Get a cluster and its member facts."""
    try:
        repo = Repo(DEFAULT_DSN)
        members = repo.get_cluster_members(cluster_id)
        repo.close()

        if not members:
            raise HTTPException(status_code=404, detail=f"Cluster not found: {cluster_id}")

        # First member is typically the representative
        return ClusterResponse(
            cluster_id=cluster_id,
            representative_fact_id=members[0] if members else "",
            member_fact_ids=members
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving cluster: {str(e)}")


@app.post("/search", response_model=SearchResponse)
async def search_facts(request: SearchRequest):
    """Search facts by semantic similarity."""
    try:
        # Generate embedding for query
        query_embedding = embed_text(request.query)

        if not query_embedding:
            raise HTTPException(status_code=400, detail="Failed to generate embedding for query")

        # Search Qdrant
        vector_store = get_vector_store(DEFAULT_QDRANT_URL)
        results = vector_store.search_similar(
            embedding=query_embedding,
            limit=request.limit,
            score_threshold=request.score_threshold
        )

        # Format results
        search_results = []
        for r in results:
            search_results.append(SearchResult(
                fact_id=r["id"],
                score=r["score"],
                canonical_string=r.get("payload", {}).get("canonical_string", ""),
                video_id=r.get("payload", {}).get("video_id", ""),
                channel_id=r.get("payload", {}).get("channel_id", "")
            ))

        return SearchResponse(
            query=request.query,
            results=search_results,
            total=len(search_results)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# Run with: uvicorn src.api.app:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
