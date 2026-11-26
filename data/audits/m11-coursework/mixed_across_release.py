"""Keep one newly created synthetic guest in memory while the résumé format changes."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from check import SITE, confirm_school, expect, home, reads, sessions, sync_playwright, writes

OLD = '77603b9e0afac651bcd82428e6c59494aaa5b1ce'
START = datetime.now(timezone.utc).isoformat()
MARKER = 'Legacy synthetic mixed source during application upgrade.'
WARNING = 'Some pages have no readable text. Check the original PDF for missing content before using the extracted text.'
out = Path('m11-results')
out.mkdir(exist_ok=True)
receipt = {'stage':'starting','site':SITE,'start':START}

def report(stage):
    receipt['stage']=stage
    (out/'mixed-across-release.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(stage,flush=True)

def read_url(url):
    with urlopen(Request(url,headers={'User-Agent':'OFE-Routine-Release-Check'}),timeout=30) as res:
        return res.read()

def versions():
    html=read_url(SITE).decode()
    front=re.search(r'data-release-sha="([a-f0-9]{40})"',html)[1]
    return front,json.loads(read_url(SITE+'/api/health'))['release_sha']

assert versions()==(OLD,OLD)
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    earlier=home(browser)
    for _ in range(100):
        earlier.wait_for_timeout(200)
        if sessions and not earlier.get_by_test_id('hydration-note').is_visible():break
    assert len(sessions)==1 and earlier.locator('html').get_attribute('data-release-sha')==OLD
    confirm_school(earlier)
    earlier.locator('#student_name').fill('Synthetic legacy résumé check')
    earlier.locator('#college').select_option(label='Grainger College of Engineering')
    earlier.locator('#major').select_option(label='Computer Science')
    earlier.locator('#grade').select_option(label='Sophomore')
    document=browser.new_page()
    document.set_content('<div style="break-after:page"><p>'+MARKER+'</p><p>Coursework: Linear Algebra</p></div>'
                         '<svg width="100" height="80"><rect width="85" height="50" fill="teal"/></svg>')
    mixed=document.pdf();document.close()
    upload={'name':'own-synthetic-mixed-résumé.pdf','mimeType':'application/pdf','buffer':mixed}
    earlier.locator('input[type=file][accept*="pdf"]').first.set_input_files(upload)
    expect(earlier.get_by_text(WARNING,exact=True)).to_be_visible(timeout=55000)
    expect(earlier.get_by_text('Linear Algebra',exact=True).first).to_be_visible()
    earlier.wait_for_timeout(2500)
    old_read=home(browser,sessions[0])
    expect(old_read.get_by_role('button',name='Remove file',exact=True)).to_be_visible(timeout=55000)
    entry=next(r for r in reversed(reads) if MARKER in r['profile_data'].get('resume_text',''))
    legacy=entry['profile_data'];old_revision=entry['revision']
    assert not legacy.get('resume_incomplete_digest') and legacy['coursework']==['Linear Algebra']
    assert old_read.locator('html').get_attribute('data-release-sha')==OLD and versions()==(OLD,OLD)
    original_hash=sha256(legacy['resume_text'].encode()).hexdigest()
    receipt.update(old_version=OLD,old_revision=old_revision,original_source_sha256=original_hash,old_digest_absent=True)
    report('legacy-guest-saved-and-read')
    for _ in range(95):
        time.sleep(60)
        try:
            front,back=versions()
            if front==back and front!=OLD:
                pr=json.loads(read_url('https://api.github.com/repos/EricXu-0805/opportunity-filter-engine/pulls/1380'))
                if pr['merged'] and pr['merge_commit_sha']==front:break
        except (KeyError,IndexError,OSError,ValueError):
            continue
    else:raise TimeoutError('Released frontend and backend did not both reach the eighth batch.')
    before=len(reads)
    new_read=home(browser,sessions[0])
    expect(new_read.get_by_role('button',name='Remove file',exact=True)).to_be_visible(timeout=55000)
    expect(new_read.get_by_text('Linear Algebra',exact=True).first).to_be_visible()
    expect(new_read.get_by_text(WARNING,exact=True)).to_have_count(0)
    assert new_read.locator('html').get_attribute('data-release-sha')==front
    untouched=next(r for r in reads[before:] if MARKER in r['profile_data'].get('resume_text',''))
    assert untouched['revision']==old_revision and untouched['profile_data']==legacy
    new_read.locator('input[type=file][accept*="pdf"]').first.set_input_files(upload)
    expect(new_read.get_by_text(WARNING,exact=True)).to_be_visible(timeout=50000)
    for _ in range(120):
        new_read.wait_for_timeout(150)
        if writes and writes[-1]>old_revision:break
    before=len(reads)
    final=home(browser,sessions[0])
    expect(final.get_by_text(WARNING,exact=True)).to_be_visible(timeout=55000)
    current=next(r for r in reversed(reads[before:]) if r['revision']>old_revision)
    data=current['profile_data']
    assert data['resume_text']==legacy['resume_text'] and data['coursework']==legacy['coursework']
    assert data['resume_incomplete_digest']==original_hash and versions()==(front,back)
    receipt.update(new_version=front,new_revision=current['revision'],legacy_profile_unchanged_before_reupload=True,
                   same_file_reupload_attached_warning=True,warning_survived_independent_browser=True,
                   finish=datetime.now(timezone.utc).isoformat())
    report('same-guest-upgrade-confirmed')
    browser.close()
