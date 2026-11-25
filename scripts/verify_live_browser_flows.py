"""Replay deployed browser behavior with an isolated account. No external messages."""
import asyncio, json, os, subprocess, sys
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect
import urllib.request, urllib.error
stub = "http://127.0.0.1:51432"


def fetch(u, data=None, h=None, method="GET"):
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(u, data=data, headers=h or {}, method=method),
            timeout=24,
        )
    except urllib.error.HTTPError as ex:
        r = ex
    with r:
        return r.status, r.headers.get("Content-Type", "application/json"), r.read()


def rpc(path, data, auth={}):
    return json.loads(
        fetch(
            stub + path,
            json.dumps(data).encode(),
            {"Content-Type": "application/json", **auth},
            "POST",
        )[2]
    )




async def run(mode):
    proc = subprocess.Popen(['node','frontend/e2e/supabase-stub.mjs'],env={**os.environ,'E2E_SUPABASE_PORT':'51432'},stdout=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try: fetch(stub+'/health'); break
            except OSError: await asyncio.sleep(.1)
        session=rpc('/auth/v1/signup',{'email':'m179@example.invalid','password':'local-fixture-only'} if mode.startswith('race') else {}); uid=session['user']['id']
        profile={'name':'Synthetic Student','institution':'UC Berkeley','home_school':'ucb','college':'Letters and Science','grade':'Sophomore','major':'Cognitive Science','research_interests':'understanding how memory changes during learning in biological circuits','skills':['Python'],'coursework':[],'seeking_types':['research'],'is_international':False}
        if mode == 'merged' or mode.startswith('race'):
            profile.update(institution='UIUC',home_school='uiuc',college='Grainger College of Engineering',major='Computer Science',skills=[])
        if mode == 'urca':
            profile.update(institution='UC Santa Barbara', home_school='ucsb', major='', research_interests='', skills=[])
        eeb = ['faculty-ucla-eeb-56b5bd06','faculty-ucla-eeb-04fc2f84','faculty-ucla-eeb-792288c6','faculty-ucla-eeb-880b1219','faculty-ucla-eeb-f529eb3c']
        if mode == 'eeb':
            profile.update(institution='UCLA', home_school='ucla', major='Ecology and Evolutionary Biology',research_interests='phylogenetics, evolutionary biology', skills=[])
        auth={'Authorization':'Bearer '+session['access_token']}
        result=rpc('/rest/v1/rpc/commit_profile_patch_cas',{'p_expected_device_id':uid,'p_expected_revision':0,'p_patch':profile},auth);assert result['status']=='applied'
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
            context=await browser.new_context(service_workers='block',viewport={'width':390 if mode=='racezh' else 1280,'height':900})
            init="""if(location.hostname==='joinalab.com'&&!localStorage.getItem('oe_receipt_seed')){for(const [k,v] of Object.entries(VALUES))localStorage.setItem(k,v);localStorage.setItem('oe_receipt_seed','1')}"""
            values={'ofe_auth':json.dumps(session),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_profile':json.dumps(profile)}
            if mode.startswith('race'):
                values['ofe_lang'] = mode.removeprefix('race')
                await context.set_extra_http_headers({'Accept-Language':values['ofe_lang']})
                if values['ofe_lang'] == 'zh':
                    await context.add_cookies([{'name':'ofe_lang','value':'zh','url':'https://joinalab.com'}])
            if mode == 'merged' or mode.startswith('race'):
                values.pop('ofe_profile')
            await context.add_init_script(init.replace('VALUES',json.dumps(values)))
            fail=True; reads=0; hold=False; blocked=asyncio.Event(); release=asyncio.Event()
            receiver = None
            outage = False
            outcomes = []
            async def intercept(route):
                nonlocal reads
                req=route.request; u=urlsplit(req.url); path=u.path+('?'+u.query if u.query else '')
                cors={'Access-Control-Allow-Origin':'https://joinalab.com','Access-Control-Allow-Credentials':'true','Access-Control-Allow-Headers':req.headers.get('access-control-request-headers','*'),'Access-Control-Allow-Methods':'GET,POST,PATCH,DELETE,HEAD,OPTIONS','Access-Control-Expose-Headers':'Content-Range,Retry-After'}
                if u.hostname=='mjpirkyduibkakvlbdko.supabase.co':
                    if req.method=='OPTIONS':return await route.fulfill(status=204,headers=cors)
                    if mode.startswith('race') and u.path.endswith('/commit_profile_patch_cas'):
                        if outage:
                            return await route.fulfill(status=503,headers=cors,json={'message':'simulated disconnected write'})
                        await asyncio.sleep(.19)
                    if mode == 'merged' and u.path.endswith('/commit_profile_patch_cas') and outage and req.frame.page == receiver:
                        outcomes.append('unavailable')
                        print('Synthetic guest write unavailable',flush=True)
                        return await route.fulfill(status=503,headers=cors,json={'message':'temporary fixture outage'})
                    if mode == 'eeb' and u.path == '/rest/v1/favorites' and req.method == 'GET':
                        return await route.fulfill(status=200,headers={**cors,'Content-Range':'0-4/5'},json=[{'opportunity_id':key} for key in eeb])
                    if mode=='dashboard' and u.path=='/rest/v1/favorites' and req.method=='GET':
                        reads+=1
                        return await route.fulfill(status=503 if fail else 200,headers={**cors,'Retry-After':'0',**({} if fail else {'Content-Range':'0-0/1'})},json={'message':'controlled outage'} if fail else [{'opportunity_id':'saved-target'}])
                    h={'Content-Type':'application/json',**{k:v for k,v in req.headers.items() if k in ('authorization','prefer','accept','range')}}
                    code,ct,body=await asyncio.to_thread(fetch,stub+path,req.post_data_buffer,h,req.method)
                    if (mode == 'merged' or mode.startswith('race')) and u.path.endswith('/commit_profile_patch_cas'):
                        outcomes.append(json.loads(body).get('reason',json.loads(body).get('status')))
                    return await route.fulfill(status=code,body=body,content_type=ct,headers=cors)
                if u.hostname=='joinalab.com':
                    if u.path=='/api/opportunities/batch' and req.method=='POST' and mode=='dashboard':
                        return await route.fulfill(json={'requested':1,'found':0,'opportunities':[]})
                    if u.path=='/api/matches/view' and req.method=='POST' and mode in ('cache','urca','eeb'):
                        print('Real match view requested; holding',hold,flush=True)
                        if hold:
                            blocked.set();await asyncio.wait_for(release.wait(),30)
                        return await route.continue_()
                    if req.method in ('GET','HEAD'):return await route.continue_()
                return await route.abort()
            await context.route('**/*',intercept)
            page=await context.new_page();page.set_default_timeout(45000)
            await page.goto('https://joinalab.com/dashboard',wait_until='domcontentloaded')
            campus=page.get_by_test_id('university-card-'+profile['home_school'])
            try:
                await campus.wait_for(timeout=9000)
            except Exception:
                pass
            if await campus.is_visible():
                await campus.click()
                await page.get_by_test_id('switcher-confirm').click()
                await expect(campus).to_be_hidden(timeout=20000)
                print('Campus confirmed through the deployed campus picker',flush=True)
            if mode=='dashboard':
                await page.goto('https://joinalab.com/dashboard',wait_until='domcontentloaded')
                saved=page.get_by_test_id('saved-summary')
                await expect(saved).to_have_attribute('data-state','error',timeout=45000)
                assert '0' not in (await saved.inner_text())
                await expect(page.get_by_text("Couldn't load your saved deadlines.",exact=True)).to_be_visible()
                await expect(page.get_by_test_id('applied-summary')).to_have_attribute('data-state','ready')
                fail=False;await page.locator('p').filter(has_text="Couldn't load your saved opportunities.").get_by_role('button').click()
                await expect(saved).to_have_attribute('data-state','ready');assert '1' in (await saved.inner_text())
                fail=True;await page.goto('https://joinalab.com/favorites',wait_until='domcontentloaded')
                alert=page.get_by_role('alert').filter(has_text="Couldn't load your favorites")
                await expect(alert).to_be_visible(timeout=45000)
                fail=False;await alert.get_by_role('button').click();await expect(alert).to_have_count(0)
                await expect(page.get_by_text('1 saved',exact=True)).to_be_visible()
                assert reads>=4
                print('PASS deployed Dashboard and Favorites: controlled 503, unknown count, retry, recovered account count 1; reads',reads)
            elif mode.startswith('race'):
                lang = mode.removeprefix('race')
                await page.goto('https://joinalab.com/',wait_until='domcontentloaded')
                receiver = await context.new_page()
                await receiver.goto('https://joinalab.com/',wait_until='domcontentloaded')
                tabs = (page,receiver)
                for tab in tabs:
                    await expect(tab.locator('#major')).to_have_value('Computer Science',timeout=60000)
                outage = True
                await page.locator('#major').select_option('Electrical Engineering')
                await expect(page.get_by_test_id('retry-sync')).to_be_visible(timeout=25000)
                await receiver.locator('#major').select_option('Computer Engineering')
                keep = [tab.get_by_test_id('conflict-keep-mine') for tab in tabs]
                outage = False
                for index,tab in enumerate(tabs):
                    if not await keep[index].is_visible() and await tab.get_by_test_id('retry-sync').is_visible():
                        await tab.get_by_test_id('retry-sync').click()
                for index,tab in enumerate(tabs):
                    await expect(keep[index]).to_be_visible(timeout=30000)
                    expected = 'Changed somewhere else' if lang == 'en' else '在别处改过了'
                    await expect(tab.get_by_text(expected,exact=False)).to_be_visible()
                    if lang == 'zh':
                        dims=await keep[index].evaluate("(b)=>({width:innerWidth,height:b.getBoundingClientRect().height,line:parseFloat(getComputedStyle(b).lineHeight),pad:parseFloat(getComputedStyle(b).paddingTop)+parseFloat(getComputedStyle(b).paddingBottom)})")
                        assert dims['width'] == 390 and dims['height']-dims['pad'] <= dims['line']*2+3,dims
                    await tab.evaluate("""() => {window.receiptViews=[];new MutationObserver(()=>{
                        const s = document.querySelector('[data-testid="conflict-stale"]');
                        const retry=document.querySelector('[data-testid="retry-sync"]');
                        const failed=/Saved on this device only|仅保存在本设备|没能同步/.test(document.body.innerText);
                        if(s || retry || failed) window.receiptViews.push({stale:!!s,retry:!!retry,failed});
                    }).observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true});}""")
                outcomes.clear()
                await asyncio.gather(*(button.click(timeout=3000,force=True) for button in keep))
                for button in keep:
                    await expect(button).to_have_count(0,timeout=15000)
                await asyncio.sleep(2)
                views=[await tab.evaluate("window.receiptViews") for tab in tabs]
                saved=json.loads(fetch(stub+'/rest/v1/profiles?select=profile_data,revision&id=eq.'+uid,h=auth)[2])[0]
                major=saved['profile_data']['major']
                for tab in tabs:
                    await expect(tab.locator('#major')).to_have_value(major)
                print('Concurrent answers',lang,major,'write outcomes',outcomes,'observed stale/retry/failure', [[any(v[k] for v in vs) for k in ('stale','retry','failed')] for vs in views],flush=True)
                assert outcomes == ['applied'] and any(any(v['stale'] for v in vs) for vs in views)
                assert not any(v['retry'] or v['failed'] for vs in views for v in vs)
                await receiver.reload(wait_until='domcontentloaded')
                await expect(receiver.locator('#major')).to_have_value(major,timeout=45000)
                print('PASS double Keep, both tabs and reopened form agree, one account write;',lang,flush=True)
            elif mode == 'merged':
                import hashlib
                origin = 'https://joinalab.com/'
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
                proof = 'M138 isolated guest transfer'
                grant = rpc('/rest/v1/rpc/mint_merge_grant',{'p_secret_hash':hashlib.sha256(proof.encode()).hexdigest()},auth)
                dest = rpc('/auth/v1/signup',{'email':'m138@example.invalid','password':'local-only-fixture'})
                moved = rpc('/rest/v1/rpc/redeem_merge_grant',{'p_token':grant,'p_secret':proof},{'Authorization':'Bearer '+dest['access_token']})
                assert moved.get('merged') is True
                await page.locator('#grade').select_option('Senior')
                stale = 'This profile no longer exists in your account, so nothing is being saved.'
                for tab in (page,receiver):
                    await expect(tab.get_by_text(stale,exact=False)).to_be_visible(timeout=35000)
                    await expect(tab.get_by_test_id('retry-sync')).to_have_count(0)
                    await expect(tab.get_by_text('Profile saved',exact=True)).to_have_count(0)
                await expect(receiver.locator('#student_name')).to_have_value('Synthetic retained edit')
                assert 'merged_away' in outcomes and 'unavailable' in outcomes, outcomes
                print('PASS deployed two-tab guest merge, failed edit retained, both stale, neither offered retry or claimed saved:',outcomes)
            elif mode in ('urca','eeb'):
                async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/matches/view' and r.request.method == 'POST' and r.status == 200, timeout=80000) as data:
                    target_tab = 'all' if mode == 'urca' else 'starred'
                    await page.goto('https://joinalab.com/results?tab='+target_tab,wait_until='domcontentloaded')
                payload = await (await data.value).json()
                matches = {r['opportunity_id']: r for r in payload['results']}
                if mode == 'eeb' and not all(key in matches for key in eeb):
                    async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/matches/view' and r.request.method == 'POST' and r.status == 200 and bool(r.request.post_data_json.get('view',{}).get('favorite_ids')), timeout=60000) as targeted:
                        await page.reload(wait_until='domcontentloaded')
                    matches = {r['opportunity_id']:r for r in (await (await targeted.value).json())['results']}
                print('Public response',mode,len(matches), list(matches)[:3],flush=True)
                projects = page.locator('[id^="match-card-ucsb-urca-proj-"]' if mode == 'urca' else ','.join('#match-card-'+key for key in eeb))
                await projects.first.wait_for(timeout=80000)
                count = min(8, await projects.count())
                assert count >= (3 if mode == 'urca' else 5), count
                seen = []
                reasons = 0
                for index in range(count):
                    card = projects.nth(index)
                    await card.get_by_role('button', name='Show details').click()
                    await expect(card.get_by_role('button', name='Hide details')).to_be_visible()
                    text = (await card.inner_text()).lower()
                    assert 'this lab focuses on' not in text and 'urca undergraduate research directory' not in text
                    lists = await card.locator('h4 + ul li').all_inner_texts()
                    assert lists, await card.get_attribute('id')
                    key = (await card.get_attribute('id')).removeprefix('match-card-')
                    row = matches[key]
                    if mode == 'urca':
                        assert row['opportunity']['source'] == 'ucsb_urca_projects'
                        assert not any(reason and reason['key'] in ('lab_focus','research_summary') for reason in row['reasons_fit_keys'])
                    else:
                        assert key in eeb and "'s focus area" not in text
                        assert not any(reason and reason['key'] == 'interests_lab_focus' for reason in row['reasons_fit_keys'])
                    assert row['reasons_fit'] and all(reason.lower() in text for reason in row['reasons_fit'])
                    reasons += len(row['reasons_fit'])
                    seen.append(await card.get_attribute('id'))
                print('PASS expanded real cards', mode, count, 'displayed lines', reasons, 'public ids', seen)
            else:
                await page.goto('https://joinalab.com/results',wait_until='domcontentloaded')
                try:
                    await page.locator('[id^="match-card-"]').first.wait_for(timeout=80000)
                except Exception:
                    print('Results surface:',page.url,(await page.locator('body').inner_text())[:850],flush=True)
                    raise
                for _ in range(20):
                    state=await context.storage_state()
                    item=next((row for site in state['origins'] if site['origin']=='https://joinalab.com'
                               for row in site['localStorage'] if row['name']=='ofe_match_results_v7'),None)
                    if item is not None:break
                    await asyncio.sleep(.25)
                assert item is not None, 'fresh account did not store a match page'
                cached=json.loads(item['value']);snapshot=len(cached['results']);assert snapshot>0
                for row in cached['results']:
                    row['opportunity']['title']='M188 previous browser-only result'
                    row['reasons_fit']=['Your interest in memory closely matches the old cached result']
                cached['matcher_version']='40-old';item['value']=json.dumps(cached)
                await context.close();hold=True
                context=await browser.new_context(storage_state=state,service_workers='block')
                await context.route('**/*',intercept)
                await context.add_init_script("""new MutationObserver(()=>{if(document.body?.innerText.includes('M188 previous browser-only result'))document.documentElement.dataset.oldMatchPainted='yes'}).observe(document,{subtree:true,childList:true,characterData:true});""")
                page=await context.new_page()
                await page.goto('https://joinalab.com/results',wait_until='domcontentloaded')
                await asyncio.wait_for(blocked.wait(),35)
                assert await page.locator('[id^="match-card-"]').count()==0
                assert await page.locator('html').get_attribute('data-old-match-painted') is None
                release.set();await page.locator('[id^="match-card-"]').first.wait_for(timeout=65000)
                assert await page.locator('html').get_attribute('data-old-match-painted') is None
                assert not await page.get_by_text('M188 previous browser-only result',exact=True).count()
                print('PASS',snapshot,'old cached matches retained while real response withheld, none painted; fresh cards then displayed.')
            await browser.close()
    finally:
        proc.terminate();proc.wait()
asyncio.run(run(sys.argv[1]))
if sys.argv[1] == 'cache':
    asyncio.run(run('urca'))
    asyncio.run(run('eeb'))

if sys.argv[1] == 'dashboard':
    asyncio.run(run('merged'))

if sys.argv[1] == 'dashboard':
    asyncio.run(run('raceen'))
    asyncio.run(run('racezh'))
