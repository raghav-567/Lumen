"""Section-level alignment for structured document comparison.

Pairs topically equivalent sections across documents WITHOUT relying
on embedding proximity for polarity-opposite claims.

Pipeline:
  1. Segment each document into sections by heading detection
  2. Embed section summaries (first + last sentence)
  3. Greedy match by cosine similarity with position penalty
  4. Return only pairs above alignment_threshold (0.70)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np

from app.ingestion.embedder import generate_embeddings

logger = logging.getLogger(__name__)

SECTION_TAXONOMY = [
    "introduction_context",
    "system_design_approach",
    "public_response_economic",
    "environmental_outcomes",
    "operational_challenges",
    "governance_oversight",
    "resilience_infrastructure",
    "energy_management",
    "long_term_conclusions",
]

# Heading detection patterns
_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"\d+\.(?:\d+\.?)*\s+|"                  # "1.2.3 Title"
    r"#{1,4}\s+|"                              # "## Title"
    r"[A-Z][A-Z\s]{3,}(?:\n|$)|"              # "ALL CAPS HEADING"
    r"(?:Section|Chapter|Part)\s+\d+"          # "Section 3"
    r")",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass
class Section:
    """A logical section of a document."""
    heading: str
    content: str
    chunk_ids: list[str] = field(default_factory=list)
    position: int = 0       # ordinal position in document (0-indexed)
    word_count: int = 0


@dataclass
class SectionAlignment:
    """A paired alignment between two sections from different documents."""
    section_a: Section
    section_b: Section
    similarity: float
    position_penalty: float
    adjusted_score: float


def segment_into_sections(text: str, chunk_ids: list[str] | None = None) -> list[Section]:
    """Segment document text into sections by heading detection.

    Falls back to paragraph boundary splitting if no headings are found.
    """
    if not text:
        return []

    lines = text.split("\n")
    sections: list[Section] = []
    current_heading = "Introduction"
    current_lines: list[str] = []
    current_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            current_lines.append(line)
            continue

        # Check if this line is a heading
        is_heading = bool(_HEADING_RE.match(stripped))

        # Also treat short ALL-CAPS lines as headings
        if not is_heading and stripped.isupper() and 3 <= len(stripped.split()) <= 8:
            is_heading = True

        if is_heading and current_lines:
            content = "\n".join(current_lines).strip()
            if content and len(content.split()) >= 10:
                sections.append(Section(
                    heading=current_heading,
                    content=content,
                    position=len(sections),
                    word_count=len(content.split()),
                ))
            current_heading = stripped
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section
    content = "\n".join(current_lines).strip()
    if content and len(content.split()) >= 10:
        sections.append(Section(
            heading=current_heading,
            content=content,
            position=len(sections),
            word_count=len(content.split()),
        ))

    # Fallback: if no headings found, split by paragraph clusters
    if len(sections) <= 1 and len(text.split()) > 200:
        sections = _split_by_paragraphs(text)

    # Assign chunk_ids if provided (rough mapping by position)
    if chunk_ids and sections:
        ids_per_section = max(1, len(chunk_ids) // len(sections))
        for idx, section in enumerate(sections):
            start = idx * ids_per_section
            end = min(start + ids_per_section, len(chunk_ids))
            section.chunk_ids = chunk_ids[start:end]

    return sections


def _split_by_paragraphs(text: str, target_sections: int = 6) -> list[Section]:
    """Split text into roughly equal sections by paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and len(p.split()) >= 5]

    if not paragraphs:
        return [Section(heading="Full Document", content=text, position=0, word_count=len(text.split()))]

    paras_per_section = max(1, len(paragraphs) // target_sections)
    sections = []

    for i in range(0, len(paragraphs), paras_per_section):
        group = paragraphs[i:i + paras_per_section]
        content = "\n\n".join(group)
        first_line = group[0].split(".")[0][:60] if group else f"Section {len(sections) + 1}"
        sections.append(Section(
            heading=first_line,
            content=content,
            position=len(sections),
            word_count=len(content.split()),
        ))

    return sections


def _section_summary(section: Section) -> str:
    """Create a summary string for embedding: first + last sentence."""
    sentences = [s.strip() for s in section.content.split(".") if s.strip() and len(s.split()) >= 3]
    if not sentences:
        return section.content[:200]
    if len(sentences) == 1:
        return sentences[0]
    return f"{sentences[0]}. {sentences[-1]}."


class SectionAligner:
    """Aligns topically equivalent sections across two documents."""

    def __init__(self, alignment_threshold: float = 0.70, position_penalty_weight: float = 0.1):
        self.alignment_threshold = alignment_threshold
        self.position_penalty_weight = position_penalty_weight

    def align(
        self, sections_a: list[Section], sections_b: list[Section]
    ) -> list[SectionAlignment]:
        """Return paired sections covering the same topic across two document section lists.

        Method:
          1. Embed section summaries (first + last sentence)
          2. Compute cosine similarity matrix
          3. Apply position penalty (distant sections less likely to match)
          4. Greedy match by adjusted score
          5. Return only pairs above alignment_threshold
        """
        if not sections_a or not sections_b:
            return []

        # Generate summaries and embed
        summaries_a = [_section_summary(s) for s in sections_a]
        summaries_b = [_section_summary(s) for s in sections_b]

        all_summaries = summaries_a + summaries_b
        all_embeddings = generate_embeddings(all_summaries)

        emb_a = np.array(all_embeddings[:len(sections_a)])
        emb_b = np.array(all_embeddings[len(sections_a):])

        # Normalize for cosine similarity
        norm_a = emb_a / np.maximum(np.linalg.norm(emb_a, axis=1, keepdims=True), 1e-8)
        norm_b = emb_b / np.maximum(np.linalg.norm(emb_b, axis=1, keepdims=True), 1e-8)

        # Cosine similarity matrix
        sim_matrix = norm_a @ norm_b.T

        # Position penalty matrix
        n_a, n_b = len(sections_a), len(sections_b)
        position_matrix = np.zeros((n_a, n_b))
        for i in range(n_a):
            for j in range(n_b):
                # Normalized position difference
                pos_diff = abs(sections_a[i].position / max(n_a, 1) -
                             sections_b[j].position / max(n_b, 1))
                position_matrix[i, j] = pos_diff

        # Adjusted score = similarity - position_penalty
        adjusted_matrix = sim_matrix - (self.position_penalty_weight * position_matrix)

        # Greedy matching: pick best pair, remove both, repeat
        alignments = []
        used_a = set()
        used_b = set()

        while len(used_a) < n_a and len(used_b) < n_b:
            # Find best remaining pair
            best_score = -1
            best_i, best_j = -1, -1
            for i in range(n_a):
                if i in used_a:
                    continue
                for j in range(n_b):
                    if j in used_b:
                        continue
                    if adjusted_matrix[i, j] > best_score:
                        best_score = adjusted_matrix[i, j]
                        best_i, best_j = i, j

            if best_score < self.alignment_threshold:
                break

            used_a.add(best_i)
            used_b.add(best_j)

            alignments.append(SectionAlignment(
                section_a=sections_a[best_i],
                section_b=sections_b[best_j],
                similarity=float(sim_matrix[best_i, best_j]),
                position_penalty=float(position_matrix[best_i, best_j]),
                adjusted_score=float(best_score),
            ))

        logger.info(
            f"Section alignment: {len(alignments)} pairs from "
            f"{n_a}×{n_b} sections (threshold={self.alignment_threshold})"
        )
        return alignments

    def get_structure_confidence(self, text: str) -> float:
        """Returns 0.0-1.0 indicating how structurally regular a document is.

        High score → use structured scan path.
        Low score → fall back to embedding scan path.

        Signals:
          - Number of detected headings
          - Heading hierarchy regularity
          - Consistent paragraph lengths
        """
        if not text:
            return 0.0

        lines = text.split("\n")
        total_lines = len(lines)
        if total_lines < 5:
            return 0.0

        # Count heading-like lines
        heading_count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _HEADING_RE.match(stripped):
                heading_count += 1
            elif stripped.isupper() and 3 <= len(stripped.split()) <= 8:
                heading_count += 1

        # Score components
        heading_density = min(1.0, heading_count / max(total_lines / 30, 1))

        # Numbered headings suggest structure
        numbered_headings = len(re.findall(r"^\s*\d+\.\d*", text, re.MULTILINE))
        numbering_score = min(1.0, numbered_headings / 3) if numbered_headings > 0 else 0.0

        # Document length bonus (longer docs more likely to be structured)
        word_count = len(text.split())
        length_score = min(1.0, word_count / 500)

        confidence = (heading_density * 0.4 + numbering_score * 0.35 + length_score * 0.25)
        return round(min(1.0, confidence), 2)
