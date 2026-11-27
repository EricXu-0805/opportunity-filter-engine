"""Read the English and Chinese source-backed facets on five ordinary public details."""
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

site = os.environ.get('SITE', 'http://127.0.0.1:3000'); release = os.environ['OFE_RELEASE_SHA'];out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
checks = json.loads(Path(__file__).with_name('53-candidate-public-route-details.json').read_text())['rows'];ids={'faculty-vt-aoe-d8633d35','faculty-vt-aoe-83afac67','faculty-vt-aoe-5572a837','faculty-vt-aoe-7ebe485f','faculty-vt-aoe-4159123a'}
rows=[r for r in checks if r['id'] in ids];assert len(rows)==5

def version():
    with urlopen(site+'/about',timeout=30) as response: front=re.search(r'data-release-sha="([0-9a-f]{40})"',response.read().decode())[1]
    with urlopen(site+'/api/health',timeout=30) as response: back=json.load(response)['release_sha']
    return [front,back]

receipt={'source':release,'start':version(),'pages':[]};assert receipt['start']==[release]*2
try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        context=browser.new_context(locale='en-US');page=context.new_page()
        page.goto(site,wait_until='domcontentloaded');tour=page.get_by_test_id('onboarding-intro')
        tour.get_by_test_id('onboarding-skip').click(timeout=45000)
        tour.get_by_test_id('onboarding-school-vt').click()
        tour.get_by_test_id('onboarding-primary').click()
        tour.wait_for(state='hidden',timeout=35000)
        receipt['completed_campus_selector']=True
        for language in ('en','zh'):
            for index,r in enumerate(rows):
                response=page.goto(site+'/opportunities/'+r['id'],wait_until='domcontentloaded',timeout=60000)
                assert response.status==200;page.get_by_role('heading',name=r['pi_name'],exact=True).first.wait_for(timeout=35000)
                if language=='zh' and not index:
                    page.get_by_role('button',name='切换到中文',exact=True).first.click()
                    page.get_by_role('button',name='Switch to English',exact=True).first.wait_for(timeout=45000)
                expect(page.locator('html')).to_have_attribute('lang',language,timeout=45000)
                for toggle in page.get_by_role('main').locator('details:not([open]) > summary').all():
                    if toggle.is_visible():toggle.click()
                root='fact-professor_or_lab-';section=page.get_by_test_id(root+'faculty_directory_section');section.wait_for(timeout=35000)
                expect(section).to_contain_text(re.compile('院系名录分组' if language=='zh' else 'department directory section',re.I),timeout=35000)
                assert r['group'] in section.inner_text()
                assert page.get_by_test_id(root+'faculty_directory_section-quote-source').get_by_role('link').get_attribute('href')=='https://www.aoe.vt.edu/people/faculty.html'
                role=page.get_by_test_id(root+'faculty_rank'); assert role.is_visible()
                if r['role']:
                    assert r['role'] in role.inner_text()
                    assert page.get_by_test_id(root+'faculty_rank-quote-source').get_by_role('link').get_attribute('href')==r['profile_url']
                else:
                    assert role.get_attribute('data-state')=='unknown',role.inner_text()
                    assert not page.get_by_test_id(root+'faculty_rank-quote-source').count()
                receipt['pages'].append({'id':r['id'],'language':language,'name':r['pi_name'],'group':section.inner_text(),'title':role.inner_text(),'status':response.status});(out/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
                if r['id']=='faculty-vt-aoe-7ebe485f':section.screenshot(path=str(out/('adjunct-section-'+language+'.png')))
        context.close()
        browser.close()
finally:
    receipt['end']=version();(out/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
assert receipt['end']==receipt['start'] and len(receipt['pages'])==10
