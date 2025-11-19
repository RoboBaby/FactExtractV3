#!/usr/bin/env python3
"""
Test harness for the video facts canonicalizer pipeline.

Loads generated test data from resources directory and runs
fact extraction, with database cleanup between runs.

Usage:
    python scripts/test_harness.py
    python scripts/test_harness.py --resource-id 0001
    python scripts/test_harness.py --no-cleanup
    python scripts/test_harness.py --dsn "postgresql://user:pass@host:5432/db"
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.ingest.reader import read_blobs
from src.preprocess.normalize import sentence_split, get_sentence_id, get_evidence_window
from src.srl.client import srl_predict, build_proto_fact
from src.canonicalize.entities import EntityCanonicalizer
from src.canonicalize.predicates import map_predicate
from src.canonicalize.literals import normalize_quantities, render_timex, derive_dct
from src.verify.evidence import claim_from_fact
from src.verify.nli import LocalVerifier
from src.dedup.signature import canonical_string, fact_id_from_canonical, minhash_from_text, band_hashes
from src.dedup.lsh import embed_text, serialize_minhash, compute_jaccard_from_bytes
from src.storage.db import Database
from src.storage.repo import Repo
from src.storage.qdrant_client import get_vector_store
from src.util.logging import setup_logging, get_logger
import os

logger = get_logger("test_harness")


class TestHarness:
    """Test harness for fact extraction pipeline."""

    def __init__(
        self,
        dsn: str,
        resources_dir: str = "resources/generated_data",
        config_path: str = "configs/app.yaml"
    ):
        """
        Initialize test harness.

        Args:
            dsn: Database connection string
            resources_dir: Directory containing generated test data
            config_path: Path to pipeline config
        """
        self.dsn = dsn
        self.resources_dir = Path(resources_dir)
        self.config_path = config_path
        self.config = self._load_config()

        # Results tracking
        self.results = {
            "total_blobs": 0,
            "total_facts": 0,
            "total_entities": 0,
            "total_clusters": 0,
            "errors": [],
            "timing": {}
        }

    def _load_config(self) -> Dict[str, Any]:
        """Load pipeline configuration."""
        import yaml
        config_file = project_root / self.config_path
        if config_file.exists():
            with open(config_file, "r") as f:
                return yaml.safe_load(f)
        else:
            # Default config for testing
            return {
                "srl": {
                    "mode": "service",
                    "endpoint": "http://localhost:8001/predict"
                },
                "entity_linking": {
                    "rel_data_dir": "/data/rel",
                    "min_conf_accept": 0.75
                },
                "timex": {
                    "mode": "none"  # Disable for local testing
                },
                "quantities": {
                    "enable": True,
                    "canonical_units": {
                        "temperature": "celsius",
                        "length": "millimeter",
                        "mass": "gram",
                        "time": "second"
                    }
                },
                "verification": {
                    "enable": False,  # Disable for faster testing
                    "min_support": 0.6
                },
                "dedup": {
                    "minhash": {
                        "n_perm": 128,
                        "bands": 32,
                        "rows_per_band": 4,
                        "shingle_size": 5
                    },
                    "jaccard_threshold": 0.5,
                    "embed_fallback": False,  # Disable for faster testing
                    "embed_model": "sentence-transformers/all-MiniLM-L6-v2"
                },
                "qdrant": {
                    "url": "http://localhost:6333"
                }
            }

    def cleanup_database(self):
        """Clean all tables and Qdrant collection for fresh test run."""
        logger.info("Cleaning database tables...")

        db = Database(self.dsn)
        db.connect()

        # Drop in correct order due to foreign keys
        cleanup_sql = """
            TRUNCATE TABLE cluster_members CASCADE;
            TRUNCATE TABLE clusters CASCADE;
            TRUNCATE TABLE fact_minhash CASCADE;
            TRUNCATE TABLE facts CASCADE;
            TRUNCATE TABLE entities CASCADE;
            TRUNCATE TABLE videos CASCADE;
        """

        try:
            cur = db.cursor()
            cur.execute(cleanup_sql)
            db.commit()
            logger.info("Database tables cleaned")
        except Exception as e:
            logger.error(f"Failed to clean database: {e}")
            db.rollback()
            raise
        finally:
            db.close()

        # Clean Qdrant collection
        try:
            qdrant_url = os.environ.get("QDRANT_URL", self.config.get("qdrant", {}).get("url", "http://localhost:6333"))
            vector_store = get_vector_store(qdrant_url)
            vector_store.delete_collection()
            vector_store.ensure_collection()
            logger.info("Qdrant collection cleaned")
        except Exception as e:
            logger.warning(f"Qdrant cleanup warning: {e}")

    def init_schema(self):
        """Initialize database schema if needed."""
        logger.info("Initializing database schema...")

        db = Database(self.dsn)
        db.connect()

        try:
            db.init_schema()
            logger.info("Schema initialized")
        except Exception as e:
            logger.warning(f"Schema init warning (may already exist): {e}")
        finally:
            db.close()

    def load_resources(self, resource_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Load blobs from resource directories.

        Args:
            resource_id: Specific resource ID to load (loads all if None)

        Returns:
            List of blob dictionaries
        """
        all_blobs = []

        if resource_id:
            # Load specific resource
            resource_dir = self.resources_dir / resource_id
            if resource_dir.exists():
                blobs = self._load_resource_dir(resource_dir)
                all_blobs.extend(blobs)
            else:
                logger.error(f"Resource directory not found: {resource_dir}")
        else:
            # Load all resources
            if not self.resources_dir.exists():
                logger.warning(f"Resources directory not found: {self.resources_dir}")
                return []

            for resource_dir in sorted(self.resources_dir.iterdir()):
                if resource_dir.is_dir() and resource_dir.name.isdigit():
                    blobs = self._load_resource_dir(resource_dir)
                    all_blobs.extend(blobs)

        logger.info(f"Loaded {len(all_blobs)} blobs from resources")
        return all_blobs

    def _load_resource_dir(self, resource_dir: Path) -> List[Dict[str, Any]]:
        """Load blobs from a single resource directory."""
        blobs_file = resource_dir / "blobs.jsonl"
        if not blobs_file.exists():
            logger.warning(f"No blobs.jsonl in {resource_dir}")
            return []

        blobs = list(read_blobs(str(blobs_file)))
        logger.info(f"Loaded {len(blobs)} blobs from {resource_dir.name}")
        return blobs

    def run_extraction(self, blobs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run fact extraction pipeline on blobs.

        Args:
            blobs: List of blob dictionaries

        Returns:
            Extraction results
        """
        start_time = time.time()

        # Initialize components
        repo = Repo(self.dsn)
        el = EntityCanonicalizer(
            self.config["entity_linking"]["rel_data_dir"],
            self.config["entity_linking"]["min_conf_accept"]
        )

        verifier = None
        if self.config["verification"]["enable"]:
            verifier = LocalVerifier(
                self.config["verification"].get("retriever_embedding", "sentence-transformers/all-MiniLM-L6-v2"),
                self.config["verification"].get("nli_model", "roberta-large-mnli"),
                self.config["verification"]["min_support"]
            )

        total_facts = 0

        for blob_idx, blob in enumerate(blobs):
            try:
                facts = self._process_blob(blob, repo, el, verifier)
                total_facts += facts
                logger.info(f"[{blob_idx+1}/{len(blobs)}] Blob {blob['blob_id']}: {facts} facts")
            except Exception as e:
                error_msg = f"Error processing blob {blob['blob_id']}: {e}"
                logger.error(error_msg)
                self.results["errors"].append(error_msg)

        # Get final stats
        stats = repo.get_stats()
        repo.close()

        elapsed = time.time() - start_time

        self.results["total_blobs"] = len(blobs)
        self.results["total_facts"] = stats.get("facts", 0)
        self.results["total_entities"] = stats.get("entities", 0)
        self.results["total_clusters"] = stats.get("clusters", 0)
        self.results["timing"]["extraction_seconds"] = round(elapsed, 2)

        return self.results

    def _process_blob(
        self,
        blob: Dict,
        repo: Repo,
        el: EntityCanonicalizer,
        verifier: Optional[LocalVerifier]
    ) -> int:
        """Process a single blob through the pipeline."""
        # Ensure video exists
        repo.ensure_video(blob["video_id"], blob["channel_id"])

        # Split into sentences
        sentences = sentence_split(blob)
        if not sentences:
            return 0

        facts_extracted = 0

        for sent_idx, (sent, span) in enumerate(sentences):
            # For testing without SRL service, use simple extraction
            try:
                srl_frames = srl_predict(self.config["srl"]["endpoint"], sent)
            except Exception:
                # Fallback: create simple proto-facts from sentence
                srl_frames = self._simple_extract(sent)

            for frame in srl_frames:
                proto = build_proto_fact(frame, sent)

                if not proto.A0:
                    continue

                # Link entities
                subj = el.link_mentions([{"surface": proto.A0}])[0]
                repo.upsert_entity(subj)

                obj = None
                if proto.A1:
                    obj = el.link_mentions([{"surface": proto.A1}])[0]
                    repo.upsert_entity(obj)

                # Qualifiers
                quals = {}
                if self.config["quantities"]["enable"]:
                    quals = normalize_quantities(sent, self.config["quantities"]["canonical_units"])

                if proto.A2:
                    instr = el.link_mentions([{"surface": proto.A2}])[0]
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
                if verifier:
                    evidence_sents = get_evidence_window(sentences, sent_idx, 2)
                    claim = claim_from_fact(fact)
                    vs = verifier.score(claim, evidence_sents)
                    fact["conf"]["verify_support"] = vs
                    if vs < self.config["verification"]["min_support"]:
                        continue

                # Canonical string and ID
                cs = canonical_string(fact)
                fact["canonical_string"] = cs
                fact["fact_id"] = fact_id_from_canonical(cs)

                # MinHash
                mh_config = self.config["dedup"]["minhash"]
                mh = minhash_from_text(cs, mh_config["n_perm"], mh_config["shingle_size"])
                bands = band_hashes(mh, mh_config["bands"], mh_config["rows_per_band"])

                # Serialize MinHash for storage
                mh_bytes = serialize_minhash(mh)

                # Embedding
                embedding = None
                if self.config["dedup"]["embed_fallback"]:
                    embedding = embed_text(cs, self.config["dedup"]["embed_model"])
                fact["canonical_embedding"] = embedding

                # Query for LSH candidates
                candidates = repo.query_lsh_candidates(bands)

                # Filter candidates by Jaccard similarity
                verified_candidates = []
                jaccard_threshold = self.config["dedup"].get("jaccard_threshold", 0.5)
                for cand_id in candidates:
                    cand_mh_bytes = repo.get_minhash_signature(cand_id)
                    if cand_mh_bytes:
                        jaccard = compute_jaccard_from_bytes(mh_bytes, cand_mh_bytes, mh_config["n_perm"])
                        if jaccard >= jaccard_threshold:
                            verified_candidates.append(cand_id)

                # Store fact with MinHash signature
                fact_id = repo.insert_fact(fact, bands, mh_bytes)

                # Store embedding in Qdrant if enabled
                if embedding and self.config["dedup"]["embed_fallback"]:
                    try:
                        qdrant_url = os.environ.get("QDRANT_URL", self.config.get("qdrant", {}).get("url", "http://localhost:6333"))
                        vector_store = get_vector_store(qdrant_url)
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
                repo.assign_or_create_cluster(fact_id, verified_candidates, embedding)

                facts_extracted += 1

        return facts_extracted

    def _simple_extract(self, sent: str):
        """Simple fallback extraction when SRL service unavailable."""
        from src.util.types import SRLFrame

        # Very basic pattern matching for testing
        words = sent.split()
        frames = []

        # Find verbs (simple heuristic)
        verb_endings = ['ing', 'ed', 'es', 's']
        common_verbs = ['is', 'are', 'was', 'were', 'have', 'has', 'do', 'does',
                       'connect', 'use', 'set', 'place', 'turn', 'read', 'need',
                       'connecting', 'using', 'setting', 'placing', 'turning', 'reading']

        for i, word in enumerate(words):
            word_lower = word.lower().rstrip('.,!?;:')

            is_verb = (word_lower in common_verbs or
                      any(word_lower.endswith(end) for end in verb_endings))

            if is_verb and len(word_lower) > 2:
                # Extract arguments
                args = {}

                # Subject: words before verb
                if i > 0:
                    subj_words = words[max(0, i-3):i]
                    args["ARG0"] = " ".join(subj_words).strip(".,!?;:")

                # Object: words after verb
                if i < len(words) - 1:
                    remaining = " ".join(words[i+1:])

                    # Split on prepositions for instrument
                    for prep in [" with ", " using ", " to "]:
                        if prep in remaining.lower():
                            parts = remaining.lower().split(prep)
                            args["ARG1"] = parts[0].strip(".,!?;:")
                            if len(parts) > 1:
                                args["ARG2"] = parts[1].split()[0:4]
                                args["ARG2"] = " ".join(args["ARG2"]).strip(".,!?;:")
                            break
                    else:
                        # No preposition, take next few words as object
                        obj_words = words[i+1:min(i+5, len(words))]
                        args["ARG1"] = " ".join(obj_words).strip(".,!?;:")

                if args.get("ARG0") and args.get("ARG1"):
                    frame = SRLFrame(
                        predicate=word_lower,
                        predicate_lemma=word_lower.rstrip('ingsed'),
                        arguments=args
                    )
                    frames.append(frame)
                    break  # One frame per sentence for simple extraction

        return frames

    def print_report(self):
        """Print test results report."""
        print("\n" + "=" * 60)
        print("TEST HARNESS REPORT")
        print("=" * 60)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("-" * 60)
        print(f"Total blobs processed: {self.results['total_blobs']}")
        print(f"Total facts extracted: {self.results['total_facts']}")
        print(f"Total entities: {self.results['total_entities']}")
        print(f"Total clusters: {self.results['total_clusters']}")
        print(f"Extraction time: {self.results['timing'].get('extraction_seconds', 0)}s")

        if self.results['total_blobs'] > 0:
            avg_facts = self.results['total_facts'] / self.results['total_blobs']
            print(f"Avg facts per blob: {avg_facts:.1f}")

        if self.results['errors']:
            print("-" * 60)
            print(f"Errors ({len(self.results['errors'])}):")
            for err in self.results['errors'][:5]:
                print(f"  - {err}")
            if len(self.results['errors']) > 5:
                print(f"  ... and {len(self.results['errors']) - 5} more")

        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Test harness for video facts canonicalizer"
    )
    parser.add_argument(
        "--dsn",
        type=str,
        default="postgresql://postgres:postgres@localhost:5432/facts",
        help="Database connection string"
    )
    parser.add_argument(
        "--resources-dir",
        type=str,
        default="resources/generated_data",
        help="Directory containing generated test data"
    )
    parser.add_argument(
        "--resource-id",
        type=str,
        default=None,
        help="Specific resource ID to test (e.g., '0001')"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/app.yaml",
        help="Path to pipeline config"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip database cleanup (keep existing data)"
    )
    parser.add_argument(
        "--no-init",
        action="store_true",
        help="Skip schema initialization"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)

    logger.info("Starting test harness")

    # Initialize harness
    harness = TestHarness(
        dsn=args.dsn,
        resources_dir=args.resources_dir,
        config_path=args.config
    )

    # Initialize schema
    if not args.no_init:
        try:
            harness.init_schema()
        except Exception as e:
            logger.error(f"Schema initialization failed: {e}")
            logger.error("Make sure PostgreSQL is running and accessible")
            sys.exit(1)

    # Clean database
    if not args.no_cleanup:
        try:
            harness.cleanup_database()
        except Exception as e:
            logger.error(f"Database cleanup failed: {e}")
            sys.exit(1)

    # Load resources
    blobs = harness.load_resources(args.resource_id)

    if not blobs:
        logger.error("No blobs to process")
        logger.info("Generate test data first: python scripts/generate_test_data.py --count 5")
        sys.exit(1)

    # Run extraction
    try:
        harness.run_extraction(blobs)
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Print report
    harness.print_report()


if __name__ == "__main__":
    main()
