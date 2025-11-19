"""Qdrant client for vector storage and similarity search."""

import os
from typing import List, Optional, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    SearchParams,
)

from src.util.logging import get_logger

logger = get_logger("storage.qdrant")

# Default configuration
DEFAULT_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "fact_embeddings"
VECTOR_SIZE = 384  # MiniLM embedding size


class QdrantVectorStore:
    """Vector store using Qdrant for semantic similarity search."""

    def __init__(
        self,
        url: Optional[str] = None,
        collection_name: str = COLLECTION_NAME,
        vector_size: int = VECTOR_SIZE
    ):
        """
        Initialize Qdrant vector store.

        Args:
            url: Qdrant server URL
            collection_name: Name of the collection
            vector_size: Dimension of vectors
        """
        self.url = url or DEFAULT_QDRANT_URL
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._client = None

    @property
    def client(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._client is None:
            self._client = QdrantClient(url=self.url)
            logger.info(f"Connected to Qdrant at {self.url}")
        return self._client

    def ensure_collection(self):
        """Create collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"Created collection: {self.collection_name}")
        else:
            logger.debug(f"Collection {self.collection_name} already exists")

    def upsert_vector(
        self,
        fact_id: str,
        embedding: List[float],
        payload: Optional[Dict[str, Any]] = None
    ):
        """
        Upsert a vector into Qdrant.

        Args:
            fact_id: Unique identifier for the fact
            embedding: Vector embedding
            payload: Additional metadata to store
        """
        if not embedding:
            logger.warning(f"Empty embedding for fact {fact_id}, skipping")
            return

        point = PointStruct(
            id=self._fact_id_to_int(fact_id),
            vector=embedding,
            payload={
                "fact_id": fact_id,
                **(payload or {})
            }
        )

        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
        logger.debug(f"Upserted vector for fact {fact_id}")

    def search_similar(
        self,
        embedding: List[float],
        limit: int = 10,
        score_threshold: float = 0.0,
        filter_conditions: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors.

        Args:
            embedding: Query vector
            limit: Maximum number of results
            score_threshold: Minimum similarity score
            filter_conditions: Optional filter conditions

        Returns:
            List of results with fact_id and score
        """
        if not embedding:
            return []

        # Build filter if provided
        query_filter = None
        if filter_conditions:
            conditions = []
            for key, value in filter_conditions.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            query_filter = Filter(must=conditions)

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=embedding,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter
        )

        return [
            {
                "fact_id": hit.payload.get("fact_id"),
                "score": hit.score,
                "payload": hit.payload
            }
            for hit in results
        ]

    def get_vector(self, fact_id: str) -> Optional[List[float]]:
        """
        Get a vector by fact ID.

        Args:
            fact_id: Fact identifier

        Returns:
            Vector embedding or None
        """
        point_id = self._fact_id_to_int(fact_id)

        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_vectors=True
            )
            if points:
                return points[0].vector
        except Exception as e:
            logger.debug(f"Vector not found for {fact_id}: {e}")

        return None

    def delete_vector(self, fact_id: str):
        """
        Delete a vector by fact ID.

        Args:
            fact_id: Fact identifier
        """
        point_id = self._fact_id_to_int(fact_id)

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=[point_id]
        )
        logger.debug(f"Deleted vector for fact {fact_id}")

    def delete_collection(self):
        """Delete the entire collection."""
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")
        except Exception as e:
            logger.warning(f"Failed to delete collection: {e}")

    def get_collection_info(self) -> Dict[str, Any]:
        """Get collection statistics."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value
            }
        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            return {}

    def _fact_id_to_int(self, fact_id: str) -> int:
        """
        Convert fact_id (SHA1 hex) to integer for Qdrant point ID.

        Args:
            fact_id: SHA1 hex string

        Returns:
            Integer point ID
        """
        # Use first 16 hex chars (64 bits) to avoid overflow
        return int(fact_id[:16], 16)

    def close(self):
        """Close the client connection."""
        if self._client:
            self._client.close()
            self._client = None


# Global instance
_vector_store: Optional[QdrantVectorStore] = None


def get_vector_store(url: Optional[str] = None) -> QdrantVectorStore:
    """
    Get or create global vector store instance.

    Args:
        url: Optional Qdrant URL

    Returns:
        QdrantVectorStore instance
    """
    global _vector_store
    if _vector_store is None:
        _vector_store = QdrantVectorStore(url=url)
        _vector_store.ensure_collection()
    return _vector_store
