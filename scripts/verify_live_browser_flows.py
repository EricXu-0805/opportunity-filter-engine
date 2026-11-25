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
        session=rpc('/auth/v1/signup',{}); uid=session['user']['id']
        profile={'name':'Synthetic Student','institution':'UC Berkeley','home_school':'ucb','college':'Letters and Science','grade':'Sophomore','major':'Cognitive Science','research_interests':'understanding how memory changes during learning in biological circuits','skills':['Python'],'coursework':[],'seeking_types':['research'],'is_international':False}
        if mode == 'urca':
            profile.update(institution='UC Santa Barbara', home_school='ucsb', major='', research_interests='', skills=[])
        eeb = ['faculty-ucla-eeb-56b5bd06','faculty-ucla-eeb-04fc2f84','faculty-ucla-eeb-792288c6','faculty-ucla-eeb-880b1219','faculty-ucla-eeb-f529eb3c']
        if mode == 'eeb':
            profile.update(institution='UCLA', home_school='ucla', major='Ecology and Evolutionary Biology',research_interests='phylogenetics, evolutionary biology', skills=[])
        auth={'Authorization':'Bearer '+session['access_token']}
        result=rpc('/rest/v1/rpc/commit_profile_patch_cas',{'p_expected_device_id':uid,'p_expected_revision':0,'p_patch':profile},auth);assert result['status']=='applied'
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
            context=await browser.new_context(service_workers='block')
            init="""if(location.hostname==='joinalab.com'&&!localStorage.getItem('oe_receipt_seed')){for(const [k,v] of Object.entries(VALUES))localStorage.setItem(k,v);localStorage.setItem('oe_receipt_seed','1')}"""
            values={'ofe_auth':json.dumps(session),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_profile':json.dumps(profile)}
            await context.add_init_script(init.replace('VALUES',json.dumps(values)))
            fail=True; reads=0; hold=False; blocked=asyncio.Event(); release=asyncio.Event()
            async def intercept(route):
                nonlocal reads
                req=route.request; u=urlsplit(req.url); path=u.path+('?'+u.query if u.query else '')
                cors={'Access-Control-Allow-Origin':'https://joinalab.com','Access-Control-Allow-Credentials':'true','Access-Control-Allow-Headers':req.headers.get('access-control-request-headers','*'),'Access-Control-Allow-Methods':'GET,POST,PATCH,DELETE,HEAD,OPTIONS','Access-Control-Expose-Headers':'Content-Range,Retry-After'}
                if u.hostname=='mjpirkyduibkakvlbdko.supabase.co':
                    if req.method=='OPTIONS':return await route.fulfill(status=204,headers=cors)
                    if mode == 'eeb' and u.path == '/rest/v1/favorites' and req.method == 'GET':
                        return await route.fulfill(status=200,headers={**cors,'Content-Range':'0-4/5'},json=[{'opportunity_id':key} for key in eeb])
                    if mode=='dashboard' and u.path=='/rest/v1/favorites' and req.method=='GET':
                        reads+=1
                        return await route.fulfill(status=503 if fail else 200,headers={**cors,'Retry-After':'0',**({} if fail else {'Content-Range':'0-0/1'})},json={'message':'controlled outage'} if fail else [{'opportunity_id':'saved-target'}])
                    h={'Content-Type':'application/json',**{k:v for k,v in req.headers.items() if k in ('authorization','prefer','accept','range')}}
                    code,ct,body=await asyncio.to_thread(fetch,stub+path,req.post_data_buffer,h,req.method)
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
