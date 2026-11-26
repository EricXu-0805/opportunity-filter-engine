"""Normal production guest, real match results and free email editor, with a native keyboard and Chromium page zoom."""
import json, os, re, tempfile
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

SITE = os.environ.get('OFE_KEYBOARD_SITE', 'https://joinalab.com')
LOCAL = SITE == 'http://127.0.0.1:3100'
assert LOCAL or SITE == 'https://joinalab.com'
HOST = urlsplit(SITE).hostname
DB = HOST if LOCAL else 'mjpirkyduibkakvlbdko.supabase.co'
TARGET = 'e2e-actionable-research' if LOCAL else 'faculty-ib-78788e71'
SEARCH = 'Campus computing' if LOCAL else 'Mark Jason Lara'
NAME='Synthetic ecological methods keyboard check'

def focus(p,el,reverse=False):
    for _ in range(160):
        if el.evaluate('e=>document.activeElement===e'):return
        p.keyboard.press('Shift+Tab' if reverse else 'Tab')
    raise AssertionError(('unreachable by keyboard',str(el)))

def state(p):
    p.wait_for_timeout(1500)
    return p.evaluate("""async () => {
      const e = document.activeElement, c = getComputedStyle(e);
      const entry = await new Promise(resolve => {
        const observer = new IntersectionObserver(([entry]) => { observer.disconnect(); resolve(entry); });
        observer.observe(e);
      });
      const r = entry.intersectionRect, visible = entry.isIntersecting && r.width > 0 && r.height > 0;
      const samples = [];
      if (visible) for (const x of [.15,.5,.85]) for (const y of [.15,.5,.85]) {
        const top = document.elementFromPoint(r.left + r.width*x, r.top + r.height*y);
        samples.push(Boolean(top && (top === e || e.contains(top))));
      }
      return {tag:e.tagName,id:e.id,role:e.getAttribute('role'),focusVisible:e.matches(':focus-visible'),
              visible, visible_width:Math.round(r.width),visible_height:Math.round(r.height),
              uncovered:samples.some(Boolean),uncovered_samples:samples.filter(Boolean).length,
              ring:c.boxShadow!=='none'||(c.outlineStyle!=='none'&&parseFloat(c.outlineWidth)>0)};
    }""")
def dims(p):return p.evaluate('()=>({width:innerWidth,ratio:devicePixelRatio,client:document.documentElement.clientWidth,full:document.documentElement.scrollWidth})')
with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
    ext=Path(tmp)/'ext';ext.mkdir()
    (ext/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Native tab zoom','version':'1','permissions':['tabs'],'host_permissions':[SITE+'/*'],'background':{'service_worker':'zoom.js'}}))
    (ext/'zoom.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    probe=pw.request.new_context();sha=probe.get(SITE+'/api/health').json()['release_sha'];assert 'data-release-sha="'+sha+'"' in probe.get(SITE+'/about').text();probe.dispose()
    if LOCAL: assert sha == os.environ['OFE_RELEASE_SHA']
    results=[]
    for locale,width in [('en',1400),('zh',780)]:
        ctx=pw.chromium.launch_persistent_context(str(Path(tmp)/locale),channel='chromium',headless=False,no_viewport=True,locale='en-US',args=['--no-sandbox','--disable-dev-shm-usage','--window-size='+str(width)+',940','--disable-extensions-except='+str(ext),'--load-extension='+str(ext)])
        worker=ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker',timeout=40000)
        sessions=[];revisions=[];drafts=[];registered=[]
        copy_only=os.environ.get('OFE_CHECK_DRAFT_RECOPY')=='1'
        contact_writes=[]
        if copy_only:
            ctx.grant_permissions(['clipboard-read','clipboard-write'],origin=SITE)
            def track_write(req):
                loc=urlsplit(req.url)
                if req.method in ('POST','PATCH','PUT','DELETE') and (
                        loc.path.startswith('/rest/v1/interactions') or 'confirm_contact' in loc.path):
                    contact_writes.append(req.method)
            ctx.on('request',track_write)
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
        ctx.add_init_script("if(location.origin==="+json.dumps(SITE)+"&&!localStorage.getItem('keyboard-match-qa')){for(const[k,v]of Object.entries("+json.dumps(seed)+"))localStorage.setItem(k,v);localStorage.setItem('keyboard-match-qa','1')}")
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
        actual=worker.evaluate("async url=>{const [t]=await chrome.tabs.query({url});await chrome.tabs.setZoom(t.id,2);return await chrome.tabs.getZoom(t.id)}",SITE+"/*")
        p.wait_for_timeout(400);size=dims(p);assert actual==2 and abs(size['ratio']/pre['ratio']-2)<.01 and abs(2*size['width']-pre['width'])<6
        case={'locale':locale,'native_200_width':size['width'],'real_guest':True}
        gen=p.get_by_test_id('generate-matches');focus(p,gen);case['generate_focus']=state(p);p.keyboard.press('Enter')
        p.wait_for_url('**/results**',timeout=90000)
        group=p.get_by_role('tablist').filter(has=p.get_by_role('tab',name=re.compile(r'^(All|全部|所有)')))
        first=group.get_by_role('tab').first;expect(first).to_be_visible(timeout=65000)
        if first.get_attribute('tabindex') is None:
            # The original buttons are all in sequential tab order. The first can
            # be behind the selected category, followed by hundreds of card controls.
            focus(p,first)
        else:
            focus(p,group.locator('[aria-selected=true]'))
            p.keyboard.press('Home')
            expect(first).to_be_focused()
        p.keyboard.press('Enter'); expect(first).to_have_attribute('aria-selected','true')
        p.keyboard.press('ArrowRight');p.wait_for_timeout(450)
        second=group.get_by_role('tab').nth(1)
        case['category_right_changes_focus']=second.evaluate('e=>document.activeElement===e')
        case['category_right_changes_selection']=second.get_attribute('aria-selected')=='true'
        if case['category_right_changes_focus']:
            p.keyboard.press('End')
            last=group.get_by_role('tab').last
            expect(last).to_be_focused();expect(last).to_have_attribute('aria-selected','true')
            p.keyboard.press('ArrowRight');expect(first).to_be_focused();expect(first).to_have_attribute('aria-selected','true')
            p.keyboard.press('End');p.keyboard.press('Home')
            expect(first).to_be_focused();expect(first).to_have_attribute('aria-selected','true')
            expect(p.locator('#match-category-results[role=tabpanel]')).to_have_attribute('aria-labelledby',first.get_attribute('id'))
            case['wrap_home_end_and_panel']=True
        else:
            case['wrap_home_end_and_panel']=False
            focus(p,first);p.keyboard.press('Enter')
        if LOCAL: assert all(case[k] for k in ('category_right_changes_focus','category_right_changes_selection','wrap_home_end_and_panel')), case
        search=p.locator('#results-search-input');focus(p,search)
        def requested_search(r):
            u=urlsplit(r.url)
            return u.path=='/api/matches/view' and r.ok and r.request.post_data_json.get('view',{}).get('search_query')==SEARCH
        with p.expect_response(requested_search,timeout=90000) as found:
            p.keyboard.type(SEARCH,delay=30)
        assert TARGET in [row['opportunity_id'] for row in found.value.json()['results']]
        card=p.locator('#match-card-'+TARGET);expect(card).to_be_visible(timeout=95000)
        draft=card.get_by_role('button',name='Draft email' if locale=='en' else '起草邮件',exact=True)
        expect(draft).to_be_enabled(timeout=30000)
        focus(p,draft);case['target_card_draft_focus']=state(p);expect(draft).to_be_focused();p.keyboard.press('Enter')
        body=p.locator('#cold-email-body');expect(body).not_to_have_value('',timeout=70000)
        assert len(drafts)==1 and len(drafts[0].get('variants',[]))==3
        cond=p.get_by_test_id('email-target-conditions')
        expand=cond.locator('summary,button[aria-expanded]').first
        if expand.count():
            focus(p,expand);case['conditions_focus']=state(p);p.keyboard.press('Enter');p.wait_for_timeout(250)
            case['conditions_expanded']=expand.evaluate("e=>e.tagName==='SUMMARY'?e.parentElement.open:e.getAttribute('aria-expanded')==='true'")
        focus(p,body);case['editor_body_focus']=state(p)
        original=body.input_value()
        local=original if copy_only else 'Synthetic keyboard-only draft, kept in this browser.'
        if not copy_only:
            p.keyboard.press('Control+a');p.keyboard.type(local)
        expect(body).to_have_value(local)
        close=p.get_by_role('button',name='Close email editor' if locale=='en' else '关闭邮件编辑器',exact=True)
        if copy_only:
            copy=p.get_by_test_id('copy-draft-only').filter(visible=True)
            expect(copy).to_have_count(1)
            subject=p.locator('#cold-email-subject').input_value()
            expected_clipboard='Subject: '+subject+'\n\n'+original
            idle_label='Copy draft only' if locale=='en' else '仅复制草稿'
            copied_label='Draft copied' if locale=='en' else '草稿已复制'
            expect(copy).to_have_text(idle_label)
            for _ in range(2):
                copy.click()
                expect(copy).to_have_text(copied_label)
                assert p.evaluate('navigator.clipboard.readText()')==expected_clipboard
            # Close while the second receipt is still visible.
            expect(copy).to_have_text(copied_label)
            close.click()
            expect(body).to_have_count(0,timeout=25000)
            draft.click()
            expect(body).not_to_have_value('',timeout=70000)
            expect(copy).to_have_text(idle_label)
            fresh_body=body.input_value()
            assert fresh_body==original, 'Reopened draft text differs from the copied original'
            p.wait_for_timeout(2200)
            expect(copy).to_have_text(idle_label)
            assert p.evaluate('navigator.clipboard.readText()')==expected_clipboard and not contact_writes
            case['draft_only_recopy']={'real_clipboard_equal_after_first':True,
                'real_clipboard_equal_after_second':True,'original_text_returned_on_reopen':True,
                'new_dialog_clear_through_timer':True,'contact_writes':len(contact_writes)}
        focus(p,close,reverse=True);case['editor_close_focus']=state(p);p.keyboard.press('Enter');expect(body).to_have_count(0,timeout=25000)
        case['focus_returns_to_card']=draft.evaluate('e=>document.activeElement===e')
        case['results_geometry_after_close']=dims(p);case['templates']=len(drafts[0]['variants']);case['external_messages_sent']=0
        print('MATCH KEYBOARD CASE',json.dumps(case,ensure_ascii=False),flush=True)
        assert case['focus_returns_to_card'] and case['editor_body_focus']['visible'] and case['templates']==3, case
        results.append(case);ctx.close()
    print('MATCH KEYBOARD RECEIPT',json.dumps({'release':sha,'site':SITE,'cases':results,'human_screen_reader':False,'physical_device':False},ensure_ascii=False),flush=True)
