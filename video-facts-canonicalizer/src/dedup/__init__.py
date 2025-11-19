"""Deduplication module for MinHash LSH and clustering."""

from .signature import (
    canonical_string,
    fact_id_from_canonical,
    minhash_from_text,
    band_hashes,
    jaccard_similarity,
)
from .lsh import (
    LSHIndex,
    DedupManager,
    compute_embedding_similarity,
    embed_text,
)

__all__ = [
    "canonical_string",
    "fact_id_from_canonical",
    "minhash_from_text",
    "band_hashes",
    "jaccard_similarity",
    "LSHIndex",
    "DedupManager",
    "compute_embedding_similarity",
    "embed_text",
]
