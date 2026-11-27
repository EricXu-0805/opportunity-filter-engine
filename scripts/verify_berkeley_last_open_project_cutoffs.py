from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from bs4 import BeautifulSoup
import hashlib,json,re,requests
from playwright.sync_api import sync_playwright

base='https://joinalab.com'
import os
sha=os.environ['OFE_EXPECTED_SITE_SHA']
ids=[('ucb-urap-proj-5c5989122fc1','20081-1'),('ucb-urap-proj-4029d15a89db','20152-2')]
where=Path(os.environ['RUNNER_TEMP'])/'berkeley-last-open'
where.mkdir(exist_ok=True)
def get(url):
    last=None
    for attempt in range(2):
        try:
            r=requests.get(url,timeout=(8,24));r.raise_for_status();return r
        except requests.RequestException as error:
            last=error
    raise last
def endpoints():
    with ThreadPoolExecutor(2) as ex:
        health,page=list(ex.map(get,[base+'/api/health',base+'/about']))
    return [health.json()['release_sha'],re.search(r'data-release-sha="([a-f0-9]{40})"',page.text)[1]]
def source(identity):
    oid,pid=identity
    url='https://urapprojects.berkeley.edu/detail.php?id='+pid
    school=get(url)
    
    api=get(base+'/api/opportunities/'+oid+'?_release_scope=mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2').json()
    soup=BeautifulSoup(school.content,'html.parser')
    h=[x.get_text(' ',strip=True) for x in soup.select('h3')]
    notice=next(x.strip() for x in soup.stripped_strings if 'deadline to apply is Monday, August 31st, 4pm' in x)
    assert api['title'] in h and 'Fall 2026' in soup.stripped_strings
    assert api['target_truth']['reference_only'] and not api['target_truth']['actionable']
    return {'id':oid,'school_project_id':pid,'title':api['title'],'official_url':url,'university_http':school.status_code,'official_term':'Fall 2026','official_notice':notice[notice.index('The deadline'):], 'roster_page_status':'Open','fetched_source_hash':hashlib.sha256(school.content).hexdigest(),'api_deadline':api.get('deadline'),'api_cutoff':api['target_truth']['expires_at'],'api_closed_reference':True}
start=endpoints()
assert start==[sha,sha],start
with ThreadPoolExecutor(2) as ex: rows=list(ex.map(source,ids))
with sync_playwright() as pw:
    b=pw.chromium.launch(channel='chrome',headless=True)
    p=b.new_page(locale='en-US')
    for item in rows:
        resp=p.goto(base+'/opportunities/'+item['id'],wait_until='domcontentloaded',timeout=55000)
        p.get_by_role('heading',name=item['title'],exact=True).wait_for()
        main=p.locator('main')
        text=main.inner_text()
        checks={'date_visible':bool(re.search(r'(?:Aug(?:ust)?\s+31|08/31|2026-08-31|8/31)',text,re.I)),
                'apply_now_count':main.get_by_role('link',name='Apply now',exact=True).count(),'open_application_count':main.get_by_role('link',name='Open application page',exact=True).count(),
                'source_link_visible':bool(main.locator('a').evaluate_all('(xs,url)=>xs.some(x=>x.href===url && x.getBoundingClientRect().width>0)',item['official_url']))}
        assert resp.ok and p.locator('html').get_attribute('data-release-sha')==sha and not checks['apply_now_count'] and not checks['open_application_count']
        item.update(checks)
        
    b.close()
end=endpoints();assert end==start
out={'started_release':start,'finished_release':end,'last_observed_utc':datetime.now(UTC).isoformat(),'rows':rows}
(where/'readback.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
for r in rows: print(r['school_project_id'],r['api_deadline'],r['api_cutoff'],r['date_visible'],r['source_link_visible'])
