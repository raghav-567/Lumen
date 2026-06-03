"""Normalized proposition extraction for structured contradiction detection.

Wraps the existing LLM extraction mode (Qwen/Ollama) to produce structured
propositions with entity, attribute, polarity, and confidence metadata.

This enables polarity-aware comparison — catching contradictions that
embedding similarity misses because both sentences use similar vocabulary
but opposite meaning.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Proposition:
    """A normalized factual proposition extracted from a document."""
    entity: str             # primary subject ("decentralized routing system")
    attribute: str          # what is claimed ("traffic oscillation stability")
    polarity: str           # positive / negative / mixed / neutral
    confidence_level: str   # certain / hedged / speculative
    modality: str           # factual / predicted / disputed
    source_sentence: str    # verbatim original
    chunk_id: str = ""
    doc_id: str = ""
    section_heading: str = ""


PROPOSITION_EXTRACTION_PROMPT = """Extract all factual propositions from this paragraph. For each proposition output:
- entity: the primary subject of the claim
- attribute: what specifically is being claimed about that entity
- polarity: positive (improved/increased/succeeded) / negative (worsened/failed/declined) / mixed / neutral
- confidence_level: certain (states/demonstrated/confirmed) / hedged (suggested/partially/some) / speculative (predicted/may/could)
- modality: factual / predicted / disputed
- source_sentence: the exact verbatim sentence this came from

Return ONLY a JSON array. No preamble, no markdown fences.
If a sentence contains no falsifiable factual claim, omit it.

Text:
{text}"""


# ── Polarity signal words ──────────────────────────────

_POSITIVE_SIGNALS = frozenset({
    "increased", "improved", "succeeded", "enhanced", "boosted",
    "gained", "rose", "grew", "strengthened", "exceeded",
    "effective", "efficient", "successful", "positive", "benefit",
    "offset", "maintained", "stable", "robust", "thrived",
    "dropped", "reduced", "decreased",  # for costs/problems these are positive
})

_NEGATIVE_SIGNALS = frozenset({
    "decreased", "declined", "failed", "worsened", "struggled",
    "insufficient", "inadequate", "minimal", "limited", "partial",
    "fell", "dropped", "reduced", "deteriorated", "collapsed",
    "exceeded",  # for costs this is negative
    "stalled", "stagnated", "underperformed",
})

_HEDGING_SIGNALS = frozenset({
    "suggested", "partially", "some", "somewhat", "may",
    "could", "might", "possibly", "potentially", "appears",
    "seems", "approximately", "roughly", "about",
})

_CERTAIN_SIGNALS = frozenset({
    "demonstrated", "confirmed", "proved", "established",
    "clearly", "significantly", "definitively", "conclusively",
    "states", "shows", "reveals", "indicates",
})


def extract_propositions(
    text: str,
    chunk_id: str = "",
    doc_id: str = "",
    section_heading: str = "",
) -> list[Proposition]:
    """Extract normalized propositions from text.

    Uses LLM extraction if available, falls back to rule-based extraction.
    """
    if not text or len(text.strip()) < 30:
        return []

    # Try LLM extraction first
    if settings.EXTRACTION_ENABLED:
        props = _extract_with_llm(text, chunk_id, doc_id, section_heading)
        if props:
            return props

    # Rule-based fallback
    return _extract_rule_based(text, chunk_id, doc_id, section_heading)


def _extract_with_llm(
    text: str, chunk_id: str, doc_id: str, section_heading: str
) -> list[Proposition] | None:
    """Extract propositions using Ollama/Qwen LLM."""
    import requests

    prompt = PROPOSITION_EXTRACTION_PROMPT.format(text=text[:3000])

    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={
                "model": settings.EXTRACTION_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2000},
            },
            timeout=settings.EXTRACTION_TIMEOUT,
        )
        if resp.status_code != 200:
            return None

        raw = resp.json().get("response", "")
        return _parse_llm_propositions(raw, chunk_id, doc_id, section_heading)
    except Exception as e:
        logger.debug(f"LLM proposition extraction failed: {e}")
        return None


def _parse_llm_propositions(
    raw: str, chunk_id: str, doc_id: str, section_heading: str
) -> list[Proposition] | None:
    """Parse LLM response into Proposition objects."""
    # Clean JSON from response
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON array in response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return None
        try:
            items = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    if not isinstance(items, list):
        return None

    propositions = []
    for item in items:
        if not isinstance(item, dict):
            continue

        entity = str(item.get("entity", "")).strip()
        attribute = str(item.get("attribute", "")).strip()
        source = str(item.get("source_sentence", "")).strip()

        if not entity or not attribute:
            continue

        polarity = str(item.get("polarity", "neutral")).strip().lower()
        if polarity not in ("positive", "negative", "mixed", "neutral"):
            polarity = _infer_polarity(source)

        confidence_level = str(item.get("confidence_level", "certain")).strip().lower()
        if confidence_level not in ("certain", "hedged", "speculative"):
            confidence_level = _infer_confidence(source)

        modality = str(item.get("modality", "factual")).strip().lower()
        if modality not in ("factual", "predicted", "disputed"):
            modality = "factual"

        prop = Proposition(
            entity=entity,
            attribute=attribute,
            polarity=polarity,
            confidence_level=confidence_level,
            modality=modality,
            source_sentence=source,
            chunk_id=chunk_id,
            doc_id=doc_id,
            section_heading=section_heading,
        )

        # Polarity validation
        prop = _validate_polarity(prop)
        propositions.append(prop)

    return propositions if propositions else None


def _extract_rule_based(
    text: str, chunk_id: str, doc_id: str, section_heading: str
) -> list[Proposition]:
    """Rule-based proposition extraction from sentences.

    Splits text into sentences, infers entity/attribute/polarity from
    syntactic patterns. Less accurate than LLM but always available.
    """
    import nltk
    try:
        sentences = nltk.sent_tokenize(text)
    except Exception:
        sentences = re.split(r'(?<=[.!?])\s+', text)

    propositions = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 30 or len(sentence.split()) < 5:
            continue

        # Simple entity extraction: first noun phrase (capitalized words at start)
        words = sentence.split()
        entity_words = []
        for w in words[:6]:
            if w[0].isupper() or w.lower() in ("the", "a", "an"):
                entity_words.append(w)
            else:
                break
        entity = " ".join(entity_words) if entity_words else words[0]

        # Attribute: rest of sentence minus entity
        attribute = " ".join(words[len(entity_words):])[:100]

        polarity = _infer_polarity(sentence)
        confidence_level = _infer_confidence(sentence)

        propositions.append(Proposition(
            entity=entity,
            attribute=attribute,
            polarity=polarity,
            confidence_level=confidence_level,
            modality="factual",
            source_sentence=sentence,
            chunk_id=chunk_id,
            doc_id=doc_id,
            section_heading=section_heading,
        ))

    return propositions


def _infer_polarity(text: str) -> str:
    """Infer polarity from signal words in text."""
    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))

    pos_count = len(words & _POSITIVE_SIGNALS)
    neg_count = len(words & _NEGATIVE_SIGNALS)

    # Check for negation
    has_negation = any(neg in lower for neg in (
        "not ", "no ", "never ", "neither ", "nor ",
        "didn't", "doesn't", "don't", "won't", "can't",
        "failed to", "unable to", "lack of",
    ))

    if has_negation:
        pos_count, neg_count = neg_count, pos_count

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    elif pos_count > 0 and neg_count > 0:
        return "mixed"
    return "neutral"


def _infer_confidence(text: str) -> str:
    """Infer confidence level from hedging/certainty signals."""
    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))

    hedge_count = len(words & _HEDGING_SIGNALS)
    certain_count = len(words & _CERTAIN_SIGNALS)

    if hedge_count > certain_count:
        return "hedged"
    if certain_count > 0:
        return "certain"
    # Check for speculative markers
    if any(s in lower for s in ("predict", "forecast", "expect", "anticipate")):
        return "speculative"
    return "certain"


def _validate_polarity(prop: Proposition) -> Proposition:
    """Validate extracted polarity against source sentence signals.

    Flags cases where LLM-extracted polarity contradicts strong signal words.
    """
    source_lower = prop.source_sentence.lower()

    strong_negative = any(w in source_lower for w in (
        "failed", "declined", "worsened", "insufficient", "collapsed",
        "struggled", "deteriorated", "inadequate",
    ))

    if prop.polarity == "positive" and strong_negative:
        logger.warning(
            f"Polarity mismatch: extracted 'positive' but source contains "
            f"strong negative signals. Source: '{prop.source_sentence[:80]}'"
        )
        prop.polarity = "negative"

    strong_positive = any(w in source_lower for w in (
        "succeeded", "improved", "enhanced", "thrived", "exceeded expectations",
    ))

    if prop.polarity == "negative" and strong_positive:
        logger.warning(
            f"Polarity mismatch: extracted 'negative' but source contains "
            f"strong positive signals. Source: '{prop.source_sentence[:80]}'"
        )
        prop.polarity = "positive"

    return prop
