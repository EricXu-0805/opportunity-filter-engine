EXPECTED_RELEASE='1b2c5b397c4ddd374d7e2cb4115e7066185fd75d'
CASES=[{'id': 'faculty-ucb-cdss-118019dd', 'name': 'Eric Kim', 'destination_url': 'https://eric-kim.net/eric-kim-net/index.html', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://eric-kim.net/eric-kim-net/index.html', 'page_title': 'eric-kim.net'}, {'id': 'faculty-ucb-cdss-768987a3', 'name': 'Jordan Thomas Mursinna', 'destination_url': 'https://history.berkeley.edu/people/faculty/visiting/jordan-thomas-mursinna', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://history.berkeley.edu/people/faculty/visiting/jordan-thomas-mursinna', 'page_title': 'Jordan Thomas Mursinna | Department of History'}, {'id': 'faculty-ucb-cdss-cbe1719c', 'name': 'Ramesh Sridharan', 'destination_url': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'page_title': 'Data Science Undergraduate Studies Faculty | CDSS at UC Berkeley'}, {'id': 'faculty-ucb-cdss-0ac5b942', 'name': 'Michael Boots', 'destination_url': 'https://ccb.berkeley.edu/people/michael-boots', 'directory': 'https://ccb.berkeley.edu/people/core-faculty', 'final_url': 'https://ccb.berkeley.edu/people/michael-boots', 'page_title': 'Michael Boots | Center for Computational Biology'}, {'id': 'faculty-ucb-cdss-adcdda66', 'name': 'Sung-Hou Kim', 'destination_url': 'https://ccb.berkeley.edu/people/sung-hou-kim-0', 'directory': 'https://ccb.berkeley.edu/people/core-faculty', 'final_url': 'https://ccb.berkeley.edu/people/sung-hou-kim-0', 'page_title': 'Sung-Hou Kim | Center for Computational Biology'}, {'id': 'faculty-ucb-cdss-2b37be00', 'name': 'Friedrich Sommer', 'destination_url': 'https://ccb.berkeley.edu/people/friedrich-sommer', 'directory': 'https://ccb.berkeley.edu/people/core-faculty', 'final_url': 'https://ccb.berkeley.edu/people/friedrich-sommer', 'page_title': 'Friedrich Sommer | Center for Computational Biology'}, {'id': 'faculty-ucb-cdss-c0576a7c', 'name': 'Dennis Feehan', 'destination_url': 'https://dennisfeehan.org/', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://dennisfeehan.org/', 'page_title': 'Dennis M. Feehan'}, {'id': 'faculty-ucb-cdss-a4440777', 'name': 'Giles Hooker', 'destination_url': 'https://statistics.berkeley.edu/people/giles-hooker', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://statistics.berkeley.edu/people/giles-hooker', 'page_title': 'Giles Hooker | Department of Statistics'}, {'id': 'faculty-ucb-cdss-2bb51126', 'name': 'Daniel Roddy', 'destination_url': 'https://history.berkeley.edu/people/faculty/visiting/daniel-roddy', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://history.berkeley.edu/people/faculty/visiting/daniel-roddy', 'page_title': 'Daniel Roddy | Department of History'}, {'id': 'faculty-ucb-cdss-61b4cd4b', 'name': 'Eric Van Dusen', 'destination_url': 'https://cdss.berkeley.edu/people/eric-van-dusen', 'directory': 'https://cdss.berkeley.edu/dsus/data-science-undergraduate-studies-faculty', 'final_url': 'https://cdss.berkeley.edu/people/eric-van-dusen', 'page_title': 'Eric Van Dusen | CDSS at UC Berkeley'}]
import json,re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
BASE='https://joinalab.com'
SCOPE='mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
out=Path('evidence');out.mkdir(exist_ok=True)
def norm(s):return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()
def homepage(url):return urlsplit(url)._replace(fragment='').geturl().rstrip('/')
report={'at':datetime.now(timezone.utc).isoformat(),'expected_release':EXPECTED_RELEASE,'visits':[]}
with sync_playwright() as pw:
    b=pw.chromium.launch(channel='chrome');context=b.new_context(locale='en-US')
    def current_sha():return context.request.get(BASE+'/api/health').json()['release_sha']
    assert current_sha()==EXPECTED_RELEASE
    for x in CASES:
        page=context.new_page();target=None
        row={'id':x['id'],'professor':x['name']}
        try:
            source=BASE+'/opportunities/'+x['id'];d=context.request.get(BASE+'/api/opportunities/'+x['id'],params={'_release_scope':SCOPE}).json()
            assert d['id']==x['id'] and d['url']==x['destination_url'] and d['source_url']==x['directory']
            for retry in range(3):
                nav=page.goto(source,wait_until='domcontentloaded',timeout=40000)
                try:page.get_by_role('heading',name=x['name'],exact=True).first.wait_for(timeout=13000);break
                except Exception:
                    if retry==2:raise
            row.update(detail_url=source,release=page.locator('html').get_attribute('data-release-sha'),detail_http=nav.status,navigation_attempts=retry+1)
            assert row['release']==EXPECTED_RELEASE
            is_directory=x['destination_url']==x['directory']
            label='View source' if is_directory else 'View faculty profile'
            action=page.get_by_role('link',name=label,exact=True)
            assert action.count()==1 and action.get_attribute('href')==x['destination_url']
            if is_directory:assert page.get_by_role('link',name='View faculty profile',exact=True).count()==0
            welcome=page.get_by_role('dialog',name='Welcome to JoinALab')
            if len(report['visits'])==0:
                try:welcome.wait_for(state='visible',timeout=6000)
                except Exception:pass
            if welcome.is_visible():
                welcome.get_by_role('button',name='Skip tour',exact=True).click()
                school=welcome.get_by_test_id('onboarding-school-ucb')
                school.click()
                assert school.get_attribute('aria-pressed')=='true'
                welcome.get_by_test_id('onboarding-primary').click()
                welcome.wait_for(state='hidden',timeout=30000)
                row['welcome']='Selected Berkeley through the ordinary welcome dialog'
            landed=[]
            def observe(response):
                if response.request.is_navigation_request():landed.append([response.url,response.status])
            context.on('response',observe)
            if action.get_attribute('target')=='_blank':
                with context.expect_page(timeout=20000) as popup:action.click()
                target=popup.value
            else:action.click();target=page
            target.wait_for_load_state('domcontentloaded',timeout=35000)
            text=norm((target.title() or '')+' '+target.locator('body').inner_text(timeout=20000))
            tokens=norm(x['name']).split();name_found=tokens[0] in text.split() and tokens[-1] in text.split()
            row.update(primary_action=label,href=x['destination_url'],landing=target.url,official_title=target.title(),name_on_landing=name_found)
            row['official_http']=next((code for url,code in reversed(landed) if homepage(url)==homepage(target.url)),None)
            context.remove_listener('response',observe)
            assert row['official_http']==200 and homepage(target.url)==homepage(x['final_url']) and name_found
            row['passed']=True
        except Exception as exc:row.update(passed=False,error=str(exc)[:230])
        finally:
            report['visits'].append(row)
            if target and target!=page:target.close()
            page.close()
    report['release_after']=current_sha();b.close()
(out/'berkeley-destinations.json').write_text(json.dumps(report,indent=2)+'\n')
assert len(report['visits'])==10 and all(r['passed'] for r in report['visits']) and report['release_after']==EXPECTED_RELEASE
