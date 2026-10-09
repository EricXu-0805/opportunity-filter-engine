"""Source scope through actual local normalize/import/save/load paths; no provider."""
import json
import socket
from copy import deepcopy
from dataclasses import asdict

import pytest

from backend import data_loader
from src.collectors.manual_importer import (
    create_opportunity,
    load_from_csv,
    load_from_json,
    save_opportunities,
    validate_opportunity,
)
from src.collectors.url_parser import _merge_llm_into_base, parse_url
from src.import_source import import_source_from_raw, sanitize_import_source
from src.normalizers.normalizer import normalize

URL = 'https://example.edu/program'
SOURCE = 'The project studies sensor readings. ' * 150 + 'LATE_SOURCE_MARKER. Python is required.'


def raw(source='url_parser', description_source='page_text', **extra):
    return {'source': source, 'source_url': URL if source == 'url_parser' else '',
            'url': URL if source == 'url_parser' else '', 'title': 'Research project',
            'description_raw': SOURCE, 'extra_fields': {'description_source': description_source, **extra}}


def info(source='page_text', scope='unknown', enriched=False):
    return {'version': 1, 'description_source': source, 'ai_input_scope': scope, 'llm_enriched': enriched}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('No network allowed'))
    monkeypatch.setattr('backend.lib.llm.chat_completion', lambda *a, **k: pytest.fail('No provider allowed'))


@pytest.fixture
def temporary_loader(monkeypatch, tmp_path):
    monkeypatch.setattr(data_loader, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data_loader, '_opp_cache', [])
    monkeypatch.setattr(data_loader, '_opp_cache_by_id', {})
    monkeypatch.setattr(data_loader, '_opp_cache_mtime', 0)
    # The real JSON loader/sanitizer runs; corpus ranking is outside this test.
    monkeypatch.setattr(data_loader, '_prepare_ranker_corpus', lambda *a: None)
    return tmp_path / 'opportunities.json'


@pytest.mark.parametrize(('source', 'label'), [('url_parser', 'page_text'), ('url_parser', 'page_excerpt'), ('text_parser', 'pasted_text')])
def test_labels_remain_separate_from_full_local_source(source, label):
    value = raw(source, label, ai_input_scope='source_excerpt', llm_enriched=True)
    before = deepcopy(value)
    result = normalize(value)
    assert result['description_raw'] == SOURCE
    assert result['metadata']['import_source'] == info(label, 'source_excerpt', True)
    assert value == before
    assert result['metadata']['manually_reviewed'] is False


@pytest.mark.parametrize('source', ['url_parser', 'text_parser', 'manual', 'faculty_graph'])
def test_old_untagged_record_is_not_upgraded_from_its_length_or_source(source):
    value = raw(source)
    value['extra_fields'] = {}
    assert import_source_from_raw(value) is None
    assert 'import_source' not in normalize(value)['metadata']


@pytest.mark.parametrize(('source', 'label'), [('url_parser', 'pasted_text'), ('text_parser', 'page_text'), ('text_parser', 'page_excerpt'), ('manual', 'page_text'), ('unknown', 'pasted_text')])
def test_source_type_contradiction_downgrades_both_scopes(source, label):
    assert import_source_from_raw(raw(source, label, ai_input_scope='source_excerpt', llm_enriched=True)) == info('unknown')


@pytest.mark.parametrize('scope', ['other', 'FULL_SOURCE', None, [], {}, True])
def test_unsupported_scope_cannot_claim_complete_model_reading(scope):
    value = raw(ai_input_scope=scope, llm_enriched=True)
    assert import_source_from_raw(value) == info('page_text', 'unknown', True)


# The parser stamps full_source when every saved word reached the model. Like
# source_excerpt, the label needs the literal enrichment flag, and only page or
# pasted text can have reached the model whole.
@pytest.mark.parametrize(('source', 'label'), [('url_parser', 'page_text'), ('text_parser', 'pasted_text')])
def test_recorded_full_source_scope_is_kept(source, label):
    assert import_source_from_raw(raw(source, label, ai_input_scope='full_source', llm_enriched=True)) == info(
        label, 'full_source', True)


@pytest.mark.parametrize(('source', 'label', 'enriched', 'expected'), [
    ('url_parser', 'page_excerpt', True, info('page_excerpt', 'unknown', True)),
    ('url_parser', 'page_text', False, info()),
    ('url_parser', 'page_text', 'true', info()),
    ('text_parser', 'page_text', True, info('unknown')),
])
def test_full_source_scope_needs_enrichment_and_whole_page_or_pasted_text(source, label, enriched, expected):
    assert import_source_from_raw(raw(source, label, ai_input_scope='full_source', llm_enriched=enriched)) == expected


@pytest.mark.parametrize('enriched', [False, 1, 'true', [], {}, None])
def test_excerpt_requires_literal_success_marker(enriched):
    assert import_source_from_raw(raw(ai_input_scope='source_excerpt', llm_enriched=enriched)) == info()


@pytest.mark.parametrize('body', ['', '  \n', None, [], {}, '\ud800'])
def test_missing_invalid_or_empty_body_cannot_support_scope(body):
    value = raw(ai_input_scope='source_excerpt', llm_enriched=True)
    value['description_raw'] = body
    assert import_source_from_raw(value) == info('unknown')


@pytest.mark.parametrize('label', [None, {}, [], True, 'full_page', 'PAGE_TEXT'])
def test_malformed_source_label_is_not_promoted(label):
    assert import_source_from_raw(raw(description_source=label, ai_input_scope='source_excerpt', llm_enriched=True)) == info('unknown')


def test_normalized_manual_save_and_actual_loader_preserve_valid_scope(temporary_loader):
    value = normalize(raw(ai_input_scope='source_excerpt', llm_enriched=True))
    value['id'] = 'source-roundtrip'
    assert save_opportunities([value], str(temporary_loader)) == (1, 0)
    on_disk = temporary_loader.read_bytes()
    restored = data_loader.load_opportunities_by_id()['source-roundtrip']
    assert restored['metadata']['import_source'] == info('page_text', 'source_excerpt', True)
    assert restored['description_raw'] == SOURCE
    assert temporary_loader.read_bytes() == on_disk


@pytest.mark.parametrize('stored', [None, [], True, {'version':True}, {'version':2},
                                   {'version':1,'description_source':'page_text','ai_input_scope':'full_source','llm_enriched':False},
                                   {'version':1,'description_source':'page_excerpt','ai_input_scope':'full_source','llm_enriched':True}])
def test_loader_sanitizes_invalid_persisted_scope_without_rewriting_disk(stored, temporary_loader):
    record = normalize(raw())
    record['id'] = 'invalid-scope'
    record['metadata']['import_source'] = stored
    save_opportunities([record], str(temporary_loader))
    on_disk = temporary_loader.read_bytes()
    restored = data_loader.load_opportunities_by_id()['invalid-scope']
    assert restored['metadata']['import_source']['ai_input_scope'] == 'unknown'
    assert temporary_loader.read_bytes() == on_disk


def test_actual_loader_keeps_a_recorded_full_source_scope(temporary_loader):
    value = normalize(raw('text_parser', 'pasted_text', ai_input_scope='full_source', llm_enriched=True))
    value['id'] = 'full-source-roundtrip'
    assert save_opportunities([value], str(temporary_loader)) == (1, 0)
    restored = data_loader.load_opportunities_by_id()['full-source-roundtrip']
    assert restored['metadata']['import_source'] == info('pasted_text', 'full_source', True)


def test_source_record_changed_after_normalization_cannot_keep_old_scope():
    value = normalize(raw(ai_input_scope='source_excerpt', llm_enriched=True))
    value['source'] = 'text_parser'
    sanitize_import_source(value)
    assert value['metadata']['import_source'] == info('unknown')


def test_copy_json_raw_import_is_normalized_with_full_source_and_scope(tmp_path, temporary_loader):
    value = raw(ai_input_scope='source_excerpt', llm_enriched=True)
    path = tmp_path / 'copy-json.json'
    path.write_text(json.dumps(value))
    imported = load_from_json(str(path))
    assert len(imported) == 1
    assert imported[0]['description_raw'] == SOURCE
    assert imported[0]['metadata']['import_source'] == info('page_text', 'source_excerpt', True)
    save_opportunities(imported, str(temporary_loader))
    restored = data_loader.load_opportunities_by_id()[imported[0]['id']]
    assert restored['description_raw'] == SOURCE
    assert restored['metadata']['import_source'] == info('page_text', 'source_excerpt', True)


def test_pasted_raw_import_never_invents_a_publishable_url(tmp_path):
    value = raw('text_parser', 'pasted_text', ai_input_scope='source_excerpt', llm_enriched=True)
    path = tmp_path / 'paste.json'
    path.write_text(json.dumps(value))
    imported = load_from_json(str(path))[0]
    assert imported['url'] == imported['source_url'] == ''
    assert 'Missing url' in validate_opportunity(imported)
    assert imported['metadata']['manually_reviewed'] is False


@pytest.mark.parametrize(('key', 'value'), [('description_raw', []), ('extra_fields', []), ('url', None), ('source_url', None), ('title', 3)])
def test_invalid_known_raw_import_fails_without_private_value_echo(key, value, tmp_path):
    item = raw()
    item[key] = value
    item['PRIVATE_FIELD'] = 'DO_NOT_ECHO'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(item))
    with pytest.raises(ValueError, match=r'^Invalid imported opportunity record\.$') as raised:
        load_from_json(str(path))
    assert 'DO_NOT_ECHO' not in str(raised.value)


def test_old_flat_and_full_normalized_input_paths_remain(tmp_path):
    normalized = normalize(raw())
    flat = {'title':'Manual opportunity','url':URL,'description':'Curator source text.','school':'national'}
    path = tmp_path / 'old-formats.json'
    path.write_text(json.dumps([flat, normalized]))
    restored = load_from_json(str(path))
    assert restored[0]['description_raw'] == flat['description']
    assert restored[0]['metadata']['manually_reviewed'] is True
    assert restored[1] == normalized


def _flat(**extra):
    return {'title': 'Summer research program', 'url': URL, 'description': 'Curator source text.', **extra}


def _import_json(tmp_path, items):
    path = tmp_path / 'manual.json'
    path.write_text(json.dumps(items))
    return load_from_json(str(path))


def test_a_manual_entry_without_a_school_is_refused(tmp_path):
    """create_opportunity wrote neither school nor audience, and
    apply_school_audience files such a record as (None, 'unknown'): one
    uiuc-* hand import then fails test_uiuc_manual_seeds_are_school_tagged
    and holds back its school's shard."""
    with pytest.raises(ValueError, match='names no school'):
        _import_json(tmp_path, [_flat(id='uiuc-new-program')])
    with pytest.raises(ValueError, match='names no school'):
        create_opportunity(title='Summer research program', url=URL)


def test_a_hosted_entry_is_tagged_and_keeps_its_tags_through_the_refresh(tmp_path):
    from src.normalizers.school_audience import apply_school_audience

    campus, recruiting = _import_json(tmp_path, [
        _flat(id='uiuc-new-program', school=' UIUC '),
        _flat(id='uiuc-new-reu', title='Physics REU', school='uiuc', audience='open'),
    ])
    assert (campus['school'], campus['audience']) == ('uiuc', 'campus')
    assert (recruiting['school'], recruiting['audience']) == ('uiuc', 'open')
    apply_school_audience([campus, recruiting])
    assert (campus['school'], campus['audience']) == ('uiuc', 'campus')
    assert (recruiting['school'], recruiting['audience']) == ('uiuc', 'open')


def test_a_national_entry_is_named_as_national(tmp_path):
    named, null = _import_json(tmp_path, [_flat(school='national'), _flat(title='Other program', school=None)])
    assert (named['school'], named['audience']) == (None, 'open')
    assert (null['school'], null['audience']) == (None, 'open')


@pytest.mark.parametrize(('school', 'audience', 'message'), [
    ('illinois', None, 'unknown school'),
    ('', None, 'unknown school'),
    ('uiuc', 'unknown', 'audience'),
    ('national', 'campus', 'audience'),
])
def test_a_school_or_audience_the_corpus_cannot_publish_is_refused(tmp_path, school, audience, message):
    item = _flat(school=school)
    if audience is not None:
        item['audience'] = audience
    with pytest.raises(ValueError, match=message):
        _import_json(tmp_path, [item])


def test_a_full_schema_manual_record_needs_a_school_too(tmp_path):
    """data/manual_entries/seed_v1.json has this shape and no school key:
    importing it again would replace the nine tagged uiuc seeds with
    untagged copies."""
    record = create_opportunity(title='Summer research program', url=URL, school='uiuc', audience='open')
    untagged = {key: value for key, value in record.items() if key not in ('school', 'audience')}
    with pytest.raises(ValueError, match='names no school'):
        _import_json(tmp_path, [untagged])
    stated, derived = _import_json(tmp_path, [record, {**untagged, 'school': 'uiuc'}])
    assert (stated['school'], stated['audience']) == ('uiuc', 'open')
    assert (derived['school'], derived['audience']) == ('uiuc', 'campus')


def test_a_csv_row_needs_a_school(tmp_path):
    path = tmp_path / 'manual.csv'
    path.write_text(f'title,url\nSummer research program,{URL}\n')
    with pytest.raises(ValueError, match='names no school'):
        load_from_csv(str(path))
    path.write_text(f'title,url,school\nSummer research program,{URL},\n')
    with pytest.raises(ValueError, match='names no school'):
        load_from_csv(str(path))
    path.write_text(f'title,url,school,audience\nSummer research program,{URL},uiuc,open\nNational program,{URL}/n,national,\n')
    hosted, national = load_from_csv(str(path))
    assert (hosted['school'], hosted['audience']) == ('uiuc', 'open')
    assert (national['school'], national['audience']) == (None, 'open')


def test_model_suggestions_are_not_source_requirements_even_after_roundtrip(tmp_path, temporary_loader):
    base = parse_url(URL, html='<html><body><p>Students study sensor measurements.</p></body></html>')
    merged = _merge_llm_into_base(base, {'skills_required':['Kubernetes'], 'description':'Kubernetes is required.', 'title':'Kubernetes engineer'})
    merged.extra_fields['ai_input_scope'] = 'source_excerpt'
    path = tmp_path / 'copy-model-json.json'
    path.write_text(json.dumps(asdict(merged)))
    imported = load_from_json(str(path))
    save_opportunities(imported, str(temporary_loader))
    restored = data_loader.load_opportunities_by_id()[imported[0]['id']]
    assert restored['description_raw'] == base.description_raw
    assert restored['eligibility']['skills_required'] == []
    assert restored['metadata']['skill_mentions'] == []
    assert restored['metadata']['import_source'] == info('page_text', 'source_excerpt', True)


@pytest.mark.parametrize(('source', 'label', 'text'), [
    ('url_parser', 'page_text', 'GPA < 3.0 needs review; scores > 80 preferred.'),
    ('text_parser', 'pasted_text', 'Literal example: <script>alert("source text")</script> must remain text.'),
])
def test_identified_import_raw_is_not_reinterpreted_as_html(source, label, text, temporary_loader):
    value = raw(source, label)
    value['description_raw'] = text
    record = normalize(value)
    record['id'] = 'literal-import-source'
    save_opportunities([record], str(temporary_loader))
    on_disk = temporary_loader.read_bytes()
    restored = data_loader.load_opportunities_by_id()[record['id']]
    assert restored['description_raw'] == text
    assert temporary_loader.read_bytes() == on_disk


def test_unlabeled_legacy_html_keeps_existing_loader_sanitization():
    record = normalize(raw())
    record['metadata'].pop('import_source')
    record['description_raw'] = '<b>Legacy description</b>'
    assert data_loader._sanitize_opportunity(record)['description_raw'] == 'Legacy description'


def test_invalid_source_labels_do_not_bypass_legacy_html_sanitization():
    record = normalize(raw())
    record['metadata']['import_source']['version'] = True
    record['description_raw'] = '<b>Legacy description</b>'
    result = data_loader._sanitize_opportunity(record)
    assert result['metadata']['import_source'] == info('unknown')
    assert result['description_raw'] == 'Legacy description'


@pytest.mark.parametrize('mode', ['url', 'text'])
def test_actual_api_copy_json_normalize_save_and_loader_without_expanding_model_input(mode, monkeypatch, tmp_path, temporary_loader):
    import requests
    from fastapi.testclient import TestClient

    from backend.main import app
    from src.collectors import url_parser

    monkeypatch.setattr('backend.main._warmup', lambda: None)
    monkeypatch.setattr('backend.lib.material_cleanup.configured', lambda: False)
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: True)
    calls = []
    def provider(messages, **kwargs):
        calls.append(messages)
        return json.dumps({'description':'AI summary, not source.', 'skills_required':['Kubernetes']})
    monkeypatch.setattr('backend.lib.llm.chat_completion', provider)
    source = 'Complete source content. ' * 400 + 'GPA < 3.0 needs review; scores > 80 preferred. LATE_MARKER'
    if mode == 'url':
        response = requests.Response()
        response.status_code = 200
        response.url = URL
        response.headers['Content-Type'] = 'text/html'
        response.encoding = 'utf-8'
        response._content = ('<html><body><p>' + source.replace('<', '&lt;').replace('>', '&gt;') + '</p></body></html>').encode()
        response._content_consumed = True
        monkeypatch.setattr(url_parser, '_safe_fetch', lambda _url: response)
    with TestClient(app) as client:
        result = client.post('/api/import-url' if mode == 'url' else '/api/import-text', json={'url':URL} if mode == 'url' else {'text':source})
    assert result.status_code == 200
    assert result.json()['ok'] is True
    returned = result.json()['opportunity']
    path = tmp_path / 'api-copy.json'
    path.write_text(json.dumps(returned))
    imported = load_from_json(str(path))
    save_opportunities(imported, str(temporary_loader))
    on_disk = temporary_loader.read_bytes()
    restored = data_loader.load_opportunities_by_id()[imported[0]['id']]
    assert restored['description_raw'] == returned['description_raw'] == source
    assert restored['metadata']['import_source'] == info('page_text' if mode == 'url' else 'pasted_text', 'source_excerpt', True)
    assert 'Kubernetes' not in restored['eligibility']['skills_required']
    assert temporary_loader.read_bytes() == on_disk
    assert len(calls) == 1
    assert all('LATE_MARKER' not in message['content'] for message in calls[0])
