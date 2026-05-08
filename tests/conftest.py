"""Shared test fixtures."""

import os
import sys
import pytest

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture
def sample_text():
    return (
        "The company policy mandates 2 days in office per week. "
        "Remote work is allowed 3 days. All employees must follow "
        "the standard working hours from 9 AM to 5 PM."
    )


@pytest.fixture
def contradicting_text():
    return (
        "The company policy mandates 5 days in office. "
        "Remote work is strictly prohibited. "
        "Working hours are from 7 AM to 7 PM with no exceptions."
    )
