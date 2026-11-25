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
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(f'Isolated account service exited with {proc.returncode}')
            try:
                fetch(stub + '/health')
                break
            except OSError:
                await asyncio.sleep(.25)
        else:
            raise RuntimeError('Isolated account service not ready after 30 seconds')
        print('Isolated account service ready:',mode,flush=True)
        session=rpc('/auth/v1/signup',{'email':'m179@example.invalid','password':'local-fixture-only'} if mode.startswith('race') else {}); uid=session['user']['id']
        profile={'name':'Synthetic Student','institution':'UC Berkeley','home_school':'ucb','college':'Letters and Science','grade':'Sophomore','major':'Cognitive Science','research_interests':'understanding how memory changes during learning in biological circuits','skills':['Python'],'coursework':[],'seeking_types':['research'],'is_international':False}
        if mode == 'merged' or mode.startswith('race'):
            profile.update(institution='UIUC',home_school='uiuc',college='Grainger College of Engineering',major='Computer Science',skills=[])
        if '-resume-' in mode:
            profile.update(resume_text='Earlier resume: I checked sensor measurements.',
                           coursework=['ECE 220'], experience_entries=[{
                               'id':'prior-independent-entry','revision':1,'status':'confirmed',
                               'text':'I recorded an independent control measurement.',
                               'source':{'kind':'manual'}}])
        listing = mode in ('listingen', 'listingzh')
        error_page = mode in ('erroren', 'errorzh')
        listing_id = 'purdue-2d597d3a3d77'
        if listing:
            profile.update(institution='Purdue University', home_school='purdue', major='English', grade='Freshman',
                           research_interests='history', college='', seeking_types=['research','summer_program'])
        if mode == 'urca':
            profile.update(institution='UC Santa Barbara', home_school='ucsb', major='', research_interests='', skills=[])
        eeb = ['faculty-ucla-eeb-56b5bd06','faculty-ucla-eeb-04fc2f84','faculty-ucla-eeb-792288c6','faculty-ucla-eeb-880b1219','faculty-ucla-eeb-f529eb3c']
        if mode == 'eeb':
            profile.update(institution='UCLA', home_school='ucla', major='Ecology and Evolutionary Biology',research_interests='phylogenetics, evolutionary biology', skills=[])
        auth={'Authorization':'Bearer '+session['access_token']}
        result=rpc('/rest/v1/rpc/commit_profile_patch_cas',{'p_expected_device_id':uid,'p_expected_revision':0,'p_patch':profile},auth);assert result['status']=='applied'
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
            context=await browser.new_context(service_workers='block',viewport={'width':390 if mode.startswith('racezh') or mode in ('listingzh','errorzh') else 1280,'height':900})
            init="""if(location.hostname==='joinalab.com'&&!localStorage.getItem('oe_receipt_seed')){for(const [k,v] of Object.entries(VALUES))localStorage.setItem(k,v);localStorage.setItem('oe_receipt_seed','1')}"""
            values={'ofe_auth':json.dumps(session),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_profile':json.dumps(profile)}
            if mode.startswith('race') or listing or error_page:
                values['ofe_lang'] = mode[-2:] if listing or error_page else mode.removeprefix('race').split('-')[0]
                await context.set_extra_http_headers({'Accept-Language':values['ofe_lang']})
                if values['ofe_lang'] == 'zh':
                    await context.add_cookies([{'name':'ofe_lang','value':'zh','url':'https://joinalab.com'}])
            if mode == 'merged' or mode.startswith('race'):
                values.pop('ofe_profile')
            await context.add_init_script(init.replace('VALUES',json.dumps(values)))
            fail=True; reads=0; hold=False; blocked=asyncio.Event(); release=asyncio.Event()
            receiver = None
            failed_assets = []
            blocked_assets = set()
            outage = False
            outcomes = []
            async def intercept(route):
                nonlocal reads
                req=route.request; u=urlsplit(req.url); path=u.path+('?'+u.query if u.query else '')
                cors={'Access-Control-Allow-Origin':'https://joinalab.com','Access-Control-Allow-Credentials':'true','Access-Control-Allow-Headers':req.headers.get('access-control-request-headers','*'),'Access-Control-Allow-Methods':'GET,POST,PATCH,DELETE,HEAD,OPTIONS','Access-Control-Expose-Headers':'Content-Range,Retry-After'}
                if u.hostname=='mjpirkyduibkakvlbdko.supabase.co':
                    if req.method=='OPTIONS':return await route.fulfill(status=204,headers=cors)
                    if mode.startswith('race') and u.path.endswith('/commit_profile_patch_cas'):
                        patch = req.post_data_json or {}
                        print('Observed save', 'second' if req.frame.page==receiver else 'first',
                              'outage',outage,'expected rev',patch.get('p_expected_revision'),
                              'patch major',(patch.get('p_patch') or {}).get('major'),flush=True)
                        if outage:
                            return await route.fulfill(status=503,headers=cors,json={'message':'simulated disconnected write'})
                        await asyncio.sleep(.19)
                    if mode == 'merged' and u.path.endswith('/commit_profile_patch_cas') and outage and req.frame.page == receiver:
                        outcomes.append('unavailable')
                        print('Synthetic guest write unavailable',flush=True)
                        return await route.fulfill(status=503,headers=cors,json={'message':'temporary fixture outage'})
                    if (mode == 'eeb' or listing) and u.path == '/rest/v1/favorites' and req.method == 'GET':
                        ids = [listing_id] if listing else eeb
                        return await route.fulfill(status=200,headers={**cors,'Content-Range':f'0-{len(ids)-1}/{len(ids)}'},json=[{'opportunity_id':key} for key in ids])
                    if mode=='dashboard' and u.path=='/rest/v1/favorites' and req.method=='GET':
                        reads+=1
                        return await route.fulfill(status=503 if fail else 200,headers={**cors,'Retry-After':'0',**({} if fail else {'Content-Range':'0-0/1'})},json={'message':'controlled outage'} if fail else [{'opportunity_id':'saved-target'}])
                    h={'Content-Type':'application/json',**{k:v for k,v in req.headers.items() if k in ('authorization','prefer','accept','range')}}
                    code,ct,body=await asyncio.to_thread(fetch,stub+path,req.post_data_buffer,h,req.method)
                    if (mode == 'merged' or mode.startswith('race')) and u.path.endswith('/commit_profile_patch_cas'):
                        outcomes.append(json.loads(body).get('reason',json.loads(body).get('status')))
                    return await route.fulfill(status=code,body=body,content_type=ct,headers=cors)
                if u.hostname=='joinalab.com':
                    if req.url in blocked_assets:
                        failed_assets.append(req.url)
                        return await route.abort('failed')
                    if u.path=='/api/opportunities/batch' and req.method=='POST' and mode=='dashboard':
                        return await route.fulfill(json={'requested':1,'found':0,'opportunities':[]})
                    if u.path=='/api/matches/view' and req.method=='POST' and (mode in ('cache','urca','eeb') or listing):
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
                lang = mode.removeprefix('race').split('-')[0]
                await page.goto('https://joinalab.com/',wait_until='domcontentloaded')
                receiver = await context.new_page()
                await receiver.goto('https://joinalab.com/',wait_until='domcontentloaded')
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
                    await editor.locator('summary').click()
                    await context.set_offline(True)
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
                        return json.loads(fetch(stub+'/rest/v1/profiles?select=profile_data,revision&id=eq.'+uid,h=auth)[2])[0]
                    stored=saved_resume(); data=stored['profile_data']
                    assert data['name']==profile['name']
                    assert any(x.get('id')=='prior-independent-entry' for x in data['experience_entries'])
                    if mode.endswith('keep'):
                        assert not data.get('resume_text'),data.get('resume_text')
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
                    await browser.close()
                    return
                outage = True
                await page.locator('#major').select_option('Electrical Engineering')
                await expect(page.get_by_test_id('retry-sync')).to_be_visible(timeout=25000)
                await receiver.locator('#major').select_option('Computer Engineering')
                keep = [tab.get_by_test_id('conflict-keep-mine') for tab in tabs]
                await expect(receiver.get_by_test_id('retry-sync').or_(keep[1]).first).to_be_visible(timeout=20000)
                outage = False
                for index,tab in enumerate(tabs):
                    await tab.bring_to_front()
                    retry = tab.get_by_test_id('retry-sync')
                    if not await keep[index].is_visible() and await retry.is_visible():
                        try:
                            await retry.click(timeout=2500)
                        except Exception:
                            await expect(keep[index]).to_be_visible(timeout=7500)
                messages = []
                for index,tab in enumerate(tabs):
                    await expect(keep[index]).to_be_visible(timeout=30000)
                    expected = 'Changed somewhere else' if lang == 'en' else '在别处改过了'
                    message = await tab.locator('#profile-save-status').inner_text()
                    messages.append(expected in message)
                    print('Open choice',lang,index,'visible major',await tab.locator('#major').input_value(),repr(message),flush=True)
                    if lang == 'zh':
                        dims=await keep[index].evaluate("(b)=>({width:innerWidth,height:b.getBoundingClientRect().height,line:parseFloat(getComputedStyle(b).lineHeight),pad:parseFloat(getComputedStyle(b).paddingTop)+parseFloat(getComputedStyle(b).paddingBottom)})")
                        assert dims['width'] == 390 and dims['height']-dims['pad'] <= dims['line']*2+3,dims
                    await tab.evaluate("""() => {window.receiptViews=[];window.statusHistory=[];window.receiptClicks=0;document.addEventListener('click',e=>{if(e.target.closest('[data-testid="conflict-keep-mine"]')){window.receiptClicks++;window.receiptClickTime=Date.now()}},true);new MutationObserver(()=>{
                        const msg=document.querySelector('#profile-save-status')?.innerText;
                        if(msg && window.statusHistory.at(-1)!==msg && window.statusHistory.length<30) window.statusHistory.push(msg);
                        const s = document.querySelector('[data-testid="conflict-stale"]');
                        const retry=document.querySelector('[data-testid="retry-sync"]');
                        const failed=/Saved on this device only|仅保存在本设备|没能同步/.test((document.querySelector('#profile-save-status')?.innerText || ''));
                        if(s || retry || failed) window.receiptViews.push({stale:!!s,retry:!!retry,failed});
                    }).observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true});}""")
                outcomes.clear()
                staggered = mode.endswith('-staggered')
                second_available = True
                if staggered:
                    await keep[0].click()
                    await asyncio.sleep(.8)
                    for i,t in enumerate(tabs):
                        print('Before second attempt',i,await t.locator('#major').input_value(),repr(await t.locator('#profile-save-status').inner_text()),flush=True)
                    second_available = await keep[1].is_visible()
                    if second_available:
                        try:
                            await keep[1].click(timeout=500)
                        except Exception:
                            if await keep[1].is_visible():
                                raise
                            second_available = False
                    print('Choice still actionable after 0.8s', lang, second_available, flush=True)
                else:
                    await asyncio.gather(*(button.click(timeout=3000) for button in keep))
                for button in keep:
                    await expect(button).to_have_count(0,timeout=15000)
                await asyncio.sleep(2)
                views=[await tab.evaluate("window.receiptViews") for tab in tabs]
                saved=json.loads(fetch(stub+'/rest/v1/profiles?select=profile_data,revision&id=eq.'+uid,h=auth)[2])[0]
                major=saved['profile_data']['major']
                for tab in tabs:
                    await tab.bring_to_front()
                    await expect(tab.locator('#student_name')).to_have_value(profile['name'],timeout=45000)
                    campus_picker = tab.get_by_test_id('university-card-uiuc')
                    if await campus_picker.is_visible():
                        await campus_picker.click()
                        await tab.get_by_test_id('switcher-confirm').click()
                        await expect(campus_picker).to_be_hidden(timeout=15000)
                    await expect(tab.locator('#major')).to_have_value(major)
                print('Concurrent answers',lang,major,'write outcomes',outcomes,'observed stale/retry/failure', [[any(v[k] for v in vs) for k in ('stale','retry','failed')] for vs in views],flush=True)
                clicks = [await tab.evaluate('window.receiptClicks') for tab in tabs]
                print('Click receipts',clicks,'approved conflict explanation present',messages,flush=True)
                times = [await tab.evaluate('window.receiptClickTime ?? null') for tab in tabs]
                print('Click interval in ms', times[1]-times[0] if all(times) else None, flush=True)
                print('Ordered status history', [[v.replace('\n',' / ') for v in await tab.evaluate('window.statusHistory')] for tab in tabs],flush=True)
                assert all(messages), messages
                assert clicks == [1,int(second_available)] and outcomes == ['applied']
                if second_available:
                    assert any(any(v['stale'] for v in vs) for vs in views)
                if staggered:
                    assert major == 'Electrical Engineering'
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
            elif error_page:
                zh = mode.endswith('zh')
                healthy = await context.new_page()
                assets = set()
                async def find_uploader(response):
                    if response.request.resource_type == 'script' and '/_next/' in response.url:
                        try:
                            code = await response.body()
                        except Exception:
                            return
                        if b'resume.errOnlyPdf' in code and b'resume.uploadAria' in code:
                            assets.add(response.url)
                healthy.on('response', find_uploader)
                await healthy.goto('https://joinalab.com/',wait_until='domcontentloaded')
                await expect(healthy.locator('#resume-upload')).to_have_count(1,timeout=40000)
                for _ in range(40):
                    if assets: break
                    await asyncio.sleep(.1)
                assert len(assets)==1, assets
                blocked_assets.update(assets)
                broken = await context.new_page()
                await broken.goto('https://joinalab.com/',wait_until='domcontentloaded')
                heading = '这个页面出了点问题。' if zh else 'Something went wrong on this page.'
                await expect(broken.get_by_role('heading',name=heading)).to_be_visible(timeout=45000)
                hint = '可以重试；如果问题仍然存在，请刷新页面。' if zh else 'You can retry, or reload the page if the problem persists.'
                await expect(broken.get_by_text(hint,exact=True)).to_be_visible()
                retry = broken.get_by_role('button',name='重试' if zh else 'Try again',exact=True)
                await expect(retry).to_be_visible()
                await expect(broken.get_by_role('link',name='返回首页' if zh else 'Back home',exact=True)).to_have_attribute('href','/')
                await broken.get_by_text('技术详情' if zh else 'Technical details',exact=True).click()
                await expect(broken.locator('details[open] pre')).to_be_visible()
                assert failed_assets, 'The controlled local asset failure did not occur'
                print('PASS official error boundary',mode,'heading',heading,'hint',hint,'isolated failed asset count',len(failed_assets),flush=True)
                blocked_assets.clear()
                await broken.reload(wait_until='domcontentloaded')
                await expect(broken.locator('#resume-upload')).to_have_count(1,timeout=45000)
                await expect(broken.get_by_role('heading',name=heading)).to_have_count(0)
                print('PASS healthy reload after restoring the asset',mode,flush=True)
            elif listing:
                zh = mode.endswith('zh')
                await page.goto('https://joinalab.com/results?tab=starred',wait_until='domcontentloaded')
                card = page.locator('#match-card-'+listing_id)
                await card.get_by_role('button',name='展开详情' if zh else 'Show details').click(timeout=85000)
                warning = '项目页面未确认' if zh else 'not confirmed on the program page'
                reason = card.locator('li').filter(has_text=warning).filter(has_text='computer science').first
                await expect(reason).to_be_visible(timeout=15000)
                line = await reason.inner_text()
                assert ('我们列表里的信息提示偏向' if zh else 'Our listing suggests') in line, line
                print('PASS public matched card', listing_id, mode, line, flush=True)
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


async def saved_faculty_links():
    pairs = (
        ('faculty-purdue-cs-412c3ce0', 'faculty-purdue-cs-bb6831d2'),
        ('faculty-georgetown-engl-9b02f5b4', 'faculty-georgetown-engl-be9bd333'),
    )
    site = 'https://joinalab.com'
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
        for lang, label in [('en','View current faculty record'), ('zh','查看当前教师档案')]:
            ctx = await browser.new_context(viewport={'width':390 if lang == 'zh' else 1280,'height':900})
            await ctx.add_cookies([{'name':'ofe_lang','value':lang,'url':site}])
            # The affected entry point is a returning visitor opening a saved URL.
            await ctx.add_init_script("localStorage.setItem('ofe_onboarding_seen','1')")
            page = await ctx.new_page()
            async def choose_campus():
                await page.get_by_test_id('university-card-uiuc').click()
                await page.get_by_test_id('switcher-confirm').click()
            await page.add_locator_handler(page.get_by_test_id('university-card-uiuc'), choose_campus)
            for old, current in pairs:
                await page.goto(site + '/opportunities/' + old, wait_until='domcontentloaded')
                link = page.get_by_role('link', name=label, exact=True)
                await expect(link).to_be_visible(timeout=35000)
                await expect(link).to_have_attribute('href', '/opportunities/' + current)
                await link.click()
                await expect(page).to_have_url(site + '/opportunities/' + current, timeout=30000)
                heading = page.get_by_role('heading',level=1)
                expected = 'Taram' if 'purdue' in old else 'Holmes'
                await expect(heading).to_contain_text(expected,timeout=30000)
                name = await heading.inner_text()
                print('PASS official archived faculty link clicked', lang, old, current, name, flush=True)
            await ctx.close()
        await browser.close()


if sys.argv[1] == 'dashboard':
    asyncio.run(saved_faculty_links())
