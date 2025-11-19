"""LSH-based deduplication using PostgreSQL and Qdrant.

This module provides deduplication using:
- PostgreSQL for LSH band-based candidate retrieval
- Qdrant for semantic similarity search (vector embeddings)
- MinHash signatures stored in PostgreSQL for Jaccard comparison
"""

import pickle
from typing import List, Optional

from datasketch import MinHash

from src.util.logging import get_logger

logger = get_logger("dedup.lsh")


def compute_embedding_similarity(
    emb1: List[float],
    emb2: List[float]
) -> float:
    """
    Compute cosine similarity between embeddings.

    Args:
        emb1: First embedding vector
        emb2: Second embedding vector

    Returns:
        Cosine similarity score
    """
    if not emb1 or not emb2:
        return 0.0

    try:
        import numpy as np
        a = np.array(emb1)
        b = np.array(emb2)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    except Exception as e:
        logger.error(f"Embedding similarity computation failed: {e}")
        return 0.0


def embed_text(
    text: str,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
) -> Optional[List[float]]:
    """
    Generate embedding for text.

    Args:
        text: Input text
        model_name: Sentence transformer model name

    Returns:
        Embedding vector or None
    """
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return None


def serialize_minhash(mh: MinHash) -> bytes:
    """
    Serialize MinHash object to bytes for database storage.

    Args:
        mh: MinHash object

    Returns:
        Serialized bytes
    """
    return pickle.dumps(mh.hashvalues)


def deserialize_minhash(data: bytes, n_perm: int = 128) -> MinHash:
    """
    Deserialize MinHash from bytes.

    Args:
        data: Serialized bytes
        n_perm: Number of permutations

    Returns:
        MinHash object
    """
    hashvalues = pickle.loads(data)
    mh = MinHash(num_perm=n_perm)
    mh.hashvalues = hashvalues
    return mh


def compute_jaccard(mh1: MinHash, mh2: MinHash) -> float:
    """
    Compute Jaccard similarity between two MinHash signatures.

    Args:
        mh1: First MinHash
        mh2: Second MinHash

    Returns:
        Jaccard similarity score
    """
    return mh1.jaccard(mh2)


def compute_jaccard_from_bytes(
    data1: bytes,
    data2: bytes,
    n_perm: int = 128
) -> float:
    """
    Compute Jaccard similarity from serialized MinHash signatures.

    Args:
        data1: First serialized MinHash
        data2: Second serialized MinHash
        n_perm: Number of permutations

    Returns:
        Jaccard similarity score
    """
    mh1 = deserialize_minhash(data1, n_perm)
    mh2 = deserialize_minhash(data2, n_perm)
    return compute_jaccard(mh1, mh2)


# Lazy-loaded embedding model
_embed_model = None


def get_embedding_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """
    Get or create the embedding model singleton.

    Args:
        model_name: Model name

    Returns:
        SentenceTransformer model
    """
    global _embed_model
    if _embed_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embed_model = SentenceTransformer(model_name)
            logger.info(f"Loaded embedding model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
    return _embed_model


def embed_text_cached(
    text: str,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
) -> Optional[List[float]]:
    """
    Generate embedding using cached model.

    Args:
        text: Input text
        model_name: Sentence transformer model name

    Returns:
        Embedding vector or None
    """
    model = get_embedding_model(model_name)
    if model is None:
        return None

    try:
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return None
