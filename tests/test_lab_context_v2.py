"""Snapshot V2 boundaries, independent of network and current policy history."""
import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest

from src.lab_context import (
    lab_context_for,
    lab_snapshot_version,
    resolve_lab_link,
    validate_lab_snapshot,
    validate_public_lab_context,
)
from tests.lab_nielsen_fixtures import nielsen_record
from tests.test_lab_context import NOW, historical, snapshot
from tests.test_lab_nielsen_chain import collected


def source():
    return collected()[0]['lab_snapshot']


def test_golden_hash_matches_independent_serialization_and_history_is_unchanged():
    golden=json.loads((Path(__file__).parent/'fixtures/lab-context-v2-golden.json').read_text())
    before=deepcopy(golden)
    private={k:v for k,v in golden['snapshot'].items() if k!='snapshot_version'}
    expected='ls2:'+hashlib.sha256(json.dumps(private,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    assert golden['snapshot']['snapshot_version']==expected==lab_snapshot_version(private)
    assert validate_public_lab_context(golden) and golden==before
    for status in ('available','stale'):
        golden['status']=status
        assert validate_public_lab_context(golden) and golden['status']==status
    legacy=historical(snapshot()); before=deepcopy(legacy)
    assert validate_public_lab_context(legacy) and legacy==before
    assert legacy['snapshot']['snapshot_version'].startswith('ls1:')


@pytest.mark.parametrize('mutate',[
    lambda s:s.update(extra=True),lambda s:s.update(policy_version=1),lambda s:s.update(version=True),
    lambda s:s['source_chain'].update(extra=True),lambda s:s['source_chain']['documents'].pop(),
    lambda s:s['source_chain']['links'].reverse(),lambda s:s['source_chain']['documents'].reverse(),
    lambda s:s['source_chain']['documents'][0].update(role='home'),
    lambda s:s['source_chain']['documents'][0].update(body_sha256='A'*64),
    lambda s:s['source_chain']['documents'][0].update(checked_at='2026-09-26T11:59:59Z'),
    lambda s:s['source_chain']['documents'][0].update(page_title='Wrong page'),
    lambda s:s['source_chain']['documents'][0].update(source_url='https://other.example.org/'),
    lambda s:s['source_chain']['documents'][0].update(extra=True),
    lambda s:s['source_chain']['links'][1].update(from_url=s['record_source_url']),
    lambda s:s['source_chain']['links'][1].update(raw_href='team/'),
    lambda s:s['source_chain']['links'][1].update(anchor_text=''),
    lambda s:s['source_chain']['links'][1].update(extra=True),
    lambda s:s['source_chain']['identity'].update(source_url=s['record_source_url']),
    lambda s:s['source_chain']['identity'].update(full_name='R. Nielsen'),
    lambda s:s['source_chain']['identity'].update(role_text=''),
    lambda s:s['source_chain']['identity'].update(extra=True),
    lambda s:s['pages'][1].update(identity_text='Rasmus Nielsen'),
    lambda s:s['pages'][1].update(linked_from=None),
    lambda s:s['pages'][1].update(kind='lab_website'),
    lambda s:s['pages'][1]['sections'][0].update(section_id='s10'),
    lambda s:s['pages'][1]['sections'][0].update(text=''),
    lambda s:s['pages'][1]['sections'][0].update(text='bad\x00value'),
    lambda s:s['pages'][1]['sections'][0].update(text='bad\ud800value'),
])
def test_invalid_v2_fails_closed_for_both_historical_and_current_consumers(mutate):
    private=source(); public=historical(private); mutate(private)
    public['snapshot']={**private,'snapshot_version':public['snapshot']['snapshot_version']}
    assert not validate_public_lab_context(public)
    assert validate_lab_snapshot(private,nielsen_record(),now=NOW) is None
    with pytest.raises(ValueError): lab_snapshot_version(private)


@pytest.mark.parametrize('mutate',[
    lambda s:s['source_chain']['documents'][1].update(body_sha256='1'*64),
    lambda s:s['source_chain']['links'][0].update(raw_href='https://nielsen-lab.github.io/'),
    lambda s:s['source_chain']['identity'].update(role_text='A different historical role'),
    lambda s:s['pages'][1]['sections'][-1].update(text='Changed final section.'),
])
def test_chain_and_full_last_section_are_part_of_saved_content_hash(mutate):
    private=source(); old_hash=lab_snapshot_version(private); mutate(private)
    assert lab_snapshot_version(private)!=old_hash
    assert not validate_public_lab_context({'version':1,'status':'available','snapshot':{**private,'snapshot_version':old_hash}})


def test_current_policy_is_stricter_than_historical_shape_without_rewriting_history():
    private=source();private['source_chain']['identity']['role_text']='A former role'
    saved=historical(private); assert validate_public_lab_context(saved)
    assert validate_lab_snapshot(private,nielsen_record(),now=NOW) is None
    private=source();private['pages'][1]['sections'].pop()
    assert validate_public_lab_context(historical(private))
    assert validate_lab_snapshot(private,nielsen_record(),now=NOW) is None
    private=source();private['source_chain']['links'][1]['raw_href']='https://nielsen-lab.github.io/team/'
    assert validate_public_lab_context(historical(private))
    assert validate_lab_snapshot(private,nielsen_record(),now=NOW) is None


@pytest.mark.parametrize('field,value', [('id','same-person-different-record'),('school','uiuc'),('source','ucb_bio_faculty'),
    ('department','Department of Integrative Biology'),('pi_name','Rasmus Other Nielsen'),('source_type','internship')])
def test_current_binding_does_not_generalize_the_reviewed_lab(field,value):
    item=nielsen_record();item['metadata']['lab_snapshot']=source(); item[field]=value
    assert lab_context_for(item,now=NOW)['status']=='unavailable'


def test_age_future_and_revocation_are_rechecked_without_modifying_saved_v2():
    item=nielsen_record();private=source();item['metadata']['lab_snapshot']=private
    saved=lab_context_for(item,now=NOW);before=deepcopy(saved)
    assert lab_context_for(item,now=NOW-timedelta(seconds=1))['status']=='unavailable'
    assert lab_context_for(item,now=NOW+timedelta(days=30))['status']=='available'
    assert lab_context_for(item,now=NOW+timedelta(days=30,seconds=1))['status']=='stale'
    item['metadata']['lab_refresh']={'checked_at':private['checked_at'],'status':'failed','reason':'source_link_removed'}
    assert lab_context_for(item,now=NOW)['status']=='unavailable'
    assert validate_public_lab_context(saved) and saved==before


def test_unicode_limits_and_total_content_are_checked_without_truncation():
    private=source();section=private['pages'][1]['sections'][0];section['text']='🧬'*4000
    assert validate_public_lab_context(historical(private))
    section['text']+='🧬'
    with pytest.raises(ValueError): lab_snapshot_version(private)
    private=source();private['pages'][0]['sections']=[{'section_id':'s1','heading':'','text':'p'}]
    private['pages'][1]['sections']=[{'section_id':f's{i+1}','heading':'','text':'x'*4000} for i in range(6)]
    private['pages'][1]['sections'][-1]['text']='x'*3999
    assert validate_public_lab_context(historical(private))
    private['pages'][1]['sections'][-1]['text']+='x'
    with pytest.raises(ValueError): lab_snapshot_version(private)


@pytest.mark.parametrize('href', ['team/','//nielsen-lab.github.io/team/','/a/../team/','/a/%2e%2e/team/',
    '/team/?q=1','/team/#a','https://nielsen-lab.github.io:443/team/','https://user@nielsen-lab.github.io/team/',
    '/team/\\bad',None,[],{}])
def test_raw_link_resolution_rejects_unreviewed_normalization(href):
    assert resolve_lab_link('https://nielsen-lab.github.io/',href) is None


@pytest.mark.parametrize('href,expected',[
    ('https://nielsen-lab.github.io','https://nielsen-lab.github.io/'),
    ('https://nielsen-lab.github.io/','https://nielsen-lab.github.io/'),
    ('/team/','https://nielsen-lab.github.io/team/'),
    ('https://nielsen-lab.github.io/research/','https://nielsen-lab.github.io/research/'),
])
def test_raw_link_resolution_retains_only_explicit_supported_forms(href,expected):
    assert resolve_lab_link('https://nielsen-lab.github.io/',href)==expected
