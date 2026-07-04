"""Contradiction detection engine using Google Gemini API and local NLI.

Pipeline:
1. Candidate selection: retrieve top-K similar chunks for a given document
2. Pairwise comparison: filter by semantic similarity threshold
3. LLM classification: send pairs to Gemini for CONSISTENT/CONTRADICTORY/SUPERSEDES/UNRELATED
4. Post-processing: filter low-confidence, deduplicate
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from app.core.config import settings
from app.ingestion.embedder import generate_embeddings
from app.ingestion.indexer import query_similar
from app.contradiction.nli import classify_claim_pairs
from app.pipeline.noise_filter import is_structural_noise, _STOPWORDS

logger = logging.getLogger(__name__)

_TERM_RE = re.compile(r"[a-z0-9]+")


def _shared_salient_terms(text_a: str, text_b: str) -> int:
    """Count salient (non-stopword, >2 char) terms common to both claims.

    A proxy for "are these two claims about the same subject" — used to reject
    same-topic-but-different-subject NLI false positives.
    """
    def terms(s: str) -> set[str]:
        return {t for t in _TERM_RE.findall(s.lower()) if len(t) > 2 and t not in _STOPWORDS}

    return len(terms(text_a) & terms(text_b))


@dataclass
class ContradictionResult:
    chunk_a_id: str
    chunk_b_id: str
    chunk_a_text: str
    chunk_b_text: str
    classification: str  # CONSISTENT, CONTRADICTORY, SUPERSEDES, UNRELATED
    confidence: float
    explanation: str
    conflicting_claims: list[str]
    sampled: bool = False          # True if this pair was below the gate but retained for calibration
    gate_similarity: float = 0.0   # embedding cosine similarity at time of detection
    confidence_band: str = ""      # "high", "borderline", or "" — routes borderline to review queue
    requires_review: bool = False  # True for borderline pairs that need human validation
    scan_path: str = ""            # "structured" or "embedding" — which router path produced this
    contradiction_type: str = ""   # taxonomy subtype (direct_opposition, outcome_inversion, ...)


# ── Gemini client ────────────────────────────────────────────────


def _get_gemini_client() -> genai.Client:
    """Create Gemini API client."""
    return genai.Client(api_key=settings.GEMINI_API_KEY)


# ── Prompt template ──────────────────────────────────────────────


CLASSIFICATION_PROMPT = """You are an expert document analyst specializing in detecting contradictions and inconsistencies in organizational documents.

Compare these two passages from organizational documents and classify their relationship.

PASSAGE A (from "{doc_a_title}", dated {doc_a_date}):
\"\"\"{chunk_a_text}\"\"\"

PASSAGE B (from "{doc_b_title}", dated {doc_b_date}):
\"\"\"{chunk_b_text}\"\"\"

Classify their relationship as exactly one of:
- CONSISTENT: Both passages agree or are compatible
- CONTRADICTORY: The passages contain conflicting information
- SUPERSEDES: Passage B updates or replaces information in Passage A
- UNRELATED: The passages discuss different topics

Respond in JSON format:
{{
  "classification": "CONSISTENT|CONTRADICTORY|SUPERSEDES|UNRELATED",
  "confidence": 0.0-1.0,
  "explanation": "Brief explanation of your reasoning",
  "conflicting_claims": ["claim from A", "contradicting claim from B"]
}}"""


# ── Candidate retrieval ─────────────────────────────────────────


def find_similar_chunks(
    org_id: str,
    chunk_id: str,
    chunk_text: str,
    top_k: int = 5,
) -> list[dict]:
    """Find similar chunks from other documents via ChromaDB."""
    from app.ingestion.embedder import generate_single_embedding
    query_embedding = generate_single_embedding(chunk_text)

    results = query_similar(org_id, query_embedding, top_k=top_k + 5)

    candidates = []
    if results["ids"] and results["ids"][0]:
        for i, cid in enumerate(results["ids"][0]):
            if cid == chunk_id:
                continue

            distance = results["distances"][0][i] if results["distances"] else 1.0
            similarity = 1.0 - distance
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            text = results["documents"][0][i] if results["documents"] else ""

            if similarity >= settings.SIMILARITY_THRESHOLD:
                candidates.append({
                    "id": cid,
                    "text": text,
                    "document_id": metadata.get("document_id", ""),
                    "similarity": similarity,
                    "metadata": metadata,
                })

    return candidates[:top_k]


# ── LLM classification ──────────────────────────────────────────


def classify_contradiction(
    chunk_a_text: str,
    chunk_b_text: str,
    doc_a_title: str = "Document A",
    doc_b_title: str = "Document B",
    doc_a_date: str = "Unknown",
    doc_b_date: str = "Unknown",
) -> dict:
    """Use Gemini to classify the relationship between two text chunks."""
    prompt = CLASSIFICATION_PROMPT.format(
        doc_a_title=doc_a_title,
        doc_b_title=doc_b_title,
        doc_a_date=doc_a_date,
        doc_b_date=doc_b_date,
        chunk_a_text=chunk_a_text[:2000],
        chunk_b_text=chunk_b_text[:2000],
    )

    try:
        client = _get_gemini_client()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=500,
            ),
        )
        text = response.text.strip()
        # Try to extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        result = json.loads(text)
        return {
            "classification": result.get("classification", "UNRELATED"),
            "confidence": float(result.get("confidence", 0.5)),
            "explanation": result.get("explanation", ""),
            "conflicting_claims": result.get("conflicting_claims", []),
        }
    except Exception as e:
        logger.error(f"Gemini classification failed: {e}")
        return {
            "classification": "UNRELATED",
            "confidence": 0.0,
            "explanation": f"Classification failed: {str(e)}",
            "conflicting_claims": [],
        }


# ── Full scan ────────────────────────────────────────────────────


def scan_document_contradictions(
    org_id: str,
    document_id: str,
    chunks: list[dict],
) -> list[ContradictionResult]:
    """Scan all chunks of a document for contradictions with other documents."""
    all_results = []

    for chunk in chunks:
        candidates = find_similar_chunks(
            org_id, chunk["embedding_id"], chunk["content"],
            top_k=settings.MAX_COMPARISONS_PER_CHUNK,
        )

        for cand in candidates:
            if cand["document_id"] == document_id:
                continue

            result = classify_contradiction(
                chunk["content"], cand["text"],
                doc_a_title=chunk.get("document_title", "Source"),
                doc_b_title=cand["metadata"].get("document_title", "Target"),
            )

            if result["classification"] in ("CONTRADICTORY", "SUPERSEDES"):
                if result["confidence"] >= settings.CONTRADICTION_CONFIDENCE_THRESHOLD:
                    all_results.append(ContradictionResult(
                        chunk_a_id=chunk["embedding_id"],
                        chunk_b_id=cand["id"],
                        chunk_a_text=chunk["content"],
                        chunk_b_text=cand["text"],
                        classification=result["classification"],
                        confidence=result["confidence"],
                        explanation=result["explanation"],
                        conflicting_claims=result.get("conflicting_claims", []),
                    ))

    return _deduplicate(all_results)


# ── NLI-based claim scanning ────────────────────────────────────


EXPLANATION_PROMPT = """You are an expert document analyst. Two claims from an organization's knowledge base have been flagged as contradictory by an automated system.

Claim A: "{claim_a}"

Claim B: "{claim_b}"

Write a clear, concise 1-2 sentence explanation of how these two claims contradict each other. Focus on the specific factual difference. Do not use technical jargon. Write as if explaining to a non-technical stakeholder.

Respond with ONLY the explanation text, no JSON or formatting."""


def _generate_explanation(claim_a: str, claim_b: str, nli_score: float) -> str:
    """Generate a human-readable explanation of why two claims contradict.

    Tries Groq (Llama 3.3 70B, free tier) first, then Gemini, then fallback.
    """
    prompt_text = EXPLANATION_PROMPT.format(
        claim_a=claim_a[:500],
        claim_b=claim_b[:500],
    )

    # ── Try Groq first (free, fast, generous limits) ──
    if settings.GROQ_API_KEY:
        explanation = _call_groq(prompt_text)
        if explanation:
            return explanation

    # ── Fallback to Gemini ──
    if settings.GEMINI_API_KEY:
        explanation = _call_gemini(prompt_text)
        if explanation:
            return explanation

    # ── Final fallback: descriptive template ──
    return (
        f"These two statements present conflicting information. "
        f"The system detected a contradiction with {nli_score*100:.0f}% confidence. "
        f"Review both claims to determine which reflects the current policy."
    )


def _call_groq(prompt: str) -> str | None:
    """Call Groq API (Llama 3.3 70B) via REST. No extra packages needed."""
    import time
    import requests

    max_retries = 2
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 200,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"].strip()
                if text and len(text) > 10:
                    return text
            elif resp.status_code == 429:
                wait = (2 ** attempt) * 3
                logger.info(f"Groq rate limited, retrying in {wait}s")
                time.sleep(wait)
                continue
            else:
                logger.warning(f"Groq API returned {resp.status_code}: {resp.text[:200]}")
                break
        except Exception as e:
            logger.warning(f"Groq API call failed: {e}")
            break
    return None


def _call_gemini(prompt: str) -> str | None:
    """Call Gemini API with retry for rate limits."""
    import time

    max_retries = 2
    for attempt in range(max_retries):
        try:
            client = _get_gemini_client()
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=200,
                ),
            )
            text = response.text.strip()
            if text and len(text) > 10:
                return text
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                wait = (2 ** attempt) * 5
                logger.info(f"Gemini rate limited, retrying in {wait}s")
                time.sleep(wait)
                continue
            logger.warning(f"Gemini explanation failed: {e}")
            break
    return None


# ── Fix 2.2: Entailment asymmetry check ─────────────────

def is_genuine_contradiction(
    claim_a: str, claim_b: str
) -> tuple[bool, str]:
    """Run NLI in both directions to detect elaboration vs genuine contradiction.

    If either direction returns ENTAILMENT, it's elaboration not contradiction.
    Both directions must show CONTRADICTION for a genuine bidirectional contradiction.
    """
    forward_results = classify_claim_pairs([(claim_a, claim_b)])
    reverse_results = classify_claim_pairs([(claim_b, claim_a)])

    if not forward_results or not reverse_results:
        return False, "nli_failure"

    forward = forward_results[0]
    reverse = reverse_results[0]

    forward_label = forward["label"]
    reverse_label = reverse["label"]

    # Either direction entails → elaboration or specificity mismatch
    if forward_label == "entailment" or reverse_label == "entailment":
        return False, "elaboration"

    # Both directions contradict → genuine bidirectional contradiction
    if forward_label == "contradiction" and reverse_label == "contradiction":
        return True, "bidirectional_contradiction"

    # One-directional contradiction → specificity mismatch
    return False, "specificity_mismatch"


# ── Fix 2.3: Modality alignment gate ────────────────────

COMPARABLE_MODALITY_PAIRS = {
    ("MANDATORY", "MANDATORY"),
    ("MANDATORY", "PROHIBITED"),
    ("MANDATORY", "RECOMMENDED"),
    ("PROHIBITED", "PROHIBITED"),
    ("PROHIBITED", "RECOMMENDED"),
    ("RECOMMENDED", "RECOMMENDED"),
    ("OPTIONAL", "OPTIONAL"),
    ("INFORMATIONAL", "INFORMATIONAL"),
    # INFORMATIONAL ↔ MANDATORY/PROHIBITED removed — incomparable modalities
}


def modalities_are_comparable(modality_a: str | None, modality_b: str | None) -> bool:
    """Check if two claim modalities are comparable for contradiction detection.

    Returns True if the modality pair makes sense to compare (both regulatory,
    both quantitative, etc). Returns True for missing modalities (permissive fallback).
    """
    if not modality_a or not modality_b:
        return True  # Missing modality → don't block, let NLI decide

    pair = (modality_a.upper(), modality_b.upper())
    return pair in COMPARABLE_MODALITY_PAIRS or pair[::-1] in COMPARABLE_MODALITY_PAIRS


# ── Fix 2.4: Specificity ratio filter ───────────────────

def specificity_ratio(text_a: str, text_b: str) -> float:
    """Compute length ratio between two claims.

    If one claim is 2x+ longer, it's likely an elaboration not a contradiction.
    """
    len_a = len(text_a.split())
    len_b = len(text_b.split())
    return max(len_a, len_b) / max(min(len_a, len_b), 1)


def scan_claims_nli(
    org_id: str,
    claim_id: str,
    claim_text: str,
    top_k: int = 5,
    metrics: "PipelineMetrics | None" = None,
    source_modality: str | None = None,
    target_document_id: str | None = None,
) -> tuple[list[ContradictionResult], list[str]]:
    """Compare a claim against other claims using NLI with hierarchical reduction.

    Optimized pipeline:
      embed → dynamic retrieval → similarity gate → (optional rerank) → NLI → lazy explain
    """
    from app.ingestion.embedder import generate_single_embedding

    query_embedding = generate_single_embedding(claim_text)

    # ── Dynamic retrieval size ──
    if settings.DYNAMIC_RETRIEVAL:
        retrieve_k = settings.RERANK_RETRIEVE_K  # start at configured K
    else:
        retrieve_k = settings.RERANK_RETRIEVE_K if settings.RERANK_ENABLED else top_k + 5

    # When restricted to a specific partner document (pairwise routed scan),
    # filter retrieval to that doc so near-duplicate docs can't crowd top-K and
    # hide a genuine contradiction partner.
    base_filter = {"is_claim": True}
    if target_document_id:
        base_filter["document_id"] = target_document_id

    try:
        similar_claims = query_similar(
            org_id,
            query_embedding,
            top_k=retrieve_k,
            where_filter=base_filter,
        )
        has_results = (
            similar_claims and similar_claims.get("ids")
            and similar_claims["ids"][0]
            and len(similar_claims["ids"][0]) > 0
        )
        if not has_results and not target_document_id:
            similar_claims = query_similar(
                org_id,
                query_embedding,
                top_k=retrieve_k,
            )
    except Exception as e:
        logger.error(f"Failed to query similar claims: {e}")
        return [], []

    candidates = []
    source_doc_id = None

    if similar_claims and similar_claims["ids"] and similar_claims["ids"][0]:
        for i, cid in enumerate(similar_claims["ids"][0]):
            if cid == claim_id:
                meta = similar_claims["metadatas"][0][i] if similar_claims["metadatas"] else {}
                source_doc_id = meta.get("document_id")
                break

    if similar_claims["ids"]:
        all_similarities = []  # Track for debug logging
        gate_passed = 0
        gate_rejected = 0
        gate_sampled = 0

        for i, cid in enumerate(similar_claims["ids"][0]):
            if cid == claim_id:
                continue

            metadata = similar_claims["metadatas"][0][i] if similar_claims["metadatas"] else {}
            if source_doc_id and metadata.get("document_id") == source_doc_id:
                continue

            distance = similar_claims["distances"][0][i] if similar_claims["distances"] else 1.0
            similarity = 1.0 - distance
            all_similarities.append(round(similarity, 3))

            # ── Similarity Gate: aggressive early rejection with sampling ──
            gate_threshold = settings.SIMILARITY_GATE_THRESHOLD
            is_sampled = False
            if similarity < gate_threshold:
                # Randomly retain a fraction of below-threshold candidates for calibration
                if settings.GATE_SAMPLE_RATE > 0 and random.random() < settings.GATE_SAMPLE_RATE:
                    is_sampled = True
                    gate_sampled += 1
                    logger.debug(f"Gate sample: retaining below-threshold pair (sim={similarity:.3f})")
                else:
                    gate_rejected += 1
                    if metrics:
                        metrics.nli_skipped += 1
                    continue
            else:
                gate_passed += 1

            text = similar_claims["documents"][0][i] if similar_claims["documents"] else ""

            # ── Structural-noise gate on the candidate ──
            # The claim corpus contains non-claim noise (page headers, draft
            # boilerplate, garbled table cells) that the cross-encoder pairs with
            # everything as a high-confidence contradiction. Drop it before NLI.
            if settings.NOISE_FILTER_ENABLED and (not text or is_structural_noise(text)):
                continue

            candidates.append({
                "id": cid,
                "text": text,
                "document_id": metadata.get("document_id", ""),
                "similarity": similarity,
                "metadata": metadata,
                "_sampled": is_sampled,
            })

        # ── Gate summary logging ──
        total_evaluated = gate_passed + gate_rejected + gate_sampled
        if total_evaluated > 0:
            logger.debug(
                f"[{claim_id[:8]}] similarity scores: {all_similarities} "
                f"(threshold: {settings.SIMILARITY_GATE_THRESHOLD})"
            )
            logger.debug(
                f"[{claim_id[:8]}] Gate result: {gate_passed} passed, "
                f"{gate_rejected} rejected, {gate_sampled} sampled of {total_evaluated}"
            )

    if metrics:
        metrics.total_candidates_retrieved += len(candidates)

    if not candidates:
        return [], []

    # ── Dynamic top-K: high-similarity clusters get fewer candidates ──
    if settings.DYNAMIC_RETRIEVAL and candidates:
        max_sim = max(c["similarity"] for c in candidates)
        if max_sim > 0.92:
            effective_k = 3
        elif max_sim > 0.85:
            effective_k = 5
        else:
            effective_k = top_k
        candidates = candidates[:effective_k]

    if metrics:
        metrics.after_similarity_gate += len(candidates)

    # ── Optional Rerank ──
    if settings.RERANK_ENABLED and len(candidates) > top_k:
        try:
            from app.retrieval.reranker import rerank_candidates
            candidates = rerank_candidates(
                query=claim_text,
                candidates=candidates,
                top_k=settings.RERANK_FINAL_K,
            )
        except Exception as e:
            logger.warning(f"Reranking failed, using embedding similarity: {e}")
            candidates = candidates[:top_k]
    else:
        candidates = candidates[:top_k]

    if metrics:
        metrics.after_rerank += len(candidates)

    if not candidates:
        return [], []

    # ── NLI classification with false-positive reduction ──
    pairs = [(claim_text, cand["text"]) for cand in candidates]
    nli_results = classify_claim_pairs(pairs)

    if metrics:
        metrics.nli_comparisons += len(pairs)

    ret = []
    for cand, result in zip(candidates, nli_results):
        score = float(result["score"])

        if result["label"] != "contradiction":
            continue

        cand_text = cand["text"]

        # ── Fix 2.3: Modality alignment gate ──
        cand_modality = cand.get("metadata", {}).get("modality")
        if not modalities_are_comparable(source_modality, cand_modality):
            logger.debug(f"Skipping incompatible modality pair: {source_modality} vs {cand_modality}")
            continue

        # ── Fix 2.4: Specificity ratio — raise threshold for length-mismatched pairs ──
        spec_ratio = specificity_ratio(claim_text, cand_text)
        if spec_ratio > 2.0:
            effective_threshold = max(settings.NLI_CONTRADICTION_THRESHOLD, 0.85)
        else:
            effective_threshold = settings.NLI_CONTRADICTION_THRESHOLD

        # ── Fix 2.1: Threshold bands ──
        if score >= effective_threshold:
            confidence_band = "high"
            requires_review = False
        elif score >= settings.NLI_BORDERLINE_THRESHOLD:
            confidence_band = "borderline"
            requires_review = True
        else:
            # Below borderline threshold — discard
            logger.debug(
                f"Discarding low-confidence pair (score={score:.3f}, "
                f"threshold={effective_threshold}, borderline={settings.NLI_BORDERLINE_THRESHOLD})"
            )
            continue

        # ── Fix 2.2: Entailment asymmetry check ──
        # Run the bidirectional check on EVERY surviving candidate, regardless of
        # forward score. The dominant false-positive mode on real documents is a
        # high forward-NLI score (0.95–1.0) on two same-topic but unrelated
        # sentences; the reverse direction exposes them as one-directional
        # (specificity_mismatch / elaboration). The old `score < 0.90` skip let
        # exactly those high-confidence false positives straight through.
        if settings.ENTAILMENT_ASYMMETRY_CHECK:
            genuine, reason = is_genuine_contradiction(claim_text, cand_text)
            if not genuine:
                logger.debug(f"Filtered pair — reason: {reason} (score={score:.3f})")
                continue

        # ── Subject-overlap gate ──
        # Two claims can be embedding-similar (same topic) yet about different
        # subjects (a PIN definition vs a binding-code rule); the cross-encoder
        # still calls them contradictory. Require a minimum shared-term overlap
        # so a genuine contradiction is anchored to common subject matter.
        if settings.MIN_SHARED_CLAIM_TERMS > 0:
            if _shared_salient_terms(claim_text, cand_text) < settings.MIN_SHARED_CLAIM_TERMS:
                logger.debug(f"Filtered pair — no shared subject terms (score={score:.3f})")
                continue

        # ── Lazy explanation: defer API call ──
        if settings.LAZY_EXPLANATIONS:
            explanation = (
                f"These two statements present conflicting information. "
                f"Contradiction detected with {score*100:.0f}% confidence."
            )
            if metrics:
                metrics.explanations_deferred += 1
        else:
            explanation = _generate_explanation(claim_text, cand_text, score)
            if metrics:
                metrics.explanations_generated += 1

        ret.append(ContradictionResult(
            chunk_a_id=claim_id,
            chunk_b_id=cand["id"],
            chunk_a_text=claim_text,
            chunk_b_text=cand_text,
            classification="CONTRADICTORY",
            confidence=score,
            explanation=explanation,
            conflicting_claims=[claim_text, cand_text],
            sampled=cand.get("_sampled", False),
            gate_similarity=cand.get("similarity", 0.0),
            confidence_band=confidence_band,
            requires_review=requires_review,
            scan_path="embedding",
            contradiction_type=classify_pair_taxonomy(claim_text, cand_text),
        ))

    if metrics:
        metrics.contradictions_found += len(ret)

    aligned_doc_ids = [cand.get("document_id") for cand in candidates if cand.get("document_id")]
    return ret, aligned_doc_ids


# ── Lazy explanation generation (on-demand) ─────────────

def generate_explanation_on_demand(claim_a: str, claim_b: str, confidence: float) -> str:
    """Generate explanation when user views a contradiction (lazy mode)."""
    return _generate_explanation(claim_a, claim_b, confidence)


def classify_pair_taxonomy(text_a: str, text_b: str) -> str:
    """Best-effort taxonomy subtype for a detected contradiction.

    Extracts a proposition from each sentence and runs the taxonomy classifier.
    Returns the subtype value (e.g. "outcome_inversion") or "" when the pair
    can't be confidently subtyped (entities/attributes don't align). Never
    raises — taxonomy labelling is advisory, not required for storage.
    """
    try:
        from app.contradiction.proposition_extractor import extract_propositions
        from app.contradiction.taxonomy_classifier import ContradictionTaxonomyClassifier

        props_a = extract_propositions(text_a)
        props_b = extract_propositions(text_b)
        if not props_a or not props_b:
            return ""

        classifier = ContradictionTaxonomyClassifier()
        best = ""
        best_conf = 0.0
        for pa in props_a:
            for pb in props_b:
                result = classifier.classify(pa, pb)
                if result.type is not None and result.confidence > best_conf:
                    best = result.type.value
                    best_conf = result.confidence
        return best
    except Exception as e:
        logger.debug(f"Taxonomy classification skipped: {e}")
        return ""


def _deduplicate(results: list[ContradictionResult]) -> list[ContradictionResult]:
    """Remove duplicate contradiction pairs."""
    seen = set()
    unique = []
    for r in results:
        key = tuple(sorted([r.chunk_a_id, r.chunk_b_id]))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ── Fix 3.4: Structured scan path ────────────────────────


def scan_structured(
    org_id: str,
    doc_a_text: str,
    doc_b_text: str,
    doc_a_id: str = "",
    doc_b_id: str = "",
    doc_a_chunk_ids: list[str] | None = None,
    doc_b_chunk_ids: list[str] | None = None,
    metrics: "PipelineMetrics | None" = None,
) -> list[ContradictionResult]:
    """Structured contradiction scan: section-align → extract propositions → classify by taxonomy.

    This path is used for structurally regular documents (reports, policies)
    where section headings enable topic-level alignment that embedding
    similarity alone misses (e.g., polarity-opposite claims about the same entity).

    Returns:
        List of ContradictionResult with taxonomy type in classification field.
    """
    from app.contradiction.section_aligner import SectionAligner, segment_into_sections
    from app.contradiction.proposition_extractor import extract_propositions
    from app.contradiction.taxonomy_classifier import ContradictionTaxonomyClassifier

    aligner = SectionAligner()
    classifier = ContradictionTaxonomyClassifier()

    # Segment documents
    sections_a = segment_into_sections(doc_a_text, doc_a_chunk_ids)
    sections_b = segment_into_sections(doc_b_text, doc_b_chunk_ids)

    if not sections_a or not sections_b:
        logger.info("Structured scan: insufficient sections for alignment")
        return []

    # Align sections
    alignments = aligner.align(sections_a, sections_b)

    if not alignments:
        logger.info("Structured scan: no section alignments found")
        return []

    logger.info(
        f"Structured scan: {len(alignments)} aligned section pairs "
        f"from {len(sections_a)}×{len(sections_b)} sections"
    )

    results = []
    for alignment in alignments:
        # Extract propositions from each aligned section pair
        props_a = extract_propositions(
            alignment.section_a.content,
            chunk_id=alignment.section_a.chunk_ids[0] if alignment.section_a.chunk_ids else "",
            doc_id=doc_a_id,
            section_heading=alignment.section_a.heading,
        )
        props_b = extract_propositions(
            alignment.section_b.content,
            chunk_id=alignment.section_b.chunk_ids[0] if alignment.section_b.chunk_ids else "",
            doc_id=doc_b_id,
            section_heading=alignment.section_b.heading,
        )

        if not props_a or not props_b:
            continue

        # Compare all proposition pairs in aligned sections
        for pa in props_a:
            for pb in props_b:
                result = classifier.classify(pa, pb)

                if result.type is None:
                    continue

                results.append(ContradictionResult(
                    chunk_a_id=pa.chunk_id or f"{doc_a_id}_structured",
                    chunk_b_id=pb.chunk_id or f"{doc_b_id}_structured",
                    chunk_a_text=pa.source_sentence,
                    chunk_b_text=pb.source_sentence,
                    classification="CONTRADICTORY",
                    confidence=result.confidence,
                    explanation=(
                        f"[{result.type.value}] {result.reason}. "
                        f"Section: '{alignment.section_a.heading}' ↔ '{alignment.section_b.heading}'"
                    ),
                    conflicting_claims=[pa.source_sentence, pb.source_sentence],
                    confidence_band="high" if result.confidence >= 0.75 else "borderline",
                    requires_review=result.confidence < 0.75,
                    scan_path="structured",
                    contradiction_type=result.type.value,
                ))

    logger.info(f"Structured scan: {len(results)} contradictions found")

    if metrics:
        metrics.contradictions_found += len(results)

    return _deduplicate(results)


# ── Dual-path router ────────────────────────────────────


def _run_embedding_scan(
    org_id: str,
    doc_a_id: str,
    doc_b_id: str,
    metrics: "PipelineMetrics | None" = None,
) -> list[ContradictionResult]:
    """Embedding scan path: claim-level pairwise NLI between two documents.

    Compares each of doc_a's claims against doc_b's claims (retrieval restricted
    to doc_b), so polarity-flipped claims are caught at claim granularity rather
    than collapsed into coarse chunk comparisons. Results are keyed by claim
    embedding IDs so the caller can dedup/persist at claim grain (Fix C).
    """
    from app.ingestion.indexer import get_or_create_collection, invalidate_collection_cache

    if not doc_a_id or not doc_b_id:
        logger.info("Embedding scan: missing document IDs, skipping")
        return []

    # Fetch doc_a's claims (id + text + metadata) from the claims collection. A
    # cached handle can be stale after a reindex; refetch once before giving up,
    # since returning [] here would silently drop the whole document from the scan.
    def _fetch_claims():
        return get_or_create_collection(org_id, name_suffix="claims").get(
            where={"document_id": doc_a_id}, include=["documents", "metadatas"]
        )

    try:
        got = _fetch_claims()
    except Exception as e:
        logger.warning(f"Embedding scan: claims fetch failed for {doc_a_id} ({e}); refetching once")
        invalidate_collection_cache(org_id, "claims")
        try:
            got = _fetch_claims()
        except Exception as e2:
            logger.warning(f"Embedding scan: failed to fetch claims for {doc_a_id}: {e2}")
            return []

    ids = got.get("ids", []) or []
    docs = got.get("documents", []) or []
    metas = got.get("metadatas", []) or []
    if not ids:
        logger.info(f"Embedding scan: no claims indexed for doc {doc_a_id}")
        return []

    # Build the set of source claims to scan, dropping structural noise (headers/
    # boilerplate/table fragments) so they never seed a pairwise scan.
    seeds = []
    for idx, claim_id in enumerate(ids):
        text = docs[idx] if idx < len(docs) else None
        if not text:
            continue
        if settings.NOISE_FILTER_ENABLED and is_structural_noise(text):
            continue
        meta = metas[idx] if idx < len(metas) and metas[idx] else {}
        weight = meta.get("importance_weight", 1.0) or 1.0
        seeds.append((claim_id, text, weight))

    # ── Cap source claims per pair (bounds the O(claims × candidates) scan) ──
    # Keep the highest-importance claims so a contradiction-bearing claim, which
    # is high-signal, still seeds the scan even on a 1000+ claim document.
    cap = settings.EMBEDDING_SCAN_MAX_CLAIMS
    if cap and len(seeds) > cap:
        seeds.sort(key=lambda s: s[2], reverse=True)
        logger.info(
            f"Embedding scan: capping {len(seeds)} source claims to top {cap} by "
            f"importance for {doc_a_id}↔{doc_b_id}"
        )
        seeds = seeds[:cap]

    results = []
    for claim_id, text, _weight in seeds:
        claim_results, _ = scan_claims_nli(
            org_id=org_id,
            claim_id=claim_id,
            claim_text=text,
            top_k=5,
            metrics=metrics,
            target_document_id=doc_b_id,
        )
        results.extend(claim_results)

    return _deduplicate(results)


def scan_document_pair_routed(
    org_id: str,
    doc_a_text: str,
    doc_b_text: str,
    doc_a_id: str = "",
    doc_b_id: str = "",
    doc_a_chunk_ids: list[str] | None = None,
    doc_b_chunk_ids: list[str] | None = None,
    metrics: "PipelineMetrics | None" = None,
) -> tuple[list[ContradictionResult], str]:
    """Route between structured and embedding scan paths based on document structure.

    Returns:
        Tuple of (results, scan_path_used) where scan_path_used is "structured" or "embedding".
    """
    from app.contradiction.section_aligner import SectionAligner

    threshold = settings.STRUCTURED_SCAN_THRESHOLD
    aligner = SectionAligner()

    # Check structure confidence for both documents
    conf_a = aligner.get_structure_confidence(doc_a_text)
    conf_b = aligner.get_structure_confidence(doc_b_text)

    # Both documents must be structurally regular for the structured path
    min_confidence = min(conf_a, conf_b)

    logger.info(
        f"Scan router: structure_confidence A={conf_a:.2f}, B={conf_b:.2f}, "
        f"min={min_confidence:.2f}, threshold={threshold}"
    )

    def _stamp(results: list[ContradictionResult], path: str) -> list[ContradictionResult]:
        for r in results:
            if not r.scan_path:
                r.scan_path = path
        return results

    if min_confidence >= threshold:
        try:
            results = scan_structured(
                org_id=org_id,
                doc_a_text=doc_a_text,
                doc_b_text=doc_b_text,
                doc_a_id=doc_a_id,
                doc_b_id=doc_b_id,
                doc_a_chunk_ids=doc_a_chunk_ids,
                doc_b_chunk_ids=doc_b_chunk_ids,
                metrics=metrics,
            )
            return _stamp(results, "structured"), "structured"
        except Exception as e:
            logger.warning(
                f"Structured scan failed, falling back to embedding scan: {e}",
                exc_info=True,
            )
            # Actually run embedding scan instead of returning empty
            results = _run_embedding_scan(
                org_id=org_id,
                doc_a_id=doc_a_id,
                doc_b_id=doc_b_id,
                metrics=metrics,
            )
            return _stamp(results, "embedding"), "embedding"
    else:
        # Insufficient document structure — use embedding-based scan
        logger.info("Using embedding scan path (insufficient document structure)")
        results = _run_embedding_scan(
            org_id=org_id,
            doc_a_id=doc_a_id,
            doc_b_id=doc_b_id,
            metrics=metrics,
        )
        return _stamp(results, "embedding"), "embedding"
