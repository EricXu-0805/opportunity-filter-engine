"""Opt-in contact/application isolation and lifecycle on a local fixture.

Creates synthetic PDFs only. The supplied three formal users must be disposable.
It merges/deletes those fixture accounts, never hosted or unrelated accounts.
Credentials remain in the 0600 fixture/private journal; reports contain no secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from verify_material_archive_local import candidate_target, loopback, pdf, sanitized_report, verify_fixture_identity

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.lib.material_archive import MaterialService


def verify_candidate_database_info(details, expected_port):
    ports=details.get('HostConfig',{}).get('PortBindings',{}).get('5432/tcp',[])
    if (not details.get('State',{}).get('Running') or len(ports)!=1
        or ports[0].get('HostPort')!=str(expected_port) or ports[0].get('HostIp')!='127.0.0.1'):
        raise ValueError('Candidate database must have exactly one explicit loopback port binding')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expected-api-url',required=True);p.add_argument('--expected-project-id',required=True);p.add_argument('--fixture-prefix',required=True);p.add_argument('--db-container',required=True);p.add_argument('--db-port',type=int,required=True)
    p.add_argument('--fixture',required=True);p.add_argument('--app-base',required=True);p.add_argument('--output',required=True);p.add_argument('--private-state',required=True)
    args=p.parse_args()
    report={'local_only':True,'project_id':args.expected_project_id,'omitted_checks':[],'steps':[]}
    with sanitized_report(args.output,report):
        run(args,report)


def run(args,report):
    fixture=json.loads(Path(args.fixture).read_text());api=candidate_target(fixture,args.expected_api_url,args.expected_project_id,args.fixture_prefix);app=loopback(args.app_base)
    if args.expected_project_id=='ofe-b37-m65' and app not in ('http://127.0.0.1:8200','http://127.0.0.1:3200'):
        raise ValueError('Batch37 must use its separate backend or frontend')
    if args.db_container != 'supabase_db_'+args.expected_project_id:
        raise ValueError('Database container does not match candidate project')
    if args.expected_project_id=='ofe-b37-m65' and args.db_port!=56322:
        raise ValueError('Batch37 database must use its separate candidate port')
    inspected=subprocess.run(['/usr/local/bin/docker','inspect',args.db_container],text=True,capture_output=True)
    if inspected.returncode:raise RuntimeError('Candidate container inspection failed')
    details=json.loads(inspected.stdout)[0]
    verify_candidate_database_info(details,args.db_port)
    source,other,target=fixture['users'];assert [u['label'] for u in (source,other,target)]==['owner_a','owner_b','merge_target']
    journal=Path(args.private_state);assert not journal.exists(),'Private journal exists; inspect before rerunning'
    state={'materials':{},'fixture':args.fixture};report.update({'started_at':datetime.now(UTC).isoformat(),'local_only':True,'project_id':args.expected_project_id,'complete':False,'omitted_checks':[],'steps':[],
      'boundary':'Real local HTTP/Auth/PostgREST/Storage. Merge grant is locally preseeded, then redeemed with the real target session; not browser merge UX or mail delivery.'})
    def save():
        fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(state,f,indent=2)
        os.chmod(journal,0o600);Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    def record(name,**details):report['steps'].append({'name':name,'passed':True,**details});save();print(name+': passed',flush=True)
    def sql(query):
        r=subprocess.run(['/usr/local/bin/docker','exec','-i',args.db_container,'psql','-X','-q','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-At','-f','-'],input=query,text=True,capture_output=True)
        if r.returncode:raise RuntimeError('Local SQL failed; private output withheld')
        return r.stdout.strip()
    def q(value):return "'"+str(value).replace("'","''")+"'"
    def auth(user=None,service=False):
        key=fixture['service_role_key'] if service else fixture['anon_key'];return {'apikey':key,'Authorization':'Bearer '+(user['access_token'] if user else key)}
    client=httpx.Client(timeout=45,follow_redirects=False,trust_env=False)
    def req(method,path,user=None,service=False,**kw):return client.request(method,api+path,headers=auth(user,service),**kw)
    def ok(response,expected=200):
        if response.status_code!=expected:raise RuntimeError(f'Local HTTP {response.status_code}, expected {expected}')
        return response.json() if response.content and 'json' in response.headers.get('content-type','') else None
    def scope(kind,user,event_owner=None):
        event_owner=event_owner or user;return {'expected_owner_id':user['id'],'opportunity_id':event_owner['opportunity_id'],f'{kind}_event_id':event_owner['event_id'] if kind=='application' else event_owner['contact_event_id']}
    def material(kind,user,label):
        m={'version':1,**scope(kind,user),'material_id':str(uuid4()),'record_id':str(uuid4()),'filename':label+'.pdf','mime_type':'application/pdf','byte_length':len(contents),'bytes_sha256':sha,'attested':True}
        state['materials'][label]={'kind':kind,**m};save();return m
    def upload(kind,user,m):return client.post(app+f'/api/{kind}-materials',headers=auth(user),files={'metadata':(None,json.dumps(m)),'file':(m['filename'],contents,'application/pdf')})
    def read(kind,user,m,file=False,event_owner=None):return client.get(app+f'/api/{kind}-materials/'+m['record_id']+('/file' if file else ''),headers=auth(user),params=scope(kind,user,event_owner))
    def remove(kind,user,m):return client.request('DELETE',app+f'/api/{kind}-materials/'+m['record_id'],headers=auth(user),json={**scope(kind,user),'material_id':m['material_id']})
    def raw_object(m):return api+'/storage/v1/object/application-materials/pdf/'+m['material_id']+'.pdf'
    async def cleanup():
        async with httpx.AsyncClient(timeout=45,follow_redirects=False,trust_env=False) as transport:return await MaterialService(transport,api,fixture['service_role_key']).cleanup()
    contents=pdf();sha=hashlib.sha256(contents).hexdigest();save()
    try:
        for user in (source,other,target):verify_fixture_identity(client,fixture,user)
        identities=' or '.join('(id='+q(u['id'])+' and email='+q(u['email'])+')' for u in (source,other,target))
        if sql('select count(*) from auth.users where '+identities+';')!='3':raise ValueError('Candidate database does not contain the exact fixture identities')
        record('live_disposable_auth_and_database_identities_verified',accounts=3)
        # An identical event UUID exists under another owner and in both scopes.
        assert source['event_id']==source['contact_event_id']==other['event_id']==other['contact_event_id']
        original_event=ok(req('GET','/rest/v1/contact_events',source,params={'device_id':'eq.'+source['id'],'event_id':'eq.'+source['contact_event_id']}))[0]
        ready_contact=material('contact',source,'ready-contact');ready_app=material('application',source,'ready-application')
        before={}
        for kind,m in [('contact',ready_contact),('application',ready_app)]:
            before[kind]=ok(upload(kind,source,m))['record'];response=read(kind,source,m,True);ok(response);assert response.content==contents
        wrong=[]
        for kind,m in [('contact',ready_contact),('application',ready_app)]:
            opposite='application' if kind=='contact' else 'contact'
            for response in [read(opposite,source,m),read(opposite,source,m,True),remove(opposite,source,m)]:
                assert response.status_code in (403,404,409,422);wrong.append(response.status_code)
            mapped={k:v for k,v in m.items() if k!=f'{kind}_event_id'};mapped[f'{opposite}_event_id']=source['event_id']
            conflict=upload(opposite,source,mapped);assert conflict.status_code in (403,404,409,422);wrong.append(conflict.status_code)
            assert read(kind,source,m,True).content==contents
            assert read(kind,other,m).status_code==404;assert read(kind,other,m,True).status_code==404
        current_event=ok(req('GET','/rest/v1/contact_events',source,params={'device_id':'eq.'+source['id'],'event_id':'eq.'+source['contact_event_id']}))[0]
        assert current_event==original_event
        record('identical_event_uuid_still_isolates_owner_and_source_kind',wrong_scope_statuses=wrong,original_contact_unchanged=True,pdf_bytes=len(contents),sha256=sha)
        # Same bytes are separate artifacts; deleting one contact does not remove application bytes.
        disposable=material('contact',source,'separate-contact');ok(upload('contact',source,disposable));ok(remove('contact',source,disposable))
        assert read('application',source,ready_app,True).content==contents;assert read('contact',source,ready_contact,True).content==contents
        record('same_bytes_are_independent_artifacts_after_contact_deletion')
        staged_by_kind={};state['stage_receipts']={}
        for kind in ('application','contact'):
            staged=material(kind,source,'staged-'+kind)
            receipt=ok(req('POST',f'/rest/v1/rpc/stage_{kind}_material',source,json={'p_expected_owner':source['id'],'p_material_id':staged['material_id'],'p_record_id':staged['record_id'],f'p_{kind}_event_id':source['event_id'] if kind=='application' else source['contact_event_id'],'p_opportunity_id':source['opportunity_id'],'p_filename':staged['filename'],'p_byte_length':len(contents),'p_sha256':sha}))
            assert receipt['artifact']['status']=='staged';state['stage_receipts'][kind]=receipt;staged_by_kind[kind]=staged;save()
            response=client.post(raw_object(staged),headers={**auth(service=True),'content-type':'application/pdf','x-upsert':'false'},content=contents);assert response.status_code in (200,201)
        grant=str(uuid4());sql('insert into public.merge_grants(token,source_device_id,target_email,expires_at) values('+','.join((q(grant),q(source['id']),q(target['email']),"now()+interval '1 hour'"))+');')
        assert ok(req('POST','/rest/v1/rpc/redeem_merge_grant',target,json={'p_token':grant,'p_secret':None}))['merged'] is True
        for kind,m in [('contact',ready_contact),('application',ready_app)]:
            after=ok(read(kind,target,m,event_owner=source))['record'];assert {k:v for k,v in after.items() if k!='owner_id'}=={k:v for k,v in before[kind].items() if k!='owner_id'}
            assert read(kind,target,m,True,event_owner=source).content==contents;assert read(kind,source,m).status_code==401
        old_finalize_statuses={}
        for kind,staged in staged_by_kind.items():
            tomb=ok(read(kind,target,staged,event_owner=source))['record'];assert tomb['status']=='deleted' and tomb['filename'] is None and tomb['linked_at'] is None
            receipt=state['stage_receipts'][kind]
            late=req('POST',f'/rest/v1/rpc/finalize_{kind}_material',service=True,json={'p_verified_owner':source['id'],'p_verified_session_id':source['session_id'],'p_material_id':staged['material_id'],'p_stage_token':receipt['upload']['stage_token'],'p_verified_byte_length':len(contents),'p_verified_sha256':sha});assert late.status_code==403
            old_finalize_statuses[kind]=late.status_code
        record('merge_preserves_both_ready_scopes_and_permanently_revokes_both_staged_scopes',old_finalize_statuses=old_finalize_statuses)
        verify_fixture_identity(client,fixture,source,require_session=False)
        ok(req('DELETE','/auth/v1/admin/users/'+source['id'],service=True))
        transferred_ids=','.join(q(m['material_id']) for m in (ready_contact,ready_app))
        assert sql(f'select count(*) from private.material_cleanup_outbox where material_id in ({transferred_ids});')=='0'
        source_cleanup=asyncio.run(cleanup());assert source_cleanup['failed']==0
        for kind,m in [('contact',ready_contact),('application',ready_app)]:
            response=read(kind,target,m,True,event_owner=source);ok(response);assert response.content==contents
        record('deleting_source_account_keeps_both_transferred_files',live_identity_rechecked_before_delete=True,ready_artifacts_queued_for_cleanup=0,cleanup=source_cleanup,original_bytes_verified_after_cleanup=True)
        logout_by_kind={kind:material(kind,other,'logout-'+kind) for kind in ('application','contact')}
        for kind,m in logout_by_kind.items():ok(upload(kind,other,m))
        ok(req('POST','/auth/v1/logout?scope=local',other),204)
        denied_by_kind={}
        for kind,m in logout_by_kind.items():
            denied=[read(kind,other,m).status_code,read(kind,other,m,True).status_code,upload(kind,other,m).status_code];assert denied==[401,401,401]
            denied_by_kind[kind]=denied
        record('real_signout_blocks_old_token_for_both_scopes',http_statuses_by_scope=denied_by_kind)
        for user in (target,other):
            verify_fixture_identity(client,fixture,user,require_session=False)
            ok(req('DELETE','/auth/v1/admin/users/'+user['id'],service=True))
        objects=[ready_contact,ready_app,*staged_by_kind.values(),disposable,*logout_by_kind.values()];ids=','.join(q(m['material_id']) for m in objects)
        for table in ('material_artifacts','application_material_records','contact_material_records'):assert sql(f'select count(*) from public.{table} where material_id in ({ids});')=='0'
        outcome=asyncio.run(cleanup())
        assert outcome['failed']==0
        for m in objects:
            response=client.get(raw_object(m),headers=auth(service=True));assert response.status_code==400 and response.json().get('statusCode')=='404'
        record('target_account_delete_and_cleanup_remove_physical_files',live_identities_rechecked_before_delete=2,objects_removed=len(objects),cleanup=outcome,actor='cleanup worker or explicit cleanup; physical absence checked via Storage API')
        # Late immutable bytes on either already-revoked own key are removed again.
        for staged in staged_by_kind.values():
            late_object=client.post(raw_object(staged),headers={**auth(service=True),'content-type':'application/pdf','x-upsert':'false'},content=contents);assert late_object.status_code in (200,201)
            sql('update private.material_cleanup_outbox set next_attempt_at=now(),claimed_until=null where material_id='+q(staged['material_id'])+';')
        outcome=asyncio.run(cleanup());assert outcome['failed']==0
        for staged in staged_by_kind.values():
            absent=client.get(raw_object(staged),headers=auth(service=True));assert absent.status_code==400 and absent.json().get('statusCode')=='404'
            assert sql('select count(*) from private.material_cleanup_outbox where material_id='+q(staged['material_id'])+';')=='1'
        record('extremely_late_uploads_in_both_scopes_are_erased_with_tombstones_retained',scopes=list(staged_by_kind),cleanup=outcome)
        report['passed']=True;report['complete']=True;report['completed_at']=datetime.now(UTC).isoformat();save()
    finally:client.close()


if __name__=='__main__':main()
