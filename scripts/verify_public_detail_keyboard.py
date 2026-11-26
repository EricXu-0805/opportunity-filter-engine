"""Read-only detail route, records, notes and source navigation at native 200% zoom."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
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
    cases=[]
    for locale,width in [('en',1400),('zh',780)]:
        ctx=pw.chromium.launch_persistent_context(str(root/locale),channel='chromium',headless=False,no_viewport=True,locale='en-US' if locale=='en' else 'zh-CN',
             args=['--no-sandbox','--disable-dev-shm-usage','--window-size='+str(width)+',940','--disable-extensions-except='+str(ext),'--load-extension='+str(ext)])
        worker=ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker',timeout=40000)
        ctx.add_cookies([{'name':'ofe_lang','value':locale,'url':SITE}])
        data={'ofe_lang':locale,'ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00Z'})}
        ctx.add_init_script("if(location.origin==="+json.dumps(SITE)+"&&!localStorage.getItem('keyboard-qa')){for(const[k,v]of Object.entries("+json.dumps(data)+"))localStorage.setItem(k,v);localStorage.setItem('keyboard-qa','1')}")
        writes=[]
        remember_note = os.environ.get('OFE_TEST_OWN_NOTE') == '1'
        own_user = {}
        sample = 'Keyboard note for this test visit.' if locale == 'en' else '本次验收访客的键盘测试备注。'
        target = os.environ.get('OFE_KEYBOARD_TARGET','faculty-ib-78788e71')
        def observe_auth(response):
            url = urlsplit(response.url)
            if url.hostname == DATABASE and url.path == '/auth/v1/signup' and response.ok:
                data = response.json()
                assert data['user']['is_anonymous']
                own_user['id'] = data['user']['id']
        if remember_note:
            ctx.on('response', observe_auth)
        def guard(r):
            addr=urlsplit(r.request.url)
            if addr.hostname not in (HOST,DATABASE) or (LOCAL and addr.hostname!=HOST):return r.abort()
            if r.request.method in ('GET','HEAD','OPTIONS'):return r.continue_()
            if addr.hostname==DATABASE and addr.path=='/auth/v1/signup' and not writes and not (r.request.post_data_json or {}).get('email'):
                writes.append('own anonymous sign-up');return r.continue_()
            if remember_note and own_user and addr.hostname == DATABASE and addr.path == '/rest/v1/interactions':
                payload = r.request.post_data_json or {}
                own = own_user['id']
                if (r.request.method == 'POST' and payload.get('device_id') == own and
                        payload.get('opportunity_id') == target and payload.get('interaction_type') == 'dismissed' and
                        set(payload) == {'device_id','opportunity_id','interaction_type','updated_at'}):
                    writes.append('own dismissed status')
                    return r.continue_()
                query = parse_qs(addr.query)
                if (r.request.method == 'PATCH' and query.get('device_id') == ['eq.' + own] and
                        query.get('opportunity_id') == ['eq.' + target] and payload.get('notes') == sample and
                        set(payload) == {'notes','updated_at'}):
                    writes.append('own synthetic note')
                    return r.continue_()
            return r.abort()
        ctx.route('**/*',guard)
        target = os.environ.get('OFE_KEYBOARD_TARGET','faculty-ib-78788e71')
        p=ctx.pages[0];p.goto(SITE+'/opportunities/'+target,wait_until='domcontentloaded')
        trigger=p.locator('#tracker-records > button[aria-expanded]')
        expect(trigger).to_be_visible(timeout=65000)
        native_zoom(worker,p,1)
        before=metric(p)
        native_zoom(worker,p,2)
        after=metric(p)
        assert abs(2*after['width']-before['width'])<5 and after['ratio']==before['ratio']*2
        # Detail controls are initially server-rendered. The panel is keyed by
        # the hydrated owner, which can change once during a fresh guest signup.
        for attempt in range(8):
            if trigger.get_attribute('aria-expanded')=='true':break
            focus(p,trigger);start=active(p)
            if not trigger.evaluate('e=>document.activeElement===e'):continue
            p.keyboard.press('Enter')
            try:
                expect(trigger).to_have_attribute('aria-expanded','true',timeout=1400)
            except AssertionError:pass
        expect(trigger).to_have_attribute('aria-expanded','true')
        group=p.get_by_role('tablist',name='Notes view mode' if locale=='en' else '笔记视图模式')
        expect(group).to_be_visible(timeout=20000)
        edit,preview=group.get_by_role('tab').all()
        focus(p,edit);before_arrow=active(p);p.keyboard.press('ArrowRight');p.wait_for_timeout(300)
        moved=preview.evaluate('e=>document.activeElement===e') and preview.get_attribute('aria-selected')=='true'
        if LOCAL: assert moved, (locale, active(p))
        if not moved:
            focus(p,preview);p.keyboard.press('Enter')
        expect(preview).to_have_attribute('aria-selected','true')
        view=active(p)
        if LOCAL and not view['visible']:
            p.wait_for_timeout(1800);view_late=active(p)
            print('NOTE PREVIEW SCROLL',json.dumps({'locale':locale,'before':before_arrow,'after':view,'later':view_late},ensure_ascii=False),flush=True)
        else:view_late=view
        if moved:
            expect(p.get_by_role('tabpanel',name='Preview' if locale=='en' else '预览')).to_be_visible()
            p.keyboard.press('Home');expect(edit).to_be_focused()
            p.keyboard.press('ArrowLeft');expect(preview).to_be_focused()
            p.keyboard.press('ArrowRight');expect(edit).to_be_focused()
            p.keyboard.press('End');expect(preview).to_be_focused()
            p.keyboard.press('Home');expect(edit).to_be_focused()
        else:
            focus(p,edit,reverse=True);p.keyboard.press('Enter')
        expect(edit).to_have_attribute('aria-selected','true')
        note=p.locator('#tracker-records textarea')
        expect(note).to_be_disabled()
        case={'locale':locale,'layout':after,'detail_id':target,'records_trigger':start,'notes_edit_focus':before_arrow,'notes_preview_focus':view,'settled_preview_focus':view_late,
              'arrow_changes_focus_and_selection':moved,'fallback_tab_enter_works':not moved,
              'editor_read_only_before_tracking':True,'external_messages':0}
        if remember_note:
            status = p.get_by_role('button',name='Not interested' if locale == 'en' else '不感兴趣',exact=True)
            expect(status).to_be_enabled(timeout=30000)
            focus(p,status)
            p.keyboard.press('Enter')
            expect(status).to_have_attribute('aria-pressed','true',timeout=20000)
            expect(note).to_be_enabled()
            focus(p,note)
            def is_note_receipt(response):
                return (urlsplit(response.url).path == '/rest/v1/interactions'
                        and response.request.method == 'PATCH')
            with p.expect_response(is_note_receipt,timeout=18000) as result:
                p.keyboard.insert_text(sample)
            ack=result.value
            assert ack.ok and ack.json() == [{'opportunity_id':target}]
            focus(p,edit,reverse=True)
            p.keyboard.press('ArrowRight')
            expect(p.get_by_role('tabpanel').get_by_text(sample,exact=True)).to_be_visible()
            p.reload(wait_until='domcontentloaded')
            expect(status).to_have_attribute('aria-pressed','true',timeout=25000)
            if trigger.get_attribute('aria-expanded') != 'true':
                focus(p,trigger)
                p.keyboard.press('Enter')
            expect(note).to_have_value(sample,timeout=15000)
            assert writes == ['own anonymous sign-up','own dismissed status','own synthetic note'], writes
            case['own_private_note']={'status':'dismissed','write_http':ack.status,
                'read_back_in_preview':True,'read_back_after_reloading':True,'writes':writes}
        print('DETAIL KEYBOARD CASE',json.dumps(case,ensure_ascii=False),flush=True)
        if LOCAL:
            assert all(item['visible'] and item['uncovered'] and item['focused'] for item in (before_arrow,view)),case
        cases.append(case);ctx.close()
    print('DETAIL KEYBOARD RECEIPT',json.dumps({'site':SITE,'release':health,'cases':cases},ensure_ascii=False))
