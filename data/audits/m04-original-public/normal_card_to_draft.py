"""Read a displayed match reason and the free draft opened from the same original card."""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

SITE = 'https://joinalab.com'
CASES = {
    'caltech': ('faculty-caltech-phys-b6dd07e7', 'Sergei Gukov', 'Physics', 'mathematical physics, quantum field theory'),
    'uiuc': ('simplify-intern-3ea65aaa-0297-4b8f-9378-51e35478fb95', 'Data Engineer Intern', 'Computer Science', 'data engineering, data science, Python'),
}
CAMPUS = os.environ['CAMPUS']
OID, TITLE, MAJOR, INTERESTS = CASES[CAMPUS]
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'site': SITE, 'campus': CAMPUS, 'id':OID, 'account':{}}

def version():
    with urlopen(SITE + '/api/health', timeout=45) as response:
        back = json.load(response)['release_sha']
    with urlopen(SITE + '/about', timeout=45) as response:
        front = re.search(r'data-release-sha="(\w{40})"', response.read().decode())[1]
    return dict(front=front, back=back)


def save():
    (OUT/'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def field(page, key, free_text, preferences):
    control = page.locator('#' + key)
    if control.evaluate('e => e.tagName') != 'SELECT':
        control.fill(free_text)
        return free_text
    control.locator("option:not([value='']):not([disabled])").first.wait_for(state='attached', timeout=30000)
    options = control.locator("option:not([value='']):not([disabled])").evaluate_all(
        'items => items.map(x => ({v:x.value, label:x.textContent.trim()}))')
    choice = next((x for term in preferences for x in options if term in x['label'].casefold()), options[0])
    control.select_option(choice['v'])
    return choice['label']


def onboarding(page):
    account = receipt['account']
    page.goto(SITE, wait_until='domcontentloaded')
    tour = page.get_by_test_id('onboarding-intro')
    tour.get_by_test_id('onboarding-skip').click(timeout=45000)
    tour.get_by_test_id('onboarding-school-' + CAMPUS).click()
    assert tour.get_by_test_id('onboarding-school-' + CAMPUS).get_attribute('aria-pressed') == 'true'
    account['onboarding_attempts'] = []
    for _ in range(3):
        tour.get_by_test_id('onboarding-primary').click()
        try:
            tour.wait_for(state='hidden', timeout=10000)
            account['onboarding_attempts'].append('closed')
            break
        except Exception:
            error = tour.get_by_test_id('onboarding-error')
            account['onboarding_attempts'].append(error.inner_text() if error.is_visible() else 'school confirmation still open')
            page.screenshot(path=OUT/'campus-confirmation-retry.png')
            save()
            page.wait_for_timeout(3500)
    tour.wait_for(state='hidden', timeout=20000)
    page.locator('#student_name').wait_for()
    page.get_by_test_id('hydration-note').wait_for(state='hidden',timeout=45000)
    page.get_by_test_id('profile-refresh-status').wait_for(state='hidden',timeout=45000)
    page.locator('#student_name').fill('Example Student')
    college = 'Division of Physics, Mathematics and Astronomy' if CAMPUS == 'caltech' else 'Grainger College of Engineering'
    account['college'] = field(page, 'college', college, [college.lower(), 'physics' if CAMPUS == 'caltech' else 'engineering'])
    account['major'] = field(page, 'major', MAJOR, [MAJOR.lower()])
    page.locator('#grade').select_option(label='Junior')
    page.locator('#research_interests').fill(INTERESTS)
    if CAMPUS == 'uiuc':
        seeking = page.locator('fieldset').filter(has=page.get_by_text('Preferred Opportunity Types', exact=True))
        option = seeking.get_by_role('button', name=re.compile('internship', re.I))
        if option.get_attribute('aria-pressed') != 'true':
            option.click()
    page.locator('#grade').focus()
    for _ in range(160):
        if account.get('signup') == 200 and account.get('profile_commit') == 'applied': break
        page.wait_for_timeout(250)
    assert account.get('profile_commit') == 'applied' and account.get('signup') == 200
    save()


def run():
    receipt['start'] = version()
    assert receipt['start']['front'] == receipt['start']['back']
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        ctx=browser.new_context(locale='en-US', service_workers='block', viewport={'width':1200,'height':1000})
        drafted={}
        def guard(route):
            req=route.request
            u=urlsplit(req.url)
            if u.scheme == 'mailto' or u.hostname in ('mail.google.com','outlook.office.com','outlook.live.com'):return route.abort()
            if req.method=='POST' and u.hostname=='joinalab.com' and u.path.startswith('/api/'):
                if u.path in ('/api/events','/api/health'):return route.continue_()
                if u.path=='/api/matches/view' and 'llm=false' in u.query:return route.continue_()
                if u.path=='/api/cold-email/variants' and req.post_data_json.get('opportunity_id')==OID:return route.continue_()
                return route.abort()
            return route.continue_()
        def observe(response):
            path=urlsplit(response.url).path
            if path=='/auth/v1/signup':receipt['account']['signup']=response.status
            if path.endswith('/rpc/commit_profile_patch_cas') and response.ok:
                x=response.json()
                if isinstance(x,list):x=x[0] if x else {}
                if x.get('status')=='applied':receipt['account']['profile_commit']='applied'
            if path=='/api/matches/view' and response.ok and response.request.method=='POST':
                for row in response.json().get('results',[]):
                    opp=row.get('opportunity',{})
                    if opp.get('id')==OID:
                        receipt['card_api']={'kind':opp.get('record_kind'),'contact':opp.get('contact_email_status'),
                            'next_steps':row.get('next_steps'),'http':response.status,'title':opp.get('title'),'ai_refined':response.json().get('ai_refined')}
            if path=='/api/cold-email/variants' and response.ok:
                data=response.json()
                assert response.request.post_data_json['opportunity_id']==OID
                drafted.update({v['id']:(v['subject'].strip(),v['body'].strip()) for v in data['variants']})
        ctx.route('**/*',guard)
        ctx.on('response',observe)
        ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');}")
        page=ctx.new_page()
        page.set_default_timeout(45000)
        onboarding(page)
        page.goto(SITE+'/opportunities/'+OID,wait_until='domcontentloaded')
        main=page.get_by_role('main')
        main.get_by_role('heading',level=1,name=TITLE,exact=True).wait_for(timeout=75000)
        main.get_by_role('button',name='Add to favorites',exact=True).click()
        main.get_by_role('button',name='Remove from favorites',exact=True).wait_for()
        query='Gukov' if CAMPUS=='caltech' else 'Octaura'
        page.goto(SITE+'/results?'+urlencode({'tab':'starred','q':query,'ai':'0'}),wait_until='domcontentloaded')
        card=page.locator('#match-card-'+OID)
        card.wait_for(timeout=95000)
        assert TITLE in card.get_by_role('heading',level=3).inner_text()
        card.get_by_role('button',name='Show details',exact=True).click()
        why=card.get_by_role('heading',name='Why it fits',exact=True)
        why.wait_for()
        reasons=why.locator('..').locator('li').all_inner_texts()
        assert reasons and all(r.strip() for r in reasons)
        receipt['visible_reasons']=reasons
        raw=receipt['card_api']
        assert raw['http']==200 and raw['ai_refined'] is False
        if CAMPUS=='caltech':
            assert raw['kind']=='faculty_contact' and raw['contact']=='unavailable'
            label=card.get_by_text('Faculty profile · openings not confirmed',exact=True)
            label.wait_for()
            personal=card.get_by_role('link',name='Faculty page',exact=True)
            receipt['faculty_link']={'url':personal.get_attribute('href'),'primary_style': 'bg-indigo-600' in (personal.get_attribute('class') or '')}
            assert receipt['faculty_link']['url']=='https://www.pma.caltech.edu/people/gukov'
            assert card.get_by_role('link',name='Apply now',exact=True).count()==0
        else:
            assert raw['kind']=='listing'
            apply=card.get_by_role('link',name='Apply now',exact=True)
            receipt['greenhouse_url']=apply.get_attribute('href')
            assert '/octaura/jobs/' in receipt['greenhouse_url']
        page.screenshot(path=OUT/'card.png')
        draft=card.get_by_role('button',name='Draft email',exact=True)
        receipt['draft_button_is_primary']='bg-indigo-600' in (draft.get_attribute('class') or '')
        draft.click()
        body=page.locator('#cold-email-body')
        body.wait_for(timeout=75000)
        subject=page.locator('#cold-email-subject').input_value().strip()
        message=body.input_value().strip()
        assert subject and message and len(drafted)==3 and (subject,message) in drafted.values()
        receipt['editor']={'subject':subject,'body':message,'matches_clicked_id_response':True,'three_variants':sorted(drafted)}
        if CAMPUS=='caltech':
            assert 'research' in subject.lower() and 'gukov' in message.lower() and '?' in message
            assert not any(term in message.lower() for term in ('your open position','you are hiring'))
        else:
            assert 'data engineer intern' in subject.lower() and 'data engineer intern' in message.lower()
        body.screenshot(path=OUT/'body.png')
        receipt['end']=version()
        assert receipt['start']==receipt['end'] and page.locator('html').get_attribute('data-release-sha')==receipt['end']['front']
        receipt['passed']=True
        browser.close()


try:
    run()
except Exception as exc:
    receipt['failure']=str(exc)[:1000]
    raise
finally:
    save()
