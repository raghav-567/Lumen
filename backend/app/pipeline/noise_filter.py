"""Aggressive noise filtering for document text and claims.

Two-stage pipeline:
  Stage 1: Structural/regex filtering — remove boilerplate BEFORE extraction
  Stage 2: Claim salience scoring — discard low-information sentences AFTER extraction

Expected reduction: 693 raw sentences → 80-120 meaningful claims
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Stage 1: Structural noise patterns ──────────────────

# Patterns that indicate non-claim text (compiled once)
BOILERPLATE_PATTERNS = [
    # References / Bibliography
    re.compile(r"^\s*\[?\d+\]?\s*[A-Z][a-z]+.*\d{4}\b", re.MULTILINE),  # "[1] Author et al. 2024"
    re.compile(r"^\s*references\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*bibliography\s*$", re.IGNORECASE | re.MULTILINE),
    # Figure/Table captions
    re.compile(r"^\s*(figure|fig\.?|table|tab\.?)\s+\d+", re.IGNORECASE),
    # Acknowledgements
    re.compile(r"^\s*acknowledgements?\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"the\s+authors?\s+(would\s+like\s+to|wish\s+to)\s+thank", re.IGNORECASE),
    # Page numbers / headers
    re.compile(r"^\s*-?\s*\d+\s*-?\s*$"),
    re.compile(r"^\s*page\s+\d+\s*(of\s+\d+)?\s*$", re.IGNORECASE),
    # Section headers (very short lines)
    re.compile(r"^\s*\d+\.?\d*\.?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+){0,3}\s*$"),
    # Email / URL lines
    re.compile(r"^\s*(https?://|www\.|[a-zA-Z0-9._%+-]+@)", re.IGNORECASE),
    # Citation-only lines
    re.compile(r"^\s*\(([A-Z][a-z]+,?\s*)+\d{4}[a-z]?\)\s*$"),
    # Copyright / license
    re.compile(r"(copyright|©|all rights reserved|creative commons)", re.IGNORECASE),
    # DOI / ISSN
    re.compile(r"^\s*(doi|issn|isbn)\s*:", re.IGNORECASE),
]

# Lines to strip from start/end of chunks
HEADER_FOOTER_PATTERNS = [
    re.compile(r"^\s*\d+\s*$"),  # bare page numbers
    re.compile(r"^\s*(abstract|keywords?|introduction)\s*$", re.IGNORECASE),
]

# Sentence-level discard patterns
SENTENCE_NOISE_PATTERNS = [
    re.compile(r"^(in\s+this\s+(section|paper|study|chapter|article))", re.IGNORECASE),
    re.compile(r"^(the\s+rest\s+of\s+(this|the)\s+(paper|section))", re.IGNORECASE),
    re.compile(r"^(as\s+(shown|described|discussed|mentioned|noted)\s+(in|above|below))", re.IGNORECASE),
    re.compile(r"^(see\s+(figure|fig|table|section|appendix))", re.IGNORECASE),
    re.compile(r"^(we\s+(also|further|next|now|then)\s+(discuss|describe|present|show|consider))", re.IGNORECASE),
    re.compile(r"^(let\s+us\s+(consider|define|assume|denote))", re.IGNORECASE),
    re.compile(r"^(note\s+that\s+)", re.IGNORECASE),
    re.compile(r"^(it\s+(is|should\s+be)\s+(noted|worth|important))", re.IGNORECASE),
    re.compile(r"(et\s+al\.?\s*[,\(]\s*\d{4})", re.IGNORECASE),  # inline citations
]


def filter_text_structural(text: str) -> str:
    """Stage 1: Remove structural noise from raw document text.

    This runs BEFORE chunking/extraction to reduce input volume.
    Returns cleaned text with boilerplate removed.
    """
    if not text:
        return text

    lines = text.split("\n")
    cleaned_lines = []
    in_references = False

    for line in lines:
        stripped = line.strip()

        # Detect reference/bibliography section → discard everything after
        if re.match(r"^\s*(references|bibliography|works\s+cited)\s*$",
                     stripped, re.IGNORECASE):
            in_references = True
            continue

        if in_references:
            # Allow resuming if we hit a clearly new section
            if re.match(r"^\s*(appendix|supplementary|about)", stripped, re.IGNORECASE):
                in_references = False
            else:
                continue

        # Check boilerplate patterns
        is_noise = False
        for pattern in BOILERPLATE_PATTERNS:
            if pattern.search(stripped):
                is_noise = True
                break

        if is_noise:
            continue

        # Skip very short or very long lines
        if len(stripped) < 5:
            continue

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    reduction = len(text) - len(result)
    if reduction > 100:
        pct = round(reduction / len(text) * 100, 1)
        logger.info(f"Structural filter: removed {reduction} chars ({pct}%)")

    return result


# ── Stage 2.5: Unresolved reference patterns ──
UNRESOLVED_REFERENCE_PATTERNS = [
    re.compile(r"\b(as\s+(described|noted|mentioned|stated|discussed|shown)\s+(above|below|earlier|previously))", re.IGNORECASE),
    re.compile(r"\b(see\s+(section|chapter|appendix|above|below|figure|table|page))", re.IGNORECASE),
    re.compile(r"\b(the\s+following\s+(section|table|figure|list|example)s?)\b", re.IGNORECASE),
    re.compile(r"\b(as\s+noted\b)", re.IGNORECASE),
    re.compile(r"\b(the\s+above\s+(results?|findings?|analysis|discussion|table|figure))", re.IGNORECASE),
    re.compile(r"\b(discussed\s+(below|above|later|earlier))\b", re.IGNORECASE),
    re.compile(r"\b(refer\s+to\s+(section|appendix|table|figure))", re.IGNORECASE),
]

# Dangling pronouns — sentence starts with a pronoun that has no referent
# in isolation. We allow "This/These + specific noun" like "This routing protocol..."
# but reject bare "This is..." or "These are..." and generic-noun patterns
# like "These results confirm..." (the referent of "these" is ambiguous)
DANGLING_PRONOUN_RE = re.compile(
    r"^(This|These|Those|It|They|Such|Here)\s+"
    r"(is|are|was|were|has|have|had|can|could|may|might|will|would|shall|should|also|further|additionally)\b",
    re.IGNORECASE,
)

# "These results", "Those findings", etc. — generic nouns with dangling demonstratives
DANGLING_GENERIC_NOUN_RE = re.compile(
    r"^(These|Those)\s+(results?|findings?|data|values?|numbers?|factors?|issues?|changes?|conditions?|observations?|outcomes?|conclusions?|measures?|effects?|aspects?)\b",
    re.IGNORECASE,
)

# English stopwords for content-word counting
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "under",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "than", "too", "very",
    "that", "this", "these", "those", "it", "its", "they", "them",
    "their", "we", "our", "he", "she", "his", "her", "i", "me", "my",
    "you", "your", "who", "which", "what", "when", "where", "how",
    "if", "then", "also", "just", "about", "up", "out", "over",
})

# ── Bullet/list marker pattern ──
_BULLET_PREFIX_RE = re.compile(r'^[\s•\-\*>◦▪\u2022\u2023\u25E6\u2043\u2219]+')

# ── Headless predicate pattern (starts with copula after bullet stripping) ──
_HEADLESS_PREDICATE_RE = re.compile(
    r'^(is|are|was|were|has|have|had|can|will|shall|should|does|do|may|might|could|would)\b',
    re.IGNORECASE,
)

# ── Normative-modal pattern ──
# Crisp regulatory statements ("Verifiers SHALL NOT…", "Passwords MUST…") are
# high-value claims even when short, so they get a lower content-word bar.
_REGULATORY_MODAL_RE = re.compile(
    r'\b(shall(\s+not)?|must(\s+not)?|may\s+not|prohibited|mandatory|required\s+to)\b',
    re.IGNORECASE,
)

# ── Running-header / draft-boilerplate patterns ──
# Standards PDFs repeat a running header/footer on every page (a page number
# followed by the publication identifier) and carry retired/draft notices. These
# survive the verb/length gates ("… Guidelines is …") but are not claims, and
# they pair with everything as high-confidence NLI contradictions.
DOCUMENT_HEADER_PATTERNS = [
    re.compile(r'\bRETIRED\s+DRAFT\b', re.IGNORECASE),
    re.compile(r'\bDRAFT\s+(document|Special\s+Publication)\b', re.IGNORECASE),
    # page-number-prefixed running header carrying a publication identifier
    re.compile(
        r'^[\d.\)]+\s+.*\b(NIST\s+SP|SP\s?800-\d|FIPS\s+\d|Digital\s+Identity\s+Guidelines)\b',
        re.IGNORECASE,
    ),
    # date-prefixed announcement header ("21, 2009 SP 800-118 DRAFT …")
    re.compile(r'^\s*\d{1,2},?\s+\d{4}\s+.*\bSP\s?\d{3}', re.IGNORECASE),
]


def _is_repetitive_fragment(words: list[str]) -> bool:
    """Detect garbled table cells flattened into prose (e.g. 'Yes Yes Yes Can …').

    PDF table regions bleed into the prose stream as runs of repeated cell
    values. These aren't propositions, but they survive the verb/length gates
    and then generate pure-noise NLI comparisons that the cross-encoder
    confidently mislabels as contradictions. Triggers on a run of >=3 identical
    consecutive tokens, or a low unique-token ratio.
    """
    if len(words) < 4:
        return False
    run = mx = 1
    for i in range(1, len(words)):
        if words[i].lower() == words[i - 1].lower():
            run += 1
            mx = max(mx, run)
        else:
            run = 1
    if mx >= 3:
        return True
    unique = len({w.lower() for w in words})
    return len(words) >= 6 and unique / len(words) < 0.5


def preprocess_for_salience(sentence: str) -> str:
    """Strip bullet characters and leading punctuation/whitespace.

    Converts '• is initial estimate location.' → 'is initial estimate location.'
    so downstream checks operate on the actual content.
    """
    return _BULLET_PREFIX_RE.sub('', sentence).strip()


def check_claim_worthy(sentence: str) -> tuple[bool, str]:
    """Determine if a sentence is worth extracting as a claim.

    Returns (is_worthy, rejection_reason). If is_worthy=True, reason is empty.
    """
    sentence = sentence.strip()

    # ── Strip bullet/list markers before all checks ──
    cleaned = preprocess_for_salience(sentence)
    if not cleaned:
        return False, "empty_after_bullet_strip"

    # ── Headless predicate: sentence starts with copula after stripping ──
    if _HEADLESS_PREDICATE_RE.match(cleaned):
        logger.debug(f"[REJECTED] '{sentence[:80]}' — reason: headless_predicate")
        return False, "headless_predicate"

    # Use cleaned version for remaining checks
    sentence = cleaned

    # ── Length gates ──
    if len(sentence) < 25:
        return False, "too_short"
    if len(sentence) > 600:
        return False, "too_long"

    # ── Alpha ratio (too many numbers/symbols = not a claim) ──
    alpha_count = sum(1 for c in sentence if c.isalpha())
    if alpha_count / max(len(sentence), 1) < 0.55:
        return False, "low_alpha_ratio"

    # ── Word count check ──
    words = sentence.split()
    if len(words) < 5:
        return False, "too_few_words"
    if len(words) > 80:
        return False, "too_many_words"

    # ── Repetitive table-cell fragment (e.g. "Yes Yes Yes Can …") ──
    if _is_repetitive_fragment(words):
        return False, "repetitive_fragment"

    # ── Running header / draft boilerplate (page headers, RETIRED DRAFT) ──
    for pattern in DOCUMENT_HEADER_PATTERNS:
        if pattern.search(sentence):
            return False, "document_header"

    # ── Noise patterns ──
    for pattern in SENTENCE_NOISE_PATTERNS:
        if pattern.search(sentence):
            return False, "boilerplate_pattern"

    # ── Starts with lowercase (continuation fragment) ──
    if sentence[0].islower() and not sentence.startswith(("i ", "e.g.", "i.e.")):
        return False, "lowercase_start"

    # ── Dangling pronoun check ──
    # Reject "This is...", "These are...", "It has..." etc. that lack a referent
    if DANGLING_PRONOUN_RE.match(sentence):
        return False, "dangling_pronoun"

    # Reject "These results...", "Those findings..." — generic nouns with dangling demonstratives
    if DANGLING_GENERIC_NOUN_RE.match(sentence):
        return False, "dangling_generic_reference"

    # ── Unresolved reference check ──
    for pattern in UNRESOLVED_REFERENCE_PATTERNS:
        if pattern.search(sentence):
            return False, "unresolved_reference"

    # ── Content word count (after stripping stopwords) ──
    # Regulatory claims (SHALL/MUST/SHALL NOT/PROHIBITED) carry a full proposition
    # in few words, so they clear a lower bar — otherwise real policy statements
    # like "Verifiers SHALL NOT require periodic password changes." get dropped.
    content_words = [w for w in words if w.lower().strip(".,;:!?\"'()") not in _STOPWORDS]
    min_content_words = 4 if _REGULATORY_MODAL_RE.search(sentence) else 8
    if len(content_words) < min_content_words:
        return False, "insufficient_content_words"

    # ── Contains a verb → likely a statement ──
    lower = sentence.lower()
    has_verb = any(v in lower for v in (
        " is ", " are ", " was ", " were ", " has ", " have ", " had ",
        " must ", " shall ", " should ", " will ", " can ", " may ",
        " require ", " requires ", " required ",
        " define ", " defines ", " defined ",
        " mean ", " means ", " meant ",
        " state ", " states ", " stated ",
        " provide ", " provides ", " provided ",
        " include ", " includes ", " included ",
        " specify ", " specifies ", " specified ",
        " establish ", " establishes ", " established ",
        " determine ", " determines ", " determined ",
        " involve ", " involves ", " involved ",
        " prohibit ", " prohibits ", " prohibited ",
        " allow ", " allows ", " allowed ",
        " mandate ", " mandates ", " mandated ",
        " recommend ", " recommends ", " recommended ",
        " demonstrate ", " demonstrates ", " demonstrated ",
        " indicate ", " indicates ", " indicated ",
        " reduce ", " reduces ", " reduced ",
        " increase ", " increases ", " increased ",
        " show ", " shows ", " showed ", " shown ",
        " suggest ", " suggests ", " suggested ",
        " represent ", " represents ", " represented ",
        " consist ", " consists ", " consisted ",
        " produce ", " produces ", " produced ",
        " operate ", " operates ", " operated ",
        " support ", " supports ", " supported ",
        " use ", " uses ", " used ",
        " need ", " needs ", " needed ",
        " achieve ", " achieves ", " achieved ",
        " exceed ", " exceeds ", " exceeded ",
        " fail ", " fails ", " failed ",
        " improve ", " improves ", " improved ",
        " decline ", " declines ", " declined ",
        " result ", " results ", " resulted ",
        " maintain ", " maintains ", " maintained ",
    ))
    if not has_verb:
        return False, "no_verb"

    return True, ""


def is_claim_worthy(sentence: str) -> bool:
    """Stage 2: Determine if a sentence is worth extracting as a claim.

    Lightweight heuristic classifier — runs per-sentence, no model required.
    Returns True if the sentence likely contains a factual assertion.
    """
    worthy, _ = check_claim_worthy(sentence)
    return worthy


def is_structural_noise(sentence: str) -> bool:
    """Cheap structural-noise check for the CONTRADICTION SCAN corpus.

    Unlike `check_claim_worthy` — which is tuned for prose *extraction* quality and
    deliberately drops short / low-information sentences — this removes only
    clearly non-propositional garbage: page headers, draft boilerplate, garbled
    table cells, and number/symbol soup. The cross-encoder confidently mislabels
    that garbage as contradictions, but a real-but-terse claim ("Costs exceeded
    gains.") must still reach NLI, so we do NOT apply the content-word / verb /
    dangling-reference gates here. Returns True if the text is noise.
    """
    s = preprocess_for_salience(sentence.strip())
    if not s:
        return True

    words = s.split()
    if len(words) < 3:
        return True

    # Number/symbol soup (tables, figure coordinates, page furniture).
    alpha = sum(1 for c in s if c.isalpha())
    if alpha / max(len(s), 1) < 0.55:
        return True

    if _is_repetitive_fragment(words):
        return True

    for pattern in DOCUMENT_HEADER_PATTERNS:
        if pattern.search(s):
            return True

    for pattern in SENTENCE_NOISE_PATTERNS:
        if pattern.search(s):
            return True

    return False


def filter_claims(claims: list, min_weight: float = 0.3) -> list:
    """Filter extracted claims by salience and weight.

    Removes low-value claims that would waste retrieval/NLI compute.
    """
    filtered = []
    for claim in claims:
        text = claim.get("content", "") if isinstance(claim, dict) else claim.content
        weight = claim.get("importance_weight", 1.0) if isinstance(claim, dict) else claim.importance_weight

        if weight < min_weight:
            continue
        if not is_claim_worthy(text):
            continue
        filtered.append(claim)

    removed = len(claims) - len(filtered)
    if removed > 0:
        logger.info(f"Claim salience filter: {len(claims)} → {len(filtered)} "
                    f"(removed {removed}, {round(removed/max(len(claims),1)*100)}%)")

    return filtered
