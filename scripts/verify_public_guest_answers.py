"""Only one newly registered synthetic guest. No email, external services or record deletion."""
import asyncio,json
from urllib.parse import urlsplit
from playwright.async_api import async_playwright,expect
from profile_answer_browser_check import check_answers

SITE='https://joinalab.com'
DB='mjpirkyduibkakvlbdko.supabase.co'
NAME='Synthetic conflict check'
async def run():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        session=None
        try:
            for mode in ['raceen','raceen-staggered','racezh','racezh-staggered']:
                lang='zh' if mode.startswith('racezh') else 'en'
                ctx=await browser.new_context(viewport={'width':390,'height':844},locale='zh-CN' if lang=='zh' else 'en-US',service_workers='block')
                await ctx.add_cookies([{'name':'ofe_lang','value':lang,'url':SITE}])
                seed={'ofe_lang':lang,'ofe_onboarding_seen':'1'}
                if session: seed['ofe_auth']=json.dumps(session)
                await ctx.add_init_script("if(location.origin==='https://joinalab.com'&&!localStorage.getItem('profile_qa_init')){for(const [k,v] of Object.entries("+json.dumps(seed)+"))localStorage.setItem(k,v);localStorage.setItem('profile_qa_init','1')}")
                down=False
                headers=None
                outcomes=[]
                def fault(flag):
                    nonlocal down
                    down=flag
                async def guard(route):
                    nonlocal session,headers
                    req=route.request;u=urlsplit(req.url)
                    if u.hostname not in (DB,'joinalab.com'):return await route.abort()
                    if req.method in ('GET','HEAD','OPTIONS'):return await route.continue_()
                    if u.hostname==DB and u.path=='/auth/v1/signup' and req.method=='POST':
                        assert not session and not (req.post_data_json or {}).get('email')
                        resp=await route.fetch()
                        assert resp.status==200
                        session=await resp.json()
                        assert session['user']['is_anonymous'] is True
                        return await route.fulfill(response=resp)
                    if u.hostname==DB and u.path=='/auth/v1/token':return await route.continue_()
                    if u.hostname==DB and u.path.endswith('/rpc/commit_profile_patch_cas') and req.method=='POST':
                        assert session and req.post_data_json['p_expected_device_id']==session['user']['id']
                        headers={k:v for k,v in req.headers.items() if k in ('apikey','authorization')}
                        if down:
                            return await route.fulfill(status=503,headers={'access-control-allow-origin':SITE},json={'message':'controlled local fault; database did not receive this request'})
                        # Keep both browser actions observable; delegate every real response to the production service.
                        await asyncio.sleep(.19)
                        resp=await route.fetch()
                        assert resp.status==200
                        outcome=(await resp.json()).get('status')
                        outcomes.append(outcome)
                        return await route.fulfill(response=resp)
                    if u.hostname=='joinalab.com' and u.path=='/api/events' and req.method=='POST':return await route.continue_()
                    return await route.abort()
                await ctx.route('**/*',guard)
                page=await ctx.new_page()
                page.set_default_timeout(35000)
                await page.goto(SITE+'/',wait_until='domcontentloaded',timeout=60000)
                await page.locator('#student_name').wait_for()
                for _ in range(100):
                    if session and not await page.get_by_test_id('hydration-note').is_visible():break
                    await page.wait_for_timeout(150)
                assert session
                uiuc=page.get_by_test_id('university-card-uiuc')
                if await uiuc.is_visible():
                    await uiuc.click();await page.get_by_test_id('switcher-confirm').click()
                if mode=='raceen':
                    await page.locator('#student_name').fill(NAME)
                    await page.locator('#college').select_option(label='Grainger College of Engineering')
                    await page.locator('#grade').select_option(label='Sophomore')
                else:
                    await expect(page.locator('#student_name')).to_have_value(NAME)
                await page.locator('#major').select_option('Computer Science')
                async def owned_row():
                    if not headers: return {}
                    authorized=await ctx.request.get('https://'+DB+'/rest/v1/profiles?select=profile_data,revision&id=eq.'+session['user']['id'],headers=headers)
                    assert authorized.status==200
                    rows=await authorized.json()
                    return rows[0] if rows else {}
                for _ in range(70):
                    s=await owned_row()
                    if s.get('profile_data',{}).get('major')=='Computer Science':break
                    await page.wait_for_timeout(250)
                assert s.get('profile_data',{}).get('major')=='Computer Science'
                receiver=await ctx.new_page(); receiver.set_default_timeout(35000)
                await receiver.goto(SITE+'/',wait_until='domcontentloaded')
                await expect(receiver.locator('#student_name')).to_have_value(NAME)
                await expect(receiver.locator('#major')).to_have_value('Computer Science')
                await check_answers(mode,page,receiver,outcomes,fault,owned_row,NAME)
                print('PUBLIC RECEIPT',mode,'anonymous principal, both 390px buttons, one CAS write; school and name retained. Revision',(await owned_row())['revision'],flush=True)
                await ctx.close()
        finally:await browser.close()

asyncio.run(run())
