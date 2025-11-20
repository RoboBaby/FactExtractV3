#!/usr/bin/env python3
"""CLI entrypoint for the video facts canonicalizer pipeline."""

import argparse
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.ingest.reader import read_blobs
from src.preprocess.normalize import sentence_split, get_sentence_id, get_evidence_window
from src.preprocess.coref import resolve_pronouns_in_sentences
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
    import time
    start_time = time.time()
    
    blob_id = blob.get("blob_id", "unknown")
    video_id = blob.get("video_id", "unknown")
    logger.info(f"Processing blob {blob_id} (video: {video_id})")
    
    # Ensure video exists
    repo.ensure_video(blob["video_id"], blob["channel_id"])

    # Split into sentences
    logger.info(f"  [1/6] Splitting into sentences...")
    sentences = sentence_split(blob)
    if not sentences:
        logger.warning(f"  No sentences found in blob {blob_id}")
        return 0
    logger.info(f"  [1/6] ✓ Split into {len(sentences)} sentences")

    # Apply coreference resolution if enabled
    if cfg.get("coreference", {}).get("enable", False):
        logger.info(f"  [2/6] Applying coreference resolution...")
        try:
            sentences = resolve_pronouns_in_sentences(sentences)
            logger.info(f"  [2/6] ✓ Coreference resolution complete")
        except Exception as e:
            logger.warning(f"  [2/6] ✗ Coreference resolution failed: {e}, continuing without it")
    else:
        logger.info(f"  [2/6] Coreference resolution disabled")

    facts_extracted = 0
    srl_calls = 0
    entity_links = 0

    logger.info(f"  [3/6] Processing {len(sentences)} sentences for SRL and fact extraction...")
    for sent_idx, (sent, span) in enumerate(sentences):
        if (sent_idx + 1) % 5 == 0 or sent_idx == 0:
            logger.info(f"    Processing sentence {sent_idx + 1}/{len(sentences)}: {sent[:60]}...")
        # Run SRL
        try:
            srl_calls += 1
            srl_frames = srl_predict(cfg["srl"]["endpoint"], sent)
            if srl_frames:
                logger.debug(f"      → SRL extracted {len(srl_frames)} frame(s)")
        except Exception as e:
            logger.warning(f"      ✗ SRL failed for sentence: {e}")
            srl_frames = []

        for frame_idx, frame in enumerate(srl_frames):
            logger.debug(f"      Processing frame {frame_idx + 1}/{len(srl_frames)}: {frame.predicate_lemma}")
            
            # Extract entities from sentence for snapping
            sent_entities = el.extract_entities_from_sentence(sent) if hasattr(el, "extract_entities_from_sentence") else []
            
            # Build proto-fact
            proto = build_proto_fact(frame, sent, entities=sent_entities)

            # Skip if no subject
            if not proto.A0:
                continue

            # Link entities
            logger.debug(f"        Linking subject: {proto.A0}")
            subj = el.link_mentions([{"surface": proto.A0}])[0]
            repo.upsert_entity(subj)
            entity_links += 1
            if subj.get("qid"):
                logger.debug(f"        ✓ Subject linked to Wikidata: {subj['qid']}")
            else:
                logger.debug(f"        → Subject using local ID: {subj.get('local_id', 'unknown')}")

            obj = None
            if proto.A1:
                logger.debug(f"        Linking object: {proto.A1}")
                obj = el.link_mentions([{"surface": proto.A1}])[0]
                repo.upsert_entity(obj)
                entity_links += 1
                if obj.get("qid"):
                    logger.debug(f"        ✓ Object linked to Wikidata: {obj['qid']}")

            # Handle instrument qualifier
            if proto.A2:
                logger.debug(f"        Linking instrument: {proto.A2}")
                instr = el.link_mentions([{"surface": proto.A2}])[0]
                repo.upsert_entity(instr)
                entity_links += 1

            # Normalize quantities
            logger.debug(f"        [4/6] Normalizing quantities...")
            quals = {}
            if cfg["quantities"]["enable"]:
                quals = normalize_quantities(sent, cfg["quantities"]["canonical_units"])
                if quals:
                    logger.debug(f"        ✓ Found quantities: {list(quals.keys())}")

            # Add instrument to qualifiers
            if proto.A2:
                instr = el.link_mentions([{"surface": proto.A2}])[0]
                quals["instrument"] = instr

            # Time normalization
            logger.debug(f"        [5/6] Normalizing temporal expressions...")
            if cfg["timex"]["mode"] != "none":
                try:
                    dct = derive_dct(blob["video_id"])
                    timexes = heideltime_parse(cfg["timex"]["endpoint"], sent, dct)
                    time_quals = render_timex(timexes, blob.get("t_start"), blob.get("t_end"))
                    quals.update(time_quals)
                    if time_quals:
                        logger.debug(f"        ✓ Found temporal expressions: {list(time_quals.keys())}")
                except Exception as e:
                    logger.debug(f"        → Time normalization failed: {e}")

            # Map predicate
            pred = map_predicate(proto.predicate_lemma)

            # Assemble fact
            fact = assemble_fact(blob, subj, obj, pred, quals, sent, span, proto)

            # Verification
            logger.debug(f"        [6/6] Verifying fact...")
            if cfg["verification"]["enable"] and verifier:
                evidence_sents = get_evidence_window(sentences, sent_idx, cfg["verification"]["evidence_window_sentences"])
                claim = claim_from_fact(fact)
                vs = verifier.score(claim, evidence_sents)
                fact["conf"]["verify_support"] = vs
                logger.debug(f"        → Verification score: {vs:.2f}")

                if vs < cfg["verification"]["min_support"]:
                    logger.debug(f"        ✗ Fact below support threshold ({vs:.2f} < {cfg['verification']['min_support']})")
                    continue
                else:
                    logger.debug(f"        ✓ Fact verified (score: {vs:.2f})")

            # Generate canonical string and ID
            logger.debug(f"        Generating canonical fact...")
            cs = canonical_string(fact)
            fact["canonical_string"] = cs
            fact["fact_id"] = fact_id_from_canonical(cs)

            # Generate MinHash
            logger.debug(f"        Checking for duplicates...")
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
            subject_surface = fact.get('subject', {}).get('surface', '?')
            predicate_frame = pred.get('frame', '?')
            object_surface = fact.get('object', {}).get('surface', '?') if fact.get('object') else '(no object)'
            logger.info(f"        ✓ Fact #{facts_extracted}: {subject_surface} {predicate_frame} {object_surface}")

    elapsed = time.time() - start_time
    logger.info(f"  ✓ Blob {blob_id} complete: {facts_extracted} facts extracted in {elapsed:.2f}s")
    logger.info(f"    Stats: {len(sentences)} sentences, {srl_calls} SRL calls, {entity_links} entity links")
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
        cfg["entity_linking"]["min_conf_accept"],
        use_ner=cfg.get("entity_linking", {}).get("use_ner", True)
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
    import time
    pipeline_start = time.time()
    total_facts = 0
    total_blobs = 0
    
    logger.info("=" * 60)
    logger.info("Starting fact extraction pipeline")
    logger.info("=" * 60)

    for blob in read_blobs(args.blobs):
        try:
            logger.info("")
            logger.info(f"[Blob {total_blobs + 1}] Processing: {blob.get('blob_id', 'unknown')}")
            facts = process_blob(blob, cfg, el, verifier, repo)
            total_facts += facts
            total_blobs += 1
            logger.info(f"[Blob {total_blobs}] ✓ Complete: {facts} facts extracted")
        except Exception as e:
            logger.error(f"[Blob {total_blobs + 1}] ✗ Error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            continue

    # Print summary
    stats = repo.get_stats()
    pipeline_elapsed = time.time() - pipeline_start
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Processed: {total_blobs} blob(s)")
    logger.info(f"Extracted: {total_facts} fact(s)")
    logger.info(f"Average: {total_facts / total_blobs:.2f} facts per blob" if total_blobs > 0 else "Average: N/A")
    logger.info(f"Time: {pipeline_elapsed:.2f}s ({pipeline_elapsed / total_blobs:.2f}s per blob)" if total_blobs > 0 else f"Time: {pipeline_elapsed:.2f}s")
    logger.info("")
    logger.info("Database stats:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 60)

    repo.close()


if __name__ == "__main__":
    main()
