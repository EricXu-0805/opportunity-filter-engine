"""Complete V2 source publication in temporary Git repositories only."""
import json
from copy import deepcopy
from datetime import timedelta

import pytest

from src.collectors.lab_website import build_lab_candidate
from src.lab_context import NIELSEN_HOME, NIELSEN_PROFILE, NIELSEN_TEAM, lab_context_for
from tests.lab_nielsen_fixtures import nielsen_fetch, nielsen_pages, nielsen_record
from tests.test_lab_candidate import SHARD, apply, build, git, setup, verify
from tests.test_lab_candidate import offline as offline
from tests.test_lab_context import NOW
from tests.test_lab_nielsen_chain import collected


def test_complete_v2_candidate_verify_apply_is_idempotent_and_preserves_full_chain(tmp_path):
    c=setup(tmp_path,[nielsen_record()],read=nielsen_fetch()); before=(c['repo']/SHARD).read_bytes()
    manifest=build(c); assert verify(c)==manifest and (c['repo']/SHARD).read_bytes()==before
    expected=deepcopy(c['envelope']['results'][0]['patch']['lab_snapshot'])
    assert apply(c)['status']=='applied'
    actual=json.loads((c['repo']/SHARD).read_text())[0]
    assert actual['metadata']['lab_snapshot']==expected
    assert len(expected['source_chain']['documents'])==4 and len(expected['pages'][1]['sections'])==10
    assert lab_context_for(actual,now=NOW)['status']=='available'
    after=(c['repo']/SHARD).read_bytes()
    assert apply(c)['status']=='already_applied' and (c['repo']/SHARD).read_bytes()==after


def revoked_record():
    record=nielsen_record(); old=collected(now=NOW-timedelta(days=2))[0]
    record['metadata'].update(old)
    record['metadata']['lab_refresh']={'checked_at':'2026-09-25T12:00:00Z','status':'failed','reason':'source_link_removed',
        'identity_revoked_at':'2026-09-25T12:00:00Z'}
    return record


@pytest.mark.parametrize('existing',['none','v2','revoked'])
def test_nielsen_success_cannot_downgrade_to_profile_only_v1(tmp_path,existing):
    item=revoked_record() if existing=='revoked' else nielsen_record()
    if existing=='v2': item['metadata'].update(collected(now=NOW-timedelta(days=1))[0])
    c=setup(tmp_path,[item],read=nielsen_fetch());private=c['envelope']['results'][0]['patch']['lab_snapshot']
    private.pop('source_chain');private.update(version=1,policy_version=1,pages=private['pages'][:1])
    before=(c['repo']/SHARD).read_bytes()
    with pytest.raises(ValueError,match='lab_chain_downgrade'): build(c)
    assert (c['repo']/SHARD).read_bytes()==before and not c['output'].exists()


@pytest.mark.parametrize('url',[NIELSEN_PROFILE,NIELSEN_HOME,NIELSEN_TEAM])
def test_verified_link_or_identity_revocation_survives_apply_then_outage_then_full_recheck(tmp_path,url):
    item=nielsen_record(); item['metadata'].update(collected(now=NOW-timedelta(days=2))[0]); old=deepcopy(item['metadata']['lab_snapshot'])
    pages=nielsen_pages()
    if url==NIELSEN_PROFILE:
        pages[url]=pages[url].replace(b'https://nielsen-lab.github.io',b'https://different.example.org/')
    elif url==NIELSEN_HOME:
        pages[url]=pages[url].replace(b'href="/team/"',b'href="/elsewhere/"')
    else: pages[url]=pages[url].replace(b'>Rasmus Nielsen<',b'>Other Nielsen<')
    c=setup(tmp_path,[item],read=nielsen_fetch(pages));build(c);apply(c)
    revoked=json.loads((c['repo']/SHARD).read_text())[0]
    assert revoked['metadata']['lab_snapshot']==old
    assert lab_context_for(revoked,now=NOW)['status']=='unavailable'
    tombstone=revoked['metadata']['lab_refresh']['identity_revoked_at']
    for index,read in enumerate((lambda _:(None,'request_failed'),nielsen_fetch()),1):
        git(c['repo'],'add','.');git(c['repo'],'commit','-qm','fixture observation')
        c.update(base=git(c['repo'],'rev-parse','HEAD'),output=tmp_path/f'candidate-{index}',now=NOW+timedelta(hours=index))
        c['envelope']=build_lab_candidate([revoked],[revoked['id']],now=c['now'],fetch=read)
        build(c);apply(c);revoked=json.loads((c['repo']/SHARD).read_text())[0]
        if index==1:
            assert revoked['metadata']['lab_refresh']['identity_revoked_at']==tombstone
            assert revoked['metadata']['lab_snapshot']==old
            assert lab_context_for(revoked,now=c['now'])['status']=='unavailable'
        else:
            assert 'identity_revoked_at' not in revoked['metadata']['lab_refresh']
            assert revoked['metadata']['lab_snapshot']['version']==2
            assert lab_context_for(revoked,now=c['now'])['status']=='available'


@pytest.mark.parametrize('mutation',[
    lambda p:p['lab_refresh'].pop('identity_revoked_at'),
    lambda p:p['lab_refresh'].update(identity_revoked_at='2026-09-24T12:00:00Z'),
])
def test_candidate_cannot_drop_or_rewind_source_link_revocation(tmp_path,mutation):
    c=setup(tmp_path,[revoked_record()],read=lambda _:(None,'request_failed'))
    mutation(c['envelope']['results'][0]['patch'])
    with pytest.raises(ValueError,match='lab_revocation_not_preserved'): build(c)


@pytest.mark.parametrize('mutation',[
    lambda s:s['source_chain']['documents'][3].update(source_url='https://unreviewed.example.org/research/'),
    lambda s:s['source_chain']['identity'].update(role_text='Former Professor'),
    lambda s:s['source_chain']['links'][0].update(anchor_text='Former lab'),
    lambda s:s['source_chain']['links'][1].update(anchor_text='Past team'),
    lambda s:s['source_chain']['links'][2].update(anchor_text='Archived research'),
    lambda s:s['source_chain']['links'][1].update(raw_href='https://nielsen-lab.github.io/team/'),
    lambda s:s['pages'][1]['sections'].pop(),
])
def test_candidate_revalidates_current_chain_policy_before_writing(tmp_path,mutation):
    c=setup(tmp_path,[nielsen_record()],read=nielsen_fetch());mutation(c['envelope']['results'][0]['patch']['lab_snapshot'])
    before=(c['repo']/SHARD).read_bytes()
    with pytest.raises(ValueError,match='invalid_lab_source_snapshot'): build(c)
    assert (c['repo']/SHARD).read_bytes()==before and not c['output'].exists()
