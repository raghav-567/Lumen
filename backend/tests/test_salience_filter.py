"""Tests for the noise/salience filter — covers Fix 1.2b and verb list fix.

Tests bullet stripping, headless predicate rejection, dangling references,
the new DANGLING_GENERIC_NOUN_RE pattern, and past-tense verb recognition.
"""

import pytest
from app.pipeline.noise_filter import (
    check_claim_worthy,
    preprocess_for_salience,
    is_claim_worthy,
    DANGLING_GENERIC_NOUN_RE,
)


class TestPreprocessForSalience:
    """Bullet/marker stripping."""

    def test_bullet_prefix_stripped(self):
        result = preprocess_for_salience("• is initial estimate location.")
        assert result == "is initial estimate location."

    def test_dash_prefix_stripped(self):
        result = preprocess_for_salience("- Some policy statement about X.")
        assert result == "Some policy statement about X."

    def test_asterisk_prefix_stripped(self):
        result = preprocess_for_salience("* Requirements for system compliance.")
        assert result == "Requirements for system compliance."

    def test_no_prefix_unchanged(self):
        result = preprocess_for_salience("The routing protocol is stable.")
        assert result == "The routing protocol is stable."


class TestHeadlessPredicate:
    """Sentences that start with a copula after stripping should be rejected."""

    def test_headless_predicate_rejected(self):
        ok, reason = check_claim_worthy("• is initial estimate location.")
        assert not ok
        assert reason == "headless_predicate"

    def test_headless_are_rejected(self):
        ok, reason = check_claim_worthy("- are the expected output values for calibration purposes.")
        assert not ok
        assert reason == "headless_predicate"

    def test_non_headless_accepted(self):
        """A normal sentence with a past-tense verb should pass all filters."""
        ok, reason = check_claim_worthy(
            "The decentralized routing system has demonstrated improved traffic "
            "oscillation stability and reduced signal propagation delays significantly."
        )
        assert ok, f"Expected acceptance but got rejected with reason: {reason}"


class TestDanglingPronouns:
    """Bare pronouns without referent should be rejected."""

    def test_bare_this_is_rejected(self):
        ok, reason = check_claim_worthy(
            "This is particularly important for the overall system performance and reliability."
        )
        assert not ok
        assert reason == "dangling_pronoun"

    def test_bare_it_has_rejected(self):
        ok, reason = check_claim_worthy(
            "It has been demonstrated through multiple independent verification studies and analyses."
        )
        assert not ok
        assert reason == "dangling_pronoun"


class TestDanglingGenericNoun:
    """Fix 1.2b: 'These results confirm...' should be rejected."""

    def test_these_results_rejected(self):
        ok, reason = check_claim_worthy(
            "These results confirm the findings from the previous investigation phase."
        )
        assert not ok
        assert reason == "dangling_generic_reference"

    def test_those_findings_rejected(self):
        ok, reason = check_claim_worthy(
            "Those findings indicate a significant improvement in operational performance metrics."
        )
        assert not ok
        assert reason == "dangling_generic_reference"

    def test_these_observations_rejected(self):
        ok, reason = check_claim_worthy(
            "These observations suggest that the system requires additional calibration procedures."
        )
        assert not ok
        assert reason == "dangling_generic_reference"

    def test_these_with_specific_noun_accepted(self):
        """'These routing protocols' is specific enough to keep."""
        # Not matched by DANGLING_GENERIC_NOUN_RE (specific noun not in generic list)
        assert not DANGLING_GENERIC_NOUN_RE.match(
            "These routing protocols demonstrated improved traffic handling."
        )


class TestUnresolvedReferences:
    """Sentences referencing other parts of a document should be rejected."""

    def test_see_section_rejected(self):
        ok, reason = check_claim_worthy(
            "See section 3 for details about the implementation methodology and results."
        )
        assert not ok
        # Could be boilerplate_pattern or unresolved_reference

    def test_above_categories_rejected(self):
        ok, reason = check_claim_worthy(
            "This applies to all employees in the above categories who meet the eligibility requirements."
        )
        assert not ok


class TestVerbRecognition:
    """Verb list should recognize past-tense forms."""

    def test_past_tense_demonstrated(self):
        ok, reason = check_claim_worthy(
            "The monitoring system demonstrated significant improvement in detection "
            "accuracy across multiple operational scenarios during the evaluation period."
        )
        assert ok, f"Past-tense 'demonstrated' should be recognized, but rejected: {reason}"

    def test_past_tense_exceeded(self):
        ok, reason = check_claim_worthy(
            "Implementation costs exceeded productivity gains in most operational regions "
            "resulting in a negative return on investment during the evaluation phase."
        )
        assert ok, f"Past-tense 'exceeded' should be recognized, but rejected: {reason}"

    def test_past_tense_failed(self):
        ok, reason = check_claim_worthy(
            "The routing algorithm failed to maintain stable connections under peak "
            "load conditions across multiple geographic deployment regions."
        )
        assert ok, f"Past-tense 'failed' should be recognized, but rejected: {reason}"


class TestSalienceFilterIntegration:
    """End-to-end checks for the salience filter."""

    def test_good_claim_accepted(self):
        ok, reason = check_claim_worthy(
            "Implementation costs exceeded productivity gains in most operational "
            "regions resulting in a negative return on overall investment."
        )
        assert ok, f"Good claim should be accepted, but rejected with reason: {reason}"

    def test_too_short_rejected(self):
        ok, reason = check_claim_worthy("OK")
        assert not ok
        assert reason == "too_short"

    def test_no_verb_rejected(self):
        ok, reason = check_claim_worthy(
            "Table of Contents Introduction Background Methodology Results Conclusion"
        )
        assert not ok
        # reason could be no_verb or boilerplate_pattern


class TestRepetitiveFragment:
    """Garbled table cells flattened into prose should be rejected."""

    def test_repeated_token_run_rejected(self):
        ok, reason = check_claim_worthy(
            "Yes Yes Yes Can the user authenticate without performing additional steps"
        )
        assert not ok
        assert reason == "repetitive_fragment"

    def test_low_unique_ratio_rejected(self):
        ok, reason = check_claim_worthy("No No yes No yes No No yes can verify")
        assert not ok
        assert reason == "repetitive_fragment"

    def test_normal_sentence_not_flagged(self):
        ok, reason = check_claim_worthy(
            "The authentication system requires a salted hash to verify each "
            "submitted password value."
        )
        assert ok, f"normal sentence rejected: {reason}"


class TestDocumentHeader:
    """PDF running headers / footers and draft boilerplate should be rejected."""

    def test_page_running_header_rejected(self):
        ok, reason = check_claim_worthy(
            "113 NIST SP 800-63B-4 July 2025 Digital Identity Guidelines "
            "Authentication and Authenticator Management requirements apply."
        )
        assert not ok
        assert reason == "document_header"

    def test_retired_draft_boilerplate_rejected(self):
        ok, reason = check_claim_worthy(
            "RETIRED DRAFT April 1, 2016 The attached DRAFT document is provided "
            "here for historical purposes only and is superseded."
        )
        assert not ok
        assert reason == "document_header"

    def test_real_claim_citing_a_standard_kept(self):
        """A real claim that references a standard must NOT be flagged as a header."""
        ok, _ = check_claim_worthy(
            "An approved password hashing scheme published in the latest revision "
            "of SP 800-132 must be used to protect stored secrets."
        )
        assert ok


class TestRegulatoryModalExemption:
    """Crisp SHALL/MUST claims survive the content-word gate."""

    def test_short_shall_not_claim_kept(self):
        ok, reason = check_claim_worthy(
            "Verifiers SHALL NOT require users to change passwords periodically."
        )
        assert ok, f"regulatory claim rejected: {reason}"

    def test_short_non_modal_still_rejected(self):
        """Without a normative modal, the same brevity is still filtered."""
        ok, reason = check_claim_worthy("Users sometimes pick weaker passwords here.")
        assert not ok
        assert reason == "insufficient_content_words"
