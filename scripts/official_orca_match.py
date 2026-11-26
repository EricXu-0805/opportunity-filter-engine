"""Verify official results and their free draft using native X11 keyboard events and Orca."""
from array import array
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


SITE = 'https://joinalab.com'
DB = 'mjpirkyduibkakvlbdko.supabase.co'
TARGET = 'faculty-ib-78788e71'
SEARCH = 'Mark Jason Lara'
NAME = 'Synthetic ecological methods keyboard check'
LABELS = {
    'en': {'category': 'All', 'draft': 'Draft email', 'conditions': 'Target conditions for this draft',
           'body': 'Body', 'close': 'Close email editor'},
    'zh': {'category': '全部', 'draft': '起草邮件', 'conditions': '本次参考的目标条件',
           'body': '正文', 'close': '关闭邮件编辑器'},
}
SAFE_LABELS = {label for labels in LABELS.values() for label in labels.values()} | {'所有'}
SAFE_ROLES = {'push button','button','page tab','tab list','multi-line','text','entry','panel',
              'expanded','collapsed','toggle button','selected','not selected','text area','editable'}
ORCA_OUTPUT = re.compile(r"SPEECH OUTPUT: '(.*)'(?:\s+\{|\s*$)")


def tokens(utterance):
    # Save only public interface labels and a fixed set of role/state words. Neither
    # the full Orca event stream nor the draft or account's form data is recorded.
    clean = utterance.strip().casefold()
    result = []
    for label in sorted(SAFE_LABELS):
        needle = label.casefold()
        if clean.startswith(needle):
            tail = clean[len(needle):]
            if not needle.isascii() or not tail or not tail[0].isalnum() or tail[0].isdigit():
                result.append(label)
    result.extend(role for role in sorted(SAFE_ROLES) if clean == role)
    return result


def filter_speech(fifo, destination):
    with open(fifo,encoding='utf-8',errors='replace') as source, open(destination,'w',buffering=1) as out:
        for line in source:
            match = ORCA_OUTPUT.search(line)
            if match:
                accepted = tokens(match.group(1))
                if accepted:
                    print(json.dumps([time.monotonic(),accepted],ensure_ascii=False),file=out)


def filter_audio(destination):
    with open(destination,'w',buffering=1) as out:
        while block := sys.stdin.buffer.read(3200):
            samples=array('h')
            samples.frombytes(block[:len(block)//2*2])
            if samples:
                print(json.dumps([time.monotonic(),max(map(abs,samples)),len(samples)]),file=out)


def xkey(name):
    subprocess.run(['xdotool','key','--clearmodifiers',name],check=True)


def records(path, since):
    entries = []
    for line in path.read_text().splitlines():
        try:
            rec=json.loads(line)
        except ValueError:
            continue
        if rec[0]>=since:
            entries.append(rec)
    return entries


def landing(page, target, keyname='Tab'):
    for _ in range(180):
        start=time.monotonic()
        xkey(keyname)
        page.wait_for_timeout(170)
        if target.evaluate('e=>e===document.activeElement'):
            return start
    raise AssertionError('Control unreachable by native keyboard')


def heard(page, target, locale, control, start, keyname):
    from playwright.sync_api import expect
    expect(target).to_be_focused(timeout=5000)
    labels=[LABELS[locale][control]]
    if locale=='zh' and control=='category':
        labels.append('所有')
    speech=Path(os.environ['ORCA_SAFE_SPEECH'])
    audio=Path(os.environ['ORCA_SAFE_AUDIO'])
    def wait_for_speech(since):
        found=[]
        for _ in range(32):
            page.wait_for_timeout(150)
            found=[token for _,items in records(speech,since) for token in items]
            if any(label in found for label in labels):
                break
        return found
    spoken=wait_for_speech(start)
    spoken_on_key=any(label in spoken for label in labels)
    page.wait_for_timeout(1500)
    frames=records(audio,start)
    query=[]
    if not spoken_on_key:
        later=time.monotonic()
        xkey('KP_Enter')
        query=wait_for_speech(later)
    metrics=target.evaluate("""el=>({visible_focus:el.matches(':focus-visible'),tag:el.tagName})""")
    entry={'control':control,'key':keyname,'spoken_label_after_key':[s for s in spoken if s in labels],
           'spoken_roles':sorted({s for s in spoken if s in SAFE_ROLES}),'heard_on_key':spoken_on_key,
           'query_labels':[s for s in query if s in labels], 'peak_after_key':max((f[1] for f in frames),default=0),
           'frames_after_key':sum(f[2] for f in frames),**metrics}
    print('READER CONTROL',locale,json.dumps(entry,ensure_ascii=False),flush=True)
    return entry


def deployed(probe):
    release=probe.get(SITE+'/api/health').json()['release_sha']
    assert re.fullmatch('[a-f0-9]{40}',release)
    assert 'data-release-sha="'+release+'"' in probe.get(SITE+'/about').text()
    return release


def exercise(pw, root, locale, width):
    from playwright.sync_api import expect
    chrome=pw.chromium.launch_persistent_context(str(root/locale),channel='chromium',headless=False,no_viewport=True,
        locale='en-US',args=['--no-sandbox','--force-renderer-accessibility','--disable-dev-shm-usage',
        '--window-size='+str(width)+',940','--disable-extensions-except='+str(root/'ext'),'--load-extension='+str(root/'ext')])
    page=chrome.pages[0]
    worker=chrome.service_workers[0] if chrome.service_workers else chrome.wait_for_event('serviceworker',timeout=40000)
    owner=[];signups=[];revisions=[];draft_counts=[]
    def received(r):
        u=urlsplit(r.url)
        if not r.ok:
            return
        if u.hostname==DB and u.path=='/auth/v1/signup':
            user=r.json()['user']
            assert user['is_anonymous'] and not owner
            owner.append(user['id'])
        if u.hostname==DB and u.path.endswith('/rpc/commit_profile_patch_cas') and r.json().get('status')=='applied':
            revisions.append(r.json()['revision'])
        if u.hostname=='joinalab.com' and u.path=='/api/cold-email/variants':
            draft_counts.append(len(r.json()['variants']))
    def restrict(route):
        r=route.request
        u=urlsplit(r.url)
        if u.hostname not in ('joinalab.com',DB):
            return route.abort()
        if r.method in ('GET','HEAD','OPTIONS'):
            return route.continue_()
        if r.method=='POST':
            data=r.post_data_json or {}
            if u.hostname==DB:
                if u.path=='/auth/v1/signup' and not signups and not data.get('email'):
                    signups.append(True)
                    return route.continue_()
                if u.path=='/auth/v1/token' and owner:
                    return route.continue_()
                if u.path.endswith('/rpc/commit_profile_patch_cas') and owner and data.get('p_expected_device_id')==owner[0]:
                    return route.continue_()
            if u.hostname=='joinalab.com' and u.path=='/api/matches/view' and 'llm=false' in u.query:
                return route.continue_()
            if (u.hostname=='joinalab.com' and u.path=='/api/cold-email/variants' and owner
                    and data.get('opportunity_id')==TARGET and data.get('profile',{}).get('name')==NAME):
                return route.continue_()
        return route.abort()
    chrome.on('response',received)
    chrome.route('**/*',restrict)
    chrome.add_cookies([{'name':'ofe_lang','value':'en','url':SITE}])
    prefs={'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00Z'})}
    chrome.add_init_script("if(location.origin==="+json.dumps(SITE)+"&&!localStorage.getItem('reader-match-qa')){for(const[k,v]of Object.entries("+json.dumps(prefs)+"))localStorage.setItem(k,v);localStorage.setItem('reader-match-qa','1')}")
    page.goto(SITE,wait_until='domcontentloaded')
    page.bring_to_front()
    expect(page.locator('#student_name')).to_be_visible(timeout=65000)
    for _ in range(180):
        if owner and not page.get_by_test_id('hydration-note').is_visible():
            break
        page.wait_for_timeout(200)
    assert owner
    school=page.get_by_test_id('university-card-uiuc')
    if school.is_visible():
        school.click()
        page.get_by_test_id('switcher-confirm').click()
    page.locator('#student_name').fill(NAME)
    page.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
    page.locator('#major').select_option(label='Integrative Biology')
    page.locator('#grade').select_option(label='Junior')
    page.locator('#research_interests').fill('Wetlands, ecology and GIS')
    for _ in range(180):
        if revisions:
            break
        page.wait_for_timeout(200)
    assert revisions
    if locale=='zh':
        chrome.add_cookies([{'name':'ofe_lang','value':'zh','url':SITE}])
        page.evaluate("localStorage.setItem('ofe_lang','zh')")
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#student_name')).to_have_value(NAME,timeout=60000)
    def size():
        return page.evaluate('()=>({width:innerWidth,ratio:devicePixelRatio,visualScale:visualViewport.scale})')
    before=size()
    zoom=worker.evaluate("async url=>{const [t]=await chrome.tabs.query({url});await chrome.tabs.setZoom(t.id,2);return await chrome.tabs.getZoom(t.id)}",SITE+'/*')
    page.wait_for_timeout(450)
    after=size()
    assert zoom==2 and abs(after['ratio']/before['ratio']-2)<.01 and abs(2*after['width']-before['width'])<6
    assert after['visualScale']==1 and abs(after['width']-width/2)<6
    landing(page,page.get_by_test_id('generate-matches'))
    xkey('Return')
    page.wait_for_url('**/results**',timeout=90000)
    group=page.get_by_role('tablist').filter(has=page.get_by_role('tab',name=re.compile(r'^(All|全部|所有)')))
    first=group.get_by_role('tab').first
    expect(first).to_be_visible(timeout=70000)
    if first.get_attribute('tabindex')=='-1':
        landing(page,group.locator('[aria-selected=true]'))
        start=time.monotonic()
        xkey('Home')
        first_key='Home'
    else:
        start=landing(page,first)
        first_key='Tab'
    controls=[heard(page,first,locale,'category',start,first_key)]
    xkey('Return')
    expect(first).to_have_attribute('aria-selected','true',timeout=40000)
    search=page.locator('#results-search-input')
    landing(page,search)
    def searched(r):
        u=urlsplit(r.url)
        return u.path=='/api/matches/view' and r.ok and r.request.post_data_json.get('view',{}).get('search_query')==SEARCH
    with page.expect_response(searched,timeout=90000) as response:
        subprocess.run(['xdotool','type','--clearmodifiers','--delay','30',SEARCH],check=True)
    assert TARGET in [o['opportunity_id'] for o in response.value.json()['results']]
    card=page.locator('#match-card-'+TARGET)
    draft=card.get_by_role('button',name=LABELS[locale]['draft'],exact=True)
    expect(draft).to_be_enabled(timeout=70000)
    controls.append(heard(page,draft,locale,'draft',landing(page,draft),'Tab'))
    xkey('Return')
    body=page.locator('#cold-email-body')
    expect(body).to_be_visible(timeout=60000)
    for _ in range(180):
        if draft_counts and body.input_value():
            break
        page.wait_for_timeout(200)
    assert draft_counts==[3] and bool(body.input_value()),'Three free drafts did not become available'
    cond=page.get_by_test_id('email-target-conditions').locator('summary').first
    expect(cond).to_be_visible()
    controls.append(heard(page,cond,locale,'conditions',landing(page,cond),'Tab'))
    xkey('Return')
    expect(cond.locator('..')).to_have_attribute('open','')
    controls.append(heard(page,body,locale,'body',landing(page,body),'Tab'))
    close=page.get_by_role('button',name=LABELS[locale]['close'],exact=True)
    controls.append(heard(page,close,locale,'close',landing(page,close,'shift+Tab'),'Shift+Tab'))
    start=time.monotonic()
    xkey('Return')
    expect(body).to_have_count(0,timeout=25000)
    expect(draft).to_be_focused()
    returned=heard(page,draft,locale,'draft',start,'Return on Close')
    returned['control']='returned to original draft button'
    controls.append(returned)
    print('READER CASE COMPLETE',locale,flush=True)
    result={'locale':locale,'actual_page_lang':page.locator('html').get_attribute('lang'),'zoom':zoom,
            'before':before,'after':after,'tested_opportunity_id':TARGET,'free_variant_count':3,
            'returned_to_original_card':True,'controls':controls,'external_messages':0}
    chrome.close()
    return result


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        root=Path(tmp)
        ext=root/'ext'
        ext.mkdir()
        (ext/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Native tab zoom','version':'1',
            'permissions':['tabs'],'host_permissions':[SITE+'/*'],'background':{'service_worker':'zoom.js'}}))
        (ext/'zoom.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        http=pw.request.new_context()
        release=deployed(http)
        assert release==os.environ['OFE_EXPECTED_SITE_SHA'],('Release moved before first guest', release)
        results=[]
        for language,width in [('en',1400),('zh',780)]:
            results.append(exercise(pw,root,language,width))
        assert deployed(http)==release, 'Release changed during the run'
        http.dispose()
        receipt={'site':SITE,'release':release,'reader':subprocess.check_output(['orca','--version'],text=True).strip(),
                 'reader_interface_language':'en','human_listener':False,'physical_device':False, 'cases':results}
        print('OFFICIAL MATCH READER RECEIPT',json.dumps(receipt,ensure_ascii=False),flush=True)


if __name__=='__main__':
    if sys.argv[1:2]==['speech']:
        filter_speech(*sys.argv[2:])
    elif sys.argv[1:2]==['audio']:
        filter_audio(*sys.argv[2:])
    else:
        main()
