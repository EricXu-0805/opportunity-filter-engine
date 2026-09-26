"""Finite resume-only research actions; not general semantic entailment."""
import pytest

from backend.lib.email_experience_attribution import experience_attribution_violations as check
from backend.lib.target_resume_ai_grounding import claim_upgrade_detected


@pytest.mark.parametrize('claim', ['I study Python sensors.', 'Studied Python sensors.', 'I researched Python sensors.',
                                  'Investigated Python sensors.', 'I wrote parser tests and studied Python sensors.'])
def test_new_personal_research_action_is_rejected(claim):
    source = 'I wrote parser tests using Python.'
    assert check(claim, [source], allow_subjectless_claims=True)
    assert claim_upgrade_detected(claim, source)
    # New bounded research vocabulary is not silently enabled for email.
    expected_default = ['unsupported experience attribution: personal write'] if claim.startswith('I wrote') else []
    assert check(claim, [source]) == expected_default


@pytest.mark.parametrize('source,claim', [
    ('I studied Python sensors.', 'Studied Python sensors.'),
    ('I studied Python sensors using NumPy.', 'I study Python sensors.'),
    ('Researched sensor calibration with Python.', 'I researched sensor calibration.'),
    ('I investigated 10000 sensor samples.', 'Investigated 10,000 sensor samples.'),
    ('Project A: I studied Python sensors.', 'Project A: Studied Python sensors.'),
    ('I did not study Python sensors. I wrote tests.', 'I wrote tests. I did not study Python sensors.'),
    ('My team researched sensors. I wrote tests.', 'I wrote tests. My team researched sensors.'),
])
def test_supported_inflection_and_safe_shortening_preserve_research_fact(source, claim):
    assert check(claim, [source], allow_subjectless_claims=True) == []
    assert not claim_upgrade_detected(claim, source)


@pytest.mark.parametrize('source,claim', [
    ('My team studied Python sensors. I wrote tests.', 'I study Python sensors. My team studied Python sensors. I wrote tests.'),
    ('My team investigated 88 samples. I wrote tests.', 'Investigated 88 samples, My team investigated 88 samples. I wrote tests.'),
    ('I did not research Python sensors.', 'I researched Python sensors. I did not research Python sensors.'),
    ('I studied sensor calibration.', 'I studied climate models.'),
    ('I studied Python sensors.', 'I researched Python sensors.'),
    ('I investigated 88 samples.', 'I investigated 99 samples.'),
    ('Project A: I studied 88 samples. Project B: I studied 99 samples.', 'Project A: I studied 99 samples. Project B: I studied 88 samples.'),
    ('Outcome: Studied Python sensors.', 'I studied Python sensors.'),
])
def test_actor_negation_object_project_and_number_do_not_transfer(source, claim):
    assert check(claim, [source], allow_subjectless_claims=True)
    assert claim_upgrade_detected(claim, source)
