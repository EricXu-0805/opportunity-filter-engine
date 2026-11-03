"""No provider traffic. The long line and its candidate rewrite are synthetic."""
import json
from copy import deepcopy

import pytest

from backend.lib import evidence_map
from backend.lib import target_resume_ai as engine
from backend.lib import target_resume_output_budget as budget
from backend.lib.target_resume_ai_validation import confirmed_document, units_for
from tests import test_target_resume_ai as suggestions

endpoint = suggestions.endpoint

# A 927-character Chinese experience and a faithful personal_first reorder of its two sentences.
DUTIES = "；".join(["核对采集时间和记录顺序、整理缺失读数并保留原始记录、逐项对照仪器日志、记录手工检查的结果、"
                   "按采样时段整理文件并核对文件名、把发现的不一致交给组员确认"] * 12)
LONG_ORIGINAL = f"与两名同学一起搭建了气象站。本人负责传感器读数的整理，{DUTIES}。"
LONG_REWRITE = f"本人负责传感器读数的整理，{DUTIES}。与两名同学一起搭建了气象站。"
LONG_OUTPUT = json.dumps({"units": [{"unit_id": "line-3", "links": [], "decision": "rewrite", "ops": [{"op": "personal_first"}],
                                     "text": LONG_REWRITE, "keep_reason": None, "priority": "normal",
                                     "reason": "necessary_background"}]}, ensure_ascii=False, separators=(",", ":"))
# tiktoken 0.14.0 counts LONG_OUTPUT at 998 (cl100k_base) and 788 (o200k_base)
# tokens, both above the former fixed 350 + 320. Counted once offline when this
# fixture was written; the test does not recount them. An estimate for OpenAI
# encodings, not for the model that serves the route.
LONG_OUTPUT_TOKENS = 998


@pytest.mark.parametrize('verdict,expected_status,expected_reason', [
    ('accepted', 'suggested', None),
    ('rejected', 'unchanged', 'review_rejected'),
    ('unavailable', 'skipped', 'rewrite_unchecked'),
])
def test_long_reviewable_rewrite_has_room_but_still_requires_review(endpoint, monkeypatch, verdict, expected_status, expected_reason):
    client, _, _, calls = endpoint
    assert len(LONG_ORIGINAL) == 927
    doc = suggestions.make_doc(LONG_ORIGINAL)
    reviewed = []

    def model(messages, **kwargs):
        calls.append((messages, kwargs))
        # Simulate require_complete's refusal of a length-truncated response.
        return LONG_OUTPUT if kwargs['max_tokens'] >= LONG_OUTPUT_TOKENS else None

    def review(pairs, deadline=None):
        reviewed.extend(pairs)
        return [verdict] * len(pairs)

    monkeypatch.setattr(engine, 'chat_completion', model)
    monkeypatch.setattr(evidence_map, 'ai_review', review)
    request = suggestions.payload(doc, ['line-3'])
    request['locale'] = 'zh'
    response = client.post(suggestions.PATH, json=request)
    assert response.status_code == 200
    receipt = response.json()['receipts'][0]
    assert receipt['status'] == expected_status, receipt
    assert receipt['reason_code'] == expected_reason
    proposed = receipt['suggestion']['proposed_text'] if receipt['suggestion'] else None
    assert proposed == (LONG_REWRITE if verdict == 'accepted' else None)
    assert reviewed and reviewed[0].original == LONG_ORIGINAL
    assert reviewed[0].rewrite == LONG_REWRITE
    assert len(calls) == 1 and calls[0][1]['require_complete'] is True


def support_document():
    doc = suggestions.make_doc()
    snapshot = doc['base_snapshot']
    entries = [
        {'id': f'exp-{index}', 'revision': 1, 'status': 'confirmed', 'source': {'kind': 'manual'},
         'text': f'记录第 {index} 组实验结果，并整理原始文件。'} for index in range(8)
    ]
    entries.append({'id': 'supplement', 'revision': 1, 'status': 'confirmed', 'source': {'kind': 'manual'},
                    'text': '核对采集时间和记录顺序，并将缺失记录交给组员确认。' * 60})
    snapshot['experience_entries'] = entries
    snapshot['resume_master']['activities'][0]['details'] = [{'id': entry['id'], 'revision': 1} for entry in entries]
    doc['document'] = confirmed_document(snapshot, doc['base']['source_signature'])
    for section in doc['document']['sections']:
        section['included'] = True
        for block in section['blocks']:
            block['included'] = True
            for line in block['lines']:
                line.update(text=line['original'], included=True)
    units, _ = units_for(doc)
    supplement = next(unit for unit in units if unit['evidence']['id'] == 'supplement')
    main = [unit for unit in units if unit['evidence']['id'].startswith('exp-')]
    return doc, main, supplement


def test_shared_support_can_overflow_output_while_input_fits_and_smaller_batches_keep_every_source(endpoint, monkeypatch):
    client, _, _, calls = endpoint
    doc, main, support = support_document()
    ids = [unit['unit_id'] for unit in main]
    request = suggestions.payload(doc, ids)
    request['support_groups'] = [{'unit_id': ident, 'support_unit_ids': [support['unit_id']], 'confirmed': True} for ident in ids]
    originals = deepcopy(request)
    _, _, _, processable = engine.prepare_batch(engine_request(request), doc)
    assert not engine.prompt_too_large(engine.build_prompt(doc, processable, 'en', suggestions.anchors_of(doc)))
    assert not budget.output_budget_fits(processable)

    def model(messages, **kwargs):
        calls.append((messages, kwargs))
        assert kwargs['max_tokens'] <= budget.OUTPUT_BUDGET_POLICY['max_tokens']
        incoming = json.loads(messages[1]['content'])
        return json.dumps({'units': [suggestions.row(unit['unit_id'], priority='normal', reason='necessary_background') for unit in incoming['units']]})

    monkeypatch.setattr(engine, 'chat_completion', model)
    response = client.post(suggestions.PATH, json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['logical_calls'] == 0 and not calls
    assert [receipt['unit_id'] for receipt in body['receipts']] == ids
    assert {receipt['reason_code'] for receipt in body['receipts']} == {'batch_context_too_large'}
    for ident in ids:
        smaller = {**request, 'selected_unit_ids': [ident],
                   'support_groups': [group for group in request['support_groups'] if group['unit_id'] == ident]}
        result = client.post(suggestions.PATH, json=smaller)
        assert result.status_code == 200, result.text
        receipt = result.json()['receipts'][0]
        assert receipt['status'] == 'unchanged' and receipt['reason_code'] == 'no_link'
        assert receipt['suggestion']['source_evidence'][1]['quote'] == support['original']
    assert len(calls) == len(ids) and request == originals


def engine_request(request):
    return suggestions.FullTargetRequest.model_validate(request)


@pytest.mark.parametrize('original', ['a' * 6000, '中' * 6000, '😀' * 6000])
def test_a_single_full_length_experience_still_fits(original):
    doc = suggestions.make_doc(original)
    _, _, _, processable = engine.prepare_batch(engine_request(suggestions.payload(doc, ['line-3'])), doc)
    assert budget.output_budget_fits(processable)
    assert engine.batch_preflight(doc, processable, 'en', suggestions.anchors_of(doc))[1] is None


def test_a_unit_whose_own_output_cannot_fit_is_too_large_not_retryable():
    doc, main, support = support_document()
    big, small = deepcopy(main[:2])
    big.update(original='中' * 6000, support_sources=[support])
    assert not budget.output_budget_fits([big]) and budget.output_budget_fits([small])
    anchors = suggestions.anchors_of(doc)
    assert not engine.prompt_too_large(engine.build_prompt(doc, [big, small], 'en', anchors))
    assert engine.batch_preflight(doc, [big], 'en', anchors) == (None, 'context_too_large')
    assert engine.batch_preflight(doc, [big, small], 'en', anchors) == (
        None, {big['unit_id']: 'context_too_large', small['unit_id']: 'batch_context_too_large'})


@pytest.mark.parametrize(('kind', 'original', 'expected'), [
    ('experience', 'a' * 50, 350 + 320),  # short lines keep the former 320 per line
    ('experience', 'a' * 100, 350 + 200 + 123),  # 102 JSON characters x 1.2, rounded up
    ('experience', '中' * 100, 350 + 200 + 243),  # non-ASCII counts twice
    ('experience', '😀' * 100, 350 + 200 + 243),
    ('experience', 'é' * 100, 350 + 200 + 243),  # only ASCII counts once, not Latin-1
    ('experience', '"' * 100, 350 + 200 + 243),  # JSON escaping counts
    ('fact', '中' * 100, 350 + 120),
])
def test_output_reservation_follows_each_source_character(kind, original, expected):
    assert budget.suggestion_output_tokens([{'evidence': {'kind': kind}, 'original': original}]) == expected

def test_sizing_counts_supplements_per_output_not_per_unique_source():
    _, main, support = support_document()
    a, b = deepcopy(main[:2])
    a['support_sources'] = [support]
    b['support_sources'] = [support]
    combined = budget.suggestion_output_tokens([a, b])
    separate = budget.suggestion_output_tokens([a]) + budget.suggestion_output_tokens([b])
    assert combined == separate - budget.OUTPUT_BUDGET_POLICY['envelope_tokens']
    assert combined > budget.suggestion_output_tokens(main[:2])


def test_protected_fact_wording_does_not_reserve_a_replacement():
    doc = suggestions.make_doc()
    units, _ = units_for(doc)
    before = budget.suggestion_output_tokens(units)
    next(unit for unit in units if unit['evidence']['kind'] == 'fact')['original'] = '中' * 6000
    assert budget.suggestion_output_tokens(units) == before


def test_over_cap_dispatch_does_not_call_a_provider(endpoint):
    _, _, _, calls = endpoint
    _, main, support = support_document()
    for unit in main:
        unit['support_sources'] = [support]
    assert engine.dispatch([], main) == (None, 'batch_context_too_large', 0)
    assert calls == []


def test_the_cap_admits_a_reservation_of_exactly_16000_tokens():
    # 350 + 200 + 12,875 JSON characters x 1.2 = 16,000.
    exactly = [{'evidence': {'kind': 'experience'}, 'original': 'a' * 12873}]
    assert budget.suggestion_output_tokens(exactly) == budget.OUTPUT_BUDGET_POLICY['max_tokens']
    assert budget.output_budget_fits(exactly)
    over = [*exactly, {'evidence': {'kind': 'fact'}, 'original': 'a'}]
    assert not budget.output_budget_fits(over)


def test_the_call_reserves_output_only_for_lines_it_sends(endpoint):
    client, doc, _, calls = endpoint
    value = 'F' * 16001
    doc['base_snapshot']['resume_master']['skills'][0]['value'] = value
    doc['document']['sections'][2]['blocks'][0]['lines'][0].update(original=value, text=value)
    request = suggestions.payload(doc)
    _, _, selected, processable = engine.prepare_batch(engine_request(request), doc)
    assert len(selected) == len(processable) + 1
    body = client.post(suggestions.PATH, json=request).json()
    assert body['receipts'][-1]['reason_code'] == 'unit_too_large'
    assert [kwargs['max_tokens'] for _, kwargs in calls] == [budget.suggestion_output_tokens(processable)]
