"""Exercise the deployed commit against an isolated real Supabase instance.""" 
import asyncio, json, os, sys, uuid
from urllib import request, error
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

api = 'http://127.0.0.1:54321'
site = 'http://127.0.0.1:3100/'
config = json.load(open(sys.argv[1]))
assert config['API_URL'] == api
key = config['ANON_KEY']
def req(path, data=None, auth=None):
    r=request.Request(api+path, data=None if data is None else json.dumps(data).encode(),
        headers={'apikey':key, 'Content-Type':'application/json',**(auth or {})})
    try:
        with request.urlopen(r, timeout=15) as v: return json.load(v)
    except error.HTTPError as exc:
        raise RuntimeError((path.split('?')[0],exc.code,exc.read().decode()[:270])) from None
rpc=req
def new_credentials():
    return {'email':str(uuid.uuid4())+'@example.com','password':uuid.uuid4().hex+'Ab3!'}

async def scenario(browser,mode):
    initial = {} if mode=='merged' else new_credentials()
    session=rpc('/auth/v1/signup',initial)
    uid=session['user']['id']
    assert bool(session['user'].get('is_anonymous'))==(mode=='merged')
    auth={'Authorization':'Bearer '+session['access_token']}
    profile={'name':'Synthetic Student','home_school':'uiuc','search_weight':50,'additional_majors':[],
        'experience_entries':[{'id':'prior-independent-entry','revision':1,'status':'confirmed',
        'text':'I recorded an independent control measurement.','source':{'kind':'manual'}}],
        'resume_master':None,'institution':'UIUC - University of Illinois Urbana-Champaign','college':'Grainger College of Engineering',
        'grade':'Sophomore','major':'Computer Science','research_interests':'computing','skills':[],'coursework':[],
        'seeking_types':['research'],'is_international':False}
    result=rpc('/rest/v1/rpc/commit_profile_patch_cas',{'p_expected_device_id':uid,'p_expected_revision':0,'p_patch':profile},auth)
    assert result['status']=='applied' and result['revision']==1,result['status']
    def stored_row():
        return req('/rest/v1/profiles?select=profile_data,revision&id=eq.'+uid,auth=auth)[0]
    lang='zh' if mode.startswith('racezh') else 'en'
    context=await browser.new_context(service_workers='block',viewport={'width':390,'height':844},locale='zh-CN' if lang=='zh' else 'en-US')
    await context.add_cookies([{'name':'ofe_lang','value':lang,'url':site}])
    values={'ofe_auth':json.dumps(session),'ofe_lang':lang,'ofe_onboarding_seen':'1',
        'ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T08:00:00Z'})}
    await context.add_init_script("if(location.hostname==='127.0.0.1'&&!localStorage.getItem('qa_started')){for(const [k,v] of Object.entries("+json.dumps(values)+"))localStorage.setItem(k,v);localStorage.setItem('qa_started','1')}")
    outage=False
    receiver=None
    outcomes=[]
    async def intercept(route):
        req0=route.request; u=urlsplit(req0.url)
        if u.hostname not in ('127.0.0.1','localhost'): return await route.abort()
        if u.path.endswith('/rpc/commit_profile_patch_cas') and req0.method=='POST':
            if outage and (mode!='merged' or req0.frame.page==receiver):
                outcomes.append('unavailable')
                return await route.fulfill(status=503,headers={'access-control-allow-origin':'*'},json={'message':'temporary simulated network outage'})
            if not mode=='merged': await asyncio.sleep(.19)
            response=await route.fetch()
            assert response.status==200,(response.status,await response.text())
            body=await response.json()
            outcomes.append(body.get('reason') or body['status'])
            return await route.fulfill(response=response)
        return await route.continue_()
    await context.route('**/*',intercept)
    page=await context.new_page()
    page.set_default_timeout(45000)
    if mode.startswith('race'):
        lang = mode.removeprefix('race').split('-')[0]
        await page.goto(site,wait_until='domcontentloaded')
        if '-resume-' in mode:
            blank=await browser.new_page()
            await blank.set_content('<p>Research assistant</p><p>I checked synthetic sensor measurements.</p><p>Coursework: ECE 220</p>')
            pdf=await blank.pdf()
            await blank.close()
            await page.locator('input[type=file][accept*="pdf"]').first.set_input_files({
                'name':'synthetic-old-resume.pdf','mimeType':'application/pdf','buffer':pdf})
            await expect(page.get_by_role('button',name='Remove file' if lang=='en' else '移除文件',exact=True)).to_be_visible(timeout=60000)
            for _ in range(100):
                before=stored_row()
                if 'synthetic sensor measurements' in (before['profile_data'].get('resume_text') or ''):break
                await asyncio.sleep(.3)
            assert 'synthetic sensor measurements' in before['profile_data']['resume_text']
            assert '220' in str(before['profile_data']['coursework']),before['profile_data']['coursework']
            print('Original PDF uploaded through the product parser, confirmed by separate SQL-backed PostgREST read, rev',before['revision'])
        receiver = await context.new_page()
        await receiver.goto(site,wait_until='domcontentloaded')
        tabs = (page,receiver)
        for tab in tabs:
            await tab.bring_to_front()
            await expect(tab.locator('#student_name')).to_have_value(profile['name'],timeout=45000)
            campus_picker = tab.get_by_test_id('university-card-uiuc')
            if await campus_picker.is_visible():
                await campus_picker.click()
                await tab.get_by_test_id('switcher-confirm').click()
                await expect(campus_picker).to_be_hidden(timeout=15000)
            await expect(tab.locator('#major')).to_have_value('Computer Science',timeout=60000)
        if '-resume-' in mode:
            remove = receiver.get_by_role('button', name='Remove file' if lang == 'en' else '移除文件', exact=True)
            await expect(remove).to_be_visible(timeout=30000)
            note = 'I independently checked the second sensor sample.'
            editor = page.locator('#experience-library details').last
            await page.bring_to_front()
            if not await editor.locator('textarea').is_visible():
                await editor.locator('summary').click()
            await expect(editor.locator('textarea')).to_be_visible()
            await context.set_offline(True)
            if not await editor.locator('textarea').is_visible():
                await editor.locator('summary').click()
            outage = True
            await editor.locator('textarea').fill(note)
            await editor.get_by_role('button').click()
            await expect(page.locator('#experience-library summary').get_by_text(note,exact=True)).to_be_visible(timeout=15000)
            await remove.click()
            await expect(remove).to_be_hidden(timeout=15000)
            await context.set_offline(False)
            outage = False
            choices = [tab.get_by_test_id('conflict-keep-mine') for tab in tabs]
            for index,tab in enumerate(tabs):
                await tab.bring_to_front()
                retry = tab.get_by_test_id('retry-sync')
                if not await choices[index].is_visible() and await retry.is_visible():
                    await retry.click(timeout=2000)
            answer_tab = receiver if mode.endswith('keep') else page
            answer = answer_tab.get_by_test_id('conflict-keep-mine' if mode.endswith('keep') else 'conflict-use-cloud')
            print('Resume choices before first answer',mode,[(await t.locator('#profile-save-status').inner_text()) for t in tabs],flush=True)
            await expect(answer).to_be_visible(timeout=20000)
            await answer.click()
            for q in choices:
                await expect(q).to_have_count(0,timeout=20000)
            def saved_resume():
                return stored_row()
            stored=saved_resume(); data=stored['profile_data']
            assert data['name']==profile['name']
            assert any(x.get('id')=='prior-independent-entry' for x in data['experience_entries'])
            if mode.endswith('keep'):
                assert not data.get('resume_text'),data.get('resume_text')
            else:
                assert data.get('resume_text') == before['profile_data']['resume_text'] and data.get('coursework')==before['profile_data']['coursework']
            if '-followup-' in mode:
                # Leave both forms mounted. An edit from the other tab must use the
                # chosen resume, even before a navigation can reload the account.
                other_tab = page if answer_tab is receiver else receiver
                await other_tab.bring_to_front()
                button = other_tab.get_by_role('button',name='Remove file' if lang=='en' else '移除文件',exact=True)
                await asyncio.sleep(2)
                painted_resume = await button.is_visible()
                print('Resume before independent edit', mode, 'account', bool(data.get('resume_text')),
                      'other tab displays attachment', painted_resume, flush=True)
                follow = other_tab.locator('#experience-library details').last
                if not await follow.locator('textarea').is_visible():
                    await follow.locator('summary').click()
                new_note = 'I repeated the independent control measurement.'
                await follow.locator('textarea').fill(new_note)
                await follow.get_by_role('button').click()
                await expect(other_tab.locator('#experience-library summary').get_by_text(new_note,exact=True)).to_be_visible()
                for _ in range(60):
                    after = saved_resume()
                    if any(x.get('text')==new_note for x in after['profile_data'].get('experience_entries',[])):
                        break
                    await asyncio.sleep(.25)
                assert any(x.get('text')==new_note for x in after['profile_data']['experience_entries'])
                assert after['profile_data'].get('resume_text')==data.get('resume_text')
                assert after['profile_data'].get('coursework')==data.get('coursework')
                assert after['revision']>stored['revision']
                print('PASS other tab follow-up before reload',mode,'old revision',stored['revision'],
                      'new revision',after['revision'],'resume retained',bool(data.get('resume_text')),
                      'unchanged coursework',after['profile_data'].get('coursework'),flush=True)
                assert painted_resume==bool(data.get('resume_text')), 'Peer still displays the superseded attachment state'
                stored=after
                data=after['profile_data']
            for tab in tabs:
                await tab.reload(wait_until='domcontentloaded')
                await expect(tab.locator('#student_name')).to_have_value(profile['name'],timeout=35000)
                await expect(tab.get_by_test_id('conflict-keep-mine')).to_have_count(0)
                removed = tab.get_by_role('button',name='Remove file' if lang=='en' else '移除文件',exact=True)
                if data.get('resume_text'):
                    await expect(removed).to_be_visible()
                else:
                    await expect(removed).to_have_count(0)
            assert saved_resume()==stored
            print('PASS resume removal and concurrent experience edit, one answer, two reloads', mode,
                  'revision',stored['revision'],'stored resume',bool(data.get('resume_text')),
                  'experience count',len(data['experience_entries']),flush=True)
            await context.close()
            return
        from profile_answer_browser_check import check_answers
        def fail(flag):
            nonlocal outage
            outage=flag
        async def read_row(): return stored_row()
        await check_answers(mode,page,receiver,outcomes,fail,read_row,profile['name'])
    else:
        import hashlib
        origin = site
        await page.goto(origin,wait_until='domcontentloaded')
        receiver = await context.new_page()
        await receiver.goto(origin,wait_until='domcontentloaded')
        for tab in (page,receiver):
            await expect(tab.locator('#student_name')).to_have_value(profile['name'],timeout=45000)
            await expect(tab.locator('#grade')).to_have_value('Sophomore')
        outage = True
        await receiver.locator('#student_name').fill('Synthetic retained edit')
        await receiver.locator('#student_name').press('Tab')
        try:
            await expect(receiver.get_by_text('Saved on this device only',exact=False)).to_be_visible(timeout=25000)
        except AssertionError:
            print('Receiver save states',outcomes,(await receiver.locator('body').inner_text())[-1300:],flush=True)
            raise
        proof = uuid.uuid4().hex + uuid.uuid4().hex
        grant = rpc('/rest/v1/rpc/mint_merge_grant',{'p_target_email':None,'p_secret_hash':hashlib.sha256(proof.encode()).hexdigest()},auth)
        dest = rpc('/auth/v1/signup',new_credentials())
        moved = rpc('/rest/v1/rpc/redeem_merge_grant',{'p_token':grant,'p_secret':proof},{'Authorization':'Bearer '+dest['access_token']})
        assert moved.get('merged') is True, {k:v for k,v in moved.items() if isinstance(v,bool)}
        print('Distinct Auth sessions merged; true PostgREST RPC succeeded and old account is anonymous')
        await page.locator('#grade').select_option('Senior')
        stale = 'This profile no longer exists in your account, so nothing is being saved.'
        for tab in (page,receiver):
            await expect(tab.get_by_text(stale,exact=False)).to_be_visible(timeout=35000)
            await expect(tab.get_by_test_id('retry-sync')).to_have_count(0)
            await expect(tab.get_by_text('Profile saved',exact=True)).to_have_count(0)
        await expect(receiver.locator('#student_name')).to_have_value('Synthetic retained edit')
        assert 'merged_away' in outcomes and 'unavailable' in outcomes, outcomes
        print('PASS isolated database two-tab guest merge, failed edit retained, both stale, neither offered retry or claimed saved:',outcomes)

    await context.close()

async def main():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            await scenario(browser,sys.argv[2])
        finally:
            await browser.close()
asyncio.run(main())
