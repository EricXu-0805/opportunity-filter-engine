"""Tests for ucb_common._detect_funding (faculty compensation signal).

ucb_common imports bs4 at module load, so guard with importorskip — the funding
logic itself is pure string matching and runs in CI where bs4 is installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("bs4")

from src.collectors.ucb_common import _detect_funding  # noqa: E402


class TestDetectFunding:
    def test_paid_position_upgrades_to_yes(self):
        paid, note = _detect_funding("This is a paid position in the lab.")
        assert paid == "yes"
        assert note and "paid" in note.lower()

    def test_stipend_and_workstudy_upgrade_to_stipend(self):
        assert _detect_funding("Summer stipend available")[0] == "stipend"
        assert _detect_funding("work-study eligible RA position")[0] == "stipend"
        assert _detect_funding("research assistantship offered")[0] == "stipend"

    def test_no_signal_stays_unknown_with_helpful_note(self):
        paid, note = _detect_funding("Research in computer vision and robotics.")
        assert paid == "unknown"
        # Never blank — gives the user actionable guidance instead.
        assert note and "funding" in note.lower()

    def test_empty_text_is_unknown(self):
        assert _detect_funding("")[0] == "unknown"
