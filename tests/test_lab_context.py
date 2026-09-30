"""Synthetic website snapshots, independent from real-source verification."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from src.lab_context import lab_context_for, lab_snapshot_version, validate_public_lab_context

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
URL = 'https://statistics.berkeley.edu/people/peng-ding'


def record():
    return {'id': 'faculty-ucb-stat-fixture', 'school': 'ucb', 'source': 'ucb_stat_faculty',
            'source_type': 'faculty_research', 'department': 'Department of Statistics', 'pi_name': 'Peng Ding',
            'source_url': URL, 'url': URL, 'metadata': {}}


def snapshot(*, now=NOW):
    item = record()
    return {'version': 1, 'source': 'official_website', 'record_id': item['id'], 'record_source_url': URL,
            'school': 'ucb', 'department': item['department'], 'identity_name': item['pi_name'], 'policy_version': 1,
            'checked_at': now.isoformat().replace('+00:00', 'Z'), 'pages': [{
                'kind': 'faculty_profile', 'requested_url': URL, 'source_url': URL,
                'page_title': 'Peng Ding', 'identity_text': 'Peng Ding', 'linked_from': None,
                'sections': [{'section_id': 's1', 'heading': 'Research Expertise and Interests',
                              'text': 'Causal inference, econometrics, experimental design.'}]}]}


def sourced_record(*, now=NOW):
    item = record(); item['metadata']['lab_snapshot'] = snapshot(now=now)
    return item


def test_valid_context_has_complete_detached_source_and_exact_hash():
    item = sourced_record(); before = deepcopy(item)
    value = lab_context_for(item, now=NOW)
    assert value['status'] == 'available'
    assert value['snapshot']['snapshot_version'] == lab_snapshot_version(snapshot())
    assert validate_public_lab_context(value)
    value['snapshot']['pages'][0]['sections'][0]['text'] = 'Changed later'
    assert item == before and not validate_public_lab_context(value)


def test_saved_status_does_not_change_when_historical_parser_reads_it():
    value = lab_context_for(sourced_record(), now=NOW)
    assert validate_public_lab_context(value)
    assert lab_context_for(sourced_record(), now=NOW + timedelta(days=30, seconds=1))['status'] == 'stale'
    assert validate_public_lab_context(value) and value['status'] == 'available'


@pytest.mark.parametrize('key,value', [('id','other'), ('school','uiuc'), ('source','user_import'),
    ('department','Department of Chemistry'), ('pi_name','Other Ding'), ('source_url','https://statistics.berkeley.edu/people/other')])
def test_changed_current_identity_never_uses_retained_snapshot(key,value):
    item=sourced_record();item[key]=value
    assert lab_context_for(item,now=NOW)['status']=='unavailable'


def test_no_openalex_attribution_or_legacy_text_can_mint_website_source():
    item=record();item.update(description_clean='Official research about optics')
    item['metadata']={'verification_scope':'profile','research_areas_raw':'Optics','publication_attribution_status':'verified_author_id'}
    assert lab_context_for(item,now=NOW)['status']=='unavailable'
    item=sourced_record()
    assert lab_context_for(item,now=NOW)['status']=='available'


def test_future_and_identity_revocation_are_not_current_authority():
    assert lab_context_for(sourced_record(now=NOW+timedelta(seconds=1)),now=NOW)['status']=='unavailable'
    item=sourced_record();item['metadata']['lab_refresh']={'checked_at':NOW.isoformat().replace('+00:00','Z'),'reason':'identity_mismatch'}
    assert lab_context_for(item,now=NOW)['status']=='unavailable'
    item['metadata']['lab_refresh']['reason']='request_failed'
    assert lab_context_for(item,now=NOW)['status']=='available'


def historical(value):
    return {'version':1, 'status':'available', 'snapshot':{**value, 'snapshot_version':lab_snapshot_version(value)}}


@pytest.mark.parametrize('value', [None, True, [], {}, 1, '', 'null'])
def test_malformed_values_do_not_raise_or_gain_source_authority(value):
    assert not validate_public_lab_context(value)
    assert lab_context_for(value, now=NOW)['status'] == 'unavailable'


@pytest.mark.parametrize('url', [None, 'https://statistics.berkeley.edu', 'https://STATISTICS.berkeley.edu/',
    'https://statistics.berkeley.edu:443/', 'https://statistics.berkeley.edu:444/', 'https://127.0.0.1/',
    'https://statistics.berkeley.edu/a/../b', 'https://statistics.berkeley.edu/a/%2e%2e/b',
    'https://statistics.berkeley.edu/a?x=1', 'https://statistics.berkeley.edu/a#b',
    'https://statistics.berkeley.edu/a\\b', 'https://statistics.berkeley.edu/研究',
    'https://statistics.berkeley.edu/a b', 'https://user@statistics.berkeley.edu/a'])
def test_url_parser_rejects_noncanonical_forms_including_null(url):
    from src.lab_context import canonical_lab_url
    assert canonical_lab_url(url) is None
    value=snapshot();value['record_source_url']=url
    value['pages'][0]['requested_url']=url;value['pages'][0]['source_url']=url
    with pytest.raises(ValueError):
        lab_snapshot_version(value)


@pytest.mark.parametrize('stamp', ['2026-02-30T12:00:00Z', '2026-09-26T12:00:00+00:00',
    '2026-09-26', '2026-09-26T12:00:60Z', '2026-09-26T12:00:00.1234567Z', None])
def test_dates_reject_rollover_and_noncanonical_forms(stamp):
    value=snapshot();value['checked_at']=stamp
    with pytest.raises(ValueError):
        lab_snapshot_version(value)


def test_codepoint_and_aggregate_limits_do_not_truncate_unicode():
    value=snapshot(); section=value['pages'][0]['sections'][0]
    section['heading']=''; section['text']='😀'*4000
    assert validate_public_lab_context(historical(value))
    section['text']+='😀'
    with pytest.raises(ValueError): lab_snapshot_version(value)
    section['text']='x'*4000
    value['pages'][0]['sections']=[{**section,'section_id':f's{i+1}'} for i in range(6)]
    assert validate_public_lab_context(historical(value))
    value['pages'][0]['sections'][0]['heading']='x'
    with pytest.raises(ValueError): lab_snapshot_version(value)


@pytest.mark.parametrize('mutation', [
    lambda s:s.update(extra=True),
    lambda s:s.update(version=True),
    lambda s:s.update(policy_version=2),
    lambda s:s['pages'][0].update(extra=True),
    lambda s:s['pages'][0].update(linked_from={}),
    lambda s:s['pages'][0]['sections'][0].update(extra=True),
    lambda s:s['pages'][0]['sections'][0].update(section_id='s2'),
    lambda s:s['pages'][0]['sections'][0].update(text=''),
    lambda s:s['pages'][0]['sections'][0].update(text='bad\x00text'),
    lambda s:s['pages'][0]['sections'][0].update(text='bad\ud800text'),
    lambda s:s['pages'][0].update(sections=[]),
])
def test_strict_schema_rejects_unknown_fields_bad_ids_and_invalid_text(mutation):
    value=snapshot();mutation(value)
    with pytest.raises(ValueError): lab_snapshot_version(value)


def test_historical_two_page_shape_preserved_but_no_current_lab_policy_is_invented():
    value=snapshot(); page=deepcopy(value['pages'][0]); lab_url='https://lab.example.org/research/'
    page.update(kind='lab_website', requested_url=lab_url, source_url=lab_url,
                linked_from={'profile_url':URL,'anchor_text':'Research lab','href':lab_url})
    value['pages'].append(page)
    saved=historical(value)
    assert validate_public_lab_context(saved)
    item=record();item['metadata']['lab_snapshot']=value
    assert lab_context_for(item,now=NOW)['status']=='unavailable'


def test_hash_covers_complete_content_binding_and_check_time():
    original=snapshot(); original_hash=lab_snapshot_version(original)
    for field,value in [('record_id','different'),('checked_at','2026-09-26T11:00:00Z')]:
        changed=deepcopy(original);changed[field]=value
        assert lab_snapshot_version(changed)!=original_hash
    changed=deepcopy(original);changed['pages'][0]['sections'][0]['text']+='!'
    assert lab_snapshot_version(changed)!=original_hash


@pytest.mark.parametrize('url,valid', [
    ('https://statistics.berkeley.edu/a^b',False),
    ('https://xn--example-9db.edu/',False),
    ('https://example.edu-/',False),
    ('https://xn--fa-hia.de/',True),
    ('https://statistics.berkeley.edu/a%5Eb',True),
    ('https://statistics.berkeley.edu/%E7%A0%94%E7%A9%B6',True),
])
def test_url_punycode_and_encoded_path_match_browser_canonical_rules(url,valid):
    from src.lab_context import canonical_lab_url
    assert (canonical_lab_url(url)==url) is valid


def _rescrape(existing, **changes):
    from src.collectors.uiuc_faculty import _carry_forward_enrichment
    incoming = {**record(), 'metadata': {'first_seen_at': '2026-09-27T00:00:00'}, **changes}
    _carry_forward_enrichment(existing, incoming)
    return incoming


def test_rescrape_carries_applied_lab_source_through_ucb_merge(monkeypatch, tmp_path):
    import json

    from src.collectors import ucb_common
    existing = sourced_record()
    existing['metadata']['lab_refresh'] = {'checked_at': snapshot()['checked_at'], 'status': 'success', 'reason': None}
    path = tmp_path / 'opportunities.json'; path.write_text(json.dumps([existing]))
    monkeypatch.setattr(ucb_common, 'PROCESSED_FILE', path)
    ucb_common.merge_into_processed([{**record(), 'metadata': {'first_seen_at': '2026-09-27T00:00:00'}}])
    [saved] = json.loads(path.read_text())
    assert saved['metadata']['lab_snapshot'] == existing['metadata']['lab_snapshot']
    assert saved['metadata']['lab_refresh'] == existing['metadata']['lab_refresh']
    assert lab_context_for(saved, now=NOW)['status'] == 'available'


def test_rescrape_of_changed_identity_keeps_refresh_but_not_snapshot():
    existing = sourced_record()
    existing['metadata']['lab_refresh'] = {'checked_at': snapshot()['checked_at'], 'status': 'success', 'reason': None}
    incoming = _rescrape(existing, pi_name='Other Ding')
    assert 'lab_snapshot' not in incoming['metadata']
    assert incoming['metadata']['lab_refresh'] == existing['metadata']['lab_refresh']


def test_rescrape_keeps_revocation_with_withheld_snapshot():
    later = (NOW + timedelta(days=1)).isoformat().replace('+00:00', 'Z')
    existing = sourced_record()
    existing['metadata']['lab_refresh'] = {'checked_at': later, 'status': 'failed', 'reason': 'identity_mismatch',
                                           'identity_revoked_at': later}
    incoming = _rescrape(existing)
    assert incoming['metadata']['lab_refresh'] == existing['metadata']['lab_refresh']
    assert incoming['metadata']['lab_snapshot'] == existing['metadata']['lab_snapshot']
    assert lab_context_for(incoming, now=NOW + timedelta(days=2))['status'] == 'unavailable'
