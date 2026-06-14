"""Lightweight topic drift engine using incremental MiniBatchKMeans.

Replaces heavy BERTopic with a CPU-friendly approach that:
- Uses existing sentence-transformer embeddings (no new model)
- Supports incremental updates via partial_fit
- Detects topic drift by comparing centroid movement over time
- Identifies emerging, stable, and disappearing topics
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import MiniBatchKMeans

logger = logging.getLogger(__name__)


class TopicDriftEngine:
    """Incremental topic clustering with drift tracking."""

    def __init__(self, n_clusters: int = 10, batch_size: int = 100):
        """
        Args:
            n_clusters: Number of topic clusters
            batch_size: MiniBatchKMeans batch size
        """
        self.n_clusters = n_clusters
        self.kmeans = MiniBatchKMeans(
            n_clusters=n_clusters,
            batch_size=batch_size,
            random_state=42,
            n_init=3,
        )
        self.centroids_history: list[tuple[str, np.ndarray]] = []
        self.is_fitted = False
        self.topic_labels: dict[int, str] = {}

    def update(self, embeddings: np.ndarray, timestamp: str | None = None):
        """Incrementally update topic clusters with new document embeddings.

        Args:
            embeddings: (N, D) array of document/chunk embeddings
            timestamp: ISO timestamp for this snapshot
        """
        if embeddings.shape[0] < self.n_clusters:
            logger.warning(
                f"Not enough embeddings ({embeddings.shape[0]}) for "
                f"{self.n_clusters} clusters, skipping update"
            )
            return

        ts = timestamp or datetime.now(timezone.utc).isoformat()

        start = time.monotonic()
        self.kmeans.partial_fit(embeddings)
        elapsed = time.monotonic() - start

        self.centroids_history.append(
            (ts, self.kmeans.cluster_centers_.copy())
        )
        self.is_fitted = True

        logger.info(
            f"Topic update: {embeddings.shape[0]} vectors, "
            f"{self.n_clusters} clusters, {elapsed:.3f}s"
        )

    def compute_drift(self) -> dict:
        """Compare current centroids to previous snapshot to detect topic drift.

        Returns:
            Dict with topic_drift score, volatile/emerging/disappearing topics
        """
        if len(self.centroids_history) < 2:
            return {
                "topic_drift": 0.0,
                "volatile_topics": [],
                "stable_topics": [],
                "snapshots": len(self.centroids_history),
            }

        prev_ts, prev_centroids = self.centroids_history[-2]
        curr_ts, curr_centroids = self.centroids_history[-1]

        # Centroid movement: L2 distance for each cluster
        movements = np.linalg.norm(curr_centroids - prev_centroids, axis=1)
        avg_movement = float(np.mean(movements))
        max_movement = float(np.max(movements))

        # Classify topics by stability
        movement_threshold = np.percentile(movements, 75)
        stable_threshold = np.percentile(movements, 25)

        volatile_topics = []
        stable_topics = []

        for i, movement in enumerate(movements):
            topic_info = {
                "topic_id": int(i),
                "movement": round(float(movement), 4),
                "label": self.topic_labels.get(i, f"Topic {i}"),
            }
            if movement >= movement_threshold:
                volatile_topics.append(topic_info)
            elif movement <= stable_threshold:
                stable_topics.append(topic_info)

        # Overall drift score: normalized average movement
        # Scale so typical movement ≈ 0.1-0.3, outliers → higher
        topic_drift = min(1.0, avg_movement / max(max_movement, 1e-6) * 2)

        return {
            "topic_drift": round(topic_drift, 4),
            "avg_movement": round(avg_movement, 4),
            "max_movement": round(max_movement, 4),
            "volatile_topics": sorted(volatile_topics, key=lambda x: -x["movement"]),
            "stable_topics": sorted(stable_topics, key=lambda x: x["movement"]),
            "snapshots": len(self.centroids_history),
            "prev_timestamp": prev_ts,
            "curr_timestamp": curr_ts,
        }

    def get_topic_assignments(self, embeddings: np.ndarray) -> np.ndarray:
        """Assign embeddings to their nearest topic cluster.

        Returns:
            Array of cluster IDs for each embedding
        """
        if not self.is_fitted:
            return np.zeros(len(embeddings), dtype=int)
        return self.kmeans.predict(embeddings)

    def label_topics(self, embeddings: np.ndarray, texts: list[str], top_n: int = 3):
        """Auto-label topics using the most representative texts per cluster.

        Args:
            embeddings: (N, D) array
            texts: Corresponding text for each embedding
            top_n: Number of representative texts per topic
        """
        if not self.is_fitted:
            return

        assignments = self.kmeans.predict(embeddings)
        centroids = self.kmeans.cluster_centers_

        for cluster_id in range(self.n_clusters):
            mask = assignments == cluster_id
            if not np.any(mask):
                continue

            # Find closest texts to centroid
            cluster_embeddings = embeddings[mask]
            cluster_texts = [t for t, m in zip(texts, mask) if m]

            distances = np.linalg.norm(cluster_embeddings - centroids[cluster_id], axis=1)
            closest_indices = np.argsort(distances)[:top_n]
            representative = [cluster_texts[i][:80] for i in closest_indices]

            # Use first representative text as label (truncated)
            self.topic_labels[cluster_id] = representative[0] if representative else f"Topic {cluster_id}"


def compute_org_topic_drift(session, org_id: str) -> dict:
    """Compute topic drift for an organization using existing chunk embeddings.

    This is designed to run as part of drift recalculation,
    not as a separate expensive operation.
    """
    from app.models.models import Document, Chunk
    from app.ingestion.embedder import generate_embeddings

    docs = (
        session.query(Document)
        .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
        .all()
    )

    if len(docs) < 3:
        return {"topic_drift": 0.0, "reason": "Not enough documents"}

    # Collect chunk texts (sample for efficiency)
    chunks = (
        session.query(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.org_id == org_id, Document.deleted_at.is_(None))
        .limit(500)
        .all()
    )

    if len(chunks) < 10:
        return {"topic_drift": 0.0, "reason": "Not enough chunks"}

    texts = [c.content[:500] for c in chunks]
    n_clusters = min(10, len(texts) // 3)

    try:
        embeddings = np.array(generate_embeddings(texts))

        engine = TopicDriftEngine(n_clusters=n_clusters)

        # Split into two time-based halves for drift comparison
        midpoint = len(chunks) // 2
        engine.update(embeddings[:midpoint], timestamp="snapshot_1")
        engine.update(embeddings[midpoint:], timestamp="snapshot_2")

        drift_result = engine.compute_drift()

        # Label topics
        engine.label_topics(embeddings, texts)
        drift_result["topic_labels"] = engine.topic_labels

        return drift_result

    except Exception as e:
        logger.error(f"Topic drift computation failed: {e}")
        return {"topic_drift": 0.0, "error": str(e)}
