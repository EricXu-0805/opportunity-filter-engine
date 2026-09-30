"""The faculty description the server writes is re-said in the UI language.

frontend/src/lib/faculty-profile-copy.ts recognises this exact English text
and translates the product sentences around the source's research areas. If
the server's wording changes, regenerate the shared fixture and the frontend
helper together; otherwise the Chinese UI silently falls back to English.
"""
import json
from pathlib import Path

import pytest

from src.evidence import _faculty_profile_summary

_FIXTURE = Path(__file__).resolve().parents[1] / 'frontend/src/lib/__fixtures__/faculty-profile-summary.json'
_CASES = json.loads(_FIXTURE.read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', _CASES, ids=[case['name'] for case in _CASES])
def test_shared_fixture_is_what_the_server_writes(case):
    assert _faculty_profile_summary(case['record']) == case['server_text']
    areas = case['research_areas']
    assert (f'Research areas: {areas} ' in case['server_text']) if areas else ('Research areas:' not in case['server_text'])


def test_fixture_covers_every_availability_sentence_and_affiliation_shape():
    texts = [case['server_text'] for case in _CASES]
    for sentence in (
        'Contact this faculty member to ask whether undergraduate research opportunities are currently available.',
        'The source profile states that this faculty contact is not currently accepting undergraduate students or researchers.',
        'The source profile reports that this faculty member is not currently conducting active research.',
    ):
        assert any(text.endswith(sentence) for text in texts)
    records = [case['record'] for case in _CASES]
    assert {(bool(r.get('department')), bool(r.get('organization'))) for r in records} == {
        (True, True), (True, False), (False, True), (False, False),
    }
