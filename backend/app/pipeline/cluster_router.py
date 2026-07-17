"""Cluster-based semantic routing for contradiction retrieval.

Instead of searching globally across the entire corpus,
claims are assigned to semantic clusters and retrieval is
scoped to the relevant cluster(s).

This converts O(N) global retrieval to O(N/K) cluster-local retrieval
where K = number of clusters.
"""

from __future__ import annotations

import logging
import time

import numpy as np
from sklearn.cluster import MiniBatchKMeans

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton
_router: ClusterRouter | None = None


class ClusterRouter:
    """Assigns claims to semantic clusters for scoped retrieval."""

    def __init__(self, n_clusters: int = 20, batch_size: int = 100):
        self.n_clusters = n_clusters
        self.kmeans = MiniBatchKMeans(
            n_clusters=n_clusters,
            batch_size=batch_size,
            random_state=42,
            n_init=3,
            max_iter=50,
        )
        self.is_fitted = False
        self.cluster_sizes: dict[int, int] = {}

    def fit(self, embeddings: np.ndarray):
        """Fit clusters on existing corpus embeddings."""
        if embeddings.shape[0] < self.n_clusters:
            logger.warning(
                f"Not enough embeddings ({embeddings.shape[0]}) for "
                f"{self.n_clusters} clusters, reducing to {max(2, embeddings.shape[0] // 3)}"
            )
            self.n_clusters = max(2, embeddings.shape[0] // 3)
            self.kmeans = MiniBatchKMeans(
                n_clusters=self.n_clusters,
                batch_size=100,
                random_state=42,
                n_init=3,
                max_iter=50,
            )

        start = time.monotonic()
        self.kmeans.fit(embeddings)
        self.is_fitted = True
        elapsed = time.monotonic() - start

        # Track cluster sizes
        labels = self.kmeans.labels_
        for cid in range(self.n_clusters):
            self.cluster_sizes[cid] = int(np.sum(labels == cid))

        avg_size = np.mean(list(self.cluster_sizes.values()))
        logger.info(
            f"Cluster router: {self.n_clusters} clusters, "
            f"avg_size={avg_size:.0f}, fit_time={elapsed:.3f}s"
        )

    def assign(self, embedding: np.ndarray) -> int:
        """Assign a single embedding to its nearest cluster."""
        if not self.is_fitted:
            return 0
        emb = embedding.reshape(1, -1) if embedding.ndim == 1 else embedding
        return int(self.kmeans.predict(emb)[0])

    def assign_batch(self, embeddings: np.ndarray) -> np.ndarray:
        """Assign a batch of embeddings to clusters."""
        if not self.is_fitted:
            return np.zeros(len(embeddings), dtype=int)
        return self.kmeans.predict(embeddings)

    def get_nearby_clusters(self, embedding: np.ndarray, n_neighbors: int = 2) -> list[int]:
        """Get the nearest N cluster IDs for an embedding.

        Returns the primary cluster + closest neighbors for wider recall.
        """
        if not self.is_fitted:
            return [0]

        emb = embedding.reshape(1, -1) if embedding.ndim == 1 else embedding
        distances = np.linalg.norm(self.kmeans.cluster_centers_ - emb, axis=1)
        nearest = np.argsort(distances)[:n_neighbors]
        return [int(c) for c in nearest]

    def get_metrics(self) -> dict:
        if not self.is_fitted:
            return {"fitted": False}
        sizes = list(self.cluster_sizes.values())
        return {
            "fitted": True,
            "n_clusters": self.n_clusters,
            "avg_cluster_size": round(np.mean(sizes), 1),
            "min_cluster_size": int(np.min(sizes)),
            "max_cluster_size": int(np.max(sizes)),
            "std_cluster_size": round(float(np.std(sizes)), 1),
        }


def get_cluster_router(session=None, org_id: str = "") -> ClusterRouter:
    """Get or initialize the cluster router for an organization.

    Lazily fits on first use by loading all claim embeddings from ChromaDB.
    """
    global _router

    if _router is not None and _router.is_fitted:
        return _router

    _router = ClusterRouter(n_clusters=20)

    # Try to fit from existing embeddings
    if org_id:
        try:
            from app.ingestion.indexer import get_or_create_collection
            collection = get_or_create_collection(org_id, name_suffix="claims")
            result = collection.get(
                include=["embeddings"],
                limit=2000,
            )
            if result and result["embeddings"] and len(result["embeddings"]) >= 20:
                embeddings = np.array(result["embeddings"])
                _router.fit(embeddings)
            else:
                logger.info("Not enough embeddings to fit cluster router, using global retrieval")
        except Exception as e:
            logger.warning(f"Failed to fit cluster router: {e}")

    return _router
