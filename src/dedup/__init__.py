"""Deduplication module for MinHash LSH and clustering."""

from .signature import (
    canonical_string,
    fact_id_from_canonical,
    minhash_from_text,
    band_hashes,
    jaccard_similarity,
)
from .lsh import (
    compute_embedding_similarity,
    embed_text,
    embed_text_cached,
    serialize_minhash,
    deserialize_minhash,
    compute_jaccard,
    compute_jaccard_from_bytes,
    get_embedding_model,
)

__all__ = [
    "canonical_string",
    "fact_id_from_canonical",
    "minhash_from_text",
    "band_hashes",
    "jaccard_similarity",
    "compute_embedding_similarity",
    "embed_text",
    "embed_text_cached",
    "serialize_minhash",
    "deserialize_minhash",
    "compute_jaccard",
    "compute_jaccard_from_bytes",
    "get_embedding_model",
]
