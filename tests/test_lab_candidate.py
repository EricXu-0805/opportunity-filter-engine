"""Local temporary Git repositories and synthetic website transport only."""
from __future__ import annotations

import json
import socket
import subprocess
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
import requests

from scripts import lab_candidate as candidate
from scripts import refresh_artifact as artifacts
from src.collectors.lab_website import build_lab_candidate, canonical_record_sha
from src.lab_context import lab_context_for
from tests.test_lab_context import NOW, URL, record, snapshot
from tests.test_ucb_stat_faculty import PROFILE_WITH_INTERESTS_HTML

SHARD='data/processed/shards/ucb.json'
OTHER='data/processed/shards/uiuc.json'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('Unexpected network request')
    monkeypatch.setattr(requests.Session,'send',forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)


def git(repo,*args):
    return subprocess.run(['git','-C',str(repo),*args],capture_output=True,text=True,check=True).stdout.strip()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def fetch(url):
    return {'requested_url':url,'source_url':url,'html':PROFILE_WITH_INTERESTS_HTML.encode()},None


def setup(tmp_path,records=None,*,source_shards=None,read=fetch,when=NOW):
    repo=tmp_path/'repository';repo.mkdir()
    records=[record()] if records is None else records
    for rec in records:
        rec.setdefault('metadata',{}).update(research_snapshot={'preserve':'whole paper source'},recent_works=[{'title':'Keep original','year':2025}],custom=['研究','🧪'])
    other=[{'id':'uiuc-program','school':'uiuc','pi_name':None,'department':None,'metadata':{'unchanged':True}}]
    write(repo/SHARD,records);write(repo/OTHER,other)
    git(repo,'init','-q');git(repo,'config','user.name','Local fixture');git(repo,'config','user.email','fixture@invalid.example')
    git(repo,'add','.');git(repo,'commit','-qm','fixture base')
    base=git(repo,'rev-parse','HEAD')
    shards=['ucb'] if source_shards is None else source_shards
    corpus=[rec for school in sorted(shards) for rec in (records if school=='ucb' else other)]
    envelope=build_lab_candidate(corpus,[records[0]['id']],now=when,fetch=read)
    return {'repo':repo,'base':base,'shards':shards,'envelope':envelope,'output':tmp_path/'artifact','now':when,'records':records}


def build(c):
    return candidate.build_candidate(c['envelope'],repository_root=c['repo'],base_sha=c['base'],source_shards=c['shards'],output=c['output'],now=c['now'])


def verify(c):
    return candidate.validate_candidate(c['output'],repository_root=c['repo'],expected_candidate_sha256=canonical_record_sha(c['envelope']),now=c['now'])


def apply(c):
    return candidate.promote_candidate(c['output'],repository_root=c['repo'],expected_candidate_sha256=canonical_record_sha(c['envelope']),now=c['now'])


def test_collector_build_verify_apply_duplicate_preserves_other_fields_and_git(tmp_path):
    c=setup(tmp_path); repo=c['repo'];before=(repo/SHARD).read_bytes();other=(repo/OTHER).read_bytes();original=deepcopy(c['envelope'])
    manifest=build(c)
    assert manifest==verify(c) and (repo/SHARD).read_bytes()==before and c['envelope']==original
    assert apply(c)['status']=='applied'
    after=(repo/SHARD).read_bytes();row=json.loads(after)[0]
    assert lab_context_for(row,now=NOW)['status']=='available'
    assert row['metadata']['research_snapshot']=={'preserve':'whole paper source'}
    assert row['metadata']['recent_works']==[{'title':'Keep original','year':2025}]
    assert row['metadata']['custom']==['研究','🧪']
    assert (repo/OTHER).read_bytes()==other and git(repo,'rev-parse','HEAD')==c['base']
    assert apply(c)['status']=='already_applied' and (repo/SHARD).read_bytes()==after
    assert not list(repo.rglob('*.backup')) and not list(repo.rglob('*.tmp'))


def test_unselected_sibling_and_range_outside_source_shards_are_preserved(tmp_path):
    first=record();second=record();second['id']='second'
    c=setup(tmp_path,[first,second]);build(c)
    unrelated=[{'id':'new-uiuc','school':'uiuc','metadata':{'changed':'independently'}}]
    write(c['repo']/OTHER,unrelated);outside=(c['repo']/OTHER).read_bytes()
    apply(c)
    rows=json.loads((c['repo']/SHARD).read_text())
    assert rows[1]==second and 'lab_snapshot' not in rows[1]['metadata']
    assert (c['repo']/OTHER).read_bytes()==outside


def test_source_shard_scope_includes_unselected_record_changes(tmp_path):
    first=record();second=record();second['id']='sibling'
    c=setup(tmp_path,[first,second]);build(c)
    rows=json.loads((c['repo']/SHARD).read_text());rows[1]['description']='another editor'
    write(c['repo']/SHARD,rows);changed=(c['repo']/SHARD).read_bytes()
    with pytest.raises(ValueError,match='destination_changed'): apply(c)
    assert (c['repo']/SHARD).read_bytes()==changed


def test_named_source_shard_with_no_patch_is_still_frozen(tmp_path):
    c=setup(tmp_path,source_shards=['uiuc','ucb']);build(c)
    outside=json.loads((c['repo']/OTHER).read_text());outside[0]['metadata']['new']=True;write(c['repo']/OTHER,outside)
    with pytest.raises(ValueError,match='destination_changed'): apply(c)


@pytest.mark.parametrize('phase',['base','current'])
def test_duplicate_id_anywhere_in_repository_blocks_candidate(phase,tmp_path):
    c=setup(tmp_path)
    if phase=='current': build(c)
    other=json.loads((c['repo']/OTHER).read_text());other[0]['id']=c['records'][0]['id'];write(c['repo']/OTHER,other)
    if phase=='base':
        git(c['repo'],'add','.');git(c['repo'],'commit','-qm','duplicate fixture');c['base']=git(c['repo'],'rev-parse','HEAD')
    with pytest.raises(ValueError,match='duplicate_research_record_id'):
        build(c) if phase=='base' else apply(c)


@pytest.mark.parametrize('error',['request_failed','unsupported_template','identity_mismatch','rate_limited'])
def test_failed_attempt_retains_last_success_without_renewing_time(tmp_path,error):
    rec=record();old=snapshot(now=NOW-timedelta(days=31));rec['metadata']['lab_snapshot']=old
    c=setup(tmp_path,[rec],read=lambda _:(None,error))
    # A transport cannot mint identity rejection; use the actual collector's parsed wrong-person path.
    if error=='identity_mismatch':
        wrong=PROFILE_WITH_INTERESTS_HTML.replace('>Peng Ding<','>Other Ding<')
        c['envelope']=build_lab_candidate(c['records'],[rec['id']],now=NOW,
            fetch=lambda url:({'requested_url':url,'source_url':url,'html':wrong.encode()},None))
    build(c);apply(c);row=json.loads((c['repo']/SHARD).read_text())[0]
    assert row['metadata']['lab_snapshot']==old
    assert row['metadata']['lab_refresh']['reason']==error
    assert lab_context_for(row,now=NOW)['status']==('unavailable' if error=='identity_mismatch' else 'stale')


def test_prior_revocation_survives_failure_and_newer_success_can_clear_it(tmp_path):
    rec=record();rec['metadata']['lab_snapshot']=snapshot(now=NOW-timedelta(days=2))
    rec['metadata']['lab_refresh']={'checked_at':'2026-09-25T12:00:00Z','status':'failed','reason':'identity_mismatch','identity_revoked_at':'2026-09-25T12:00:00Z'}
    c=setup(tmp_path,[rec],read=lambda _:(None,'request_failed'));build(c);apply(c)
    failed=json.loads((c['repo']/SHARD).read_text())[0]
    assert lab_context_for(failed,now=NOW)['status']=='unavailable'
    assert failed['metadata']['lab_refresh']['identity_revoked_at']=='2026-09-25T12:00:00Z'
    git(c['repo'],'add','.');git(c['repo'],'commit','-qm','failed observation fixture')
    c['base']=git(c['repo'],'rev-parse','HEAD');c['output']=tmp_path/'success-artifact';c['now']=NOW+timedelta(hours=1)
    c['envelope']=build_lab_candidate([failed],[failed['id']],now=c['now'],fetch=fetch)
    build(c);apply(c);new=json.loads((c['repo']/SHARD).read_text())[0]
    assert 'identity_revoked_at' not in new['metadata']['lab_refresh']
    assert lab_context_for(new,now=c['now'])['status']=='available'


@pytest.mark.parametrize('mutation', [
    lambda e:e.update(extra=True),lambda e:e.update(version=True),lambda e:e.update(kind='other'),
    lambda e:e.update(corpus_sha256='0'*64),lambda e:e.update(created_at='2099-01-01T00:00:00Z'),
    lambda e:e.update(results=[]),lambda e:e['results'].append(deepcopy(e['results'][0])),
    lambda e:e['results'][0].update(record_id='not-present'),lambda e:e['results'][0].update(before_sha256='0'*64),
    lambda e:e['results'][0].update(extra=True),lambda e:e['results'][0]['patch'].update(recent_works=[]),
    lambda e:e['results'][0]['patch'].update(description='not allowed'),
    lambda e:e['results'][0]['patch']['lab_refresh'].update(extra=True),
    lambda e:e['results'][0]['patch']['lab_refresh'].update(checked_at='2026-09-25T12:00:00Z'),
    lambda e:e['results'][0]['patch']['lab_refresh'].update(status='failed',reason='request_failed'),
    lambda e:e['results'][0]['patch']['lab_refresh'].update(status='success',reason='request_failed'),
    lambda e:e['results'][0]['patch']['lab_refresh'].update(identity_revoked_at=None),
    lambda e:e['results'][0]['patch']['lab_snapshot'].update(record_id='other'),
    lambda e:e['results'][0]['patch']['lab_snapshot'].update(identity_name='Other Ding'),
    lambda e:e['results'][0]['patch']['lab_snapshot'].update(school='uiuc'),
    lambda e:e['results'][0]['patch']['lab_snapshot'].update(policy_version=2),
    lambda e:e['results'][0]['patch']['lab_snapshot'].update(checked_at='2026-09-25T12:00:00Z'),
    lambda e:e['results'][0]['patch']['lab_snapshot']['pages'][0].update(identity_text='Other Ding'),
    lambda e:e['results'][0]['patch']['lab_snapshot']['pages'][0].update(source_url=URL+'/'),
    lambda e:e['results'][0]['patch']['lab_snapshot']['pages'][0]['sections'][0].update(text=''),
])
def test_invalid_envelope_or_snapshot_never_builds_or_writes(mutation,tmp_path):
    c=setup(tmp_path);before=(c['repo']/SHARD).read_bytes();mutation(c['envelope'])
    with pytest.raises(ValueError): build(c)
    assert not c['output'].exists() and (c['repo']/SHARD).read_bytes()==before


@pytest.mark.parametrize('reason',['unsupported_policy','invalid_target','unknown','PRIVATE secret'])
def test_unusable_failure_not_promoted_even_on_supported_target(tmp_path,reason):
    c=setup(tmp_path,read=lambda _:(None,'request_failed'))
    c['envelope']['results'][0]['patch']['lab_refresh']['reason']=reason
    with pytest.raises(ValueError,match='invalid_lab_failure'): build(c)


def test_unsupported_target_attempt_cannot_change_another_school(tmp_path):
    c=setup(tmp_path,source_shards=['ucb','uiuc'])
    corpus=[*c['records'],*json.loads((c['repo']/OTHER).read_text())]
    c['envelope']=build_lab_candidate(corpus,['uiuc-program'],now=NOW,fetch=lambda _:pytest.fail())
    with pytest.raises(ValueError,match='policy_unavailable'): build(c)


@pytest.mark.parametrize('mutation',[
    lambda patch:patch['lab_refresh'].pop('identity_revoked_at'),
    lambda patch:patch['lab_refresh'].update(identity_revoked_at='2026-09-24T12:00:00Z'),
    lambda patch:patch['lab_refresh'].update(identity_revoked_at=None),
])
def test_failed_patch_cannot_drop_or_weaken_existing_revocation(tmp_path,mutation):
    rec=record();rec['metadata']['lab_refresh']={'checked_at':'2026-09-25T12:00:00Z','status':'failed','reason':'identity_mismatch','identity_revoked_at':'2026-09-25T12:00:00Z'}
    c=setup(tmp_path,[rec],read=lambda _:(None,'request_failed'));mutation(c['envelope']['results'][0]['patch'])
    with pytest.raises(ValueError,match='revocation_not_preserved'): build(c)


def test_unrequested_revocation_cannot_be_injected_into_network_failure(tmp_path):
    c=setup(tmp_path,read=lambda _:(None,'request_failed'))
    c['envelope']['results'][0]['patch']['lab_refresh']['identity_revoked_at']='2026-09-26T12:00:00Z'
    with pytest.raises(ValueError,match='unexpected_lab_revocation'): build(c)


def test_rewound_candidate_time_and_equal_time_revalidation_are_rejected(tmp_path):
    rec=record();rec['metadata']['lab_refresh']={'checked_at':'2026-09-26T12:00:00Z','status':'failed','reason':'identity_mismatch','identity_revoked_at':'2026-09-26T12:00:00Z'}
    c=setup(tmp_path,[rec],when=NOW+timedelta(hours=1))
    for stamp in ['2026-09-26T11:00:00Z','2026-09-26T12:00:00Z']:
        c['envelope']['created_at']=stamp
        c['envelope']['results'][0]['patch']['lab_refresh']['checked_at']=stamp
        c['envelope']['results'][0]['patch']['lab_snapshot']['checked_at']=stamp
        with pytest.raises(ValueError): build(c)


@pytest.mark.parametrize('kind',['candidate','manifest','extra','shard','duplicate_json','hardlink','symlink'])
def test_changed_artifact_rejected_before_destination_write(tmp_path,kind):
    c=setup(tmp_path);build(c);before=(c['repo']/SHARD).read_bytes()
    if kind=='candidate':
        value=json.loads((c['output']/candidate.CANDIDATE_FILE).read_text());value['results'][0]['patch']['lab_snapshot']['pages'][0]['sections'][0]['text']='Tampered source';write(c['output']/candidate.CANDIDATE_FILE,value)
    elif kind=='manifest':
        value=json.loads((c['output']/candidate.MANIFEST).read_text());value['total_size']+=1;write(c['output']/candidate.MANIFEST,value)
    elif kind=='extra': (c['output']/'extra.txt').write_text('unexpected')
    elif kind=='shard': (c['output']/SHARD).write_text('[]')
    elif kind=='duplicate_json':
        path=c['output']/candidate.CANDIDATE_FILE;path.write_text(path.read_text().replace('{','{"version":1,',1))
    elif kind=='hardlink':
        (tmp_path/'linked').hardlink_to(c['output']/candidate.CANDIDATE_FILE)
    else:
        path=c['output']/candidate.CANDIDATE_FILE;raw=path.read_bytes();path.unlink();outside=tmp_path/'outside';outside.write_bytes(raw);path.symlink_to(outside)
    with pytest.raises(ValueError): apply(c)
    assert (c['repo']/SHARD).read_bytes()==before


def test_external_expected_digest_prevents_whole_artifact_substitution(tmp_path):
    c=setup(tmp_path);build(c)
    with pytest.raises(ValueError,match='digest_mismatch'):
        candidate.promote_candidate(c['output'],repository_root=c['repo'],expected_candidate_sha256='0'*64,now=NOW)


@pytest.mark.parametrize('kind',['record','whole_candidate','staged'])
def test_preflight_rejects_changes_during_staging(tmp_path,monkeypatch,kind):
    c=setup(tmp_path);build(c);before=(c['repo']/SHARD).read_bytes();real_stage=artifacts._stage_copy
    def stage(source,destination):
        path=real_stage(source,destination)
        if kind=='staged': path.write_text('[]')
        elif kind=='whole_candidate': (c['output']/candidate.CANDIDATE_FILE).write_text('{}')
        else:
            rows=json.loads((c['repo']/SHARD).read_text());rows[0]['description']='concurrent user edit';write(c['repo']/SHARD,rows)
        return path
    monkeypatch.setattr(artifacts,'_stage_copy',stage)
    with pytest.raises(ValueError): apply(c)
    if kind=='record': assert json.loads((c['repo']/SHARD).read_text())[0]['description']=='concurrent user edit'
    else: assert (c['repo']/SHARD).read_bytes()==before
    assert not list(c['repo'].rglob('*.tmp')) and not list(c['repo'].rglob('*.backup'))


def test_interrupted_install_restores_source_bytes(tmp_path,monkeypatch):
    c=setup(tmp_path);build(c);before=(c['repo']/SHARD).read_bytes();real_replace=artifacts.os.replace;raised=False
    def replace(source,destination):
        nonlocal raised
        result=real_replace(source,destination)
        if not raised and Path(source).suffix=='.tmp':
            raised=True;raise KeyboardInterrupt
        return result
    monkeypatch.setattr(artifacts.os,'replace',replace)
    with pytest.raises(KeyboardInterrupt): apply(c)
    assert (c['repo']/SHARD).read_bytes()==before and verify(c)


def test_shared_publication_lock_blocks_apply_without_overwriting(tmp_path):
    c=setup(tmp_path);build(c);before=(c['repo']/SHARD).read_bytes()
    with artifacts._publication_lock(c['repo']/'.git'):
        with pytest.raises(ValueError,match='in progress'): apply(c)
    assert (c['repo']/SHARD).read_bytes()==before


@pytest.mark.parametrize('kind',['exists','symlink_parent','shards','git'])
def test_output_location_cannot_overlap_or_replace_other_content(tmp_path,kind):
    c=setup(tmp_path)
    if kind=='exists': c['output'].mkdir();(c['output']/'keep').write_text('original')
    elif kind=='symlink_parent':
        alias=tmp_path/'alias';alias.symlink_to(c['repo'],target_is_directory=True);c['output']=alias/'artifact'
    elif kind=='shards': c['output']=c['repo']/'data/processed/shards/new'
    else: c['output']=c['repo']/'.git'/'new'
    with pytest.raises(ValueError): build(c)
    if kind=='exists': assert (c['output']/'keep').read_text()=='original'


def test_cli_build_verify_apply_round_trip(tmp_path,monkeypatch,capsys):
    c=setup(tmp_path);source=tmp_path/'envelope.json';write(source,c['envelope']);monkeypatch.setattr(candidate,'_now',lambda _:NOW)
    args=['build','--candidate',str(source),'--repo',str(c['repo']),'--base-sha',c['base'],'--source-shard','ucb','--out',str(c['output'])]
    assert candidate.main(args)==0
    digest=canonical_record_sha(c['envelope'])
    for command in ('verify','apply','apply'):
        assert candidate.main([command,'--artifact',str(c['output']),'--repo',str(c['repo']),'--expected-candidate-sha256',digest])==0
    assert 'already_applied' in capsys.readouterr().out
    assert json.loads(source.read_text())==c['envelope']


def test_cli_input_drift_is_detected_before_artifact_publication(tmp_path,monkeypatch):
    c=setup(tmp_path);source=tmp_path/'envelope.json';write(source,c['envelope']);monkeypatch.setattr(candidate,'_now',lambda _:NOW)
    original_write=candidate._write_file
    def drifting_write(path,raw):
        original_write(path,raw)
        source.write_text('{}')
    monkeypatch.setattr(candidate,'_write_file',drifting_write)
    result=candidate.main(['build','--candidate',str(source),'--repo',str(c['repo']),'--base-sha',c['base'],'--source-shard','ucb','--out',str(c['output'])])
    assert result==1 and not c['output'].exists()
    assert not list(tmp_path.glob('.lab-candidate-*'))
    assert 'lab_snapshot' not in json.loads((c['repo']/SHARD).read_text())[0]['metadata']


def test_competing_artifact_directory_is_never_overwritten(tmp_path,monkeypatch):
    c=setup(tmp_path);real_validate=candidate.validate_candidate
    def reserved(*args,**kwargs):
        result=real_validate(*args,**kwargs)
        c['output'].mkdir();(c['output']/'keep').write_text('another operation')
        return result
    monkeypatch.setattr(candidate,'validate_candidate',reserved)
    with pytest.raises(FileExistsError): build(c)
    assert [p.name for p in c['output'].iterdir()]==['keep']
    assert (c['output']/'keep').read_text()=='another operation'


def test_incomplete_artifact_build_cannot_be_applied(tmp_path,monkeypatch):
    c=setup(tmp_path);real_write=candidate._write_file
    def failed(path,raw):
        if path==c['output']/candidate.MANIFEST:
            raise OSError('simulated disk failure')
        real_write(path,raw)
    monkeypatch.setattr(candidate,'_write_file',failed)
    with pytest.raises(OSError): build(c)
    assert not (c['output']/candidate.MANIFEST).exists()
    with pytest.raises(ValueError): apply(c)
    assert 'lab_snapshot' not in json.loads((c['repo']/SHARD).read_text())[0]['metadata']
