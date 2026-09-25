"""Shared Node-generated oracles; no provider, DB, renderer, or HTTP service.

Storage compatibility is covered by the sibling TS SDK-boundary tests. This
file verifies Python full-document/context validation and export wire parsing.
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.lib.target_resume_ai import units_for
from backend.lib.target_resume_ai_validation import fingerprint, validate_document
from backend.lib.target_resume_context import (
    public_target_context,
    target_context_character_count,
    validate_target_context,
)
from backend.lib.target_resume_export_schema import ExportRequest

FIXTURES = Path(__file__).parent / 'fixtures'
GOLDEN = json.loads((FIXTURES / 'target-resume-context-v2-golden.json').read_text())
LEGACY = json.loads((FIXTURES / 'target-resume-ai-golden.json').read_text())


def test_exact_public_projection_and_whole_document_match_node_oracles():
    public = deepcopy(GOLDEN['public_opportunity'])
    before = deepcopy(public)
    target = public_target_context(public)
    assert target == GOLDEN['draft']['target_snapshot']
    assert public == before
    assert validate_target_context(target) == target
    assert fingerprint(target) == GOLDEN['draft']['base']['target_signature']
    assert target_context_character_count(target) == GOLDEN['target_character_count']
    assert validate_document(GOLDEN['draft']) == GOLDEN['draft']
    assert fingerprint(GOLDEN['draft']) == GOLDEN['document_signature']
    units, protected = units_for(GOLDEN['draft'])
    assert units == GOLDEN['units']
    assert protected == GOLDEN['manifest']['protected_unit_count']
    assert [unit['unit_id'] for unit in units] == GOLDEN['manifest']['unit_ids']


@pytest.mark.parametrize('case', GOLDEN['context_cases'], ids=lambda case: case['name'])
def test_numeric_gpa_uses_ecmascript_scalar_and_preserves_original_strings(case):
    public = deepcopy(GOLDEN['public_opportunity'])
    public['eligibility']['min_gpa'] = json.loads(case['input_json'])
    target = public_target_context(public)
    assert target['criteria']['eligibility']['min_gpa_decimal'] == case['expected_min_gpa_decimal']
    assert fingerprint(target) == case['target_signature']


@pytest.mark.parametrize('case', GOLDEN['target_cases'], ids=lambda case: case['name'])
def test_missing_null_and_inference_are_exact_signed_values(case):
    doc = deepcopy(GOLDEN['draft'])
    doc['target_snapshot'] = deepcopy(case['target'])
    doc['base']['target_signature'] = case['target_signature']
    assert validate_document(doc) == doc
    assert fingerprint(doc['target_snapshot']) == case['target_signature']


@pytest.mark.parametrize('group', ['eligibility', 'timing', 'application', 'setting', 'availability', 'attribution'])
def test_unknown_nested_fields_are_rejected_not_silently_dropped(group):
    doc = deepcopy(GOLDEN['draft'])
    doc['target_snapshot']['criteria'][group]['private_extra'] = 'not accepted'
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot'])
    with pytest.raises(ValueError):
        validate_document(doc)


@pytest.mark.parametrize(('group', 'key', 'value'), [
    ('eligibility', 'preferred_year', ['Senior']), ('timing', 'deadline', '2027-01-01'),
    ('application', 'requires_resume', 'no'), ('setting', 'remote_option', 'remote'),
    ('availability', 'faculty_availability_status', 'not_accepting'),
    ('attribution', 'skills_attribution', 'inferred'),
])
def test_every_new_group_is_bound_by_the_stored_target_signature(group, key, value):
    doc = deepcopy(GOLDEN['draft'])
    doc['target_snapshot']['criteria'][group][key] = value
    assert validate_target_context(doc['target_snapshot']) == doc['target_snapshot']
    with pytest.raises(ValueError):
        validate_document(doc)


def test_legacy_full_document_and_signature_are_not_silently_upgraded():
    before = deepcopy(LEGACY['draft'])
    assert validate_document(LEGACY['draft']) == before
    assert fingerprint(LEGACY['draft']) == GOLDEN['legacy_document_signature'] == LEGACY['document_signature']
    assert LEGACY['draft'] == before
    assert 'context_version' not in before['target_snapshot']


@pytest.mark.parametrize('format_', ['pdf', 'docx'])
@pytest.mark.parametrize('document_signature', [GOLDEN['document_signature'], GOLDEN['legacy_document_signature']])
def test_old_and_new_sources_accept_the_same_selected_text_export_wire(format_, document_signature):
    payload = {'version': 1, 'request_id': 'context-v2-export', 'format': format_,
               'document_signature': document_signature,
               'export_signature': GOLDEN['export']['export_signature'],
               'projection': deepcopy(GOLDEN['export']['projection'])}
    model = ExportRequest.model_validate(payload)
    model.verify_signature()
    assert model.model_dump() == payload
    serialized = json.dumps(payload['projection'], ensure_ascii=False)
    assert 'My manual draft edit is not evidence.' in serialized
    for private_key in ('criteria', 'target_snapshot', 'resume_text', 'evidence-one', 'original'):
        assert private_key not in serialized
