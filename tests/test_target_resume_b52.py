"""B52 direction, bounded rationale and explicit same-activity support checks."""
import json
from copy import deepcopy

import pytest

from backend.lib import evidence_map as em
from backend.lib import target_resume_ai as ai
from backend.lib import target_resume_plan as plan
from backend.lib.target_resume_ai_schema import FullTargetRequest
from backend.lib.target_resume_ai_validation import confirmed_document, fingerprint, units_for, validate_document
from backend.lib.target_resume_plan_schema import FullTargetPlanRequest
from tests.test_full_target_resume_attribution import _document

OPP = {'id': 'b52', 'title': 'Research', 'organization': 'Example', 'source_url': 'https://example.edu/lab',
       'description_clean': 'Research Python parsers.', 'eligibility': {'skills_required': ['Python']},
       'source_type': 'campus_program', 'opportunity_type': 'research', 'metadata': {'is_active': True}}
ORIGINAL = 'I wrote parser tests using Python.'
SUPPORT = 'I ran 12 parser test cases.'
ATTACK = 'Your independently led CRISPR clinical trials and five first-author Nature papers make you an ideal fit.'
QUOTE = {'field': 'requirement', 'requirement_index': 0, 'start': 0, 'end': 6, 'quote': 'Python'}
LINK = {'id': 'L1', 'anchor': 't2', 'term': 'Python', 'source': 'Python', 'relation': 'same'}
# personal_first may carry a confirmed support clause, word for word, after the student's own part.
TEAM_ORIGINAL = 'My team built a Python parser; I wrote parser tests.'
MERGED = 'I wrote parser tests and ran 12 parser test cases; my team built a Python parser.'
CANDIDATE_OPS = ([{'op': 'personal_first'}], [{'op': 'verb_first'}], [{'op': 'lead_with', 'link': 'L1'}])


def document(same_activity=True, originals=None):
    doc = _document(originals or [ORIGINAL, SUPPORT], OPP)
    if same_activity:
        master = doc['base_snapshot']['resume_master']
        master['activities'][0]['details'].extend(master['activities'][1]['details'])
        master['activities'].pop()
        doc['document'] = confirmed_document(doc['base_snapshot'], doc['base']['source_signature'])
        for section in doc['document']['sections']:
            section['included'] = True
            for block in section['blocks']:
                block['included'] = True
                for line in block['lines']:
                    line.update(text=line['original'], included=True)
    return validate_document(doc)


def request(doc, groups=None, planning=False):
    value = {'version': 1, 'request_id': 'b52', 'locale': 'en', 'draft': doc, 'document_signature': fingerprint(doc)}
    if groups is not None:
        value['support_groups'] = groups
    if planning:
        value['options'] = {'target_pages': 1}
        return FullTargetPlanRequest.model_validate(value)
    value['selected_unit_ids'] = [u['unit_id'] for u in units_for(doc)[0] if u['evidence']['id'] == 'exp-0']
    return FullTargetRequest.model_validate(value)


def group(doc):
    ids = {u['evidence']['id']: u['unit_id'] for u in units_for(doc)[0]}
    return [{'unit_id': ids['exp-0'], 'support_unit_ids': [ids['exp-1']], 'confirmed': True}]


def anchors(doc):
    return em.target_anchors(doc['target_snapshot'])


def model_unit(unit, reason=ATTACK, proposed=None, links=None, doc=None):
    """A v6 row: a keep, or the proposal under the first operations the contract admits (given doc)."""
    row = {'unit_id': unit['unit_id'], 'priority': 'high', 'reason': reason,
           'links': [dict(LINK)] if links is None else links, 'decision': 'keep', 'ops': [], 'text': None,
           'keep_reason': 'already_aligned'}
    if proposed is None:
        return row
    rows = [{**row, 'decision': 'rewrite', 'ops': ops, 'text': proposed, 'keep_reason': None} for ops in CANDIDATE_OPS]
    if doc is None:
        return rows[0]
    em_unit = ai._em_unit(unit)
    by_id = {anchor.id: anchor for anchor in anchors(doc)}
    return next((candidate for candidate in rows if em.check_rewrite(
        em_unit, candidate, by_id, output_language='en', extra_keys=ai.ROW_EXTRA_KEYS).status == 'pending'), rows[0])


def outcome(doc, selected, row):
    """Receipts after the contract, the locks and an accepting review."""
    results, pending = ai.parse_output(json.dumps({'units': [row]}), selected, anchors(doc))
    return results + ai.finalize(pending, ['accepted'] * len(pending)), pending


def refused(receipt):
    assert receipt['status'] == 'unchanged', receipt
    assert receipt['reason_code'] in ('beyond_allowed_edit', 'rewrite_rejected'), receipt
    assert receipt['suggestion']['proposed_text'] is None


def test_direction_is_complete_bound_to_document_and_never_student_fact():
    doc = document()
    before = deepcopy(doc)
    direction = '  I want to study RNA interference.\n我对表观遗传调控感兴趣。🧪  '
    doc['base_snapshot']['research_interests'] = direction
    assert validate_document(doc) == doc and fingerprint(doc) != fingerprint(before)
    req = request(doc)
    _, _, selected, _ = ai.prepare_batch(req, doc)
    payload = json.loads(ai.build_prompt(doc, selected, 'en', anchors(doc))[1]['content'])
    assert payload['student_direction'] == {'research_interests': direction}
    assert all(direction not in unit['original'] for unit in payload['units'])
    blocks, _, scope = plan.prepare_plan(request(doc, planning=True), doc)
    messages, reason = plan.plan_preflight(doc, blocks, scope, {'target_pages': 1}, 'zh')
    assert reason is None and json.loads(messages[1]['content'])['student_direction'] == {'research_interests': direction}
    assert doc['document'] == before['document']
    assert 'student_direction' not in json.loads(ai.build_prompt(before, selected, 'en', anchors(before))[1]['content'])


def test_untrusted_reason_cannot_claim_accomplishments_beside_real_quotes():
    doc = document()
    _, _, selected, _ = ai.prepare_batch(request(doc), doc)
    # With a link the reason quotes the linked words; without one, the whole original.
    for links, quoted in (([LINK], 'Python'), ([], ORIGINAL)):
        result, _ = outcome(doc, selected, model_unit(selected[0], links=links))
        reason = result[0]['suggestion']['reason']
        assert result[0]['status'] == 'unchanged' and ATTACK not in reason
        assert json.dumps(quoted) in reason
    blocks, _, _ = plan.prepare_plan(request(doc, planning=True), doc)
    line = blocks[0]['lines'][-1]
    row = {'section_id': blocks[0]['section_id'], 'block_id': blocks[0]['block_id'], 'action': 'keep', 'reason': ATTACK,
           'target_evidence': [QUOTE], 'source_evidence': [{'unit_id': line['unit_id'], 'start': 0, 'end': len(line['original']), 'quote': line['original']}], 'rewrites': []}
    items, error = plan.parse_plan_output(json.dumps({'items': [row]}), blocks, doc['target_snapshot'])
    assert error is None and len(items) == 1
    assert ATTACK not in items[0]['reason'] and line['original'] in items[0]['reason']


def test_confirmed_same_activity_support_can_supply_detail_with_full_receipt():
    doc = document(originals=[TEAM_ORIGINAL, SUPPORT])
    req = request(doc, group(doc))
    _, _, selected, _ = ai.prepare_batch(req, doc)
    result, pending = outcome(doc, selected, model_unit(selected[0], reason='method_relevance', proposed=MERGED))
    suggestion = result[0]['suggestion']
    assert suggestion and suggestion['proposed_text'] == MERGED and suggestion['ops'] == ['personal_first']
    assert [q['quote'] for q in suggestion['source_evidence']] == [TEAM_ORIGINAL, SUPPORT]
    assert [q['unit_id'] for q in suggestion['source_evidence']] == [group(doc)[0]['unit_id'], *group(doc)[0]['support_unit_ids']]
    assert SUPPORT in ai.build_prompt(doc, selected, 'en', anchors(doc))[1]['content']
    # The review sees the confirmed line it may borrow from.
    assert ai.review_pairs(pending)[0].original.endswith('Confirmed source for the same activity: ' + SUPPORT)
    envelope = ai.response_envelope(req, doc, units_for(doc)[0], 1, result, 0)
    assert envelope['support_groups'] == group(doc)


def test_without_explicit_support_same_activity_cannot_borrow_number():
    doc = document(originals=[TEAM_ORIGINAL, SUPPORT])
    _, _, selected, _ = ai.prepare_batch(request(doc), doc)
    result, pending = outcome(doc, selected, model_unit(selected[0], proposed=MERGED))
    refused(result[0])
    assert pending == [] and result[0]['reason_code'] == 'beyond_allowed_edit'


@pytest.mark.parametrize('mutation', ['other_activity', 'self', 'duplicate', 'unknown', 'not_confirmed'])
def test_invalid_support_is_rejected(mutation):
    doc = document(same_activity=mutation != 'other_activity')
    groups = group(doc)
    if mutation == 'self': groups[0]['support_unit_ids'] = [groups[0]['unit_id']]
    if mutation == 'duplicate': groups[0]['support_unit_ids'] *= 2
    if mutation == 'unknown': groups[0]['support_unit_ids'] = ['unknown']
    if mutation == 'not_confirmed': groups[0]['confirmed'] = False
    with pytest.raises(ValueError):
        ai.prepare_batch(request(doc, groups), doc)


@pytest.mark.parametrize('originals,proposed', [
    (['I wrote analysis scripts using MATLAB.', 'I executed 8 sensor checks.'],
     'I wrote MATLAB analysis scripts and ran 8 sensor checks.'),
    (['I used Rust to build ingestion pipelines.', 'I ran 5 integration checks.'],
     'I built ingestion pipelines using Rust and executed 5 integration checks.'),
    (['I analyzed sensor recordings with MATLAB.', 'I ran 8 sensor checks.'],
     'I analyzed sensor recordings using MATLAB and executed 8 sensor checks.'),
    (['团队完成了模型。本人没有训练模型。', '本人整理了12条记录。'],
     '团队完成了模型。本人没有训练模型。本人整理了12条记录。'),
])
def test_a_merge_with_no_allowed_move_or_a_new_verb_is_kept_with_its_sources(originals, proposed):
    """v5 suggested these merges. v6 offers no bare merge and no new verb ("ran" for "executed"),
    so each is kept as written, with its advice and both confirmed sources."""
    doc = document(originals=originals)
    _, _, selected, _ = ai.prepare_batch(request(doc, group(doc)), doc)
    result, _ = outcome(doc, selected, model_unit(selected[0], reason='transferable_experience', proposed=proposed, doc=doc))
    refused(result[0])
    assert result[0]['reason_code'] == 'beyond_allowed_edit'
    assert [q['quote'] for q in result[0]['suggestion']['source_evidence']] == originals


@pytest.mark.parametrize('originals,proposed', [
    (['I tested 12 parser cases.', 'I collected 45 samples.'], 'I tested 45 parser cases.'),
    (['I ran 12 parser cases.', 'I ran 8 sensor checks.'], 'I ran 8 parser cases.'),
    (['I wrote parser tests.', 'I built a model using Python.'], 'I wrote Python parser tests.'),
    (['My team built a Python parser.', 'I wrote parser tests.'], 'I built a Python parser. My team built a Python parser. I wrote parser tests.'),
    (['团队完成了模型。本人没有训练模型。', '本人整理了12条记录。'], '本人训练模型并整理了12条记录。'),
    (['I did not lead the experiment.', 'I collected 12 samples.'], 'I led the experiment and collected 12 samples.'),
])
def test_confirming_source_relationship_never_authorizes_fact_transfer(originals, proposed):
    doc = document(originals=originals)
    _, _, selected, _ = ai.prepare_batch(request(doc, group(doc)), doc)
    result, _ = outcome(doc, selected, model_unit(selected[0], proposed=proposed, doc=doc))
    refused(result[0])


@pytest.mark.parametrize('kind', ['activities', 'education', 'publications'])
@pytest.mark.parametrize('entry_id', ['exp-0', 'exp-1'])
def test_entry_also_linked_elsewhere_cannot_support_merge(kind, entry_id):
    doc = document()
    record = {'id': 'other-record', 'details': [{'id': entry_id, 'revision': 1}]}
    if kind == 'activities': record['kind'] = 'project'
    doc['base_snapshot']['resume_master'][kind].append(record)
    doc['document'] = confirmed_document(doc['base_snapshot'], doc['base']['source_signature'])
    for section in doc['document']['sections']:
        section['included'] = True
        for block in section['blocks']:
            block['included'] = True
            for line in block['lines']:
                line.update(text=line['original'], included=True)
    validate_document(doc)
    entries = [u for u in units_for(doc)[0] if u['section_id'] == 'activities' and u['block_id'] == 'project-0']
    ids = {u['evidence']['id']: u['unit_id'] for u in entries}
    groups = [{'unit_id': ids['exp-0'], 'support_unit_ids': [ids['exp-1']], 'confirmed': True}]
    req = request(doc, groups)
    with pytest.raises(ValueError, match='invalid_support_group'):
        ai.prepare_batch(req, doc)


@pytest.mark.parametrize('mutation', ['withdrawn', 'revision', 'original'])
def test_changed_support_snapshot_cannot_retain_old_valid_document(mutation):
    doc = document()
    if mutation == 'withdrawn': doc['base_snapshot']['experience_entries'][1]['status'] = 'withdrawn'
    elif mutation == 'revision': doc['base_snapshot']['experience_entries'][1]['revision'] = 2
    else: doc['document']['sections'][1]['blocks'][0]['lines'][-1]['original'] = 'I ran 99 cases.'
    with pytest.raises(ValueError): validate_document(doc)


def test_out_of_batch_target_and_fact_support_refused():
    doc = document()
    groups = group(doc)
    groups[0]['unit_id'], groups[0]['support_unit_ids'][0] = groups[0]['support_unit_ids'][0], groups[0]['unit_id']
    with pytest.raises(ValueError, match='invalid_support_group'): ai.prepare_batch(request(doc, groups), doc)
    groups = group(doc)
    groups[0]['support_unit_ids'] = [units_for(doc)[0][0]['unit_id']]
    with pytest.raises(ValueError, match='invalid_support_group'): ai.prepare_batch(request(doc, groups), doc)


@pytest.mark.parametrize('field,value', [('confirmed', 1), ('confirmed', 'true'), ('support_unit_ids', []),
                                      ('support_unit_ids', ['x'] * 25), ('unit_id', ''), ('unexpected', True)])
def test_support_group_strict_wire(field, value):
    doc = document(); groups = group(doc); groups[0][field] = value
    with pytest.raises(ValueError): request(doc, groups)


def test_empty_explicit_groups_echo_and_no_groups_stay_original_only():
    doc = document()
    for groups in (None, []):
        req = request(doc, groups)
        units, protected, selected, _ = ai.prepare_batch(req, doc)
        result = ai.response_envelope(req, doc, units, protected, [], 0)
        assert ('support_groups' in result) is (groups is not None)
        assert 'support_sources' not in selected[0]


def test_complete_direction_and_support_enter_budget_without_clipping():
    doc = document(); doc['base_snapshot']['research_interests'] = '方向🧪' * 50000
    validate_document(doc)
    req = request(doc)
    _, _, selected, _ = ai.prepare_batch(req, doc)
    assert ai.batch_preflight(doc, selected, 'en', anchors(doc)) == (None, 'interests_too_large')
    blocks, _, scope = plan.prepare_plan(request(doc, planning=True), doc)
    assert plan.plan_preflight(doc, blocks, scope, {'target_pages': 1}, 'en') == (None, 'interests_too_large')
    doc = document(originals=['I wrote tests. ' + 'a' * 3000, 'I ran checks. ' + 'b' * 3000])
    with pytest.raises(ValueError, match='batch_too_large'): ai.prepare_batch(request(doc, group(doc)), doc)


@pytest.mark.parametrize('value', [None, 3, True, ['AI'], 'bad\x00text', 'bad\ud800text'])
def test_direction_invalid_type_or_unicode_rejected(value):
    doc = document(); doc['base_snapshot']['research_interests'] = value
    with pytest.raises(ValueError): validate_document(doc)


def test_target_and_interest_cannot_become_student_skills():
    doc = document(); doc['base_snapshot']['research_interests'] = 'CRISPR clinical trials'
    _, _, selected, _ = ai.prepare_batch(request(doc), doc)
    result, _ = outcome(doc, selected, model_unit(selected[0], proposed='I led CRISPR clinical trials.', doc=doc))
    refused(result[0])


def test_grouped_plan_rewrite_uses_combined_length_and_preserves_sources():
    doc = document(); req = request(doc, group(doc), planning=True)
    blocks, manifest, scope = plan.prepare_plan(req, doc)
    line = next(line for line in blocks[0]['lines'] if line['evidence']['id'] == 'exp-0')
    proposed = 'I wrote Python parser tests and ran 12 parser test cases.'
    assert len(proposed) > len(ORIGINAL) and len(proposed) < len(ORIGINAL) + len(SUPPORT)
    source_quote = {'unit_id': line['unit_id'], 'start': 0, 'end': len(ORIGINAL), 'quote': ORIGINAL}
    row = {'section_id': blocks[0]['section_id'], 'block_id': blocks[0]['block_id'], 'action': 'compress',
           'reason': 'space_tradeoff', 'target_evidence': [QUOTE], 'source_evidence': [source_quote],
           'rewrites': [{'unit_id': line['unit_id'], 'proposed_text': proposed}]}
    items, error = plan.parse_plan_output(json.dumps({'items': [row]}), blocks, doc['target_snapshot'], 'zh')
    assert error is None
    rewrite = items[0]['rewrites'][0]
    assert rewrite['status'] == 'suggested' and rewrite['proposed_text'] == proposed
    assert [q['quote'] for q in rewrite['source_evidence']] == [ORIGINAL, SUPPORT]
    assert items[0]['reason'].startswith('建议压缩')
    assert plan.plan_response(req, doc, manifest, scope, items, None, 1)['support_groups'] == group(doc)


def test_model_cannot_select_unapproved_source_for_unit_reason():
    doc = document()
    _, _, selected, _ = ai.prepare_batch(request(doc), doc)
    row = model_unit(selected[0], reason='method_relevance')
    row['source_evidence'] = [{'unit_id': group(doc)[0]['support_unit_ids'][0], 'start': 0, 'end': len(SUPPORT), 'quote': SUPPORT}]
    result, _ = outcome(doc, selected, row)
    assert result[0]['reason_code'] == 'invalid_model_response'
    # A link may quote only the unit and its confirmed sources; an unconfirmed line is dropped.
    row = model_unit(selected[0], reason='method_relevance', links=[{**LINK, 'source': 'I ran 12 parser test cases'}])
    result, _ = outcome(doc, selected, row)
    assert result[0]['suggestion']['links'] == [] and result[0]['suggestion']['priority'] == 'normal'


@pytest.mark.parametrize('planning', [False, True])
def test_real_route_support_direction_receipts_and_untrusted_reason(monkeypatch, planning):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.routes import target_resume_ai as route
    originals = [ORIGINAL, SUPPORT] if planning else [TEAM_ORIGINAL, SUPPORT]
    doc = document(originals=originals); doc['base_snapshot']['research_interests'] = '  Computational genomics\n原文🧪  '
    req = request(doc, group(doc), planning=planning)
    before = deepcopy(doc); calls = []
    proposed = 'I wrote Python parser tests and ran 12 parser test cases.' if planning else MERGED
    monkeypatch.setattr(route, 'load_opportunities_by_id', lambda: {OPP['id']: OPP})
    monkeypatch.setattr(route, 'is_configured', lambda: True)
    monkeypatch.setattr(ai.llm_budget, 'exhausted', lambda: False)
    monkeypatch.setattr(em, 'ai_review', lambda pairs, deadline=None: ['accepted'] * len(pairs))
    def provider(messages, **_kwargs):
        data = json.loads(messages[1]['content']); calls.append(data)
        assert data['student_direction']['research_interests'] == doc['base_snapshot']['research_interests']
        if not planning:
            return json.dumps({'units': [model_unit(data['units'][0], reason=ATTACK, proposed=proposed)]})
        block = data['blocks'][0]
        line = next(line for line in block['lines'] if line['evidence']['id'] == 'exp-0')
        assert line['support_sources'] == [{'unit_id': group(doc)[0]['support_unit_ids'][0]}]
        return json.dumps({'items': [{'section_id': block['section_id'], 'block_id': block['block_id'], 'action': 'compress',
            'reason': ATTACK, 'target_evidence': [QUOTE], 'source_evidence': [{'unit_id': line['unit_id'], 'start': 0, 'end': len(ORIGINAL), 'quote': ORIGINAL}],
            'rewrites': [{'unit_id': line['unit_id'], 'proposed_text': proposed}]}]})
    monkeypatch.setattr(ai, 'chat_completion', provider)
    path = '/api/tailor/full-target/' + ('selection-plan' if planning else 'suggestions')
    response = TestClient(app).post(path, json=req.model_dump(exclude_none=True))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['support_groups'] == group(doc) and len(calls) == 1 and doc == before
    assert ATTACK not in response.text
    row = result['items'][0]['rewrites'][0] if planning else result['receipts'][0]['suggestion']
    assert row['proposed_text'] == proposed
    assert [q['quote'] for q in row['source_evidence']] == originals
    assert result['pipeline_version'] == ('full-target-plan-v4' if planning else 'full-target-v6')
    assert result['logical_calls'] == 1 + (not planning)  # the suggestions' review is a second call
    assert 'private' in response.headers['cache-control']


@pytest.mark.parametrize('planning', [False, True])
@pytest.mark.parametrize('mutation', ['cross_activity', 'unconfirmed', 'source_changed', 'over_budget'])
def test_real_route_rejects_invalid_or_oversized_input_before_provider(monkeypatch, planning, mutation):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.routes import target_resume_ai as route
    doc = document(same_activity=mutation != 'cross_activity')
    groups = group(doc)
    if mutation == 'unconfirmed': groups[0]['confirmed'] = False
    if mutation == 'source_changed': doc['base_snapshot']['experience_entries'][1]['status'] = 'withdrawn'
    if mutation == 'over_budget': doc['base_snapshot']['research_interests'] = 'x' * 125000
    # Assemble the wire directly so malformed Pydantic input is tested at the route.
    payload = {'version': 1, 'request_id': 'bad-b52', 'locale': 'en', 'draft': doc, 'document_signature': fingerprint(doc), 'support_groups': groups}
    payload.update({'options': {'target_pages': 1}} if planning else {'selected_unit_ids': [groups[0]['unit_id']]})
    monkeypatch.setattr(route, 'load_opportunities_by_id', lambda: {OPP['id']: OPP})
    monkeypatch.setattr(route, 'is_configured', lambda: True)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True); raise AssertionError('provider should not run')
    monkeypatch.setattr(ai, 'chat_completion', forbidden)
    path = '/api/tailor/full-target/' + ('selection-plan' if planning else 'suggestions')
    response = TestClient(app).post(path, json=payload)
    if mutation == 'over_budget':
        assert response.status_code == 200
        result = response.json()
        assert (result['reason_code'] if planning else result['receipts'][0]['reason_code']) == 'interests_too_large'
    else:
        assert response.status_code == 422, response.text
    assert calls == []


def test_explicit_null_support_selection_is_not_accepted_as_missing():
    doc = document()
    for planning in (False, True):
        value = request(doc, planning=planning).model_dump(exclude_none=True)
        value['support_groups'] = None
        with pytest.raises(ValueError):
            (FullTargetPlanRequest if planning else FullTargetRequest).model_validate(value)


@pytest.mark.parametrize('planning', [False, True])
@pytest.mark.parametrize('originals,proposed', [
    (['I reviewed 12 parser tests.', 'I collected 45 samples.'], 'I reviewed 45 parser tests.'),
    (['本人整理了12条记录。', '本人采集了45个样本。'], '本人整理了45条记录。'),
])
def test_routes_refuse_unrecognized_multi_source_metric_transfer(monkeypatch, planning, originals, proposed):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.routes import target_resume_ai as route
    doc = document(originals=originals); req = request(doc, group(doc), planning=planning)
    monkeypatch.setattr(route, 'load_opportunities_by_id', lambda: {OPP['id']: OPP})
    monkeypatch.setattr(route, 'is_configured', lambda: True)
    monkeypatch.setattr(ai.llm_budget, 'exhausted', lambda: False)
    calls = []
    def provider(messages, **_kwargs):
        data = json.loads(messages[1]['content']); calls.append(data)
        if not planning:
            return json.dumps({'units': [model_unit(data['units'][0], reason='method_relevance', proposed=proposed)]})
        block = data['blocks'][0]
        line = next(line for line in block['lines'] if line['evidence']['id'] == 'exp-0')
        return json.dumps({'items': [{'section_id': block['section_id'], 'block_id': block['block_id'], 'action': 'compress',
            'reason': 'method_relevance', 'target_evidence': [QUOTE],
            'source_evidence': [{'unit_id': line['unit_id'], 'start': 0, 'end': len(originals[0]), 'quote': originals[0]}],
            'rewrites': [{'unit_id': line['unit_id'], 'proposed_text': proposed}]}]}, ensure_ascii=False)
    monkeypatch.setattr(ai, 'chat_completion', provider)
    path = '/api/tailor/full-target/' + ('selection-plan' if planning else 'suggestions')
    response = TestClient(app).post(path, json=req.model_dump(exclude_none=True))
    assert response.status_code == 200 and len(calls) == 1
    result = response.json()
    if planning:
        row = result['items'][0]['rewrites'][0]
        assert row['status'] == 'skipped' and row['reason_code'] == 'ungrounded_rewrite', result
        assert row['proposed_text'] is None
    else:
        refused(result['receipts'][0])
