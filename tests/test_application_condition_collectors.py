"""Offline transport, retained DOM, and persistence checks for application collectors."""
import json
from copy import deepcopy
from datetime import datetime

import pytest
from bs4 import BeautifulSoup

from src.collectors import campus_graph as cg
from src.collectors import uiuc_sro as sro
from src.collectors.base import RawOpportunity
from src.contact_instructions import CAPTURE_KEY, SOURCE_KEY, capture_from_html, capture_metadata

URL = 'https://example.edu/summer'
STAMP = '2026-09-28T01:00:00+00:00'
HTML = '<html><body><h1>Summer research</h1><p>Applications are open.</p><p>' + ('Background. ' * 70) + '</p><h2>Eligibility</h2><p>A minimum GPA of 3.0 is required.</p><h2>Materials</h2><p>Submit a resume and transcript.</p></body></html>'


def school(shared=False, recursive=False):
    programs = [cg.program('summer', 'Summer research program', URL, 'Curated description')]
    if shared:
        programs.append(cg.program('second', 'A different summer project', URL, 'Other project'))
    return {'school_slug': 'example', 'organization': 'Example University', 'location': 'Example',
            'emit': {'campus': ('example_research_programs', 'example', 'campus')},
            'sources': [{'source_name': 'example_programs', 'source_type': cg.PROGRAM,
                         'emit': 'campus', 'crawl': cg.RECURSIVE if recursive else cg.STATIC,
                         'crawl_depth': 1, 'seeds': [URL], 'programs': programs}]}


def soup(html=HTML, final=URL, requested=URL):
    value = BeautifulSoup(html, 'html.parser')
    value._ofe_fetch_metadata = {'requested_url': requested, 'final_url': final, 'checked_at': STAMP}
    return value


def response(html, url=URL):
    class Response:
        text = html
        content = html.encode()
        def raise_for_status(self): pass
    value = Response()
    value.url = url
    return value


def raw():
    return RawOpportunity(source='uiuc_sro', source_url=sro.UIUCSROCollector.BASE_URL + '?page=0',
                          title='Summer research', description_raw='List summary', url=URL)


def test_campus_retains_late_full_source_with_real_binding(monkeypatch):
    monkeypatch.setattr(cg, '_fetch', lambda *a, **k: soup())
    records, evidence = cg.fetch_and_normalize_with_evidence(school(), deep=True)
    metadata = records[0]['metadata']
    assert metadata[CAPTURE_KEY]['status'] == 'captured'
    assert metadata[SOURCE_KEY][0]['checked_at'] == STAMP
    assert 'Submit a resume and transcript.' in str(metadata[SOURCE_KEY])
    assert '3.0' not in records[0]['description']
    assert evidence['condition_capture_counts'] == {'captured': 1, 'empty': 0, 'unsupported': 0, 'failed': 0}
    assert evidence['condition_capture_complete'] is True


@pytest.mark.parametrize('html, final, expected', [
    (HTML, 'https://example.edu/admissions', 'redirect_mismatch'),
    ('<body><h1>Sign in</h1><p>Applications open</p></body>', URL, 'access_page'),
])
def test_campus_wrong_or_access_page_not_verified(monkeypatch, html, final, expected):
    monkeypatch.setattr(cg, '_fetch', lambda *a, **k: soup(html, final))
    records, evidence = cg.fetch_and_normalize_with_evidence(school(), deep=True)
    assert records[0]['metadata']['seed_page_verified'] is False
    assert records[0]['metadata'][CAPTURE_KEY]['reason'] == expected
    assert evidence['seed_pages_loaded'] == 0
    assert evidence['condition_capture_complete'] is False


def test_campus_shared_program_page_does_not_copy_conditions(monkeypatch):
    monkeypatch.setattr(cg, '_fetch', lambda *a, **k: soup())
    records, evidence = cg.fetch_and_normalize_with_evidence(school(shared=True), deep=True)
    assert len(records) == 2
    for record in records:
        assert record['metadata'][CAPTURE_KEY]['reason'] == 'ambiguous_program_scope'
        assert not record['metadata'].get(SOURCE_KEY)
    assert evidence['condition_capture_counts']['unsupported'] == 1


def test_campus_failure_receipt_reaches_previously_discovered_record(monkeypatch, tmp_path):
    config = school(recursive=True)
    discovered_url = 'https://example.edu/research-project'
    def fetch(url, **kwargs):
        if url == URL:
            return soup('<body><p>Programs</p><a href="/research-project">Summer research project</a></body>')
        return soup(HTML, 'https://example.edu/login', requested=url)
    monkeypatch.setattr(cg, '_fetch', fetch)
    old = cg._normalize_discovered(config, config['sources'][0], 'Summer research project', discovered_url, 'Old')
    old['metadata'].update(capture_metadata(capture_from_html(HTML, source_url=discovered_url,
                                                            checked_at='2026-09-27T00:00:00+00:00')))
    old['metadata']['collector_school'] = 'example'
    path = tmp_path / 'records.json'; path.write_text(json.dumps([old]))
    monkeypatch.setattr(cg, 'PROCESSED_FILE', path)
    records, evidence = cg.fetch_and_normalize_with_evidence(config, deep=True)
    cg.merge_into_processed(records, school_slug='example', condition_capture_updates=evidence['condition_capture_updates'])
    saved = next(row for row in json.loads(path.read_text()) if row['id'] == old['id'])
    assert saved['metadata'][SOURCE_KEY] == []
    assert saved['metadata'][CAPTURE_KEY]['reason'] == 'redirect_mismatch'


DRUPAL = '<html><body><article><h1>Summer research</h1><div class="field--name-field-eligibility"><div class="field__label">Eligibility</div><div class="field__item">A minimum GPA of 3.0 is required.</div></div><div class="field--name-field-deadline"><div class="field__label">Application Deadline</div><div class="field__item">February 15, 5 PM.</div></div></article></body></html>'


def test_sro_retains_actual_drupal_labels_and_values(monkeypatch):
    monkeypatch.setattr(sro.requests, 'get', lambda *a, **k: response(DRUPAL))
    record = raw(); collector = sro.UIUCSROCollector(deep=True)
    collector._fetch_detail_page(record)
    normalized = sro.raw_to_normalized(record)
    metadata = normalized['metadata']
    assert metadata[CAPTURE_KEY]['status'] == 'captured'
    sections = metadata[SOURCE_KEY][0]['sections']
    assert {'heading': 'Summer research > Application Deadline', 'text': 'February 15, 5 PM.'} in sections
    assert {'heading': 'Summer research > Eligibility', 'text': 'A minimum GPA of 3.0 is required.'} in sections
    assert record.extra_fields['deep_scraped'] is True


@pytest.mark.parametrize('mode, expected', [('redirect', 'redirect_mismatch'), ('timeout', 'fetch_failed'), ('login', 'access_page')])
def test_sro_detail_failure_has_receipt_not_false_success(monkeypatch, mode, expected):
    def get(*args, **kwargs):
        if mode == 'timeout': raise TimeoutError('secret page body')
        return response('<body><h1>Sign in</h1><p>Login</p></body>' if mode == 'login' else DRUPAL,
                        'https://example.edu/other' if mode == 'redirect' else URL)
    monkeypatch.setattr(sro.requests, 'get', get)
    record = raw(); collector = sro.UIUCSROCollector(deep=True)
    collector._fetch_detail_page(record)
    assert record.extra_fields.get('deep_scraped') is not True
    assert record.extra_fields[CAPTURE_KEY]['reason'] == expected
    assert 'secret page body' not in str(collector.evidence)
    assert sum(collector.evidence['condition_capture_counts'].values()) == 1
    assert collector.evidence['detail_pages_attempted'] == collector.evidence['detail_pages_loaded'] + collector.evidence['detail_pages_failed']


@pytest.mark.parametrize('html, complete, failed', [
    ('<body><table class="views-table"><tbody></tbody></table></body>', True, 0),
    ('<body><p>Maintenance</p></body>', False, 1),
    ('<body><table class="views-table"><tbody><tr><td>Malformed</td></tr></tbody></table></body>', False, 1),
])
def test_sro_distinguishes_real_empty_list_from_parse_failure(monkeypatch, html, complete, failed):
    monkeypatch.setattr(sro.requests, 'get', lambda url, **k: response(html, url))
    collector = sro.UIUCSROCollector(deep=False)
    collector.MAX_PAGES = 1
    assert collector.collect() == []
    assert collector.evidence['list_complete'] is complete
    assert collector.evidence['list_pages_failed'] == failed


def test_sro_failed_detail_merge_preserves_prior_detail_and_checked_time(monkeypatch, tmp_path):
    before = sro.raw_to_normalized(raw())
    before.update(organization='True lab', eligibility={'min_gpa': 3.0}, application={'requires_resume': True},
                  deadline='2027-02-15', is_rolling=False, description_raw='Full detail', description_clean='Full detail')
    before['metadata']['last_verified'] = '2026-09-27T00:00:00'
    before['metadata'].update(capture_metadata(capture_from_html(HTML, source_url=URL, checked_at='2026-09-27T00:00:00+00:00')))
    def fail(*a, **k): raise TimeoutError()
    monkeypatch.setattr(sro.requests, 'get', fail)
    new_raw = raw(); sro.UIUCSROCollector(deep=True)._fetch_detail_page(new_raw)
    incoming = sro.raw_to_normalized(new_raw)
    incoming['title'] = 'New listing title'
    path = tmp_path / 'records.json'; path.write_text(json.dumps([before]))
    sro.merge_into_processed([incoming], str(path))
    saved = json.loads(path.read_text())[0]
    for key in ('eligibility', 'application', 'deadline', 'organization', 'description_raw'):
        assert saved[key] == before[key]
    assert saved['title'] == 'New listing title'
    assert saved['metadata']['last_verified'] == before['metadata']['last_verified']
    assert saved['metadata'][SOURCE_KEY] == before['metadata'][SOURCE_KEY]
    assert saved['metadata'][CAPTURE_KEY]['status'] == 'failed'

def _list_only_refresh(before, path, deadline_raw=''):
    item = raw(); item.extra_fields['deadline_raw'] = deadline_raw
    incoming = sro.raw_to_normalized(item)
    path.write_text(json.dumps([before]))
    sro.merge_into_processed([incoming], str(path))
    return json.loads(path.read_text())[0]


def test_sro_list_only_merge_keeps_fresh_list_deadline(tmp_path):
    before = sro.raw_to_normalized(raw())
    before.update(deadline='2026-03-01', is_rolling=False, organization='True lab')
    saved = _list_only_refresh(before, tmp_path / 'records.json', 'March 1, 2027')
    assert saved['deadline'] == '2027-03-01'
    assert saved['is_rolling'] is False
    assert saved['organization'] == 'True lab'


def test_sro_list_only_merge_carries_inference_stamps_with_values(tmp_path):
    from src.evidence import is_inferred
    item = raw(); item.extra_fields['research_area'] = 'Data Science'
    before = sro.raw_to_normalized(item)
    before['eligibility'].update(skills_required=['Python', 'PyTorch'], majors=['Chemistry'])
    before.update(paid='yes', pi_name='Dr. Guess')
    before['metadata']['skill_mentions'] = ['python']
    before['metadata']['inferred_fields'] = {
        'eligibility.skills_required': 'llm:tagger', 'paid': 'rule:paid', 'pi_name': 'rule:pi',
        'metadata.skill_mentions': 'rule:opportunity_terms', 'keywords': 'rule:keywords'}
    item = raw(); item.extra_fields['research_area'] = 'Data Science'
    incoming = sro.raw_to_normalized(item)
    assert incoming['metadata']['inferred_fields'] == {'eligibility.majors': sro.MAJORS_METHOD}
    path = tmp_path / 'records.json'; path.write_text(json.dumps([before]))
    sro.merge_into_processed([incoming], str(path))
    saved = json.loads(path.read_text())[0]
    assert saved['eligibility']['skills_required'] == ['Python', 'PyTorch']
    for field in ('eligibility.skills_required', 'paid', 'pi_name', 'metadata.skill_mentions'):
        assert is_inferred(saved, field), field
    assert saved['metadata']['skill_mentions'] == ['python']
    # The carried eligibility has no majors stamp, so the fresh list stamp
    # must not attach to the prior value; unrelated fresh fields keep theirs.
    assert saved['eligibility']['majors'] == ['Chemistry']
    assert 'eligibility.majors' not in saved['metadata']['inferred_fields']
    assert 'keywords' not in saved['metadata']['inferred_fields']


@pytest.mark.parametrize('missing', ['all', 'final_url', 'requested_url', 'checked_at', 'wrong_request', 'naive_time', 'future_time'])
def test_campus_missing_transport_observation_cannot_verify(monkeypatch, missing):
    page = soup()
    if missing == 'all':
        del page._ofe_fetch_metadata
    elif missing == 'wrong_request':
        page._ofe_fetch_metadata['requested_url'] = 'https://example.edu/unrelated'
    elif missing == 'naive_time':
        page._ofe_fetch_metadata['checked_at'] = '2026-09-28T01:00:00'
    elif missing == 'future_time':
        page._ofe_fetch_metadata['checked_at'] = '2099-01-01T00:00:00Z'
    else:
        del page._ofe_fetch_metadata[missing]
    monkeypatch.setattr(cg, '_fetch', lambda *a, **k: page)
    records, evidence = cg.fetch_and_normalize_with_evidence(school(), deep=True)
    assert records[0]['metadata']['seed_page_verified'] is False
    assert records[0]['metadata']['last_verified'] is None
    assert records[0]['metadata'][CAPTURE_KEY]['reason'] == 'fetch_metadata_missing'
    assert evidence['seed_pages_failed'] == 1


@pytest.mark.parametrize('suffix', ['#project-b', '/'])
def test_shared_page_identity_survives_equivalent_urls_and_merge(monkeypatch, tmp_path, suffix):
    config = school(shared=True)
    config['sources'][0]['programs'][1]['url'] = URL + suffix
    config['sources'][0]['seeds'].append(URL + suffix)
    monkeypatch.setattr(cg, '_fetch', lambda url, **k: soup(final=url, requested=url))
    records, _ = cg.fetch_and_normalize_with_evidence(config, deep=True)
    assert len(records) == 2
    assert all(row['metadata'][CAPTURE_KEY]['reason'] == 'ambiguous_program_scope' for row in records)
    path = tmp_path / 'records.json'; path.write_text('[]')
    monkeypatch.setattr(cg, 'PROCESSED_FILE', path)
    cg.merge_into_processed(records)
    assert len(json.loads(path.read_text())) == 2


@pytest.mark.parametrize('changed', ['school', 'collector_source', 'requested_url', 'status_shape'])
def test_failed_capture_update_is_scoped_and_malformed_safe(changed):
    from src.contact_instructions import capture_failure
    config = school()
    old = cg._normalize_program(config, config['sources'][0], config['sources'][0]['programs'][0])
    old['metadata'].update(capture_metadata(capture_from_html(HTML, source_url=URL, checked_at=STAMP)))
    before = deepcopy(old)
    update = {'school': 'example', 'collector_source': 'example_programs', 'requested_url': URL,
              'capture': capture_failure(source_url='https://example.edu/other', record_source_url=URL, reason='redirect_mismatch')}
    if changed == 'status_shape':
        update['capture']['status'] = []
    else:
        update[changed] = 'unrelated'
    assert cg.apply_condition_capture_updates([old], [update]) == 0
    assert old == before


@pytest.mark.parametrize('html,status', [('<body><p>A readable general program description.</p></body>', 'empty'),
                                       ('<body><p>Intro.</p><h2>Minimum GPA</h2><div>3.0</div></body>', 'unsupported')])
def test_sro_empty_vs_unsupported_is_explicit(monkeypatch, html, status):
    monkeypatch.setattr(sro.requests, 'get', lambda *a, **k: response(html))
    item = raw(); collector = sro.UIUCSROCollector(deep=True)
    collector._fetch_detail_page(item)
    normalized = sro.raw_to_normalized(item)
    assert normalized['metadata'][CAPTURE_KEY]['status'] == status
    assert normalized['metadata']['detail_page_verified'] is (status == 'empty')
    assert bool(normalized['metadata']['last_verified']) is (status == 'empty')
    if status == 'empty':
        assert normalized['metadata'][SOURCE_KEY] == []
    else:
        assert SOURCE_KEY not in normalized['metadata']


def test_sro_field_without_dom_label_does_not_invent_quote(monkeypatch):
    monkeypatch.setattr(sro.requests, 'get', lambda *a, **k: response(DRUPAL.replace('<div class="field__label">Eligibility</div>', '')))
    item = raw(); sro.UIUCSROCollector(deep=True)._fetch_detail_page(item)
    assert item.extra_fields[CAPTURE_KEY]['reason'] == 'missing_field_label'
    assert not item.extra_fields.get(SOURCE_KEY)


def test_sro_actual_pagination_detail_timeout_and_normalization_failure(monkeypatch):
    listing = '<body><table class="views-table"><tbody><tr><td class="views-field-title"><a href="/summer">Summer research</a>Summary</td></tr></tbody></table></body>'
    empty = '<body><table class="views-table"><tbody></tbody></table></body>'
    def get(url, **kwargs):
        if '?page=' not in url: raise TimeoutError('PRIVATE_RESPONSE')
        return response(listing if '?page=0' in url else empty, url)
    monkeypatch.setattr(sro.requests, 'get', get)
    monkeypatch.setattr(sro.UIUCSROCollector, '_rate_limit', lambda self: None)
    records, evidence = sro.fetch_and_normalize_with_evidence(deep=True)
    assert len(records) == 1 and records[0]['metadata']['last_verified'] is None
    assert evidence['list_complete'] is True
    assert evidence['list_pages_loaded'] == 2
    assert evidence['detail_pages_failed'] == 1
    assert evidence['condition_capture_counts']['failed'] == 1
    assert evidence['condition_capture_complete'] is False
    assert 'PRIVATE_RESPONSE' not in str(evidence)
    monkeypatch.setattr(sro, 'raw_to_normalized', lambda item: (_ for _ in ()).throw(ValueError('PRIVATE')))
    records, evidence = sro.fetch_and_normalize_with_evidence(deep=False)
    assert not records and evidence['normalization_failed'] == 1
    assert 'PRIVATE' not in str(evidence)


def test_sro_page_cap_is_incomplete_and_failed_shape_preserves_partial_rows(monkeypatch):
    listing = '<body><table class="views-table"><tbody><tr><td class="views-field-title"><a href="/summer">Summer</a></td></tr><tr><td>Bad row</td></tr></tbody></table></body>'
    monkeypatch.setattr(sro.requests, 'get', lambda url, **k: response(listing, url))
    collector = sro.UIUCSROCollector(config={'rate_limit_delay': 0})
    collector.MAX_PAGES = 1
    rows = collector.collect()
    assert len(rows) == 1
    assert collector.evidence['list_complete'] is False
    assert collector.evidence['list_pages_failed'] == 1
    assert collector.evidence['list_pages_attempted'] == collector.evidence['list_pages_loaded'] + collector.evidence['list_pages_failed']


def test_campus_raw_http_uses_actual_final_url_and_checked_time(monkeypatch):
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response(HTML, URL + '/'))
    page = cg._fetch(URL)
    assert page._ofe_fetch_metadata['requested_url'] == URL
    assert page._ofe_fetch_metadata['final_url'] == URL + '/'
    assert datetime.fromisoformat(page._ofe_fetch_metadata['checked_at']).tzinfo is not None
    assert cg._page_capture(page, URL)['status'] == 'captured'


def test_sro_drupal_preserves_other_applicant_scope_in_real_heading():
    result = sro.UIUCSROCollector._capture_detail_html(
        DRUPAL.replace("<h1>Summer research</h1>", "<h1>Graduate applicants</h1>"), source_url=URL)
    assert result["status"] == "captured"
    assert all(section["heading"].startswith("Graduate applicants > ")
               for section in result["sources"][0]["sections"])


def test_sro_content_budget_rejects_whole_source_instead_of_truncating():
    html = DRUPAL.replace("A minimum GPA of 3.0 is required.", "Minimum GPA " + "x" * 4001)
    result = sro.UIUCSROCollector._capture_detail_html(html, source_url=URL)
    assert result["status"] == "unsupported" and result["reason"] == "content_limit"
    assert not result.get("sources")


def test_shared_configuration_page_equivalence_is_symmetric():
    config = school(shared=True)
    config["sources"][0]["programs"][0]["url"] = "http://example.edu/summer"
    assert cg._ambiguous_program_url(config, "http://example.edu/summer") is True
    assert cg._ambiguous_program_url(config, "https://example.edu/summer") is True
