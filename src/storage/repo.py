"""Repository for storing and querying facts, entities, and clusters."""

import json
from typing import List, Dict, Any, Optional, Set

from psycopg2.extras import execute_values

from src.storage.db import Database
from src.util.logging import get_logger

logger = get_logger("storage.repo")


class Repo:
    """Repository for fact storage and retrieval."""

    def __init__(self, dsn: str):
        """
        Initialize repository.

        Args:
            dsn: PostgreSQL connection string
        """
        self.db = Database(dsn)
        self.db.connect()

    def close(self):
        """Close repository connection."""
        self.db.close()

    def ensure_video(self, video_id: str, channel_id: str, publish_time: str = None):
        """
        Ensure video exists in database.

        Args:
            video_id: Video identifier
            channel_id: Channel identifier
            publish_time: Optional publish time ISO string
        """
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO videos (video_id, channel_id, publish_time)
            VALUES (%s, %s, %s)
            ON CONFLICT (video_id) DO NOTHING
            """,
            (video_id, channel_id, publish_time)
        )
        self.db.commit()

    def upsert_entity(self, entity_dict: Dict[str, Any]) -> str:
        """
        Upsert an entity.

        Args:
            entity_dict: Entity data with qid/local_id, surface, link_conf

        Returns:
            Entity key
        """
        qid = entity_dict.get("qid")
        local_id = entity_dict.get("local_id")

        # Determine entity key
        if qid:
            entity_key = f"wikidata:{qid}"
        elif local_id:
            entity_key = f"local:{local_id}"
        else:
            # Generate from surface
            import hashlib
            surface = entity_dict.get("surface", "unknown").lower()
            hash_str = hashlib.sha1(surface.encode()).hexdigest()[:16]
            local_id = f"ent:{hash_str}"
            entity_key = f"local:{local_id}"

        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO entities (entity_key, qid, local_id, surface, link_conf, meta)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_key) DO UPDATE SET
                link_conf = GREATEST(entities.link_conf, EXCLUDED.link_conf),
                meta = COALESCE(entities.meta, '{}') || COALESCE(EXCLUDED.meta, '{}')
            RETURNING entity_key
            """,
            (
                entity_key,
                qid,
                local_id,
                entity_dict.get("surface"),
                entity_dict.get("el_conf", 0.0),
                json.dumps(entity_dict.get("meta", {}))
            )
        )
        result = cur.fetchone()
        self.db.commit()
        return result["entity_key"]

    def insert_fact(
        self,
        fact_obj: Dict[str, Any],
        band_hashes: List[tuple],
        minhash_signature: Optional[bytes] = None
    ) -> str:
        """
        Insert a fact with its MinHash bands.

        Args:
            fact_obj: Canonical fact dictionary
            band_hashes: List of (band_index, band_hash) tuples
            minhash_signature: Optional serialized MinHash for Jaccard comparison

        Returns:
            Fact ID
        """
        fact_id = fact_obj["fact_id"]

        # Check if fact already exists (idempotence)
        cur = self.db.cursor()
        cur.execute("SELECT fact_id FROM facts WHERE fact_id = %s", (fact_id,))
        if cur.fetchone():
            logger.debug(f"Fact {fact_id} already exists, skipping")
            return fact_id

        # Get entity keys
        subject_key = self._get_entity_key(fact_obj.get("subject", {}))
        object_key = None
        if fact_obj.get("object"):
            object_key = self._get_entity_key(fact_obj["object"])

        # Insert fact (vectors stored in Qdrant, not PostgreSQL)
        cur.execute(
            """
            INSERT INTO facts (
                fact_id, video_id, channel_id, subject_key, predicate_frame,
                predicate_pid, object_key, object_literal, qualifiers, evidence,
                conf, t_start, t_end, canonical_string, minhash_signature
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (fact_id) DO NOTHING
            """,
            (
                fact_id,
                fact_obj.get("video_id"),
                fact_obj.get("channel_id"),
                subject_key,
                fact_obj.get("predicate", {}).get("frame"),
                fact_obj.get("predicate", {}).get("pid"),
                object_key,
                json.dumps(fact_obj.get("object_literal")) if fact_obj.get("object_literal") else None,
                json.dumps(fact_obj.get("qualifiers", {})),
                json.dumps(fact_obj.get("evidence", {})),
                json.dumps(fact_obj.get("conf", {})),
                fact_obj.get("t_start"),
                fact_obj.get("t_end"),
                fact_obj.get("canonical_string"),
                minhash_signature
            )
        )

        # Insert MinHash bands
        if band_hashes:
            band_values = [(fact_id, band_idx, band_hash) for band_idx, band_hash in band_hashes]
            execute_values(
                cur,
                """
                INSERT INTO fact_minhash (fact_id, band_index, band_hash)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                band_values
            )

        self.db.commit()
        logger.debug(f"Inserted fact {fact_id}")
        return fact_id

    def get_minhash_signature(self, fact_id: str) -> Optional[bytes]:
        """
        Get MinHash signature for a fact.

        Args:
            fact_id: Fact identifier

        Returns:
            Serialized MinHash or None
        """
        cur = self.db.cursor()
        cur.execute(
            "SELECT minhash_signature FROM facts WHERE fact_id = %s",
            (fact_id,)
        )
        result = cur.fetchone()
        if result:
            return result["minhash_signature"]
        return None

    def _get_entity_key(self, entity: Dict[str, Any]) -> str:
        """Get entity key from entity reference."""
        if entity.get("qid"):
            return f"wikidata:{entity['qid']}"
        elif entity.get("local_id"):
            return f"local:{entity['local_id']}"
        else:
            import hashlib
            surface = entity.get("surface", "unknown").lower()
            hash_str = hashlib.sha1(surface.encode()).hexdigest()[:16]
            return f"local:ent:{hash_str}"

    def query_lsh_candidates(self, band_hashes: List[tuple]) -> List[str]:
        """
        Query for candidate duplicates using LSH bands.

        Args:
            band_hashes: List of (band_index, band_hash) tuples

        Returns:
            List of candidate fact IDs
        """
        if not band_hashes:
            return []

        cur = self.db.cursor()

        # Build query for any matching band
        conditions = []
        params = []
        for band_idx, band_hash in band_hashes:
            conditions.append("(band_index = %s AND band_hash = %s)")
            params.extend([band_idx, band_hash])

        query = f"""
            SELECT DISTINCT fact_id FROM fact_minhash
            WHERE {" OR ".join(conditions)}
        """

        cur.execute(query, params)
        return [row["fact_id"] for row in cur.fetchall()]

    def assign_or_create_cluster(
        self,
        fact_id: str,
        candidates: List[str],
        embedding: Optional[List[float]] = None
    ) -> int:
        """
        Assign fact to existing cluster or create new one.

        Args:
            fact_id: Fact identifier
            candidates: Candidate duplicate fact IDs
            embedding: Optional embedding for semantic comparison

        Returns:
            Cluster ID
        """
        cur = self.db.cursor()

        # Check if any candidate is already in a cluster
        if candidates:
            placeholders = ",".join(["%s"] * len(candidates))
            cur.execute(
                f"""
                SELECT cluster_id FROM cluster_members
                WHERE fact_id IN ({placeholders})
                LIMIT 1
                """,
                candidates
            )
            result = cur.fetchone()
            if result:
                cluster_id = result["cluster_id"]
                # Add to existing cluster
                cur.execute(
                    """
                    INSERT INTO cluster_members (cluster_id, fact_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (cluster_id, fact_id)
                )
                # Update cluster stats
                cur.execute(
                    """
                    UPDATE clusters SET global_df = global_df + 1
                    WHERE cluster_id = %s
                    """,
                    (cluster_id,)
                )
                self.db.commit()
                return cluster_id

        # Create new cluster
        cur.execute(
            """
            INSERT INTO clusters (rep_fact_id, global_df)
            VALUES (%s, 1)
            RETURNING cluster_id
            """,
            (fact_id,)
        )
        cluster_id = cur.fetchone()["cluster_id"]

        # Add fact as first member
        cur.execute(
            """
            INSERT INTO cluster_members (cluster_id, fact_id)
            VALUES (%s, %s)
            """,
            (cluster_id, fact_id)
        )

        self.db.commit()
        return cluster_id

    def get_fact(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a fact by ID.

        Args:
            fact_id: Fact identifier

        Returns:
            Fact dictionary or None
        """
        cur = self.db.cursor()
        cur.execute("SELECT * FROM facts WHERE fact_id = %s", (fact_id,))
        return cur.fetchone()

    def get_cluster_members(self, cluster_id: int) -> List[str]:
        """
        Get all fact IDs in a cluster.

        Args:
            cluster_id: Cluster identifier

        Returns:
            List of fact IDs
        """
        cur = self.db.cursor()
        cur.execute(
            "SELECT fact_id FROM cluster_members WHERE cluster_id = %s",
            (cluster_id,)
        )
        return [row["fact_id"] for row in cur.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        """
        Get database statistics.

        Returns:
            Dict with counts
        """
        cur = self.db.cursor()
        stats = {}

        for table in ["entities", "videos", "facts", "clusters"]:
            cur.execute(f"SELECT COUNT(*) as count FROM {table}")
            stats[table] = cur.fetchone()["count"]

        return stats
