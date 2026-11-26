"""Normal public and account calls to a disposable local GoTrue and PostgREST."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def verify(settings_path):
    config = json.loads(Path(settings_path).read_text())
    base = config['API_URL']
    assert base == 'http://127.0.0.1:54321'
    def request(path, data=None, user=None, method=None):
        headers = {'apikey': config['ANON_KEY'], 'Content-Type': 'application/json'}
        if user:
            headers['Authorization'] = 'Bearer ' + user['access_token']
        req = Request(base + path, headers=headers, data=json.dumps(data).encode() if data is not None else None, method=method)
        try:
            with urlopen(req, timeout=30) as result:
                return result.status, json.loads(result.read() or 'null')
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def rpc(name, data, user=None):
        code, result = request('/rest/v1/rpc/' + name, data, user)
        assert code == 200, (name, code, result.get('code'))
        return result

    def user(guest=False):
        credentials = {} if guest else {'email':f'{uuid4()}@example.com','password':str(uuid4())+'a1!'}
        status, session = request('/auth/v1/signup', credentials)
        assert status == 200 and session['user']['is_anonymous'] is guest
        return session

    author, recipient, guest = user(), user(), user(True)
    uid = author['user']['id']
    profile = {'home_school':'uiuc','name':'Private name','college':'Engineering','major':'Computing','grade':'Junior',
               'search_weight':50,'research_interests':'Original directions','resume_text':'Private résumé',
               'skills':[{'name':'Python','level':'experienced','source':'github','confirmed':True,'evidence':'Private source'}],
               'courses':[{'name':'CS 100','source':'resume','status':'completed'}]}
    def save(rev, patch):
        return rpc('commit_profile_patch_cas', {'p_expected_device_id':uid,'p_expected_revision':rev,'p_patch':patch}, author)
    assert save(0,profile)['revision'] == 1
    fields = ['interests','skills','courses']
    value = rpc('preview_profile_share',{'p_fields':fields,'p_expected_owner':uid},author)
    assert value == {'profile_revision':1,'snapshot':{'interests':'Original directions','skills':[{'n':'Python','l':'experienced'}],'courses':['CS 100']}}
    for who in [None, guest]:
        status, _ = request('/rest/v1/rpc/preview_profile_share',{'p_fields':fields,'p_expected_owner':uid},who)
        assert status in (401,403)
    code, _ = request('/rest/v1/rpc/preview_profile_share',{'p_fields':fields,'p_expected_owner':uid},recipient)
    assert code == 403
    for bad in [[],['name'],['skills','skills']]:
        status, _ = request('/rest/v1/rpc/preview_profile_share',{'p_fields':bad,'p_expected_owner':uid},author)
        assert status == 400
    token = str(uuid4())
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    publish = {'p_expected_owner':uid,'p_token':token,'p_expected_version':0,'p_fields':fields,'p_expires_at':future,'p_profile_revision':1}
    create = lambda _: rpc('publish_profile_share',publish,author)
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(create,range(2))) == [{'status':'published','version':1}]*2
    def resolve(version=None):
        return rpc('resolve_profile_share',{'p_token':token,'p_expected_version':version})
    assert resolve()['snapshot'] == value['snapshot']
    listed = request('/rest/v1/profile_shares?select=token,version',user=recipient)[1]
    assert listed == []
    assert request('/rest/v1/profile_shares?select=token,version',user=author)[1] == [{'token':token,'version':1}]
    assert rpc('revoke_profile_share',{'p_token':token,'p_expected_version':1},recipient)['status']=='unavailable'
    assert save(1,{'research_interests':'Replacement directions'})['revision']==2
    assert resolve(1)['snapshot'] == value['snapshot']
    assert rpc('publish_profile_share',dict(publish,p_expected_version=1),author)['status']=='profile_changed'
    replace = dict(publish,p_expected_version=1,p_profile_revision=2,p_fields=['interests'])
    assert rpc('publish_profile_share',replace,author) == {'status':'published','version':2}
    assert rpc('publish_profile_share',replace,author) == {'status':'published','version':2}
    assert resolve(1)=={'status':'changed'}
    assert resolve(2)['snapshot']=={'interests':'Replacement directions'}
    assert rpc('revoke_profile_share',{'p_token':token,'p_expected_version':1},author)['status']=='conflict'
    for _ in range(2):
        assert rpc('revoke_profile_share',{'p_token':token,'p_expected_version':2},author)['status']=='revoked'
    assert resolve()=={'status':'unavailable'}
    assert rpc('publish_profile_share',replace,author)['status']=='unavailable'
    token=str(uuid4())
    expiring=dict(publish,p_token=token,p_fields=['major'],p_profile_revision=2,
                  p_expires_at=(datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat())
    assert rpc('publish_profile_share',expiring,author)['status']=='published'
    assert resolve(1)['status']=='active'
    sleep(3.1)
    assert resolve(1)=={'status':'unavailable'}
    print('PASS real GoTrue and PostgREST: saved-field projection, permanent author gate, cross-account visibility, duplicate concurrent create, version replacement, recipient recheck, idempotent revoke, final revocation and timed expiry.')

if __name__ == '__main__':
    verify(sys.argv[1])
