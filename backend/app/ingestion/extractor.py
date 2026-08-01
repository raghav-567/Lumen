"""LLM-assisted claim extraction with structured output, caching, and fallback.

Pipeline:
1. Hash chunk text for cache lookup
2. If cached → return immediately
3. Call Ollama (Qwen2.5 3B) for structured JSON extraction
4. Validate + recover malformed JSON
5. Retry on failure (max 3 attempts)
6. Final fallback: rule-based NLTK extractor
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────


@dataclass
class ClaimResult:
    content: str
    original_sentence: str
    importance_weight: float
    # Structured fields (populated by LLM, empty for rule-based fallback)
    subject: str = ""
    predicate: str = ""
    value: str = ""
    condition: str = ""
    effective_from: str = ""
    effective_until: str = ""
    modality: str = "INFORMATIONAL"  # MANDATORY|OPTIONAL|PROHIBITED|RECOMMENDED|INFORMATIONAL
    confidence: float = 1.0
    extraction_model: str = "nltk_rule_based"


# ── Extraction prompt ────────────────────────────────────


EXTRACTION_PROMPT = """You are an expert document analyst. Extract all factual claims from the following text chunk.

For each claim, provide structured JSON with these fields:
- claim: the factual assertion (concise, self-contained statement)
- subject: who or what the claim is about
- predicate: the action or relationship
- value: the specific value, limit, requirement, or outcome
- condition: any conditions or prerequisites (null if none)
- effective_from: effective date if mentioned (null if not stated)
- effective_until: expiration date if mentioned (null if not stated)
- modality: one of "mandatory", "optional", "prohibited", "recommended", "informational"
- confidence: your confidence in the extraction (0.0 to 1.0)

TEXT:
\"\"\"
{chunk_text}
\"\"\"

Respond with ONLY a JSON array. No markdown, no explanation. Example format:
[
  {{
    "claim": "Employees must submit expense reports within 30 days",
    "subject": "employees",
    "predicate": "must submit",
    "value": "expense reports within 30 days",
    "condition": null,
    "effective_from": null,
    "effective_until": null,
    "modality": "mandatory",
    "confidence": 0.95
  }}
]

If no claims can be extracted, respond with: []"""


# ── Cache utilities ──────────────────────────────────────


def compute_content_hash(text: str, model: str = "") -> str:
    """SHA256 hash of chunk text + model version for cache key."""
    key = f"{text.strip()}|{model or settings.EXTRACTION_MODEL}"
    return hashlib.sha256(key.encode()).hexdigest()


# ── LLM extraction ──────────────────────────────────────


def _call_ollama(prompt: str) -> str | None:
    """Call Ollama API for text generation."""
    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={
                "model": settings.EXTRACTION_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 2048,
                },
            },
            timeout=settings.EXTRACTION_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
        elif resp.status_code == 404:
            # Model not pulled yet — trigger pull
            logger.info(f"Model {settings.EXTRACTION_MODEL} not found, pulling...")
            _pull_model()
            return None
        else:
            logger.warning(f"Ollama returned {resp.status_code}: {resp.text[:200]}")
            return None
    except requests.exceptions.ConnectionError:
        logger.warning("Ollama service not reachable")
        return None
    except requests.exceptions.Timeout:
        logger.warning("Ollama request timed out")
        return None
    except Exception as e:
        logger.warning(f"Ollama call failed: {e}")
        return None


def _pull_model():
    """Pull the extraction model into Ollama."""
    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/pull",
            json={"name": settings.EXTRACTION_MODEL, "stream": False},
            timeout=300,  # model download can take a while
        )
        if resp.status_code == 200:
            logger.info(f"Successfully pulled {settings.EXTRACTION_MODEL}")
        else:
            logger.error(f"Failed to pull model: {resp.status_code}")
    except Exception as e:
        logger.error(f"Model pull failed: {e}")


def _parse_llm_response(raw: str) -> list[dict]:
    """Parse LLM JSON output with multi-level recovery."""
    if not raw or not raw.strip():
        return []

    text = raw.strip()

    # Level 1: Direct JSON parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "claims" in result:
            return result["claims"]
    except json.JSONDecodeError:
        pass

    # Level 2: Strip markdown fences
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Level 3: Find JSON array via regex
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Level 4: Try line-by-line JSON objects
    objects = []
    for line in text.split("\n"):
        line = line.strip().rstrip(",")
        if line.startswith("{") and line.endswith("}"):
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if objects:
        return objects

    logger.debug(f"Failed to parse LLM response: {text[:200]}")
    return []


def _validate_claim(raw: dict) -> dict | None:
    """Validate and normalize a single extracted claim."""
    claim_text = raw.get("claim", "").strip()
    if not claim_text or len(claim_text) < 10:
        return None

    modality = (raw.get("modality", "informational") or "informational").lower()
    valid_modalities = {"mandatory", "optional", "prohibited", "recommended", "informational"}
    if modality not in valid_modalities:
        modality = "informational"

    confidence = raw.get("confidence", 0.8)
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        confidence = 0.8

    return {
        "claim": claim_text,
        "subject": str(raw.get("subject", "")).strip() or "",
        "predicate": str(raw.get("predicate", "")).strip() or "",
        "value": str(raw.get("value", "")).strip() or "",
        "condition": str(raw.get("condition") or "").strip() or "",
        "effective_from": str(raw.get("effective_from") or "").strip() or "",
        "effective_until": str(raw.get("effective_until") or "").strip() or "",
        "modality": modality.upper(),  # DB enum requires UPPERCASE
        "confidence": float(confidence),
    }


# ── Main extraction function ────────────────────────────


def extract_claims(text: str) -> list[ClaimResult]:
    """Extract claims from a text chunk using LLM with rule-based fallback.

    Pipeline: noise filter → LLM extraction → JSON parsing → validation → fallback → salience filter
    """
    if not text or len(text.strip()) < 20:
        return []

    # ── Stage 0: Structural noise removal ──
    if settings.NOISE_FILTER_ENABLED:
        from app.pipeline.noise_filter import filter_text_structural
        text = filter_text_structural(text)
        if len(text.strip()) < 20:
            return []

    # Try LLM extraction only if enabled (requires fast Ollama)
    if settings.EXTRACTION_ENABLED:
        claims = _extract_with_llm(text)
        if claims:
            return claims

    # Fallback to rule-based extraction (fast, always works)
    claims = _extract_rule_based(text)

    # ── Stage 1: Claim salience filtering with rejection logging ──
    if settings.NOISE_FILTER_ENABLED and claims:
        from app.pipeline.noise_filter import check_claim_worthy
        from collections import Counter

        before = len(claims)
        filtered = []
        rejection_counts: Counter = Counter()

        for c in claims:
            worthy, reason = check_claim_worthy(c.content)
            if worthy:
                filtered.append(c)
            else:
                rejection_counts[reason] += 1

        claims = filtered
        removed = before - len(claims)
        if removed > 0:
            reasons_str = ", ".join(f"{r}={n}" for r, n in rejection_counts.most_common(5))
            if len(claims) == 0:
                logger.warning(
                    f"Salience filter removed all {before} sentences. "
                    f"Proceeding with 0 claims. Reasons: {reasons_str}. "
                    f"Check filter thresholds if unexpected."
                )
            else:
                logger.info(f"Salience filter: {before} → {len(claims)} claims ({reasons_str})")

    return claims


def _extract_with_llm(text: str) -> list[ClaimResult] | None:
    """Attempt LLM-based structured extraction with retries."""
    prompt = EXTRACTION_PROMPT.format(chunk_text=text[:3000])

    for attempt in range(settings.EXTRACTION_MAX_RETRIES):
        raw_response = _call_ollama(prompt)
        if raw_response is None:
            if attempt < settings.EXTRACTION_MAX_RETRIES - 1:
                wait = (2 ** attempt) * 2  # 2s, 4s, 8s
                logger.info(f"Extraction retry {attempt+1}, waiting {wait}s")
                time.sleep(wait)
            continue

        parsed = _parse_llm_response(raw_response)
        if not parsed:
            continue

        results = []
        for raw_claim in parsed:
            validated = _validate_claim(raw_claim)
            if validated:
                # Compute importance weight from modality
                weight = _modality_weight(validated["modality"])
                results.append(ClaimResult(
                    content=validated["claim"],
                    original_sentence=validated["claim"],
                    importance_weight=weight,
                    subject=validated["subject"],
                    predicate=validated["predicate"],
                    value=validated["value"],
                    condition=validated["condition"],
                    effective_from=validated["effective_from"],
                    effective_until=validated["effective_until"],
                    modality=validated["modality"],
                    confidence=validated["confidence"],
                    extraction_model=settings.EXTRACTION_MODEL,
                ))

        if results:
            logger.info(f"LLM extracted {len(results)} claims from chunk ({len(text)} chars)")
            return results

    return None  # All retries failed


def _modality_weight(modality: str) -> float:
    """Map modality to importance weight."""
    return {
        "mandatory": 1.5,
        "prohibited": 1.5,
        "recommended": 1.2,
        "optional": 0.8,
        "informational": 1.0,
    }.get((modality or "").lower(), 1.0)


# ── Rule-based fallback ─────────────────────────────────


# Preserved from original extractor for graceful degradation
import nltk
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    try:
        nltk.download('punkt_tab', quiet=True)
        nltk.download('punkt', quiet=True)
    except Exception:
        pass

HIGH_WEIGHT_KEYWORDS = [
    "is defined as", "means", "refers to", "must", "shall",
    "is required", "mandatory", "prohibited", "policy states",
    "regulation requires", "standard requires",
]

LOW_WEIGHT_KEYWORDS = [
    "for example", "e.g.", "such as", "for instance",
    "note that", "consider", "typically",
]


def _extract_rule_based(text: str) -> list[ClaimResult]:
    """Original NLTK-based extractor as fallback."""
    try:
        sentences = nltk.sent_tokenize(text)
    except Exception:
        sentences = [s.strip() for s in text.split('.') if s.strip()]

    claims: list[ClaimResult] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15 or len(sentence) > 1000:
            continue
        alpha_ratio = sum(1 for c in sentence if c.isalpha()) / max(len(sentence), 1)
        if alpha_ratio < 0.5:
            continue

        weight = 1.0
        lower = sentence.lower()
        for kw in HIGH_WEIGHT_KEYWORDS:
            if kw in lower:
                weight = 1.5
                break
        for kw in LOW_WEIGHT_KEYWORDS:
            if kw in lower:
                weight = 0.5
                break

        claims.append(ClaimResult(
            content=re.sub(r'\s+', ' ', sentence).strip(),
            original_sentence=sentence,
            importance_weight=weight,
            extraction_model="nltk_rule_based",
        ))

    logger.debug(f"Rule-based: extracted {len(claims)} claims ({len(text)} chars)")
    return claims
