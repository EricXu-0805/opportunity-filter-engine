"""Use a genuine student profile to compare unavailable, inquiry and fallback faculty actions."""
import json
import os
import re
import sys
from datetime import datetime, timezone
from importlib import util
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

SITE = 'http://127.0.0.1:3000'
SHA = os.environ['CANDIDATE']
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True,exist_ok=True)
spec = util.spec_from_file_location('user_path', Path(__file__).resolve().parents[1]/'public-student-faculty-links'/'check.py')
base = util.module_from_spec(spec)
spec.loader.exec_module(base)
base.SITE = SITE
base.OUT = OUT
cases = [
    ('faculty-ucb-cdss-118019dd','Eric Kim','unavailable','person','https://eric-kim.net/eric-kim-net/index.html'),
    ('faculty-msu-phys-c0440436','Jonas Nils Becker','sign_in_required','person','https://directory.natsci.msu.edu/directory/Profiles/Person/102126'),
    ('faculty-msu-psl-19d4bb6d','Luisa Seguella',None,'directory','https://directory.natsci.msu.edu/Directory/Directory/Department/35'),
    ('faculty-msu-mgi-5ca9b09b','Kathleen A Hoag',None,'historical directory','https://directory.natsci.msu.edu/Directory/Directory/Department/26'),
]
result = {'utc':datetime.now(timezone.utc).isoformat(),'environment':'isolated exact candidate, real local account and migration database',
          'release':SHA,'account':base.receipt['account'],'rows':[]}


def save():
    (OUT/'receipt.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')


def actions(page,root,row,dest,kind,which):
    named = kind == 'person'
    label = ('View faculty profile' if named else 'View source') if which=='detail' else ('Faculty page' if named else 'View the source page')
    link = root.get_by_role('link',name=label,exact=True)
    link.wait_for(timeout=30000)
    group = link.locator('..')
    ordered = group.locator('a:visible,button:visible').evaluate_all("""els => els.map(e => ({
        label:(e.innerText || e.getAttribute('aria-label') || '').trim(),
        role:e.tagName,href:e.getAttribute('href'),primary:e.classList.contains('bg-indigo-600'),
        background:getComputedStyle(e).backgroundColor,disabled:e.matches(':disabled')}))""")
    info={'ordered':ordered,'profile_action':label,'page':page.url,'client_release':page.locator('html').get_attribute('data-release-sha')}
    row[which]=info
    assert info['client_release']==SHA
    target=next(a for a in ordered if a['label']==label)
    assert target['href']==dest and (target['primary']==(row['id']==cases[0][0])),(which,target)
    if which=='detail' or row['id']==cases[0][0]:
        if named:
            assert ordered[0]['label']==label, ordered
    if which=='favorites' and row['id']==cases[1][0]:
        assert ordered[0]['label']=='Draft email' and ordered[0]['primary'],ordered
    if not named:
        assert not any(w['label'] in ('View faculty profile','Faculty page') for w in ordered)
        if 'historical' in kind:
            assert all(w['label']!='Draft email' for w in ordered)
    if row['id']==cases[0][0]:
        link.focus()
        page.keyboard.press('Tab')
        info['keyboard_next']=page.evaluate("document.activeElement?.innerText?.trim()")
        assert info['keyboard_next']=='Draft email', info
    link.scroll_into_view_if_needed()
    page.screenshot(path=OUT/(row['id']+'-'+which+'.png'))
    if named:
        responses=[]
        def record(resp):
            if resp.request.is_navigation_request() and urlsplit(resp.url).hostname in ('eric-kim.net','www.eric-kim.net','directory.natsci.msu.edu'):
                responses.append({'url':resp.url.split('?')[0],'status':resp.status})
        page.context.on('response',record)
        try:
            with page.context.expect_page(timeout=30000) as popup:
                link.click(timeout=30000)
            tab=popup.value
            try:
                tab.wait_for_load_state('domcontentloaded',timeout=30000)
                info['external_title']=tab.title()
                info['external_headings']=[t.strip()[:120] for t in tab.locator('h1,h2').all_inner_texts()[:8]]
            finally:
                info['actual_destination']=tab.url.split('?')[0]
                tab.close()
        finally:
            page.context.remove_listener('response',record)
            info['public_navigation']=responses
        assert link.get_attribute('href')==dest and (info['actual_destination'].rstrip('/')==dest.rstrip('/') or any(x['url']==dest for x in responses)), info
    if row['id']==cases[1][0]:
        root.get_by_role('button',name='Draft email',exact=True).click()
        modal=page.get_by_role('dialog').last
        modal.wait_for(timeout=30000)
        info['inquiry_control_opened_dialog']=True
        info['dialog_name']=modal.get_attribute('aria-label')
        page.keyboard.press('Escape')
    save()


def run():
    result['start']=base.version()
    assert list(result['start'].values())==[SHA]*2
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        ctx=browser.new_context(locale='en-US')
        def observe(resp):
            path=urlsplit(resp.url).path
            if path=='/auth/v1/signup':result['account']['signup']=resp.status
            if path.endswith('/rpc/commit_profile_patch_cas') and resp.ok:
                try:
                    v=resp.json(); v=v[0] if isinstance(v,list) and v else v
                    if isinstance(v,dict) and v.get('status')=='applied':result['account']['profile_commit']='applied'
                except Exception:pass
        ctx.on('response',observe)
        page=ctx.new_page()
        base.onboarding(page)
        for pid,name,status,kind,dest in cases:
            row={'id':pid,'name':name,'kind':kind}
            result['rows'].append(row)
            try:
                with urlopen(SITE+'/api/opportunities/'+pid+'?'+urlencode({'_release_scope':base.SCOPE}),timeout=40) as response:
                    api=json.load(response)
                row.update(public_contact_status=api.get('contact_email_status'),actionable=api['target_truth']['actionable'])
                assert api['id']==pid and (not status or row['public_contact_status']==status)
                page.goto(SITE+'/opportunities/'+pid,wait_until='domcontentloaded',timeout=60000)
                root=page.get_by_role('main')
                root.get_by_role('link', name='Back to matches', exact=True).wait_for(timeout=45000)
                assert name in root.get_by_role('heading',level=1).inner_text()
                root.get_by_role('button',name='Add to favorites',exact=True).click(timeout=30000)
                root.get_by_role('button',name='Remove from favorites',exact=True).wait_for(timeout=30000)
                row['saved_using_detail']=True
                actions(page,root,row,dest,kind,'detail')
            except Exception as e:row['detail_failure']=str(e)[:1000]
            save()
        page.goto(SITE+'/favorites',wait_until='domcontentloaded',timeout=55000)
        for row,(_,name,status,kind,dest) in zip(result['rows'],cases):
            try:
                item=page.locator("h3 a[href='/opportunities/"+row['id']+"']")
                item.wait_for(timeout=25000)
                card=item.locator('xpath=ancestor::div[contains(@class,"rounded-2xl")][1]')
                actions(page,card,row,dest,kind,'favorites')
            except Exception as e:row['favorites_failure']=str(e)[:1000]
            save()
        browser.close()
    result['end']=base.version()
    assert result['start']==result['end']
    assert all(not r.get('detail_failure') and not r.get('favorites_failure') for r in result['rows']),'See individual ordinary action receipts.'


if __name__=='__main__':
    try:
        run()
    finally:
        save()
