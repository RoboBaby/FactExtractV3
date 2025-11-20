"""FastAPI web API for fact extraction review frontend."""

import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.db import Database
from src.storage.repo import Repo
from src.storage.qdrant_client import get_vector_store
from src.dedup.lsh import embed_text
from src.util.logging import get_logger

logger = get_logger("web.api")

# Configuration
DEFAULT_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/facts"
)
DEFAULT_QDRANT_URL = os.environ.get(
    "QDRANT_URL",
    "http://localhost:6333"
)

app = FastAPI(
    title="Fact Extraction Review API",
    description="Web API for reviewing and analyzing extracted facts",
    version="1.0.0"
)

# Mount static files
static_dir = project_root / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Response Models
class DashboardStats(BaseModel):
    """Dashboard statistics."""
    total_facts: int
    total_entities: int
    total_videos: int
    total_clusters: int
    facts_per_video_avg: float
    facts_per_video_min: int
    facts_per_video_max: int
    entity_linking_success_rate: float  # % with QID
    duplicate_rate: float  # % in clusters
    avg_verify_support: Optional[float] = None


class FactListItem(BaseModel):
    """Fact list item for table view."""
    fact_id: str
    subject: str
    predicate: str
    object: Optional[str]
    video_id: str
    channel_id: str
    el_conf: float
    verify_support: Optional[float]
    canonical_string: str
    cluster_id: Optional[int]


class FactDetail(BaseModel):
    """Detailed fact information."""
    fact_id: str
    video_id: str
    channel_id: str
    subject: Dict[str, Any]
    predicate: Dict[str, Any]
    object: Optional[Dict[str, Any]]
    object_literal: Optional[Any]
    qualifiers: Dict[str, Any]
    evidence: Dict[str, Any]
    conf: Dict[str, Any]
    canonical_string: str
    cluster_id: Optional[int]
    t_start: Optional[float]
    t_end: Optional[float]
    similar_facts: List[Dict[str, Any]] = []


class EntityListItem(BaseModel):
    """Entity list item."""
    entity_key: str
    surface: str
    qid: Optional[str]
    local_id: Optional[str]
    link_conf: Optional[float]
    fact_count: int


class EntityDetail(BaseModel):
    """Detailed entity information."""
    entity_key: str
    surface: str
    qid: Optional[str]
    local_id: Optional[str]
    link_conf: Optional[float]
    meta: Optional[Dict[str, Any]]
    facts_as_subject: List[Dict[str, Any]]
    facts_as_object: List[Dict[str, Any]]


class VideoListItem(BaseModel):
    """Video list item."""
    video_id: str
    channel_id: str
    publish_time: Optional[str]
    fact_count: int


class VideoDetail(BaseModel):
    """Detailed video information."""
    video_id: str
    channel_id: str
    publish_time: Optional[str]
    facts: List[Dict[str, Any]]
    quality_metrics: Dict[str, Any]


class ClusterListItem(BaseModel):
    """Cluster list item."""
    cluster_id: int
    representative_fact_id: str
    member_count: int
    first_seen: str
    avg_support: float


class ClusterDetail(BaseModel):
    """Detailed cluster information."""
    cluster_id: int
    representative_fact_id: str
    member_facts: List[Dict[str, Any]]


class QualityMetrics(BaseModel):
    """Quality analytics metrics."""
    subject_quality: Dict[str, Any]
    object_quality: Dict[str, Any]
    predicate_quality: Dict[str, Any]
    entity_linking_quality: Dict[str, Any]
    verification_quality: Dict[str, Any]
    deduplication_quality: Dict[str, Any]


class TimelineData(BaseModel):
    """Time series data."""
    dates: List[str]
    facts_count: List[int]
    entities_count: List[int]
    videos_count: List[int]


# API Endpoints

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    html_file = static_dir / "index.html"
    if html_file.exists():
        return FileResponse(html_file)
    return HTMLResponse("<h1>Fact Extraction Review</h1><p>Frontend not found. Please build the frontend.</p>")


@app.get("/api/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        
        # Basic counts
        stats = repo.get_stats()
        
        # Facts per video
        cur = db.cursor()
        cur.execute("""
            SELECT 
                COUNT(DISTINCT video_id) as video_count,
                COUNT(*) as fact_count
            FROM facts
        """)
        row = cur.fetchone()
        video_count = row["video_count"] if row else 0
        fact_count = row["fact_count"] if row else 0
        
        facts_per_video_avg = fact_count / video_count if video_count > 0 else 0
        
        cur.execute("""
            SELECT 
                video_id,
                COUNT(*) as fact_count
            FROM facts
            GROUP BY video_id
        """)
        video_fact_counts = [r["fact_count"] for r in cur.fetchall()]
        facts_per_video_min = min(video_fact_counts) if video_fact_counts else 0
        facts_per_video_max = max(video_fact_counts) if video_fact_counts else 0
        
        # Entity linking success rate
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE qid IS NOT NULL) as with_qid,
                COUNT(*) as total
            FROM entities
        """)
        row = cur.fetchone()
        with_qid = row["with_qid"] if row else 0
        total_entities = row["total"] if row else 0
        entity_linking_success_rate = (with_qid / total_entities * 100) if total_entities > 0 else 0
        
        # Duplicate rate
        cur.execute("""
            SELECT 
                COUNT(DISTINCT fact_id) FILTER (WHERE cluster_id IS NOT NULL) as in_clusters,
                COUNT(*) as total_facts
            FROM (
                SELECT f.fact_id, cm.cluster_id
                FROM facts f
                LEFT JOIN cluster_members cm ON f.fact_id = cm.fact_id
            ) subq
        """)
        row = cur.fetchone()
        in_clusters = row["in_clusters"] if row else 0
        total_facts_for_dup = row["total_facts"] if row else 0
        duplicate_rate = (in_clusters / total_facts_for_dup * 100) if total_facts_for_dup > 0 else 0
        
        # Average verification support
        cur.execute("""
            SELECT AVG((conf->>'verify_support')::float) as avg_verify
            FROM facts
            WHERE conf->>'verify_support' IS NOT NULL
        """)
        row = cur.fetchone()
        avg_verify_support = row["avg_verify"] if row and row["avg_verify"] else None
        
        repo.close()
        
        return DashboardStats(
            total_facts=stats.get("facts", 0),
            total_entities=stats.get("entities", 0),
            total_videos=stats.get("videos", 0),
            total_clusters=stats.get("clusters", 0),
            facts_per_video_avg=round(facts_per_video_avg, 2),
            facts_per_video_min=facts_per_video_min,
            facts_per_video_max=facts_per_video_max,
            entity_linking_success_rate=round(entity_linking_success_rate, 2),
            duplicate_rate=round(duplicate_rate, 2),
            avg_verify_support=round(avg_verify_support, 2) if avg_verify_support else None
        )
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/facts", response_model=Dict[str, Any])
async def list_facts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    channel_id: Optional[str] = None,
    predicate: Optional[str] = None,
    search: Optional[str] = None,
    min_el_conf: Optional[float] = Query(None, ge=0, le=1),
    min_verify_support: Optional[float] = Query(None, ge=0, le=1)
):
    """List facts with pagination and filters."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Build WHERE clause
        where_clauses = []
        params = []
        
        if channel_id:
            where_clauses.append("f.channel_id = %s")
            params.append(channel_id)
        
        if predicate:
            where_clauses.append("f.predicate_frame = %s")
            params.append(predicate)
        
        if search:
            where_clauses.append("(f.canonical_string ILIKE %s OR s.surface ILIKE %s OR o.surface ILIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        if min_el_conf is not None:
            where_clauses.append("(f.conf->>'el')::float >= %s")
            params.append(min_el_conf)
        
        if min_verify_support is not None:
            where_clauses.append("(f.conf->>'verify_support')::float >= %s")
            params.append(min_verify_support)
        
        where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Count total
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM facts f
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            LEFT JOIN entities o ON f.object_key = o.entity_key
            WHERE 1=1 {where_sql}
        """
        cur.execute(count_sql, params)
        total = cur.fetchone()["total"]
        
        # Get facts
        offset = (page - 1) * page_size
        facts_sql = f"""
            SELECT 
                f.fact_id,
                s.surface as subject,
                f.predicate_frame as predicate,
                o.surface as object,
                f.video_id,
                f.channel_id,
                (f.conf->>'el')::float as el_conf,
                (f.conf->>'verify_support')::float as verify_support,
                f.canonical_string,
                (SELECT cluster_id FROM cluster_members WHERE fact_id = f.fact_id LIMIT 1) as cluster_id
            FROM facts f
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            LEFT JOIN entities o ON f.object_key = o.entity_key
            WHERE 1=1 {where_sql}
            ORDER BY f.fact_id DESC
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        cur.execute(facts_sql, params)
        
        facts = []
        for row in cur.fetchall():
            facts.append(FactListItem(
                fact_id=row["fact_id"],
                subject=row["subject"] or "N/A",
                predicate=row["predicate"],
                object=row["object"],
                video_id=row["video_id"],
                channel_id=row["channel_id"],
                el_conf=row["el_conf"] or 0.0,
                verify_support=row["verify_support"],
                canonical_string=row["canonical_string"],
                cluster_id=row["cluster_id"]
            ).model_dump())
        
        repo.close()
        
        return {
            "facts": facts,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    except Exception as e:
        logger.error(f"Error listing facts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/facts/{fact_id}", response_model=FactDetail)
async def get_fact_detail(fact_id: str):
    """Get detailed fact information."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Get fact
        cur.execute("""
            SELECT 
                f.*,
                s.entity_key as subject_key,
                s.surface as subject_surface,
                s.qid as subject_qid,
                s.local_id as subject_local_id,
                s.link_conf as subject_link_conf,
                o.entity_key as object_key,
                o.surface as object_surface,
                o.qid as object_qid,
                o.local_id as object_local_id,
                o.link_conf as object_link_conf
            FROM facts f
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            LEFT JOIN entities o ON f.object_key = o.entity_key
            WHERE f.fact_id = %s
        """, (fact_id,))
        
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Fact not found: {fact_id}")
        
        # Build subject/object dicts
        subject = {
            "entity_key": row["subject_key"],
            "surface": row["subject_surface"],
            "qid": row["subject_qid"],
            "local_id": row["subject_local_id"],
            "link_conf": row["subject_link_conf"]
        }
        
        obj = None
        if row["object_key"]:
            obj = {
                "entity_key": row["object_key"],
                "surface": row["object_surface"],
                "qid": row["object_qid"],
                "local_id": row["object_local_id"],
                "link_conf": row["object_link_conf"]
            }
        
        # Get cluster members
        cluster_id = None
        similar_facts = []
        cur.execute("""
            SELECT cluster_id FROM cluster_members WHERE fact_id = %s LIMIT 1
        """, (fact_id,))
        cluster_row = cur.fetchone()
        if cluster_row:
            cluster_id = cluster_row["cluster_id"]
            # Get other members
            cur.execute("""
                SELECT fact_id, canonical_string
                FROM cluster_members cm
                JOIN facts f ON cm.fact_id = f.fact_id
                WHERE cm.cluster_id = %s AND cm.fact_id != %s
                LIMIT 10
            """, (cluster_id, fact_id))
            for member_row in cur.fetchall():
                similar_facts.append({
                    "fact_id": member_row["fact_id"],
                    "canonical_string": member_row["canonical_string"]
                })
        
        # Semantic search for similar facts (if Qdrant available)
        try:
            vector_store = get_vector_store(DEFAULT_QDRANT_URL)
            query_embedding = embed_text(row["canonical_string"])
            if query_embedding:
                semantic_results = vector_store.search_similar(
                    embedding=query_embedding,
                    limit=5,
                    score_threshold=0.7
                )
                for r in semantic_results:
                    if r.get("payload", {}).get("fact_id") != fact_id:
                        similar_facts.append({
                            "fact_id": r.get("payload", {}).get("fact_id", ""),
                            "canonical_string": r.get("payload", {}).get("canonical_string", ""),
                            "similarity_score": r.get("score", 0)
                        })
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")
        
        repo.close()
        
        return FactDetail(
            fact_id=row["fact_id"],
            video_id=row["video_id"],
            channel_id=row["channel_id"],
            subject=subject,
            predicate={"frame": row["predicate_frame"], "pid": row.get("predicate_pid")},
            object=obj,
            object_literal=row.get("object_literal"),
            qualifiers=row.get("qualifiers") or {},
            evidence=row.get("evidence") or {},
            conf=row.get("conf") or {},
            canonical_string=row["canonical_string"],
            cluster_id=cluster_id,
            t_start=row.get("t_start"),
            t_end=row.get("t_end"),
            similar_facts=similar_facts[:10]  # Limit to 10
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fact detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/entities", response_model=Dict[str, Any])
async def list_entities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    has_qid: Optional[bool] = None,
    min_link_conf: Optional[float] = Query(None, ge=0, le=1),
    search: Optional[str] = None
):
    """List entities with pagination and filters."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        where_clauses = []
        params = []
        
        if has_qid is not None:
            if has_qid:
                where_clauses.append("qid IS NOT NULL")
            else:
                where_clauses.append("qid IS NULL")
        
        if min_link_conf is not None:
            where_clauses.append("link_conf >= %s")
            params.append(min_link_conf)
        
        if search:
            where_clauses.append("surface ILIKE %s")
            params.append(f"%{search}%")
        
        where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Count
        count_sql = f"SELECT COUNT(*) as total FROM entities WHERE 1=1 {where_sql}"
        cur.execute(count_sql, params)
        total = cur.fetchone()["total"]
        
        # Get entities with fact counts
        offset = (page - 1) * page_size
        entities_sql = f"""
            SELECT 
                e.*,
                (SELECT COUNT(*) FROM facts WHERE subject_key = e.entity_key OR object_key = e.entity_key) as fact_count
            FROM entities e
            WHERE 1=1 {where_sql}
            ORDER BY fact_count DESC, e.surface
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        cur.execute(entities_sql, params)
        
        entities = []
        for row in cur.fetchall():
            entities.append(EntityListItem(
                entity_key=row["entity_key"],
                surface=row["surface"],
                qid=row.get("qid"),
                local_id=row.get("local_id"),
                link_conf=row.get("link_conf"),
                fact_count=row["fact_count"]
            ).model_dump())
        
        repo.close()
        
        return {
            "entities": entities,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    except Exception as e:
        logger.error(f"Error listing entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/entities/{entity_key}", response_model=EntityDetail)
async def get_entity_detail(entity_key: str):
    """Get detailed entity information."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Get entity
        cur.execute("SELECT * FROM entities WHERE entity_key = %s", (entity_key,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Entity not found: {entity_key}")
        
        # Get facts where entity is subject
        cur.execute("""
            SELECT 
                f.fact_id,
                f.predicate_frame,
                f.canonical_string,
                o.surface as object_surface
            FROM facts f
            LEFT JOIN entities o ON f.object_key = o.entity_key
            WHERE f.subject_key = %s
            ORDER BY f.fact_id DESC
            LIMIT 100
        """, (entity_key,))
        facts_as_subject = [dict(r) for r in cur.fetchall()]
        
        # Get facts where entity is object
        cur.execute("""
            SELECT 
                f.fact_id,
                f.predicate_frame,
                f.canonical_string,
                s.surface as subject_surface
            FROM facts f
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            WHERE f.object_key = %s
            ORDER BY f.fact_id DESC
            LIMIT 100
        """, (entity_key,))
        facts_as_object = [dict(r) for r in cur.fetchall()]
        
        repo.close()
        
        return EntityDetail(
            entity_key=row["entity_key"],
            surface=row["surface"],
            qid=row.get("qid"),
            local_id=row.get("local_id"),
            link_conf=row.get("link_conf"),
            meta=row.get("meta"),
            facts_as_subject=facts_as_subject,
            facts_as_object=facts_as_object
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting entity detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/videos", response_model=Dict[str, Any])
async def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    channel_id: Optional[str] = None
):
    """List videos with pagination."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        where_clause = ""
        params = []
        if channel_id:
            where_clause = "WHERE v.channel_id = %s"
            params.append(channel_id)
        
        # Count
        count_sql = f"SELECT COUNT(*) as total FROM videos v {where_clause}"
        cur.execute(count_sql, params)
        total = cur.fetchone()["total"]
        
        # Get videos with fact counts
        offset = (page - 1) * page_size
        videos_sql = f"""
            SELECT 
                v.*,
                (SELECT COUNT(*) FROM facts WHERE video_id = v.video_id) as fact_count
            FROM videos v
            {where_clause}
            ORDER BY v.publish_time DESC NULLS LAST, v.video_id
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        cur.execute(videos_sql, params)
        
        videos = []
        for row in cur.fetchall():
            videos.append(VideoListItem(
                video_id=row["video_id"],
                channel_id=row["channel_id"],
                publish_time=row["publish_time"].isoformat() if row.get("publish_time") else None,
                fact_count=row["fact_count"]
            ).model_dump())
        
        repo.close()
        
        return {
            "videos": videos,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    except Exception as e:
        logger.error(f"Error listing videos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/videos/{video_id}", response_model=VideoDetail)
async def get_video_detail(video_id: str):
    """Get detailed video information."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Get video
        cur.execute("SELECT * FROM videos WHERE video_id = %s", (video_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Video not found: {video_id}")
        
        # Get all facts for video
        cur.execute("""
            SELECT 
                f.*,
                s.surface as subject_surface,
                o.surface as object_surface
            FROM facts f
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            LEFT JOIN entities o ON f.object_key = o.entity_key
            WHERE f.video_id = %s
            ORDER BY f.t_start NULLS LAST, f.fact_id
        """, (video_id,))
        
        facts = []
        for fact_row in cur.fetchall():
            facts.append({
                "fact_id": fact_row["fact_id"],
                "subject": fact_row["subject_surface"],
                "predicate": fact_row["predicate_frame"],
                "object": fact_row["object_surface"],
                "canonical_string": fact_row["canonical_string"],
                "t_start": fact_row.get("t_start"),
                "t_end": fact_row.get("t_end"),
                "conf": fact_row.get("conf")
            })
        
        # Quality metrics
        cur.execute("""
            SELECT 
                COUNT(*) as fact_count,
                AVG((conf->>'el')::float) as avg_el_conf,
                AVG((conf->>'verify_support')::float) as avg_verify_support
            FROM facts
            WHERE video_id = %s
        """, (video_id,))
        metrics_row = cur.fetchone()
        
        quality_metrics = {
            "fact_count": metrics_row["fact_count"] or 0,
            "avg_el_conf": round(metrics_row["avg_el_conf"] or 0, 2),
            "avg_verify_support": round(metrics_row["avg_verify_support"] or 0, 2) if metrics_row["avg_verify_support"] else None
        }
        
        repo.close()
        
        return VideoDetail(
            video_id=row["video_id"],
            channel_id=row["channel_id"],
            publish_time=row["publish_time"].isoformat() if row.get("publish_time") else None,
            facts=facts,
            quality_metrics=quality_metrics
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting video detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/clusters", response_model=Dict[str, Any])
async def list_clusters(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    min_size: Optional[int] = Query(None, ge=1)
):
    """List clusters with pagination."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        where_clause = ""
        params = []
        if min_size:
            where_clause = "HAVING COUNT(cm.fact_id) >= %s"
            params.append(min_size)
        
        # Count
        count_sql = f"""
            SELECT COUNT(DISTINCT c.cluster_id) as total
            FROM clusters c
            JOIN cluster_members cm ON c.cluster_id = cm.cluster_id
            {where_clause.replace('HAVING', 'GROUP BY c.cluster_id HAVING') if where_clause else 'GROUP BY c.cluster_id'}
        """
        if not where_clause:
            count_sql = "SELECT COUNT(*) as total FROM clusters"
            cur.execute(count_sql)
        else:
            # Simplified count
            cur.execute("SELECT COUNT(DISTINCT cluster_id) as total FROM cluster_members")
        total = cur.fetchone()["total"]
        
        # Get clusters
        offset = (page - 1) * page_size
        clusters_sql = f"""
            SELECT 
                c.cluster_id,
                c.rep_fact_id,
                COUNT(cm.fact_id) as member_count,
                c.first_seen_ts,
                c.avg_support
            FROM clusters c
            JOIN cluster_members cm ON c.cluster_id = cm.cluster_id
            GROUP BY c.cluster_id, c.rep_fact_id, c.first_seen_ts, c.avg_support
            {where_clause}
            ORDER BY member_count DESC, c.first_seen_ts DESC
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        cur.execute(clusters_sql, params)
        
        clusters = []
        for row in cur.fetchall():
            clusters.append(ClusterListItem(
                cluster_id=row["cluster_id"],
                representative_fact_id=row["rep_fact_id"] or "",
                member_count=row["member_count"],
                first_seen=row["first_seen_ts"].isoformat() if row.get("first_seen_ts") else "",
                avg_support=row["avg_support"] or 0.0
            ).model_dump())
        
        repo.close()
        
        return {
            "clusters": clusters,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    except Exception as e:
        logger.error(f"Error listing clusters: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/clusters/{cluster_id}", response_model=ClusterDetail)
async def get_cluster_detail(cluster_id: int):
    """Get detailed cluster information."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Get cluster
        cur.execute("SELECT * FROM clusters WHERE cluster_id = %s", (cluster_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Cluster not found: {cluster_id}")
        
        # Get member facts
        cur.execute("""
            SELECT 
                f.fact_id,
                f.canonical_string,
                s.surface as subject_surface,
                f.predicate_frame,
                o.surface as object_surface,
                f.video_id,
                f.channel_id
            FROM cluster_members cm
            JOIN facts f ON cm.fact_id = f.fact_id
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            LEFT JOIN entities o ON f.object_key = o.entity_key
            WHERE cm.cluster_id = %s
            ORDER BY cm.added_ts
        """, (cluster_id,))
        
        member_facts = []
        for fact_row in cur.fetchall():
            member_facts.append({
                "fact_id": fact_row["fact_id"],
                "canonical_string": fact_row["canonical_string"],
                "subject": fact_row["subject_surface"],
                "predicate": fact_row["predicate_frame"],
                "object": fact_row["object_surface"],
                "video_id": fact_row["video_id"],
                "channel_id": fact_row["channel_id"]
            })
        
        repo.close()
        
        return ClusterDetail(
            cluster_id=cluster_id,
            representative_fact_id=row["rep_fact_id"] or "",
            member_facts=member_facts
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cluster detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/quality", response_model=QualityMetrics)
async def get_quality_metrics():
    """Get quality analytics metrics."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Subject/Object Quality
        cur.execute("""
            SELECT 
                AVG(array_length(string_to_array(s.surface, ' '), 1)) as avg_subject_words,
                COUNT(*) FILTER (WHERE array_length(string_to_array(s.surface, ' '), 1) > 8) as long_subjects,
                COUNT(*) FILTER (WHERE s.surface ILIKE 'before%' OR s.surface ILIKE 'while%' OR s.surface ILIKE 'after%') as fragment_subjects,
                COUNT(*) FILTER (WHERE f.object_key IS NULL AND f.object_literal IS NULL) as empty_objects
            FROM facts f
            JOIN entities s ON f.subject_key = s.entity_key
        """)
        subj_obj_row = cur.fetchone()
        
        subject_quality = {
            "avg_word_count": round(subj_obj_row["avg_subject_words"] or 0, 2),
            "long_subjects_count": subj_obj_row["long_subjects"] or 0,
            "fragment_subjects_count": subj_obj_row["fragment_subjects"] or 0
        }
        
        object_quality = {
            "empty_objects_count": subj_obj_row["empty_objects"] or 0
        }
        
        # Predicate Quality
        cur.execute("""
            SELECT COUNT(DISTINCT predicate_frame) as unique_predicates
            FROM facts
        """)
        unique_predicates_row = cur.fetchone()
        unique_predicates_count = unique_predicates_row["unique_predicates"] if unique_predicates_row else 0
        
        cur.execute("""
            SELECT 
                predicate_frame,
                COUNT(*) as freq
            FROM facts
            GROUP BY predicate_frame
            ORDER BY freq DESC
            LIMIT 20
        """)
        predicate_dist = [{"predicate": r["predicate_frame"], "count": r["freq"]} for r in cur.fetchall()]
        
        predicate_quality = {
            "unique_predicates": unique_predicates_count,
            "top_predicates": predicate_dist
        }
        
        # Entity Linking Quality
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE qid IS NOT NULL) as with_qid,
                COUNT(*) as total,
                AVG(link_conf) as avg_link_conf
            FROM entities
        """)
        el_row = cur.fetchone()
        
        entity_linking_quality = {
            "qid_ratio": round((el_row["with_qid"] / el_row["total"] * 100) if el_row["total"] > 0 else 0, 2),
            "avg_link_conf": round(el_row["avg_link_conf"] or 0, 2),
            "low_confidence_count": 0  # Would need threshold
        }
        
        # Verification Quality
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE conf->>'verify_support' IS NOT NULL) as verified_count,
                COUNT(*) as total,
                AVG((conf->>'verify_support')::float) as avg_support,
                COUNT(*) FILTER (WHERE (conf->>'verify_support')::float < 0.6) as below_threshold
            FROM facts
        """)
        verify_row = cur.fetchone()
        
        verification_quality = {
            "verified_count": verify_row["verified_count"] or 0,
            "total_facts": verify_row["total"] or 0,
            "avg_support": round(verify_row["avg_support"] or 0, 2) if verify_row["avg_support"] else None,
            "below_threshold_count": verify_row["below_threshold"] or 0
        }
        
        # Deduplication Quality
        cur.execute("""
            SELECT 
                COUNT(DISTINCT cluster_id) as cluster_count,
                AVG(cluster_size) as avg_cluster_size
            FROM (
                SELECT cluster_id, COUNT(*) as cluster_size
                FROM cluster_members
                GROUP BY cluster_id
            ) subq
        """)
        dedup_row = cur.fetchone()
        
        deduplication_quality = {
            "cluster_count": dedup_row["cluster_count"] or 0,
            "avg_cluster_size": round(dedup_row["avg_cluster_size"] or 0, 2) if dedup_row["avg_cluster_size"] else 0
        }
        
        repo.close()
        
        return QualityMetrics(
            subject_quality=subject_quality,
            object_quality=object_quality,
            predicate_quality=predicate_quality,
            entity_linking_quality=entity_linking_quality,
            verification_quality=verification_quality,
            deduplication_quality=deduplication_quality
        )
    except Exception as e:
        logger.error(f"Error getting quality metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/timeline", response_model=TimelineData)
async def get_timeline_data(
    days: int = Query(30, ge=1, le=365)
):
    """Get time series data for charts."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Get date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Facts over time (by video publish_time)
        cur.execute("""
            SELECT 
                DATE(v.publish_time) as date,
                COUNT(f.fact_id) as fact_count
            FROM videos v
            LEFT JOIN facts f ON v.video_id = f.video_id
            WHERE v.publish_time >= %s AND v.publish_time <= %s
            GROUP BY DATE(v.publish_time)
            ORDER BY date
        """, (start_date, end_date))
        
        timeline_rows = cur.fetchall()
        dates = [r["date"].isoformat() if r["date"] else "" for r in timeline_rows]
        facts_count = [r["fact_count"] or 0 for r in timeline_rows]
        
        # Entities and videos (simplified - just totals)
        cur.execute("SELECT COUNT(*) as count FROM entities")
        entities_total = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) as count FROM videos")
        videos_total = cur.fetchone()["count"]
        
        # For simplicity, repeat totals (could be made time-series if needed)
        entities_count = [entities_total] * len(dates) if dates else []
        videos_count = [videos_total] * len(dates) if dates else []
        
        repo.close()
        
        return TimelineData(
            dates=dates,
            facts_count=facts_count,
            entities_count=entities_count,
            videos_count=videos_count
        )
    except Exception as e:
        logger.error(f"Error getting timeline data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search/semantic")
async def semantic_search(
    query: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    score_threshold: float = Query(0.5, ge=0, le=1)
):
    """Search facts by semantic similarity."""
    try:
        vector_store = get_vector_store(DEFAULT_QDRANT_URL)
        query_embedding = embed_text(query)
        
        if not query_embedding:
            raise HTTPException(status_code=400, detail="Failed to generate embedding")
        
        results = vector_store.search_similar(
            embedding=query_embedding,
            limit=limit,
            score_threshold=score_threshold
        )
        
        # Enrich with fact details
        enriched_results = []
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        for r in results:
            fact_id = r.get("payload", {}).get("fact_id")
            if fact_id:
                cur.execute("""
                    SELECT 
                        f.fact_id,
                        f.canonical_string,
                        s.surface as subject,
                        f.predicate_frame as predicate,
                        o.surface as object,
                        f.video_id,
                        f.channel_id
                    FROM facts f
                    LEFT JOIN entities s ON f.subject_key = s.entity_key
                    LEFT JOIN entities o ON f.object_key = o.entity_key
                    WHERE f.fact_id = %s
                """, (fact_id,))
                fact_row = cur.fetchone()
                if fact_row:
                    enriched_results.append({
                        "fact_id": fact_row["fact_id"],
                        "canonical_string": fact_row["canonical_string"],
                        "subject": fact_row["subject"],
                        "predicate": fact_row["predicate"],
                        "object": fact_row["object"],
                        "video_id": fact_row["video_id"],
                        "channel_id": fact_row["channel_id"],
                        "similarity_score": round(r.get("score", 0), 3)
                    })
        
        repo.close()
        
        return {
            "query": query,
            "results": enriched_results,
            "total": len(enriched_results)
        }
    except Exception as e:
        logger.error(f"Error in semantic search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/predicates")
async def get_predicate_distribution():
    """Get predicate frequency distribution."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        cur.execute("""
            SELECT 
                predicate_frame,
                COUNT(*) as count
            FROM facts
            GROUP BY predicate_frame
            ORDER BY count DESC
            LIMIT 50
        """)
        
        predicates = [{"predicate": r["predicate_frame"], "count": r["count"]} for r in cur.fetchall()]
        
        repo.close()
        
        return {"predicates": predicates}
    except Exception as e:
        logger.error(f"Error getting predicate distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/entities")
async def get_entity_distribution():
    """Get entity frequency distribution."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        # Top subjects
        cur.execute("""
            SELECT 
                s.surface,
                COUNT(*) as count
            FROM facts f
            JOIN entities s ON f.subject_key = s.entity_key
            GROUP BY s.surface
            ORDER BY count DESC
            LIMIT 30
        """)
        top_subjects = [{"entity": r["surface"], "count": r["count"]} for r in cur.fetchall()]
        
        # Top objects
        cur.execute("""
            SELECT 
                o.surface,
                COUNT(*) as count
            FROM facts f
            JOIN entities o ON f.object_key = o.entity_key
            WHERE o.surface IS NOT NULL
            GROUP BY o.surface
            ORDER BY count DESC
            LIMIT 30
        """)
        top_objects = [{"entity": r["surface"], "count": r["count"]} for r in cur.fetchall()]
        
        repo.close()
        
        return {
            "top_subjects": top_subjects,
            "top_objects": top_objects
        }
    except Exception as e:
        logger.error(f"Error getting entity distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/channels")
async def get_channel_distribution():
    """Get channel distribution."""
    try:
        repo = Repo(DEFAULT_DSN)
        db = repo.db
        cur = db.cursor()
        
        cur.execute("""
            SELECT 
                channel_id,
                COUNT(DISTINCT video_id) as video_count,
                COUNT(f.fact_id) as fact_count
            FROM facts f
            GROUP BY channel_id
            ORDER BY fact_count DESC
        """)
        
        channels = [{"channel_id": r["channel_id"], "video_count": r["video_count"], "fact_count": r["fact_count"]} for r in cur.fetchall()]
        
        repo.close()
        
        return {"channels": channels}
    except Exception as e:
        logger.error(f"Error getting channel distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

