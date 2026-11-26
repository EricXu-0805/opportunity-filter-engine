"""Public empty tracker at real page zoom; editing and moving are only enabled in a disposable local test account."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright, expect

SITE=os.environ.get('OFE_KEYBOARD_SITE','https://joinalab.com')
HOST=urlsplit(SITE).hostname
LOCAL=HOST=='127.0.0.1'
assert LOCAL or SITE=='https://joinalab.com'
DATABASE=HOST if LOCAL else 'mjpirkyduibkakvlbdko.supabase.co'

def focus(page, locator, reverse=False):
    for _ in range(110):
        if locator.evaluate('e=>e===document.activeElement'):return
        page.keyboard.press('Shift+Tab' if reverse else 'Tab')
    raise AssertionError('Keyboard never reached '+str(locator))

def active(p):
    # Let the browser finish its normal keyboard scroll before measuring coverage.
    p.wait_for_timeout(1300)
    return p.evaluate("""() => {const e=document.activeElement, cs=getComputedStyle(e), r=e.getBoundingClientRect();
      const x=Math.max(0,Math.min(innerWidth-1,r.x+r.width/2)),y=Math.max(0,Math.min(innerHeight-1,r.y+r.height/2));
      const cover=document.elementFromPoint(x,y);return {scroll_y:Math.round(scrollY),top:Math.round(r.top),bottom:Math.round(r.bottom),viewport_h:innerHeight,doc_h:document.documentElement.scrollHeight,cover_tag:cover?.tagName,cover_id:cover?.id,tag:e.tagName,id:e.id,role:e.getAttribute('role'),name:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||'').slice(0,65),focused:e.matches(':focus-visible'),outline:cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>0,ring:cs.boxShadow!=='none',visible:r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0,uncovered:cover===e||e.contains(cover)}}""")
def metric(p):return p.evaluate('()=>({width:innerWidth,client:document.documentElement.clientWidth,document:document.documentElement.scrollWidth,ratio:devicePixelRatio,visualScale:visualViewport.scale})')

def native_zoom(worker,page,factor):
    result=worker.evaluate("""async ([factor, origin])=>{
      const [tab]=await chrome.tabs.query({url:origin+'/*'});await chrome.tabs.setZoom(tab.id,factor);
      return await chrome.tabs.getZoom(tab.id);
    }""",[factor,SITE])
    assert result==factor
    page.wait_for_timeout(320)
    return result

with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
    root=Path(tmp); ext=root/'zoom';ext.mkdir()
    (ext/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Native browser zoom check','version':'1.0','permissions':['tabs'],'host_permissions':[SITE+'/*'],'background':{'service_worker':'zoom.js'}}))
    (ext/'zoom.js').write_text('chrome.runtime.onInstalled.addListener(() => {});')
    api=pw.request.new_context();health=os.environ['OFE_LOCAL_RELEASE_SHA'] if LOCAL else api.get(SITE+'/api/health').json()['release_sha'];assert 'data-release-sha="'+health+'"' in api.get(SITE+'/about').text();api.dispose()
    if expected:=os.environ.get('OFE_EXPECTED_SITE_SHA'):
        assert health==expected
    cases=[]
    for locale,width in [('en',1400),('zh',780)]:
        ctx=pw.chromium.launch_persistent_context(str(root/locale),channel='chromium',headless=False,no_viewport=True,locale='en-US' if locale=='en' else 'zh-CN',
             args=['--no-sandbox','--disable-dev-shm-usage','--window-size='+str(width)+',940','--disable-extensions-except='+str(ext),'--load-extension='+str(ext)])
        worker=ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker',timeout=40000)
        ctx.add_cookies([{'name':'ofe_lang','value':locale,'url':SITE}])
        data={'ofe_lang':locale,'ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00Z'})}
        ctx.add_init_script("if(location.origin==="+json.dumps(SITE)+"&&!localStorage.getItem('keyboard-qa')){for(const[k,v]of Object.entries("+json.dumps(data)+"))localStorage.setItem(k,v);localStorage.setItem('keyboard-qa','1')}")
        owner=[];writes=[];requests=[];history=[];revisions=[]
        corrected=os.environ.get('OFE_TRACKER_PROFILE_CTA')=='1'
        target='e2e-actionable-research'
        note='Synthetic keyboard-only fixture note; no student or application involved.'
        def received(r):
            u=urlsplit(r.url)
            if r.ok and u.hostname==DATABASE and u.path=='/auth/v1/signup':
                who=r.json()['user'];assert who['is_anonymous'];owner.append(who['id'])
            if r.ok and u.hostname==DATABASE and u.path.endswith('/rpc/commit_profile_patch_cas') and r.json().get('status')=='applied':
                revisions.append(r.json()['revision'])
            if LOCAL and r.ok and u.path=='/rest/v1/interactions' and r.request.method in ('POST','PATCH'):
                history.append(r.request.method)
        def restrict(route):
            r=route.request;u=urlsplit(r.url)
            if u.hostname not in (HOST,DATABASE):return route.abort()
            if r.method in ('GET','OPTIONS','HEAD'):return route.continue_()
            d=r.post_data_json or {}
            if r.method=='POST' and u.hostname==DATABASE and u.path=='/auth/v1/signup' and not requests and not d.get('email'):
                requests.append(True);return route.continue_()
            if corrected and owner and r.method=='POST':
                if u.hostname==DATABASE and u.path.endswith('/rpc/commit_profile_patch_cas') and d.get('p_expected_device_id')==owner[0]:
                    return route.continue_()
                if u.hostname==HOST and u.path=='/api/matches/view' and 'llm=false' in u.query:return route.continue_()
            if corrected and owner and u.hostname==HOST and u.path=='/api/opportunities/batch' and r.method=='POST':
                return route.continue_()
            if LOCAL and owner and u.hostname==DATABASE and u.path=='/rest/v1/interactions':
                if r.method=='POST' and d.get('device_id')==owner[0] and d.get('opportunity_id')==target and d.get('interaction_type') in ('applied','interviewing'):
                    writes.append('own synthetic stage');return route.continue_()
                query=parse_qs(u.query)
                if r.method=='PATCH' and query.get('device_id')==['eq.'+owner[0]] and query.get('opportunity_id')==['eq.'+target] and d.get('notes')==note and set(d)<=set(('notes','updated_at')):
                    writes.append('own synthetic note');return route.continue_()
            return route.abort()
        ctx.on('response',received);ctx.route('**/*',restrict)
        p=ctx.pages[0];p.goto(SITE+'/tracker',wait_until='domcontentloaded')
        empty_label=('Open your profile' if locale=='en' else '打开个人资料') if corrected else ('Go to results' if locale=='en' else '去结果页')
        empty=p.get_by_role('link',name=empty_label,exact=True)
        expect(empty).to_be_visible(timeout=65000)
        expect(empty).to_have_attribute('href','/' if corrected else '/results')
        native_zoom(worker,p,1);base=metric(p);native_zoom(worker,p,2);zoom=metric(p)
        assert abs(2*zoom['width']-base['width'])<6 and zoom['ratio']==base['ratio']*2
        focus(p,empty);empty_focus=active(p);p.keyboard.press('Enter')
        p.wait_for_url(SITE+'/',timeout=65000);expect(p.locator('#student_name')).to_be_visible(timeout=45000)
        assert owner
        case={'locale':locale,'native_200':zoom,'new_guest_link_label':empty_label,'new_guest_href':'/' if corrected else '/results','empty_tracker_destination':'profile form','empty_link_focus':empty_focus}
        if corrected:
            def set_language(lang):
                ctx.add_cookies([{'name':'ofe_lang','value':lang,'url':SITE}])
                p.evaluate("(lang)=>localStorage.setItem('ofe_lang',lang)",lang)
                p.reload(wait_until='domcontentloaded')
            if locale=='zh':set_language('en')
            school=p.get_by_test_id('university-card-uiuc')
            if school.is_visible():school.click();p.get_by_test_id('switcher-confirm').click()
            p.locator('#student_name').fill('Synthetic Tracker Routing QA')
            p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
            p.locator('#major').select_option(label='Integrative Biology');p.locator('#grade').select_option(label='Junior')
            p.locator('#research_interests').fill('Computing and research methods')
            for _ in range(200):
                if revisions:break
                p.wait_for_timeout(100)
            assert revisions
            gen=p.get_by_test_id('generate-matches');focus(p,gen);p.keyboard.press('Enter');p.wait_for_url('**/results**',timeout=70000)
            if locale=='zh':set_language('zh')
            p.goto(SITE+'/tracker',wait_until='domcontentloaded')
            restored=p.get_by_role('link',name='Go to results' if locale=='en' else '去结果页',exact=True)
            expect(restored).to_have_attribute('href','/results',timeout=40000)
            focus(p,restored);p.keyboard.press('Enter');p.wait_for_url('**/results**',timeout=70000)
            expect(p.get_by_role('tablist').first).to_be_visible(timeout=70000)
            case['existing_guest_href']='/results';case['existing_profile_revision']=revisions[-1]
            case['existing_guest_landed_on_own_results']=True
        if LOCAL:
            p.goto(SITE+'/opportunities/'+target,wait_until='domcontentloaded')
            applied=p.get_by_role('group',name='Track application status' if locale=='en' else '跟踪申请状态').get_by_role('button',name='Applied' if locale=='en' else '已申请',exact=True)
            expect(applied).to_be_enabled(timeout=60000);focus(p,applied);p.keyboard.press('Enter')
            expect(applied).to_have_attribute('aria-pressed','true',timeout=60000)
            p.goto(SITE+'/tracker',wait_until='domcontentloaded')
            card=p.locator('[data-tracker-card-id="'+target+'"]')
            expect(card).to_be_visible(timeout=75000)
            textarea=card.locator('textarea').first;focus(p,textarea)
            p.keyboard.type(note);p.keyboard.press('Tab')
            for _ in range(100):
                if 'PATCH' in history:break
                p.wait_for_timeout(100)
            assert 'PATCH' in history
            button=card.locator('button[aria-haspopup="dialog"]')
            focus(p,button);p.keyboard.press('Enter')
            menu=p.get_by_role('dialog');expect(menu).to_be_visible()
            next_status=menu.get_by_role('button',name='Interviewing' if locale=='en' else '面试中',exact=True)
            focus(p,next_status);p.keyboard.press('Enter')
            expect(menu).to_have_count(0,timeout=30000)
            expect(button).to_be_focused(timeout=35000)
            expect(textarea).to_have_value(note)
            case['focus_after_column_move']=active(p)
            p.keyboard.press('Enter');expect(menu).to_be_visible()
            p.keyboard.press('Escape');expect(button).to_be_focused();case['escape_returns_to_same_card']=True
            p.reload(wait_until='domcontentloaded');expect(textarea).to_have_value(note,timeout=60000)
            case['reloaded_note_and_stage']=card.locator('button[aria-haspopup="dialog"]').get_attribute('aria-label')
            assert ('Interviewing' if locale=='en' else '面试中') in case['reloaded_note_and_stage']
            case['confirmed_local_writes']=history
        else:
            assert not writes
        case['external_messages']=0;case['production_interaction_writes']=0
        cases.append(case);print('TRACKER KEYBOARD CASE',json.dumps(case,ensure_ascii=False),flush=True);ctx.close()
    print('TRACKER KEYBOARD RECEIPT',json.dumps({'site':SITE,'release':health,'cases':cases},ensure_ascii=False))
