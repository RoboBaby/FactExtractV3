"""Canonical string generation and MinHash signatures."""

import hashlib
import re
import json
from typing import Dict, List, Tuple, Any

from datasketch import MinHash

from src.util.logging import get_logger

logger = get_logger("dedup.signature")


def canonical_string(f: Dict[str, Any]) -> str:
    """
    Create deterministic canonical string for (S|P|O|qualifiers).

    Entities use QIDs or local IDs; numbers normalized; qualifiers sorted.

    Args:
        f: Fact dictionary with subject, predicate, object, qualifiers

    Returns:
        Canonical string representation
    """
    def ent_key(ent: Dict) -> str:
        if ent.get("qid"):
            return f"Q{ent['qid'].lstrip('Q')}"
        if ent.get("local_id"):
            return ent["local_id"]
        return ent.get("surface", "").lower().strip()

    # Subject
    s = ent_key(f.get("subject", {}))

    # Predicate
    pred = f.get("predicate", {})
    p = pred.get("frame", "Unknown") if isinstance(pred, dict) else str(pred)

    # Object
    obj = f.get("object")
    obj_literal = f.get("object_literal")

    if obj and (obj.get("qid") or obj.get("local_id")):
        o = ent_key(obj)
    elif obj and obj.get("surface"):
        o = obj["surface"].lower().strip()
    elif obj_literal is not None:
        o = json.dumps(obj_literal, sort_keys=True)
    else:
        o = ""

    # Normalize qualifiers (sorted keys, normalized values)
    quals = f.get("qualifiers", {}) or {}
    norm_items = []

    for k in sorted(quals.keys()):
        v = quals[k]
        if isinstance(v, dict):
            if "qid" in v:
                norm_items.append(f"{k}={ent_key(v)}")
            elif "value" in v:
                # Numeric value with unit
                val = v.get("value", 0)
                unit = v.get("unit", "")
                norm_items.append(f"{k}={val}_{unit}")
            elif "start" in v:
                # Time interval
                start = v.get("start", "")
                end = v.get("end", "")
                if end:
                    norm_items.append(f"{k}={start}/{end}")
                else:
                    norm_items.append(f"{k}={start}")
            else:
                norm_items.append(f"{k}={json.dumps(v, sort_keys=True)}")
        else:
            norm_items.append(f"{k}={json.dumps(v, sort_keys=True)}")

    q = ";".join(norm_items)

    canon = f"S:{s}|P:{p}|O:{o}|Q:{{{q}}}"
    return canon


def fact_id_from_canonical(canon: str) -> str:
    """
    Generate fact ID from canonical string.

    Args:
        canon: Canonical string

    Returns:
        SHA1 hash as fact ID
    """
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


def minhash_from_text(
    text: str,
    n_perm: int = 128,
    shingle_size: int = 5
) -> MinHash:
    """
    Create MinHash signature from text.

    Args:
        text: Input text (typically canonical string)
        n_perm: Number of permutations
        shingle_size: Size of word shingles

    Returns:
        MinHash object
    """
    tokens = re.findall(r"\w+", text.lower())

    # Create shingles
    if len(tokens) < shingle_size:
        shingles = [" ".join(tokens)]
    else:
        shingles = [
            " ".join(tokens[i:i + shingle_size])
            for i in range(len(tokens) - shingle_size + 1)
        ]

    m = MinHash(num_perm=n_perm)
    for sh in shingles:
        m.update(sh.encode("utf-8"))

    return m


def band_hashes(
    mh: MinHash,
    bands: int,
    rows_per_band: int
) -> List[Tuple[int, str]]:
    """
    Compute LSH band hashes from MinHash signature.

    Args:
        mh: MinHash object
        bands: Number of bands
        rows_per_band: Rows per band

    Returns:
        List of (band_index, band_hash) tuples
    """
    assert bands * rows_per_band == mh.num_perm, \
        f"bands * rows_per_band ({bands * rows_per_band}) must equal num_perm ({mh.num_perm})"

    hashes = []
    sig = list(mh.hashvalues)

    for b in range(bands):
        start = b * rows_per_band
        band = tuple(sig[start:start + rows_per_band])
        # Compact hash for storage
        h = hashlib.sha1("|".join(map(str, band)).encode()).hexdigest()
        hashes.append((b, h))

    return hashes


def jaccard_similarity(mh1: MinHash, mh2: MinHash) -> float:
    """
    Compute Jaccard similarity between two MinHash signatures.

    Args:
        mh1: First MinHash
        mh2: Second MinHash

    Returns:
        Jaccard similarity score
    """
    return mh1.jaccard(mh2)
