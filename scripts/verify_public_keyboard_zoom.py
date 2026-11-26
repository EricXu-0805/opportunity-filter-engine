"""Native Chromium tab zoom and keyboard-only navigation on the deployed UI."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

SITE=os.environ.get('OFE_KEYBOARD_SITE','https://joinalab.com')
HOST=urlsplit(SITE).hostname
LOCAL=HOST=='127.0.0.1'
assert LOCAL or SITE=='https://joinalab.com'
DATABASE='mjpirkyduibkakvlbdko.supabase.co'

def focus(page, locator, reverse=False):
    for _ in range(110):
        if locator.evaluate('e=>e===document.activeElement'):return
        page.keyboard.press('Shift+Tab' if reverse else 'Tab')
    raise AssertionError('Keyboard never reached '+str(locator))

def open_menu(p,toggle):
    # An SSR header is visible before React first attaches its menu handler.
    for _ in range(8):
        if toggle.get_attribute('aria-expanded')=='true':return
        focus(p,toggle);p.keyboard.press('Enter')
        try:
            expect(toggle).to_have_attribute('aria-expanded','true',timeout=1150)
            return
        except AssertionError:pass
    raise AssertionError(('menu did not open with Enter',active(p)))

def active(p):
    return p.evaluate("""() => {const e=document.activeElement, cs=getComputedStyle(e), r=e.getBoundingClientRect();
      const x=Math.max(0,Math.min(innerWidth-1,r.x+r.width/2)),y=Math.max(0,Math.min(innerHeight-1,r.y+r.height/2));
      const cover=document.elementFromPoint(x,y);return {tag:e.tagName,id:e.id,role:e.getAttribute('role'),name:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||'').slice(0,65),focused:e.matches(':focus-visible'),outline:cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>0,ring:cs.boxShadow!=='none',visible:r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0,uncovered:cover===e||e.contains(cover)}}""")
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
        def guard(r):
            addr=urlsplit(r.request.url)
            if addr.hostname not in (HOST,DATABASE) or (LOCAL and addr.hostname!=HOST):return r.abort()
            if r.request.method in ('GET','HEAD','OPTIONS'):return r.continue_()
            if addr.hostname==DATABASE and addr.path=='/auth/v1/signup' and not writes and not (r.request.post_data_json or {}).get('email'):
                writes.append('own anonymous sign-up');return r.continue_()
            return r.abort()
        ctx.route('**/*',guard)
        p=ctx.pages[0];p.goto(SITE+'/resources',wait_until='domcontentloaded')
        outer=p.locator('#resources-tab-guides');expect(outer).to_be_visible(timeout=45000)
        native_zoom(worker,p,1); before=metric(p)
        desktop_route=None
        if locale=='en':
            about=p.locator('header a[href="/about"]:visible').first
            focus(p,about);enter_about=active(p);p.keyboard.press('Enter')
            p.wait_for_url('**/about',timeout=45000)
            resources=p.locator('header a[href="/resources"]:visible').first
            focus(p,resources);p.keyboard.press('Enter')
            p.wait_for_url('**/resources',timeout=45000)
            desktop_route={'visited':['/resources','/about','/resources'],'about_link_focus':enter_about}
        native_zoom(worker,p,2)
        after=metric(p)
        assert abs(after['ratio']/before['ratio']-2)<.02 and abs(after['width']*2-before['width'])<6,(before,after)
        assert after['visualScale']==1,(before,after)
        if locale=='zh':assert 360<=after['width']<=405,after
        case={'locale':locale,'native_browser_zoom':2,'dimensions_100':before,'dimensions_200':after,'desktop_route_100':desktop_route}
        focus(p,outer);case['outer_tab_focus']=active(p)
        p.keyboard.press('ArrowRight')
        expect(p.locator('#resources-tab-import')).to_have_attribute('aria-selected','true')
        expect(p.locator('#resources-panel-import')).to_be_visible()
        case['outer_end_focus']=active(p)
        group=p.locator('#resources-panel-import [role="tablist"]')
        url=group.get_by_role('tab').nth(0);txt=group.get_by_role('tab').nth(1)
        focus(p,url,reverse=True);case['url_focus']=active(p)
        p.keyboard.press('ArrowRight');p.wait_for_timeout(140)
        switched=txt.get_attribute('aria-selected')=='true'
        case['inner_arrow_to_text']=switched
        case['inner_group_accessible_name']=group.get_attribute('aria-label')
        case['inner_tab_to_panel']=txt.get_attribute('aria-controls')
        case['separate_tabstops']=[tab.get_attribute('tabindex') for tab in (url,txt)]
        if not switched:
            p.keyboard.press('Tab')
            assert txt.evaluate('e=>e===document.activeElement')
            p.keyboard.press('Enter')
        area=p.locator('#resources-panel-import textarea');expect(area).to_be_visible()
        focus(p,area);p.keyboard.type('Synthetic keyboard input kept on this device')
        expect(area).to_have_value('Synthetic keyboard input kept on this device')
        case['textarea_focus']=active(p)
        case['import_geometry']=metric(p)
        print('KEYBOARD IMPORT',json.dumps(case,ensure_ascii=False),flush=True)
        p.goto(SITE+'/about',wait_until='domcontentloaded')
        toggle=p.locator('button[aria-controls="mobile-nav-panel"]')
        if toggle.is_visible():
            focus(p,toggle);case['nav_toggle_focus']=active(p)
            open_menu(p,toggle)
            dest=p.locator('#mobile-nav-panel a[href="/favorites"]')
            focus(p,dest);case['nav_link_focus']=active(p)
            p.keyboard.press('Escape');expect(toggle).to_have_attribute('aria-expanded','false')
            case['escape_restores_menu_toggle']=toggle.evaluate('e=>e===document.activeElement');case['after_menu_escape']=active(p)
            open_menu(p,toggle);focus(p,dest);p.keyboard.press('Enter')
        else:
            dest=p.locator('header a[href="/favorites"]:visible').first
            focus(p,dest);case['nav_link_focus']=active(p);p.keyboard.press('Enter')
        p.wait_for_url('**/favorites',timeout=45000)
        expect(p.locator('main h1')).to_be_visible(timeout=50000)
        case['route_visited']=urlsplit(p.url).path;case['favorites_geometry']=metric(p);case['after_route_focus']=active(p)
        case['local_input_submissions']=0;case['allowed_writes']=writes
        if LOCAL:
            assert case['inner_arrow_to_text'] and case['inner_tab_to_panel'] and case['separate_tabstops']==['-1','0'],case
            assert case.get('escape_restores_menu_toggle',True) and case['route_visited']=='/favorites',case
            assert all(case[k]['document']<=case[k]['client']+1 for k in ('import_geometry','favorites_geometry'))
        cases.append(case);print('PUBLIC KEYBOARD CASE',json.dumps(case,ensure_ascii=False),flush=True)
        ctx.close()
    print('PUBLIC KEYBOARD RECEIPT',json.dumps({'site':SITE,'environment':'Xvfb real Chromium native zoom via chrome.tabs.setZoom; keyboard Tab/Shift+Tab/arrows/Enter/Escape','sha':health,'human_screen_reader':False,'physical_phone':False,'cases':cases},ensure_ascii=False),flush=True)
