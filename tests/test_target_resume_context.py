"""Provider-free public target context v2 compatibility and safety contract."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib import target_resume_ai as engine
from backend.lib.evidence_map import target_anchors
from backend.lib.target_resume_ai_validation import fingerprint, validate_document
from backend.main import app
from backend.routes import target_resume_ai as route

PATH = '/api/tailor/full-target/suggestions'
GROUPS = ('eligibility', 'timing', 'application', 'setting', 'availability', 'attribution')


def old_document():
    return json.loads((Path(__file__).parent / 'fixtures/target-resume-ai-golden.json').read_text())['draft']


def opportunity():
    old = old_document()['target_snapshot']
    return {'id': old['opportunity_id'], 'title': old['title'], 'organization': old['organization'],
            'source_url': old['source_url'], 'description_clean': old['description'],
            'source_type': 'campus_program', 'opportunity_type': 'research',
            'metadata': {'is_active': True}, 'eligibility': {'skills_required': old['requirements']},
            'application': {}}


def new_document(opp=None):
    doc = old_document()
    doc['target_snapshot'] = route.authoritative_target(opp or opportunity())
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot'])
    return doc


def request(doc):
    return {'version': 1, 'request_id': 'context-test', 'locale': 'en', 'draft': doc,
            'document_signature': fingerprint(doc), 'selected_unit_ids': [engine.units_for(doc)[0][0]['unit_id']]}


@pytest.fixture
def endpoint(monkeypatch):
    opp = opportunity()
    monkeypatch.setattr(route, 'load_opportunities_by_id', lambda: {opp['id']: opp})
    monkeypatch.setattr(route, 'is_configured', lambda: False)
    monkeypatch.setattr(engine, 'chat_completion', lambda *_a, **_kw: pytest.fail('provider must not run'))
    return TestClient(app), opp


def test_authoritative_context_contains_all_six_new_groups():
    target = route.authoritative_target(opportunity())
    assert target['context_version'] == 4
    assert set(target['criteria']) == set(GROUPS)


def test_generic_validation_accepts_strict_v2_without_changing_originals():
    doc = old_document()
    doc['target_snapshot'].update(context_version=2, criteria={key: {} for key in GROUPS})
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot'])
    assert validate_document(doc) == doc


def test_old_snapshot_still_valid_but_ai_refuses_incomplete_context(endpoint):
    client, _ = endpoint
    doc = old_document()
    before = deepcopy(doc)
    assert validate_document(doc) == before
    response = client.post(PATH, json=request(doc))
    assert response.status_code == 409
    assert response.json() == {'detail': {'code': 'legacy_target_context'}}
    assert doc == before


def test_qualification_only_change_refuses_before_provider(endpoint):
    client, opp = endpoint
    doc = new_document(opp)
    opp['eligibility']['preferred_year'] = ['senior']
    response = client.post(PATH, json=request(doc))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'target_changed'


# Each allowed field is tested independently: omitting one from the projector
# or signature makes the corresponding changed-target regression fail.
FIELD_CASES = [
    ('eligibility', 'preferred_year', ['senior']), ('eligibility', 'min_gpa_decimal', '3.5'),
    ('eligibility', 'majors', ['Chemistry']), ('eligibility', 'skills_required', ['C++']),
    ('eligibility', 'skills_preferred', ['Linux']), ('eligibility', 'citizenship_required', False),
    ('eligibility', 'international_friendly', 'unknown'), ('eligibility', 'work_auth_notes', 'Needs source review 王'),
    ('eligibility', 'first_time_researchers', True),
    ('timing', 'deadline', '2027-05-01'), ('timing', 'deadline_is_estimate', True),
    ('timing', 'is_rolling', True), ('timing', 'deadline_note', 'No closing date is stated.'),
    ('timing', 'start_date', '2027-06-01'), ('timing', 'posted_date', '2026-09-24'),
    ('timing', 'duration', '10 weeks'),
    ('application', 'contact_method', 'portal'), ('application', 'application_effort', 'unknown'),
    ('application', 'requires_resume', 'yes'), ('application', 'requires_cover_letter', 'unknown'),
    ('application', 'requires_transcript', 'no'), ('application', 'requires_recommendation', 'yes'),
    ('application', 'application_url', 'https://example.test/apply'),
    ('setting', 'location', 'Remote 王'), ('setting', 'remote_option', 'unknown'),
    ('setting', 'on_campus', False), ('setting', 'opportunity_type', 'summer_program'),
    ('setting', 'paid', 'stipend'), ('setting', 'compensation_details', 'Funding not guaranteed.'),
    ('setting', 'department', 'Physics'), ('setting', 'lab_or_program', 'Calibration Lab'),
    ('setting', 'pi_name', 'Dr Example'),
    ('availability', 'record_kind', 'unrecognized-future-kind'), ('availability', 'source_type', 'future-source'),
    ('availability', 'faculty_availability_status', 'unknown'),
    ('availability', 'target_truth', {'listing_state': 'future-state', 'actionable': False,
                                    'reference_only': True, 'accepting_state': None, 'reason_code': 'new-code'}),
    *[('attribution', field, 'inferred') for field in ('skills_attribution', 'majors_attribution',
      'preferred_year_attribution', 'international_attribution', 'citizenship_attribution', 'paid_attribution')],
]


def set_public_field(public, group, key, value):
    if group in ('eligibility', 'application'):
        public.setdefault(group, {})['min_gpa' if key == 'min_gpa_decimal' else key] = value
    elif key == 'deadline_note':
        public.setdefault('metadata', {})[key] = value
    else:
        public[key] = value


@pytest.mark.parametrize('group,key,value', FIELD_CASES)
def test_every_public_field_is_preserved_and_changes_snapshot_signature(group, key, value):
    from backend.lib.target_resume_context import public_target_context
    public = opportunity()
    before = public_target_context(public)
    set_public_field(public, group, key, value)
    after = public_target_context(public)
    assert after['criteria'][group][key] == value
    assert fingerprint(after) != fingerprint(before)
    doc = old_document()
    doc['target_snapshot'] = after
    doc['base']['target_signature'] = fingerprint(after)
    assert validate_document(doc) == doc
    # Replacing the snapshot alone cannot borrow the previous signature.
    doc['base']['target_signature'] = fingerprint(before)
    with pytest.raises(ValueError, match='invalid_signature'):
        validate_document(doc)


@pytest.mark.parametrize('group,key,value', [case for case in FIELD_CASES if case[0] != 'availability'])
def test_each_changed_public_constraint_is_rejected_by_real_route(endpoint, group, key, value):
    client, opp = endpoint
    doc = new_document(opp)
    set_public_field(opp, group, key, value)
    response = client.post(PATH, json=request(doc))
    assert response.status_code == 409, (group, key, response.text)
    assert response.json()['detail']['code'] == 'target_changed'


@pytest.mark.parametrize('group,key,value', FIELD_CASES)
def test_null_is_kept_and_missing_is_not_filled(group, key, value):
    from backend.lib.target_resume_context import public_target_context
    public = opportunity()
    # The input starts sparse so null remains distinct from absence and false.
    if group == 'eligibility' and key == 'skills_required':
        public['eligibility'].pop(key)
    elif key in public:
        public.pop(key)
    before = public_target_context(public)
    assert key not in before['criteria'][group]
    set_public_field(public, group, key, None)
    target = public_target_context(public)
    assert key in target['criteria'][group] and target['criteria'][group][key] is None
    assert fingerprint(before) != fingerprint(target)


@pytest.mark.parametrize('mutation', [
    lambda t: t.update(context_version=True), lambda t: t.update(context_version=5),
    lambda t: t.pop('context_version'), lambda t: t.pop('criteria'),
    lambda t: t['criteria'].pop('timing'), lambda t: t['criteria'].update(extra={}),
    lambda t: t['criteria'].update(eligibility=None),
    lambda t: t['criteria']['eligibility'].update(min_gpa_decimal=3),
    lambda t: t['criteria']['eligibility'].update(preferred_year='senior'),
    lambda t: t['criteria']['eligibility'].update(majors=[None]),
    lambda t: t['criteria']['eligibility'].update(citizenship_required=1),
    lambda t: t['criteria']['application'].update(requires_resume=True),
    lambda t: t['criteria']['setting'].update(paid=False),
    lambda t: t['criteria']['timing'].update(deadline='PRIVATE\ud800'),
    lambda t: t['criteria']['timing'].update(deadline='PRIVATE\x00'),
    lambda t: t['criteria']['availability'].update(target_truth={'actionable': 'yes'}),
    lambda t: t['criteria']['availability'].update(target_truth={'verified_at': '2026-09-24'}),
    lambda t: t['criteria']['attribution'].update(skills_attribution='verified'),
    lambda t: t['criteria']['application'].update(contact_email='PRIVATE@example.test'),
    lambda t: t['criteria']['eligibility'].update(eligibility_text_raw='PRIVATE'),
])
def test_invalid_new_context_returns_safe_422_without_echo(endpoint, mutation):
    client, _ = endpoint
    doc = new_document()
    mutation(doc['target_snapshot'])
    # Invalid strings cannot be hashed; use the pre-mutation signature to reach
    # real route validation without putting sensitive exception input on wire.
    body = request(new_document())
    body['draft'] = doc
    response = client.post(PATH, content=json.dumps(body, ensure_ascii=True), headers={'Content-Type': 'application/json'})
    assert response.status_code == 422 and 'PRIVATE' not in response.text
    assert {'private', 'no-store'} <= set(response.headers['cache-control'].split(', '))


@pytest.mark.parametrize('value,expected', [
    (3.0, '3'), (3.5, '3.5'), (-0.0, '0'), (1e-7, '1e-7'), (1e-6, '0.000001'),
    (1e20, '100000000000000000000'), (1e21, '1e+21'),
    (333333333.33333329, '333333333.3333333'), (' 3.00 or equivalent ', ' 3.00 or equivalent '),
    ('unknown', 'unknown'), (None, None),
])
def test_gpa_uses_ecmascript_number_scalar_without_rounding_source_strings(value, expected):
    from backend.lib.target_resume_context import public_target_context
    public = opportunity()
    public['eligibility']['min_gpa'] = value
    assert public_target_context(public)['criteria']['eligibility']['min_gpa_decimal'] == expected


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), float('-inf'), [], {}])
def test_invalid_gpa_is_not_coerced(value):
    from backend.lib.target_resume_context import public_target_context
    public = opportunity()
    public['eligibility']['min_gpa'] = value
    with pytest.raises(ValueError):
        public_target_context(public)


def test_attribute_top_null_precedes_metadata_and_inferred_stays_distinct():
    from backend.lib.target_resume_context import public_target_context
    public = opportunity()
    public['metadata']['skills_attribution'] = 'inferred'
    inferred = public_target_context(public)
    assert inferred['requirements'] == []
    assert inferred['criteria']['eligibility']['skills_required'] == public['eligibility']['skills_required']
    assert inferred['criteria']['attribution']['skills_attribution'] == 'inferred'
    public['skills_attribution'] = None
    explicit_null = public_target_context(public)
    assert explicit_null['requirements'] == public['eligibility']['skills_required']
    assert explicit_null['criteria']['attribution']['skills_attribution'] is None


def test_public_projection_redacts_private_raw_tracking_and_retains_nulls():
    opp = opportunity()
    opp.update(contact_email='PRIVATE@example.test', pi_email='PRIVATE@example.test', professor_id='PRIVATE',
               description_raw='PRIVATE', raw_html='PRIVATE', internal_note='PRIVATE',
               deadline=None, on_campus=None, paid='unknown')
    opp['metadata'].update(confidence_score=0.6, notes='PRIVATE', first_seen_at='PRIVATE',
                           deadline_note='Unknown deadline', last_verified='2026-09-24', expires_at='2026-10-01')
    opp['eligibility'].update(eligibility_text_raw='PRIVATE', min_gpa=None, citizenship_required=None,
                              work_auth_notes='Email PRIVATE@example.test')
    opp['application'].update(application_url='mailto:PRIVATE@example.test')
    before = deepcopy(opp)
    target = route.authoritative_target(opp)
    assert 'PRIVATE' not in json.dumps(target)
    assert 'verified_at' not in target['criteria']['availability']['target_truth']
    assert 'expires_at' not in target['criteria']['availability']['target_truth']
    assert target['criteria']['eligibility']['min_gpa_decimal'] is None
    assert target['criteria']['timing']['deadline'] is None
    assert target['criteria']['setting']['on_campus'] is None
    assert target['criteria']['setting']['paid'] == 'unknown'
    assert opp == before
    target['criteria']['eligibility']['skills_required'].append('mutation')
    assert opp == before


def test_unknown_record_kind_does_not_recover_removed_offer_terms():
    opp = opportunity()
    opp.pop('source_type')
    opp.update(deadline='2030-01-01', paid='yes', is_rolling=True)
    opp['eligibility'].update(citizenship_required=False)
    opp['application'].update(requires_resume='yes')
    target = route.authoritative_target(opp)
    assert target['criteria']['availability']['record_kind'] == 'unknown'
    assert target['criteria']['eligibility'] == {}
    assert target['criteria']['application'] == {}
    assert target['criteria']['timing'] == {}
    assert 'paid' not in target['criteria']['setting']


def test_legacy_prepare_refused_without_mutating_old_golden():
    from backend.lib.target_resume_ai_schema import FullTargetRequest
    doc = old_document()
    before = deepcopy(doc)
    with pytest.raises(ValueError, match='legacy_target_context'):
        engine.prepare_batch(FullTargetRequest(**request(doc)), doc)
    assert doc == before and validate_document(doc) == before


def test_new_criteria_count_complete_unicode_and_prompt_constraints_are_not_quote_sources(endpoint):
    client, opp = endpoint
    opp['eligibility']['work_auth_notes'] = 'unknown 王😀'
    doc = new_document(opp)
    target = doc['target_snapshot']
    legacy_count = sum(len(target[key]) for key in ('opportunity_id', 'title', 'organization', 'source_url', 'description')) + sum(map(len, target['requirements']))
    criteria_size = len(json.dumps(target['criteria'], ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    assert engine.target_character_count(target) == legacy_count + criteria_size + sum(len(json.dumps(target[k], ensure_ascii=False, sort_keys=True, separators=(',', ':'))) for k in ('research', 'lab'))
    units = engine.units_for(doc)[0]
    anchors = target_anchors(target)
    messages, reason = engine.batch_preflight(doc, units[:1], 'zh', anchors)
    assert reason is None
    prompt = json.loads(messages[1]['content'])
    assert prompt['criteria'] == target['criteria']
    assert '"criteria" (the opportunity\'s published constraints: never anchors, never evidence)' in messages[0]['content']
    assert anchors and not any('unknown' in anchor.text for anchor in anchors)
    assert not engine.valid_quotes([{'field': 'criteria', 'requirement_index': None, 'start': 0, 'end': 7,
                                     'quote': 'unknown'}], target)
    opp['eligibility']['work_auth_notes'] = '😀' * 15000
    opp['compensation_details'] = '王' * 15000
    response = client.post(PATH, json=request(new_document(opp)))
    assert response.status_code == 200
    assert response.json()['receipts'][0]['reason_code'] == 'target_too_large'
    assert response.json()['logical_calls'] == 0


def test_faculty_projection_keeps_unknown_null_without_recreating_listing_claims():
    opp = opportunity()
    opp.update(source_type='faculty_research', deadline='2030-01-01', paid='yes', on_campus=True,
               is_rolling=True, location='Campus', duration='12 weeks')
    opp['eligibility'].update(min_gpa=3.5, international_friendly='yes', citizenship_required=False)
    opp['application'].update(requires_resume='yes', application_url='https://example.test/apply')
    target = route.authoritative_target(opp)
    criteria = target['criteria']
    assert criteria['availability']['record_kind'] == 'faculty_contact'
    assert criteria['eligibility']['international_friendly'] == 'unknown'
    assert criteria['eligibility']['citizenship_required'] is None
    assert criteria['eligibility']['min_gpa_decimal'] is None
    assert criteria['timing']['deadline'] is None and criteria['timing']['is_rolling'] is False
    assert criteria['setting']['on_campus'] is None and criteria['setting']['paid'] == 'unknown'
    assert criteria['application']['requires_resume'] == 'unknown'
    # The existing anonymous URL sanitizer omits this null URL. Do not restore
    # the canonical faculty profile URL as an application portal.
    assert 'application_url' not in criteria['application']


def test_verification_timestamps_are_not_persisted_or_signature_changes():
    opp = opportunity()
    first = route.authoritative_target(opp)
    opp['metadata'].update(last_verified='2026-09-24', expires_at='2030-01-01')
    second = route.authoritative_target(opp)
    assert first == second
    assert fingerprint(first) == fingerprint(second)
