"""Drive the production import form with one newly registered anonymous QA visitor."""
import asyncio
import json
from urllib.parse import urlsplit, parse_qs

from playwright.async_api import async_playwright, expect

SITE = 'https://joinalab.com'
DB = 'https://mjpirkyduibkakvlbdko.supabase.co'
PROFILE = '/rest/v1/profiles'
CAS = '/rest/v1/rpc/commit_profile_patch_cas'
IMPORT = '/api/resume/github/pytorch'
OLD = {'name':'PyTorch','level':'experienced','source':'github'}
ADDED = {'name':'Git','level':'expert','confirmed':True}

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox','--disable-dev-shm-usage'])
        session = None
        key = None
        conflict_report = []
        imported = []
        raw_reads = []
        allow_signup = True
        sql_headers = {}
        second_client = None
        seed_revision = None

        async def session_gate(route, mode):
            nonlocal session, key, allow_signup, seed_revision
            req = route.request
            u = urlsplit(req.url)
            if u.hostname not in (urlsplit(DB).hostname,urlsplit(SITE).hostname):
                return await route.abort()
            if req.method in ('GET','HEAD','OPTIONS'):
                if u.path==IMPORT and req.method=='GET':
                    r = await route.fetch()
                    body = await r.json()
                    assert r.status==200, (r.status, body.get('detail'))
                    hits=[item for item in body['skill_evidence'] if item['skill']=='PyTorch']
                    assert hits
                    imported.extend(hits)
                    return await route.fulfill(response=r)
                if u.path==PROFILE and req.method=='GET' and mode=='read':
                    assert session and parse_qs(u.query).get('id')==['eq.'+session['user']['id']]
                    r=await route.fetch()
                    assert r.status==200
                    a=await r.json()
                    raw_reads.extend(a if isinstance(a,list) else [a])
                    return await route.fulfill(response=r)
                return await route.continue_()
            if u.hostname==urlsplit(SITE).hostname and u.path=='/api/events' and req.method=='POST':
                return await route.continue_()
            if u.hostname!=urlsplit(DB).hostname:
                return await route.abort()
            if u.path=='/auth/v1/signup':
                assert mode=='registration' and allow_signup and not session and not (req.post_data_json or {}).get('email')
                allow_signup=False
                resp=await route.fetch()
                assert resp.status==200
                tmp=await resp.json()
                assert tmp['user']['is_anonymous'] is True
                session=tmp
                key=req.headers['apikey']
                return await route.fulfill(response=resp)
            if u.path=='/auth/v1/token':
                return await route.continue_()
            if u.path==CAS and req.method=='POST':
                assert session and req.post_data_json['p_expected_device_id']==session['user']['id']
                if mode!='form':
                    return await route.abort()
                patch=req.post_data_json['p_patch']
                assert 'skills' in patch
                if not conflict_report:
                    assert imported and any(x['name']=='PyTorch' and x.get('evidence') for x in patch['skills'])
                    result=await apply(second_client,seed_revision,{'skills':[OLD,ADDED]})
                    assert result['status']=='applied' and result['revision']==seed_revision+1
                response=await route.fetch()
                data=await response.json()
                assert response.status==200
                conflict_report.append((req.post_data_json['p_expected_revision'],data['status'],data['revision']))
                print('Production form CAS:',conflict_report[-1],flush=True)
                return await route.fulfill(response=response)
            return await route.abort()

        async def context(mode):
            c=await browser.new_context(service_workers='block',locale='en-US')
            settings={'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
            if mode!='registration':
                assert session
                settings['ofe_auth']=json.dumps(session)
            await c.add_init_script("if(location.origin==='https://joinalab.com'&&!localStorage.getItem('m212_qa')){for(const [k,v] of Object.entries("+json.dumps(settings)+"))localStorage.setItem(k,v);localStorage.setItem('m212_qa','1')}")
            await c.route('**/*', lambda route:session_gate(route,mode))
            return c

        async def apply(client, revision, patch):
            assert session['user']['is_anonymous'] is True and sql_headers['Authorization']=='Bearer '+session['access_token']
            res=await client.post(DB+CAS,headers=sql_headers,data={'p_expected_device_id':session['user']['id'],'p_expected_revision':revision,'p_patch':patch})
            data=await res.json()
            assert res.status==200,(res.status,data.get('code'))
            return data

        async def own_row(client):
            target=DB+PROFILE+'?select=profile_data,revision&id=eq.'+session['user']['id']
            r=await client.get(target,headers=sql_headers)
            assert r.status==200
            rows=await r.json()
            assert len(rows)<=1
            return rows[0] if rows else None

        registration=await context('registration')
        page=await registration.new_page()
        await page.goto(SITE+'/',wait_until='domcontentloaded')
        for _ in range(200):
            if session:break
            await asyncio.sleep(.1)
        assert session and key
        sql_headers={'apikey':key,'Authorization':'Bearer '+session['access_token']}
        await registration.close()
        second=await context('read')
        second_client=second.request
        assert not await own_row(second_client),'the new QA visitor must start with empty storage'
        profile={
            'name':'Synthetic M212 evidence QA','home_school':'uiuc','search_weight':50,'additional_majors':[],
            'experience_entries':[],'resume_master':None,'institution':'UIUC - University of Illinois Urbana-Champaign',
            'college':'Grainger College of Engineering','grade':'Sophomore','major':'Computer Science',
            'research_interests':'computing','github_url':'https://github.com/pytorch','skills':[OLD],
            'coursework':[],'seeking_types':['research'],'is_international':False
        }
        seed=await apply(second_client,0,profile)
        assert seed['status']=='applied' and seed['revision']==1
        seed_revision=seed['revision']
        first=await context('form')
        form=await first.new_page()
        await form.goto(SITE+'/',wait_until='domcontentloaded')
        await expect(form.get_by_role('button',name='Keep this level for PyTorch (Experienced)')).to_be_visible(timeout=45000)
        await expect(form.locator('#github_url')).to_have_value(profile['github_url'])
        await form.locator('#github_url').locator('..').get_by_role('button').click()
        for _ in range(300):
            if len(conflict_report)>=2:break
            await asyncio.sleep(.1)
        assert conflict_report==[(1,'conflict',2),(2,'applied',3)],conflict_report
        await first.close()
        fresh=await context('read')
        reopened=await fresh.new_page()
        await reopened.goto(SITE+'/',wait_until='domcontentloaded')
        await expect(reopened.get_by_role('button',name='Keep this level for PyTorch (Experienced)')).to_be_visible(timeout=45000)
        await expect(reopened.get_by_role('button',name='Remove Git',exact=True)).to_be_visible()
        proof=imported[0]
        source=next(x for x in (await own_row(second_client))['profile_data']['skills'] if x['name']=='PyTorch')
        assert source==dict(OLD,evidence='repo '+proof['repo']+': '+proof['field']+' '+proof['value']),source
        await expect(reopened.locator('summary').filter(has_text='repo '+proof['repo']+', '+proof['field']+' '+proof['value']).first).to_be_visible()
        read=await own_row(second_client)
        assert read['revision']==3
        assert any(r['revision']==3 and r['profile_data']==read['profile_data'] for r in raw_reads)
        assert ADDED in read['profile_data']['skills']
        assert read['profile_data']['name']==profile['name']
        print('PUBLIC RECEIPT',json.dumps({'site':SITE,'official_import':IMPORT,'anonymous_first_party_session':True,'legacy_only_seed':[OLD],
          'independent_edit':ADDED,'server_cas':conflict_report,'cold_context_revision':3,'separate_own_row_revision':3,'persisted_source':source,
          'confirmed_level_unchanged':True,'new_browser_showed_legacy_level_git_and_real_repository':True}),flush=True)
        await browser.close()

asyncio.run(main())
