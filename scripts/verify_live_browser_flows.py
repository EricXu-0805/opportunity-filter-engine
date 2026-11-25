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
        profile={'name':'Synthetic Student','institution':'UC Berkeley','college':'Letters and Science','grade':'Sophomore','major':'Cognitive Science','research_interests':'understanding how memory changes during learning in biological circuits','skills':['Python'],'coursework':[],'seeking_types':['research'],'is_international':False}
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
                    if mode=='dashboard' and u.path=='/rest/v1/favorites' and req.method=='GET':
                        reads+=1
                        return await route.fulfill(status=503 if fail else 200,headers={**cors,'Retry-After':'0',**({} if fail else {'Content-Range':'0-0/1'})},json={'message':'controlled outage'} if fail else [{'opportunity_id':'saved-target'}])
                    h={'Content-Type':'application/json',**{k:v for k,v in req.headers.items() if k in ('authorization','prefer','accept','range')}}
                    code,ct,body=await asyncio.to_thread(fetch,stub+path,req.post_data_buffer,h,req.method)
                    return await route.fulfill(status=code,body=body,content_type=ct,headers=cors)
                if u.hostname=='joinalab.com':
                    if u.path=='/api/opportunities/batch' and req.method=='POST' and mode=='dashboard':
                        return await route.fulfill(json={'requested':1,'found':0,'opportunities':[]})
                    if u.path=='/api/matches/view' and req.method=='POST' and mode=='cache':
                        if hold:
                            blocked.set();await asyncio.wait_for(release.wait(),30)
                        return await route.continue_()
                    if req.method in ('GET','HEAD'):return await route.continue_()
                return await route.abort()
            await context.route('**/*',intercept)
            page=await context.new_page();page.set_default_timeout(45000)
            if mode=='dashboard':
                await page.goto('https://joinalab.com/dashboard',wait_until='domcontentloaded')
                saved=page.get_by_test_id('saved-summary')
                await expect(saved).to_have_attribute('data-state','error',timeout=45000)
                assert '0' not in (await saved.inner_text())
                await expect(page.get_by_text("Couldn't load your saved deadlines.",exact=True)).to_be_visible()
                await expect(page.get_by_test_id('applied-summary')).to_have_attribute('data-state','ready')
                fail=False;await page.get_by_text("Couldn't load your saved opportunities.",exact=True).locator('..').get_by_role('button').click()
                await expect(saved).to_have_attribute('data-state','ready');assert '1' in (await saved.inner_text())
                fail=True;await page.goto('https://joinalab.com/favorites',wait_until='domcontentloaded')
                alert=page.get_by_role('alert').filter(has_text="Couldn't load your favorites")
                await expect(alert).to_be_visible(timeout=45000)
                fail=False;await alert.get_by_role('button').click();await expect(alert).to_have_count(0)
                await expect(page.get_by_text('1 saved',exact=True)).to_be_visible()
                assert reads>=4
                print('PASS deployed Dashboard and Favorites: controlled 503, unknown count, retry, recovered account count 1; reads',reads)
            else:
                await page.goto('https://joinalab.com/results',wait_until='domcontentloaded')
                await page.wait_for_function("JSON.parse(localStorage.getItem('ofe_match_results_v7')||'{}').results?.length > 0",timeout=80000)
                snapshot=await page.evaluate("""()=>{const key='ofe_match_results_v7';const c=JSON.parse(localStorage.getItem(key));const n=c.results.length;for(const r of c.results){r.opportunity.title='M188 previous browser-only result';r.reasons_fit=['Your interest in memory closely matches the old cached result'];}c.matcher_version='40-old';localStorage.setItem(key,JSON.stringify(c));return n}""")
                await page.add_init_script("""window.oldMatchPainted=false;new MutationObserver(()=>{if(document.body?.innerText.includes('M188 previous browser-only result'))window.oldMatchPainted=true}).observe(document,{subtree:true,childList:true,characterData:true});""")
                hold=True
                await page.reload(wait_until='domcontentloaded')
                await asyncio.wait_for(blocked.wait(),35)
                assert await page.locator('[id^="match-card-"]').count()==0
                assert not await page.evaluate('window.oldMatchPainted')
                release.set();await page.locator('[id^="match-card-"]').first.wait_for(timeout=65000)
                assert not await page.evaluate('window.oldMatchPainted')
                assert not await page.get_by_text('M188 previous browser-only result',exact=True).count()
                print('PASS',snapshot,'old cached matches retained while real response withheld, none painted; fresh cards then displayed.')
            await browser.close()
    finally:
        proc.terminate();proc.wait()
asyncio.run(run(sys.argv[1]))
