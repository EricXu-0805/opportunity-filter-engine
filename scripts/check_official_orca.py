"""Record keyboard-triggered Orca speech from public screens in a disposable X11 desktop."""
from array import array
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


SITE = 'https://joinalab.com'
SPEECH = Path(os.environ['ORCA_LOG'])
AUDIO = Path(os.environ['ORCA_AUDIO'])
speech_line = re.compile(r"""SPEECH OUTPUT: '([^']*)'""")
cases = []


def key(name):
    subprocess.run(['xdotool', 'key', '--clearmodifiers', name], check=True)


def speech_from(offset):
    with SPEECH.open('rb') as f:
        f.seek(offset)
        return speech_line.findall(f.read().decode('utf-8', errors='replace'))


def matches(phrases, spoken):
    return any(part.casefold() in utterance.casefold() for part in phrases for utterance in spoken)


def measure(page, target, phrases, screen, locale):
    expect(target).to_be_visible(timeout=65000)
    # Capture the first genuine forward Tab that lands on the target. Resetting
    # focus and announcing the same element twice can cause Orca to suppress it.
    for _ in range(145):
        offset = SPEECH.stat().st_size
        audio_start = AUDIO.stat().st_size
        key('Tab')
        page.wait_for_timeout(180)
        if target.evaluate('el => el === document.activeElement'):
            break
    else:
        raise AssertionError('Target unreachable by forward Tab: '+str(target))
    spoken = []
    for _ in range(35):
        page.wait_for_timeout(200)
        spoken = [line.strip() for line in speech_from(offset) if line.strip()]
        if matches(phrases,spoken):
            break
    announced = matches(phrases,spoken)
    query = []
    if not announced:
        # Orca desktop layout: keypad Enter asks the reader Where Am I.
        query_offset = SPEECH.stat().st_size
        key('KP_Enter')
        for _ in range(25):
            page.wait_for_timeout(200)
            query = [line.strip() for line in speech_from(query_offset) if line.strip()]
            if matches(phrases, query):
                break
    page.wait_for_timeout(2500)
    with AUDIO.open('rb') as f:
        f.seek(audio_start)
        data = f.read()
    samples = array('h')
    samples.frombytes(data[:len(data)//2*2])
    peak = max(map(abs, samples), default=0)
    result = {'page':screen, 'page_language': page.locator('html').get_attribute('lang'),
              'expected_label_part':phrases, 'orca_speech':spoken[:15],
              'announced_on_forward_tab':announced, 'where_am_i_if_needed':query[:15],
              'announced_on_where_am_i':matches(phrases,query), 'synthesis_peak_signed_16_bit':peak,'recorded_audio_frames':len(samples)}
    assert peak>40, (screen,locale,'no synthesizer audio',peak)
    print('ORCA FOCUS', json.dumps(result, ensure_ascii=False), flush=True)
    return result


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
    health = pw.request.new_context()
    release = health.get(SITE+'/api/health').json()['release_sha']
    assert 'data-release-sha="'+release+'"' in health.get(SITE+'/about').text()
    for locale, width in [('en',1350), ('zh',520)]:
        ctx = pw.chromium.launch_persistent_context(str(Path(tmp)/locale),channel='chromium',
            headless=False, no_viewport=True, locale='zh-CN' if locale=='zh' else 'en-US',
            args=['--no-sandbox','--force-renderer-accessibility','--disable-dev-shm-usage',
                  '--window-size='+str(width)+',860', '--disable-session-crashed-bubble'])
        ctx.add_cookies([{'name':'ofe_lang','value':locale,'url':SITE}])
        prefs = {'ofe_lang':locale,'ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00Z'})}
        ctx.add_init_script('if(location.origin === '+json.dumps(SITE)+'){for(const[k,v]of Object.entries('+json.dumps(prefs)+'))localStorage.setItem(k,v)}')
        signup = []
        def restrict(route):
            req = route.request
            origin = urlsplit(req.url)
            if origin.hostname not in ('joinalab.com','mjpirkyduibkakvlbdko.supabase.co'):
                return route.abort()
            if req.method in ('GET','HEAD','OPTIONS'):
                return route.continue_()
            if req.method=='POST' and origin.hostname=='mjpirkyduibkakvlbdko.supabase.co' and origin.path=='/auth/v1/signup' and not signup and not (req.post_data_json or {}).get('email'):
                signup.append(True)
                return route.continue_()
            return route.abort()
        ctx.route('**/*',restrict)
        page=ctx.pages[0]
        page.goto(SITE+'/', wait_until='domcontentloaded')
        page.bring_to_front()
        name=page.locator('#student_name')
        expect(name).to_be_visible(timeout=65000)
        # Read the visible label, then independently check the real reader's speech
        # after an X11 keyboard focus change. Punctuation may be spoken separately.
        label=name.evaluate("el => el.labels[0].innerText.trim()")
        phrase=re.split(r'[（(＊*\n]',label)[0].strip()
        results=[measure(page,name,[phrase], 'profile', locale)]
        page.goto(SITE+'/resources',wait_until='domcontentloaded')
        tab=page.locator('#resources-tab-guides')
        expect(tab).to_be_visible(timeout=60000)
        results.append(measure(page,tab,[tab.inner_text().strip()], 'resources', locale))
        page.goto(SITE+'/tracker',wait_until='domcontentloaded')
        link=page.locator('main a[href="/results"],main a[href="/"]').filter(has_text=re.compile('Go to results|去结果页|Open your profile|打开个人资料')).first
        expect(link).to_be_visible(timeout=65000)
        results.append(measure(page,link,[link.inner_text().strip()], 'empty tracker', locale))
        assert signup
        cases.append({'locale':locale,'viewport_width':page.evaluate('innerWidth'), 'routes':results})
        ctx.close()
    assert release==health.get(SITE+'/api/health').json()['release_sha']
    assert 'data-release-sha="'+release+'"' in health.get(SITE+'/about').text()
    health.dispose()
    print('ORCA RECEIPT',json.dumps({'site':SITE,'release':release,'reader':subprocess.check_output(['orca','--version'],text=True).strip(),'cases':cases,'profile_writes':0,'messages':0},ensure_ascii=False))
