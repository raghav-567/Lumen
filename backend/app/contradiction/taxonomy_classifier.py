"""Five-type contradiction taxonomy classifier.

Replaces the single NLI binary with type-specific detection logic:
  - DIRECT_OPPOSITION:   antonym polarity, both certain
  - OUTCOME_INVERSION:   causal frame, inverted result
  - CAPABILITY_REVERSAL: same mechanism, competence assertion inverted
  - CAUSAL_ATTENUATION:  same outcome claimed, different causation
  - CONFIDENCE_CONFLICT: certain vs hedged on same claim
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from app.contradiction.nli import classify_claim_pairs
from app.ingestion.embedder import generate_embeddings

import numpy as np

logger = logging.getLogger(__name__)


class ContradictionType(str, Enum):
    DIRECT_OPPOSITION   = "direct_opposition"
    OUTCOME_INVERSION   = "outcome_inversion"
    CAPABILITY_REVERSAL = "capability_reversal"
    CAUSAL_ATTENUATION  = "causal_attenuation"
    CONFIDENCE_CONFLICT = "confidence_conflict"


@dataclass
class ClassificationResult:
    type: ContradictionType | None
    confidence: float
    severity: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    reason: str = ""


# ── Entity/attribute alignment via embedding similarity ──

def _compute_similarity(text_a: str, text_b: str) -> float:
    """Compute cosine similarity between two text snippets."""
    embeddings = generate_embeddings([text_a, text_b])
    if len(embeddings) < 2:
        return 0.0
    a = np.array(embeddings[0])
    b = np.array(embeddings[1])
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── Outcome/capability signal patterns ──

_OUTCOME_POSITIVE = re.compile(
    r'\b(offset|exceeded|surpassed|improved|gained|achieved|'
    r'successful|effective|dropped significantly|reduced)\b',
    re.IGNORECASE,
)
_OUTCOME_NEGATIVE = re.compile(
    r'\b(exceeded costs|failed|struggled|insufficient|'
    r'minimal improvement|showed minimal|underperformed|inadequate|'
    r'only partial|partially)\b',
    re.IGNORECASE,
)

_CAPABILITY_POSITIVE = re.compile(
    r'\b(automatically|seamlessly|efficiently|reliably|'
    r'successfully|maintained service|redistributed|adapted)\b',
    re.IGNORECASE,
)
_CAPABILITY_NEGATIVE = re.compile(
    r'\b(struggled to|failed to|unable to|could not|'
    r'only partial|partially|manually|required intervention)\b',
    re.IGNORECASE,
)


class ContradictionTaxonomyClassifier:
    """Classifies contradiction type from proposition pairs."""

    def __init__(self, entity_threshold: float = 0.65, attribute_threshold: float = 0.55):
        self.entity_threshold = entity_threshold
        self.attribute_threshold = attribute_threshold

    def classify(self, prop_a, prop_b) -> ClassificationResult:
        """Classify the type of contradiction between two propositions.

        Args:
            prop_a: Proposition from document A
            prop_b: Proposition from document B

        Returns:
            ClassificationResult with type, confidence, severity
        """
        from app.contradiction.proposition_extractor import Proposition

        # Guard: must share entity + attribute to be comparable
        if not self._entities_align(prop_a.entity, prop_b.entity):
            return ClassificationResult(type=None, confidence=0.0, reason="entities_misaligned")

        if not self._attributes_align(prop_a.attribute, prop_b.attribute):
            return ClassificationResult(type=None, confidence=0.0, reason="attributes_misaligned")

        # ── DIRECT_OPPOSITION: antonym polarity, both certain ──
        if (prop_a.polarity != prop_b.polarity and
            prop_a.polarity in ("positive", "negative") and
            prop_b.polarity in ("positive", "negative") and
            prop_a.confidence_level == "certain" and
            prop_b.confidence_level == "certain"):

            nli_results = classify_claim_pairs([(prop_a.source_sentence, prop_b.source_sentence)])
            if nli_results and nli_results[0]["label"] == "contradiction":
                nli_score = nli_results[0]["score"]
                if nli_score >= 0.80:
                    return ClassificationResult(
                        type=ContradictionType.DIRECT_OPPOSITION,
                        confidence=nli_score,
                        severity="HIGH",
                        reason=f"Polarity opposition: {prop_a.polarity} vs {prop_b.polarity}",
                    )

        # ── OUTCOME_INVERSION: same outcome topic, inverted result ──
        if self._detects_outcome_inversion(prop_a, prop_b):
            return ClassificationResult(
                type=ContradictionType.OUTCOME_INVERSION,
                confidence=0.75,
                severity="HIGH",
                reason="Same outcome claim with inverted result",
            )

        # ── CAPABILITY_REVERSAL: same mechanism, competence inverted ──
        if self._detects_capability_reversal(prop_a, prop_b):
            return ClassificationResult(
                type=ContradictionType.CAPABILITY_REVERSAL,
                confidence=0.70,
                severity="HIGH",
                reason="Same capability with inverted competence assertion",
            )

        # ── CAUSAL_ATTENUATION: same outcome, different causal chain ──
        if self._detects_causal_attenuation(prop_a, prop_b):
            return ClassificationResult(
                type=ContradictionType.CAUSAL_ATTENUATION,
                confidence=0.60,
                severity="MEDIUM",
                reason="Same outcome with different or absent causation",
            )

        # ── CONFIDENCE_CONFLICT: same direction, different certainty ──
        if self._detects_confidence_conflict(prop_a, prop_b):
            return ClassificationResult(
                type=ContradictionType.CONFIDENCE_CONFLICT,
                confidence=0.50,
                severity="LOW",
                reason=f"Certainty mismatch: {prop_a.confidence_level} vs {prop_b.confidence_level}",
            )

        return ClassificationResult(type=None, confidence=0.0)

    def _entities_align(self, entity_a: str, entity_b: str) -> bool:
        """Check if two entities refer to the same concept."""
        if not entity_a or not entity_b:
            return False

        # Exact or substring match
        a_lower, b_lower = entity_a.lower(), entity_b.lower()
        if a_lower == b_lower:
            return True
        if a_lower in b_lower or b_lower in a_lower:
            return True

        # Token overlap (Jaccard) — cheap check before expensive embedding
        stopwords = {"the", "a", "an", "of", "in", "to", "for", "and", "is"}
        tokens_a = set(a_lower.split()) - stopwords
        tokens_b = set(b_lower.split()) - stopwords
        if tokens_a and tokens_b:
            jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
            if jaccard >= 0.5:
                return True

        # Embedding similarity fallback (expensive)
        try:
            sim = _compute_similarity(entity_a, entity_b)
            return sim >= self.entity_threshold
        except Exception:
            return False

    def _attributes_align(self, attr_a: str, attr_b: str) -> bool:
        """Check if two attributes discuss the same property."""
        if not attr_a or not attr_b:
            return False

        a_lower, b_lower = attr_a.lower(), attr_b.lower()
        if a_lower == b_lower:
            return True

        # Check word overlap ratio
        words_a = set(a_lower.split())
        words_b = set(b_lower.split())
        stopwords = {"the", "a", "an", "of", "in", "to", "for", "and", "is", "was", "were", "are"}
        words_a -= stopwords
        words_b -= stopwords

        if not words_a or not words_b:
            return False

        overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
        if overlap >= 0.4:
            return True

        # Embedding similarity fallback
        try:
            sim = _compute_similarity(attr_a, attr_b)
            return sim >= self.attribute_threshold
        except Exception:
            return False

    def _detects_outcome_inversion(self, prop_a, prop_b) -> bool:
        """Detect inverted outcomes: 'costs offset' vs 'costs exceeded'."""
        src_a = prop_a.source_sentence
        src_b = prop_b.source_sentence

        a_positive = bool(_OUTCOME_POSITIVE.search(src_a))
        a_negative = bool(_OUTCOME_NEGATIVE.search(src_a))
        b_positive = bool(_OUTCOME_POSITIVE.search(src_b))
        b_negative = bool(_OUTCOME_NEGATIVE.search(src_b))

        # One positive, other negative on same topic
        return (a_positive and b_negative) or (a_negative and b_positive)

    def _detects_capability_reversal(self, prop_a, prop_b) -> bool:
        """Detect capability claims: 'redistributed automatically' vs 'struggled to redistribute'."""
        src_a = prop_a.source_sentence
        src_b = prop_b.source_sentence

        a_capable = bool(_CAPABILITY_POSITIVE.search(src_a))
        a_incapable = bool(_CAPABILITY_NEGATIVE.search(src_a))
        b_capable = bool(_CAPABILITY_POSITIVE.search(src_b))
        b_incapable = bool(_CAPABILITY_NEGATIVE.search(src_b))

        return (a_capable and b_incapable) or (a_incapable and b_capable)

    def _detects_causal_attenuation(self, prop_a, prop_b) -> bool:
        """Detect same outcome with different causal explanations."""
        # Both propositions discuss same attribute but one attributes causation
        # differently or omits it
        if prop_a.polarity == prop_b.polarity and prop_a.polarity != "neutral":
            # Same direction but different source sentences — could be causal difference
            src_a_words = set(prop_a.source_sentence.lower().split())
            src_b_words = set(prop_b.source_sentence.lower().split())

            causal_markers = {"because", "due", "caused", "resulted", "driven", "attributed", "owing"}
            a_has_causal = bool(src_a_words & causal_markers)
            b_has_causal = bool(src_b_words & causal_markers)

            # One has causal explanation, other doesn't — or both have different ones
            if a_has_causal != b_has_causal:
                return True

        return False

    def _detects_confidence_conflict(self, prop_a, prop_b) -> bool:
        """Detect certainty mismatches on same claim."""
        if prop_a.polarity != prop_b.polarity:
            return False  # Already caught by other types

        # Same polarity but different certainty levels
        certainty_levels = {"certain": 3, "hedged": 2, "speculative": 1}
        level_a = certainty_levels.get(prop_a.confidence_level, 2)
        level_b = certainty_levels.get(prop_b.confidence_level, 2)

        return abs(level_a - level_b) >= 2  # "certain" vs "speculative"
