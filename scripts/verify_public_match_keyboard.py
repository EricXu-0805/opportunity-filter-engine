"""Normal production guest, real match results and free email editor, with a native keyboard and Chromium page zoom."""
import json, re, tempfile
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

SITE='https://joinalab.com'; HOST='joinalab.com'; DB='mjpirkyduibkakvlbdko.supabase.co'
TARGET='faculty-ib-78788e71'; PROFESSOR='Mark Jason Lara'; NAME='Synthetic ecological methods keyboard check'

def focus(p,el,reverse=False):
    for _ in range(160):
        if el.evaluate('e=>document.activeElement===e'):return
        p.keyboard.press('Shift+Tab' if reverse else 'Tab')
    raise AssertionError(('unreachable by keyboard',str(el)))

def state(p):
    p.wait_for_timeout(380)
    return p.evaluate("""()=>{const e=document.activeElement,c=getComputedStyle(e),r=e.getBoundingClientRect(),x=Math.max(0,Math.min(innerWidth-1,r.x+r.width/2)),y=Math.max(0,Math.min(innerHeight-1,r.y+r.height/2)),top=document.elementFromPoint(x,y);return {tag:e.tagName,id:e.id,role:e.getAttribute('role'),focusVisible:e.matches(':focus-visible'),visible:r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0,uncovered:top===e||e.contains(top),ring:c.boxShadow!=='none'||(c.outlineStyle!=='none'&&parseFloat(c.outlineWidth)>0)}}""")
def dims(p):return p.evaluate('()=>({width:innerWidth,ratio:devicePixelRatio,client:document.documentElement.clientWidth,full:document.documentElement.scrollWidth})')
with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
    ext=Path(tmp)/'ext';ext.mkdir()
    (ext/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Native tab zoom','version':'1','permissions':['tabs'],'host_permissions':[SITE+'/*'],'background':{'service_worker':'zoom.js'}}))
    (ext/'zoom.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    probe=pw.request.new_context();sha=probe.get(SITE+'/api/health').json()['release_sha'];assert 'data-release-sha="'+sha+'"' in probe.get(SITE+'/about').text();probe.dispose()
    results=[]
    for locale,width in [('en',1400),('zh',780)]:
        ctx=pw.chromium.launch_persistent_context(str(Path(tmp)/locale),channel='chromium',headless=False,no_viewport=True,locale='en-US',args=['--no-sandbox','--disable-dev-shm-usage','--window-size='+str(width)+',940','--disable-extensions-except='+str(ext),'--load-extension='+str(ext)])
        worker=ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker',timeout=40000)
        sessions=[];revisions=[];drafts=[];registered=[]
        def response(r):
            u=urlsplit(r.url)
            if not r.ok:return
            if u.hostname==DB and u.path=='/auth/v1/signup':
                info=r.json();assert info['user']['is_anonymous'] and not sessions;sessions.append(info)
            if u.hostname==DB and u.path.endswith('/rpc/commit_profile_patch_cas') and r.json().get('status')=='applied':revisions.append(r.json()['revision'])
            if u.hostname==HOST and u.path=='/api/cold-email/variants':drafts.append(r.json())
        def guard(r):
            req=r.request;u=urlsplit(req.url)
            if u.hostname not in (HOST,DB):return r.abort()
            if req.method in ('GET','HEAD','OPTIONS'):return r.continue_()
            if req.method=='POST':
                d=req.post_data_json or {}
                if u.hostname==DB:
                    if u.path=='/auth/v1/signup' and not registered and not d.get('email'):
                        registered.append(True);return r.continue_()
                    if u.path=='/auth/v1/token' and sessions:return r.continue_()
                    if u.path.endswith('/rpc/commit_profile_patch_cas') and sessions and d['p_expected_device_id']==sessions[0]['user']['id']:return r.continue_()
                if u.hostname==HOST and u.path=='/api/matches/view' and 'llm=false' in u.query:return r.continue_()
                if u.hostname==HOST and u.path=='/api/cold-email/variants' and d.get('opportunity_id')==TARGET and d.get('profile',{}).get('name')==NAME:return r.continue_()
            return r.abort()
        ctx.route('**/*',guard);ctx.on('response',response)
        ctx.add_cookies([{'name':'ofe_lang','value':'en','url':SITE}])
        seed={'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00Z'})}
        ctx.add_init_script("if(location.origin==='https://joinalab.com'&&!localStorage.getItem('keyboard-match-qa')){for(const[k,v]of Object.entries("+json.dumps(seed)+"))localStorage.setItem(k,v);localStorage.setItem('keyboard-match-qa','1')}")
        p=ctx.pages[0];p.goto(SITE,wait_until='domcontentloaded');p.locator('#student_name').wait_for(timeout=60000)
        for _ in range(180):
            if sessions and not p.get_by_test_id('hydration-note').is_visible():break
            p.wait_for_timeout(200)
        assert sessions
        school=p.get_by_test_id('university-card-uiuc')
        if school.is_visible():school.click();p.get_by_test_id('switcher-confirm').click()
        p.locator('#student_name').fill(NAME);p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)');p.locator('#major').select_option(label='Integrative Biology')
        p.locator('#grade').select_option(label='Junior');p.locator('#research_interests').fill('Wetlands, ecology and GIS')
        for _ in range(105):
            if revisions:break
            p.wait_for_timeout(200)
        assert revisions
        if locale=='zh':
            ctx.add_cookies([{'name':'ofe_lang','value':'zh','url':SITE}]);p.evaluate("localStorage.setItem('ofe_lang','zh')");p.reload(wait_until='domcontentloaded')
            expect(p.locator('#student_name')).to_have_value(NAME,timeout=60000)
        pre=dims(p)
        actual=worker.evaluate("async()=>{const [t]=await chrome.tabs.query({url:'https://joinalab.com/*'});await chrome.tabs.setZoom(t.id,2);return await chrome.tabs.getZoom(t.id)}")
        p.wait_for_timeout(400);size=dims(p);assert actual==2 and abs(size['ratio']/pre['ratio']-2)<.01 and abs(2*size['width']-pre['width'])<6
        case={'locale':locale,'native_200_width':size['width'],'real_guest':True}
        gen=p.get_by_test_id('generate-matches');focus(p,gen);case['generate_focus']=state(p);p.keyboard.press('Enter')
        p.wait_for_url('**/results**',timeout=90000)
        group=p.get_by_role('tablist').filter(has=p.get_by_role('tab',name=re.compile(r'^(All|全部|所有)')))
        first=group.get_by_role('tab').first;expect(first).to_be_visible(timeout=65000)
        focus(p,first);selected=group.locator('[aria-selected=true]').inner_text();p.keyboard.press('ArrowRight');p.wait_for_timeout(450)
        case['category_right_changes_focus']=group.get_by_role('tab').nth(1).evaluate('e=>document.activeElement===e')
        case['category_right_changes_selection']=group.locator('[aria-selected=true]').inner_text()!=selected
        alltab=group.get_by_role('tab',name=re.compile(r'^(All|全部|所有)')).first
        focus(p,alltab);p.keyboard.press('Enter')
        search=p.locator('#results-search-input');focus(p,search);p.keyboard.type(PROFESSOR,delay=30)
        card=p.locator('#match-card-'+TARGET);expect(card).to_be_visible(timeout=95000)
        draft=card.get_by_role('button',name='Draft email' if locale=='en' else '起草邮件',exact=True)
        focus(p,draft);case['target_card_draft_focus']=state(p);p.keyboard.press('Enter')
        body=p.locator('#cold-email-body');expect(body).not_to_have_value('',timeout=70000)
        assert len(drafts)==1 and len(drafts[0].get('variants',[]))==3
        cond=p.get_by_test_id('email-target-conditions')
        expand=cond.locator('summary,button[aria-expanded]').first
        if expand.count():
            focus(p,expand);case['conditions_focus']=state(p);p.keyboard.press('Enter');p.wait_for_timeout(250)
            case['conditions_expanded']=expand.evaluate("e=>e.tagName==='SUMMARY'?e.parentElement.open:e.getAttribute('aria-expanded')==='true'")
        focus(p,body);case['editor_body_focus']=state(p)
        local='Synthetic keyboard-only draft, kept in this browser.';p.keyboard.press('Control+a');p.keyboard.type(local)
        expect(body).to_have_value(local)
        close=p.get_by_role('button',name='Close email editor' if locale=='en' else '关闭邮件编辑器',exact=True)
        focus(p,close,reverse=True);case['editor_close_focus']=state(p);p.keyboard.press('Enter');expect(body).to_have_count(0,timeout=25000)
        case['focus_returns_to_card']=draft.evaluate('e=>document.activeElement===e')
        case['results_geometry_after_close']=dims(p);case['templates']=len(drafts[0]['variants']);case['external_messages_sent']=0
        print('MATCH KEYBOARD CASE',json.dumps(case,ensure_ascii=False),flush=True)
        results.append(case);ctx.close()
    print('MATCH KEYBOARD RECEIPT',json.dumps({'release':sha,'site':SITE,'cases':results,'human_screen_reader':False,'physical_device':False},ensure_ascii=False),flush=True)
