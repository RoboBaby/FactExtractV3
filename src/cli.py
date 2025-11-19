#!/usr/bin/env python3
"""CLI entrypoint for the video facts canonicalizer pipeline."""

import argparse
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.ingest.reader import read_blobs
from src.preprocess.normalize import sentence_split, get_sentence_id, get_evidence_window
from src.srl.client import srl_predict, build_proto_fact, extract_mentions_from_proto
from src.canonicalize.entities import EntityCanonicalizer
from src.canonicalize.predicates import map_predicate
from src.canonicalize.literals import heideltime_parse, normalize_quantities, render_timex, derive_dct
from src.verify.evidence import claim_from_fact
from src.verify.nli import LocalVerifier
from src.dedup.signature import canonical_string, fact_id_from_canonical, minhash_from_text, band_hashes
from src.dedup.lsh import embed_text, serialize_minhash, compute_jaccard_from_bytes
from src.storage.repo import Repo
from src.storage.qdrant_client import get_vector_store
from src.util.logging import setup_logging, get_logger
import os

logger = get_logger("cli")


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def assemble_fact(
    blob: Dict,
    subject: Dict,
    obj: Optional[Dict],
    predicate: Dict,
    qualifiers: Dict,
    sent: str,
    span,
    proto
) -> Dict[str, Any]:
    """
    Assemble a canonical fact from components.

    Args:
        blob: Source blob
        subject: Subject entity reference
        obj: Object entity reference (or None)
        predicate: Predicate reference
        qualifiers: Normalized qualifiers
        sent: Source sentence
        span: Sentence span
        proto: Proto-fact

    Returns:
        Canonical fact dictionary
    """
    fact = {
        "video_id": blob["video_id"],
        "channel_id": blob["channel_id"],
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "object_literal": None,
        "qualifiers": qualifiers,
        "evidence": {
            "blob_id": blob["blob_id"],
            "sent_id": get_sentence_id(blob, span),
            "char_span": [span.start, span.end],
            "frames": blob.get("frames")
        },
        "conf": {
            "el": subject.get("el_conf", 0.0),
            "srl": 1.0,  # Placeholder
            "verify_support": 0.0
        },
        "t_start": blob.get("t_start"),
        "t_end": blob.get("t_end")
    }

    # Handle object as literal if no entity
    if not obj and proto.A1:
        fact["object_literal"] = proto.A1

    return fact


def process_blob(
    blob: Dict,
    cfg: Dict,
    el: EntityCanonicalizer,
    verifier: Optional[LocalVerifier],
    repo: Repo
) -> int:
    """
    Process a single blob through the pipeline.

    Args:
        blob: Input blob
        cfg: Configuration
        el: Entity canonicalizer
        verifier: Local verifier (or None)
        repo: Storage repository

    Returns:
        Number of facts extracted
    """
    # Ensure video exists
    repo.ensure_video(blob["video_id"], blob["channel_id"])

    # Split into sentences
    sentences = sentence_split(blob)
    if not sentences:
        return 0

    facts_extracted = 0

    for sent_idx, (sent, span) in enumerate(sentences):
        # Run SRL
        try:
            srl_frames = srl_predict(cfg["srl"]["endpoint"], sent)
        except Exception as e:
            logger.warning(f"SRL failed for sentence: {e}")
            srl_frames = []

        for frame in srl_frames:
            # Build proto-fact
            proto = build_proto_fact(frame, sent)

            # Skip if no subject
            if not proto.A0:
                continue

            # Link entities
            subj = el.link_mentions([{"surface": proto.A0}])[0]
            repo.upsert_entity(subj)

            obj = None
            if proto.A1:
                obj = el.link_mentions([{"surface": proto.A1}])[0]
                repo.upsert_entity(obj)

            # Handle instrument qualifier
            if proto.A2:
                instr = el.link_mentions([{"surface": proto.A2}])[0]
                repo.upsert_entity(instr)

            # Normalize quantities
            quals = {}
            if cfg["quantities"]["enable"]:
                quals = normalize_quantities(sent, cfg["quantities"]["canonical_units"])

            # Add instrument to qualifiers
            if proto.A2:
                instr = el.link_mentions([{"surface": proto.A2}])[0]
                quals["instrument"] = instr

            # Time normalization
            if cfg["timex"]["mode"] != "none":
                try:
                    dct = derive_dct(blob["video_id"])
                    timexes = heideltime_parse(cfg["timex"]["endpoint"], sent, dct)
                    time_quals = render_timex(timexes, blob.get("t_start"), blob.get("t_end"))
                    quals.update(time_quals)
                except Exception as e:
                    logger.debug(f"Time normalization failed: {e}")

            # Map predicate
            pred = map_predicate(proto.predicate_lemma)

            # Assemble fact
            fact = assemble_fact(blob, subj, obj, pred, quals, sent, span, proto)

            # Verification
            if cfg["verification"]["enable"] and verifier:
                evidence_sents = get_evidence_window(sentences, sent_idx, cfg["verification"]["evidence_window_sentences"])
                claim = claim_from_fact(fact)
                vs = verifier.score(claim, evidence_sents)
                fact["conf"]["verify_support"] = vs

                if vs < cfg["verification"]["min_support"]:
                    logger.debug(f"Fact below support threshold: {vs}")
                    continue

            # Generate canonical string and ID
            cs = canonical_string(fact)
            fact["canonical_string"] = cs
            fact["fact_id"] = fact_id_from_canonical(cs)

            # Generate MinHash
            mh = minhash_from_text(
                cs,
                cfg["dedup"]["minhash"]["n_perm"],
                cfg["dedup"]["minhash"]["shingle_size"]
            )
            bands = band_hashes(
                mh,
                cfg["dedup"]["minhash"]["bands"],
                cfg["dedup"]["minhash"]["rows_per_band"]
            )

            # Serialize MinHash for storage
            mh_bytes = serialize_minhash(mh)

            # Generate embedding
            embedding = None
            if cfg["dedup"]["embed_fallback"]:
                embedding = embed_text(cs, cfg["dedup"]["embed_model"])
            fact["canonical_embedding"] = embedding

            # Query for LSH candidates
            candidates = repo.query_lsh_candidates(bands)

            # Filter candidates by Jaccard similarity
            verified_candidates = []
            for cand_id in candidates:
                cand_mh_bytes = repo.get_minhash_signature(cand_id)
                if cand_mh_bytes:
                    jaccard = compute_jaccard_from_bytes(mh_bytes, cand_mh_bytes, cfg["dedup"]["minhash"]["n_perm"])
                    if jaccard >= cfg["dedup"]["jaccard_threshold"]:
                        verified_candidates.append(cand_id)

            # Store fact with MinHash signature
            fact_id = repo.insert_fact(fact, bands, mh_bytes)

            # Store embedding in Qdrant if enabled
            if embedding and cfg["dedup"]["embed_fallback"]:
                try:
                    qdrant_url = os.environ.get("QDRANT_URL", cfg.get("qdrant", {}).get("url", "http://localhost:6333"))
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
            logger.debug(f"Extracted fact: {fact_id}")

    return facts_extracted


def main():
    """Main CLI entrypoint."""
    ap = argparse.ArgumentParser(description="Video Facts Canonicalizer Pipeline")
    ap.add_argument("--blobs", required=True, help="Path to input JSONL file")
    ap.add_argument("--config", default="configs/app.yaml", help="Path to config YAML")
    ap.add_argument("--init-db", action="store_true", help="Initialize database schema")
    ap.add_argument("--log-level", default="INFO", help="Logging level")
    args = ap.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger.info("Starting video facts canonicalizer")

    # Load configuration
    cfg = load_config(args.config)
    logger.info(f"Loaded configuration from {args.config}")

    # Initialize repository
    repo = Repo(cfg["db"]["dsn"])

    # Initialize schema if requested
    if args.init_db:
        from src.storage.db import Database
        db = Database(cfg["db"]["dsn"])
        db.connect()
        db.init_schema()
        db.close()
        logger.info("Database schema initialized")

    # Initialize entity canonicalizer
    el = EntityCanonicalizer(
        cfg["entity_linking"]["rel_data_dir"],
        cfg["entity_linking"]["min_conf_accept"]
    )

    # Initialize verifier
    verifier = None
    if cfg["verification"]["enable"]:
        verifier = LocalVerifier(
            cfg["verification"]["retriever_embedding"],
            cfg["verification"]["nli_model"],
            cfg["verification"]["min_support"]
        )

    # Process blobs
    total_facts = 0
    total_blobs = 0

    for blob in read_blobs(args.blobs):
        try:
            facts = process_blob(blob, cfg, el, verifier, repo)
            total_facts += facts
            total_blobs += 1
            logger.info(f"Processed blob {blob['blob_id']}: {facts} facts")
        except Exception as e:
            logger.error(f"Error processing blob {blob['blob_id']}: {e}")
            continue

    # Print summary
    stats = repo.get_stats()
    logger.info(f"Processing complete: {total_blobs} blobs, {total_facts} facts")
    logger.info(f"Database stats: {stats}")

    repo.close()


if __name__ == "__main__":
    main()
