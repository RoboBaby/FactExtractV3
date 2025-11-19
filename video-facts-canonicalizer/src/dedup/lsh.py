"""LSH-based deduplication and clustering."""

from typing import List, Dict, Set, Optional, Any
from collections import defaultdict

from src.util.logging import get_logger

logger = get_logger("dedup.lsh")


class LSHIndex:
    """
    In-memory LSH index for candidate retrieval.

    Uses band hashes for fast approximate nearest neighbor lookup.
    """

    def __init__(self, bands: int = 32):
        """
        Initialize LSH index.

        Args:
            bands: Number of bands (must match signature generation)
        """
        self.bands = bands
        # band_index -> band_hash -> set of fact_ids
        self._index: Dict[int, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

    def add(self, fact_id: str, band_hashes: List[tuple]):
        """
        Add a fact to the index.

        Args:
            fact_id: Fact identifier
            band_hashes: List of (band_index, band_hash) tuples
        """
        for band_idx, band_hash in band_hashes:
            self._index[band_idx][band_hash].add(fact_id)

    def query(self, band_hashes: List[tuple]) -> Set[str]:
        """
        Query for candidate duplicates.

        Returns facts that share at least one band hash.

        Args:
            band_hashes: List of (band_index, band_hash) tuples

        Returns:
            Set of candidate fact IDs
        """
        candidates = set()

        for band_idx, band_hash in band_hashes:
            if band_hash in self._index[band_idx]:
                candidates.update(self._index[band_idx][band_hash])

        return candidates

    def remove(self, fact_id: str, band_hashes: List[tuple]):
        """
        Remove a fact from the index.

        Args:
            fact_id: Fact identifier
            band_hashes: List of (band_index, band_hash) tuples
        """
        for band_idx, band_hash in band_hashes:
            if band_hash in self._index[band_idx]:
                self._index[band_idx][band_hash].discard(fact_id)


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


def embed_text(text: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Optional[List[float]]:
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


class DedupManager:
    """
    Manages deduplication and clustering of facts.
    """

    def __init__(
        self,
        jaccard_threshold: float = 0.85,
        cosine_threshold: float = 0.84,
        use_embeddings: bool = True,
        embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        """
        Initialize dedup manager.

        Args:
            jaccard_threshold: MinHash Jaccard threshold for duplicates
            cosine_threshold: Embedding cosine threshold for semantic similarity
            use_embeddings: Whether to use embedding fallback
            embed_model: Sentence transformer model for embeddings
        """
        self.jaccard_threshold = jaccard_threshold
        self.cosine_threshold = cosine_threshold
        self.use_embeddings = use_embeddings
        self.embed_model = embed_model

        self._lsh_index = LSHIndex()
        self._fact_signatures: Dict[str, Any] = {}  # fact_id -> {"minhash": ..., "embedding": ...}
        self._embed_model = None

    def _get_embed_model(self):
        """Lazy load embedding model."""
        if self._embed_model is None and self.use_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                self._embed_model = SentenceTransformer(self.embed_model)
            except Exception as e:
                logger.warning(f"Failed to load embedding model: {e}")
        return self._embed_model

    def add_fact(
        self,
        fact_id: str,
        minhash,
        band_hashes: List[tuple],
        embedding: Optional[List[float]] = None
    ):
        """
        Add a fact to the dedup index.

        Args:
            fact_id: Fact identifier
            minhash: MinHash object
            band_hashes: LSH band hashes
            embedding: Optional embedding vector
        """
        self._lsh_index.add(fact_id, band_hashes)
        self._fact_signatures[fact_id] = {
            "minhash": minhash,
            "embedding": embedding
        }

    def find_duplicates(
        self,
        fact_id: str,
        minhash,
        band_hashes: List[tuple],
        embedding: Optional[List[float]] = None
    ) -> List[str]:
        """
        Find duplicate facts.

        Args:
            fact_id: New fact identifier
            minhash: MinHash of new fact
            band_hashes: LSH band hashes of new fact
            embedding: Optional embedding of new fact

        Returns:
            List of duplicate fact IDs
        """
        # Get LSH candidates
        candidates = self._lsh_index.query(band_hashes)
        candidates.discard(fact_id)  # Remove self

        if not candidates:
            return []

        duplicates = []

        for cand_id in candidates:
            cand_sig = self._fact_signatures.get(cand_id)
            if not cand_sig:
                continue

            # Check MinHash Jaccard
            cand_mh = cand_sig.get("minhash")
            if cand_mh:
                jaccard = minhash.jaccard(cand_mh)
                if jaccard >= self.jaccard_threshold:
                    duplicates.append(cand_id)
                    continue

            # Embedding fallback
            if self.use_embeddings and embedding:
                cand_emb = cand_sig.get("embedding")
                if cand_emb:
                    cosine = compute_embedding_similarity(embedding, cand_emb)
                    if cosine >= self.cosine_threshold:
                        duplicates.append(cand_id)

        return duplicates
