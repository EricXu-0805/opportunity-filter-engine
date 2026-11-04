"""A linked phrase is not the complete context of a student's experience."""
import json

import pytest

from backend.lib import evidence_map as em
from backend.lib import target_resume_ai as ai
from backend.lib.target_resume_ai_validation import validate_document
from tests.test_target_resume_b52 import (
    LINK,
    MERGED,
    SUPPORT,
    TEAM_ORIGINAL,
    anchors,
    document,
    group,
    model_unit,
    request,
)

OTHER = 'I checked the documentation for the lab.'


def selected(original):
    doc = document(originals=[original, OTHER])
    _, _, units, _ = ai.prepare_batch(request(doc), doc)
    return doc, units


@pytest.mark.parametrize('original', [
    'I did not write Python scripts for the lab.',
    'I plan to write Python scripts for the lab.',
    'I used Python scripts that my advisor wrote, not scripts I developed.',
    'Python was used by the team. I only documented their work.',
    '本人未使用 Python 进行分析。',
    '计划用 Python 分析；目前只整理记录。',
    '团队使用 Python 分析，本人只整理记录。',
])
@pytest.mark.parametrize('locale', ['en', 'zh'])
def test_kept_advice_quotes_the_complete_original_not_the_linked_phrase(original, locale):
    doc, units = selected(original)
    row = model_unit(units[0], links=[LINK], reason='method_relevance')
    kept, pending = ai.parse_output(json.dumps({'units': [row]}), units, anchors(doc), locale)
    assert not pending and len(kept) == 1
    suggestion = kept[0]['suggestion']
    label = 'Student original' if locale == 'en' else '学生原文'
    assert suggestion['reason'].count(f'{label}: ') == 1
    assert f'{label}: {json.dumps(original, ensure_ascii=False)}' in suggestion['reason']
    assert f'{label}: "Python"' not in suggestion['reason']
    assert suggestion['proposed_text'] is None
    # The link keeps its exact span for the operation checks.
    assert suggestion['links'][0]['source_evidence']['quote'] == 'Python'


def test_the_reason_quotes_the_line_as_written_not_its_edited_text():
    original = 'I did not write Python scripts for the lab.'
    doc = document(originals=[original, OTHER])
    line = next(line for section in doc['document']['sections'] for block in section['blocks']
                for line in block['lines'] if line['original'] == original)
    line['text'] = 'I wrote Python scripts for the lab.'
    doc = validate_document(doc)
    _, _, units, _ = ai.prepare_batch(request(doc), doc)
    assert units[0]['before_text'] != units[0]['original']
    row = model_unit(units[0], links=[LINK], reason='method_relevance')
    kept, _ = ai.parse_output(json.dumps({'units': [row]}), units, anchors(doc))
    reason = kept[0]['suggestion']['reason']
    assert f'Student original: {json.dumps(original)}' in reason
    assert line['text'] not in reason


@pytest.mark.parametrize('verdict', ['accepted', 'rejected'])
def test_reviewed_rewrite_and_its_refusal_quote_every_complete_source(verdict):
    doc = document(originals=[TEAM_ORIGINAL, SUPPORT])
    _, _, units, _ = ai.prepare_batch(request(doc, group(doc)), doc)
    row = model_unit(units[0], reason='method_relevance', proposed=MERGED)
    kept, pending = ai.parse_output(json.dumps({'units': [row]}), units, anchors(doc))
    assert not kept and len(pending) == 1
    suggestion = ai.finalize(pending, [verdict])[0]['suggestion']
    rows = [line for line in suggestion['reason'].splitlines() if line.startswith('Student original: ')]
    assert rows == [f'Student original: {json.dumps(TEAM_ORIGINAL)}', f'Student original: {json.dumps(SUPPORT)}']
    assert suggestion['proposed_text'] == (MERGED if verdict == 'accepted' else None)


def test_the_wording_without_terms_quotes_the_support_lines_too():
    doc = document(originals=[TEAM_ORIGINAL, SUPPORT])
    _, _, units, _ = ai.prepare_batch(request(doc, group(doc)), doc)
    outcome = em.check_rewrite(ai._em_unit(units[0]), model_unit(units[0], reason='method_relevance', proposed=MERGED),
                               {anchor.id: anchor for anchor in anchors(doc)}, output_language='en',
                               extra_keys=ai.ROW_EXTRA_KEYS)
    result = ai._suggestion(units[0], outcome, 'normal', 'method_relevance', 'en', proposed=MERGED, alternative=MERGED)
    for field in ('reason', 'alternative_reason'):
        rows = [line for line in result[field].splitlines() if line.startswith('Student original: ')]
        assert rows == [f'Student original: {json.dumps(TEAM_ORIGINAL)}', f'Student original: {json.dumps(SUPPORT)}']


def test_duplicate_links_quote_a_long_original_once_and_whole():
    original = 'I used Python for the lab. ' + 'Further context. ' * 100 + 'I did not write the scripts.'
    doc, units = selected(original)
    row = model_unit(units[0], links=[LINK, {**LINK, 'id': 'L2'}], reason='method_relevance')
    kept, pending = ai.parse_output(json.dumps({'units': [row]}), units, anchors(doc))
    assert not pending
    reason = kept[0]['suggestion']['reason']
    assert reason.count('Student original: ') == 1
    assert f'Student original: {json.dumps(original)}' in reason


@pytest.mark.parametrize('locale,phrase', [('en', 'your words'), ('zh', '你的原文')])
def test_a_confirmed_link_adds_no_row_quoting_only_its_phrase(locale, phrase):
    original = 'I did not write Python scripts for the lab.'
    doc, units = selected(original)
    outcome = em.check_rewrite(ai._em_unit(units[0]), model_unit(units[0], links=[LINK]),
                               {anchor.id: anchor for anchor in anchors(doc)}, output_language='en',
                               extra_keys=ai.ROW_EXTRA_KEYS)
    outcome.links[0].entailed = True  # As an accepting review marks it.
    result = ai._suggestion(units[0], outcome, 'normal', 'review_sources', locale, proposed=original,
                            alternative=original)
    label = 'Student original' if locale == 'en' else '学生原文'
    for field in ('reason', 'alternative_reason'):
        rows = [row for row in result[field].splitlines() if 'Python' in row]
        # The whole line, then the opportunity's own words; no row of the linked phrase alone.
        assert rows[0] == f'{label}: {json.dumps(original)}' and len(rows) == 2
        assert phrase not in result[field]
    assert result['links'][0]['entailed'] is True


@pytest.mark.parametrize('locale,label,old', [
    ('en', 'AI-linked text from the opportunity', 'Target original'),
    ('zh', 'AI 关联的机会原文', '目标原文'),
])
def test_advice_names_the_opportunity_quote_as_text_the_ai_linked(locale, label, old):
    original = 'I did not write Python scripts for the lab.'
    doc, units = selected(original)
    row = model_unit(units[0], links=[LINK], reason='method_relevance')
    kept, _ = ai.parse_output(json.dumps({'units': [row]}), units, anchors(doc), locale)
    outcome = em.check_rewrite(ai._em_unit(units[0]), row, {anchor.id: anchor for anchor in anchors(doc)},
                               output_language='en', extra_keys=ai.ROW_EXTRA_KEYS)
    rewrite = ai._suggestion(units[0], outcome, 'normal', 'review_sources', locale, proposed=original,
                             alternative=original)
    for reason in (kept[0]['suggestion']['reason'], rewrite['reason'], rewrite['alternative_reason']):
        assert f'{label}: "Python"' in reason
        assert f'{old}: ' not in reason
