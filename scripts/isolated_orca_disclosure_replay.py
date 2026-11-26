"""Compare Orca speech for the shipped public title markup on a loopback-only page."""
from array import array
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


TITLE='Target conditions for this draft'
SPEECH=Path(os.environ['ORCA_LOG'])
AUDIO=Path(os.environ['ORCA_AUDIO'])
# This complete event stream is from a synthetic homepage containing only
# these fixed public words. Official data and account services are not loaded.
PHRASE=re.compile(r"SPEECH OUTPUT: '([^']*)'")
WORDS=('target','conditions','for','this','draft')


def key(value):
    subprocess.run(['xdotool','key','--clearmodifiers',value],check=True)


def spoken(offset):
    with SPEECH.open('rb') as f:
        f.seek(offset)
        return PHRASE.findall(f.read().decode('utf8',errors='replace'))


def transcript(page, mark, audio_mark):
    page.wait_for_timeout(1750)
    speech=spoken(mark)
    with AUDIO.open('rb') as f:
        f.seek(audio_mark)
        data=f.read()
    samples=array('h')
    samples.frombytes(data[:len(data)//2*2])
    return {'utterances':speech[:20], 'peak':max(map(abs,samples),default=0),
            'frames':len(samples)}


def press_and_read(page, keyname, target):
    mark=SPEECH.stat().st_size
    audio_mark=AUDIO.stat().st_size
    key(keyname)
    expect(target).to_be_focused()
    return transcript(page,mark,audio_mark)


def measure_disclosure(page, url):
    page.goto(url,wait_until='load')
    page.bring_to_front()
    first=page.locator('#start')
    for _ in range(12):
        if first.evaluate('el=>document.activeElement===el'):break
        key('Tab')
        page.wait_for_timeout(160)
    expect(first).to_be_focused()
    page.wait_for_timeout(1300)
    summary=page.locator('summary')
    obs=press_and_read(page,'Tab',summary)
    full=' '.join(obs['utterances']).casefold()
    # In synthetic data log the exact words and ordering even if Orca combined
    # the title with preceding/following type or status announcements.
    obs['known_words_present']={w:w in full for w in WORDS}
    bound=any(re.match(r'^target conditions for this draft(?=$|[^a-zA-Z]|\d)',s.strip(),re.I) for s in obs['utterances'])
    obs['strict_production_extractor_would_match']=bound
    obs['contains_full_title']=TITLE.casefold() in full
    obs['dom_text']=summary.inner_text()
    obs['chromium_accessible_snapshot']=summary.aria_snapshot()
    key('Return')
    expect(page.locator('details')).to_have_attribute('open','')
    obs['expanded']=True
    return obs


def measure_dialog(page,url):
    page.goto(url,wait_until='load')
    page.bring_to_front()
    opener=page.get_by_role('button',name='Draft email')
    for _ in range(12):
        if opener.evaluate('el=>document.activeElement===el'):break
        key('Tab')
        page.wait_for_timeout(160)
    expect(opener).to_be_focused()
    key('Return')
    closed=page.get_by_role('button',name='Close email editor')
    expect(closed).to_be_focused()
    page.wait_for_timeout(1700)
    result=press_and_read(page,'Return',opener)
    mark=SPEECH.stat().st_size
    audio_mark=AUDIO.stat().st_size
    key('KP_Enter')
    result['location_query']=transcript(page,mark,audio_mark)
    result['focus_on_original_button']=True
    return result


with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
    directory=Path(tmp)
    actual_server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(directory)))
    Thread(target=actual_server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{actual_server.server_port}'
    shell='<!doctype html><html lang="en"><meta charset="utf-8"><title>Local controls</title><main><button id="start">Start control</button>'
    candidates={'unreviewed_shipped':('','Application conditions need review'),
                'sourced_shipped':('','2 sourced · 3 to review'),
                'unreviewed_with_space':(' ','Application conditions need review')}
    for name,(join,status) in candidates.items():
        (directory/(name+'.html')).write_text(shell+'<details><summary style="font-weight:600">'+TITLE+join+'<span style="margin-left:8px;font-weight:400">'+status+'</span></summary><p>Public condition source</p></details></main></html>')
    (directory/'dialog.html').write_text(shell+'<button id="opener" onclick="panel.showModal()">Draft email</button><dialog id="panel" aria-label="Editor"><button autofocus onclick="panel.close()">Close email editor</button></dialog></main></html>')
    chrome=pw.chromium.launch(channel='chromium',headless=False,args=['--no-sandbox','--force-renderer-accessibility','--disable-dev-shm-usage'])
    ctx=chrome.new_context(locale='en-US')
    ctx.route('**/*',lambda route: route.continue_() if urlparse(route.request.url).hostname=='127.0.0.1' else route.abort())
    page=ctx.new_page()
    result={'local_disclosures':{},'interface_language':'en'}
    for name in candidates:
        result['local_disclosures'][name]=measure_disclosure(page,base+'/'+name+'.html')
    result['native_dialog_return']=measure_dialog(page,base+'/dialog.html')
    for case in result['local_disclosures'].values():
        assert case['peak']>40 and case['frames']>0
    assert result['native_dialog_return']['peak']>40 and result['native_dialog_return']['focus_on_original_button']
    result['orca']=subprocess.check_output(['orca','--version'],text=True).strip()
    print('LOCAL ORCA COMPARISON',json.dumps(result,ensure_ascii=False),flush=True)
    chrome.close()
    actual_server.shutdown()
