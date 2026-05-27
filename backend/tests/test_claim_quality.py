"""Tests for Change 2: Rule-Based Claim Extraction — Sentence Quality Filters."""

import pytest

from app.pipeline.noise_filter import check_claim_worthy, is_claim_worthy


class TestDanglingPronounFilter:
    """Reject sentences starting with context-dependent pronouns."""

    def test_bare_this_is_rejected(self):
        worthy, reason = check_claim_worthy("This is particularly important for large-scale systems and applications.")
        assert not worthy
        assert reason == "dangling_pronoun"

    def test_these_are_rejected(self):
        worthy, reason = check_claim_worthy("These are the main findings of the study that were observed during experimentation.")
        assert not worthy
        assert reason == "dangling_pronoun"

    def test_it_has_rejected(self):
        worthy, reason = check_claim_worthy("It has been shown that the approach works well for various applications.")
        assert not worthy
        assert reason == "dangling_pronoun"

    def test_they_can_rejected(self):
        worthy, reason = check_claim_worthy("They can be applied to a wide range of applications and systems in production.")
        assert not worthy
        assert reason == "dangling_pronoun"

    def test_such_will_rejected(self):
        worthy, reason = check_claim_worthy("Such will be the case for any system that processes natural language input.")
        assert not worthy
        assert reason == "dangling_pronoun"

    def test_this_method_allowed(self):
        """'This method is...' has a nominal subject — should pass pronoun filter."""
        # Note: may still fail other filters, we just check it's NOT dangling_pronoun
        worthy, reason = check_claim_worthy(
            "This method is based on transformer architectures that process sequential data in parallel."
        )
        assert reason != "dangling_pronoun"

    def test_these_results_allowed(self):
        """'These results demonstrate...' has a nominal subject."""
        worthy, reason = check_claim_worthy(
            "These results demonstrate that transfer learning provides significant improvements in accuracy."
        )
        assert reason != "dangling_pronoun"


class TestUnresolvedReferenceFilter:
    """Reject sentences with context-dependent references."""

    def test_as_described_above(self):
        worthy, reason = check_claim_worthy(
            "As described above, the algorithm processes input sequences in batches of 32 tokens."
        )
        assert not worthy
        assert reason in ("unresolved_reference", "boilerplate_pattern")

    def test_see_section(self):
        worthy, reason = check_claim_worthy(
            "Machine learning models require careful tuning; see section 4 for full details."
        )
        assert not worthy
        assert reason == "unresolved_reference"

    def test_the_following_table(self):
        worthy, reason = check_claim_worthy(
            "The following table summarizes the performance metrics obtained across all experiments."
        )
        assert not worthy
        assert reason == "unresolved_reference"

    def test_discussed_below(self):
        worthy, reason = check_claim_worthy(
            "The implications of these findings are discussed below in the analysis section."
        )
        assert not worthy
        assert reason == "unresolved_reference"

    def test_no_reference_passes(self):
        """Clean factual sentence should not trigger reference filter."""
        worthy, reason = check_claim_worthy(
            "Transfer learning reduces the required training data by approximately 40 percent in practice."
        )
        assert reason != "unresolved_reference"


class TestContentWordFilter:
    """Reject sentences with too few content words after stripping stopwords."""

    def test_stopword_heavy_sentence(self):
        worthy, reason = check_claim_worthy(
            "It is also one of the most important things for all of us to consider."
        )
        # After removing stopwords, very few content words remain
        # (may also hit dangling_pronoun — check it doesn't pass)
        assert not worthy

    def test_content_rich_sentence_passes(self):
        """Sentence with many content words should pass."""
        worthy, reason = check_claim_worthy(
            "Supervised learning algorithms require labeled training data where each input maps to a known output."
        )
        assert worthy
        assert reason == ""


class TestRejectionReasonField:
    """Verify rejection reasons are returned correctly."""

    def test_too_short(self):
        _, reason = check_claim_worthy("Short text.")
        assert reason == "too_short"

    def test_too_long(self):
        _, reason = check_claim_worthy("Word " * 200)
        assert reason == "too_long"

    def test_no_verb(self):
        _, reason = check_claim_worthy(
            "The quick brown fox over the lazy sleeping dog near the fence post by the old barn."
        )
        assert reason == "no_verb"

    def test_boilerplate(self):
        _, reason = check_claim_worthy(
            "In this section we present the methodology used to evaluate the performance of models."
        )
        assert reason == "boilerplate_pattern"

    def test_valid_claim_empty_reason(self):
        worthy, reason = check_claim_worthy(
            "Machine learning is a subset of artificial intelligence focused on building systems that learn from data."
        )
        assert worthy
        assert reason == ""


class TestBackwardCompatibility:
    """Verify is_claim_worthy still works as a boolean wrapper."""

    def test_true_case(self):
        assert is_claim_worthy(
            "Neural networks are composed of interconnected layers of artificial neurons that process information."
        )

    def test_false_case(self):
        assert not is_claim_worthy("This is very important for everyone.")
