"""Production technical receipt, using a newly created synthetic guest and its own invented export."""
import json
import os
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from verify_public_matching_experience import cold, home, auth, revisions, site, db

expected=os.environ['OFE_EXPECTED_SITE_SHA']
person='A9999999999999999001'
other='A9999999999999999002'
prefix='W999999999999999900'
scholar='JoinALabSyntheticAuthorshipCheckM16'
url='https://scholar.google.com.hk/citations?user='+scholar
student='Synthetic publication check'
title='Synthetic transfer citation'
prior='Synthetic prior-campus citation'
doi='10.9999/joinalab-m16-synthetic'
def author(identifier,campus):
    return {'author':{'id':'https://openalex.org/'+identifier,'display_name':'Fictional Student'},'institutions':[{'display_name':campus}]}
def work(n,t,*people):
    return {'id':'https://openalex.org/'+prefix+n,'display_name':t,'authorships':people}
former=author(person,'Fictional former campus');current=author(person,'Fictional transfer campus');namesake=author(other,'Fictional former campus')
data={'results':[{**work('1',prior,former),'doi':doi},work('2',title,namesake,current),work('3','Namesake control',namesake),work('4','Ambiguous control',former,current)]}

with sync_playwright() as w:
    probe=w.request.new_context();assert probe.get(site+'/api/health').json()['release_sha']==expected
    assert 'data-release-sha="'+expected+'"' in probe.get(site+'/about').text();probe.dispose()
    b=w.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    key=[]
    def client():
        ctx=cold(b)
        def headers(r):
            p=urlsplit(r.url)
            if p.hostname==db and p.path.startswith('/rest/v1/') and r.ok:
                token=r.request.headers.get('apikey')
                if token and not key:key.append(token)
        ctx.on('response',headers)
        return ctx
    def owned(ctx):
        assert len(auth)==1 and key
        r=ctx.request.get('https://'+db+'/rest/v1/profiles?select=revision,profile_data&id=eq.'+auth[0]['user']['id'],
                          headers={'apikey':key[0],'Authorization':'Bearer '+auth[0]['access_token']})
        assert r.ok and len(r.json())==1
        return r.json()[0]
    def changed(page,old):
        for _ in range(200):
            if len(revisions)>old:return
            page.wait_for_timeout(200)
        raise AssertionError('profile commit did not settle')
    def panel(page):
        page.get_by_role('link',name='Confirm authorship and import my publications').click()
        expect(page.get_by_label('Your OpenAlex author ID or ORCID')).to_be_visible()
    def preview(page):
        page.get_by_label('Your OpenAlex author ID or ORCID').fill(person)
        check=page.get_by_label('I confirm that these author profiles are mine.')
        assert not check.is_checked()
        expect(page.get_by_label('Paste your public OpenAlex Works JSON export',exact=False)).to_have_count(0)
        expect(page.get_by_role('button',name='Check authorships')).to_have_count(0)
        check.check()
        page.get_by_label('Paste your public OpenAlex Works JSON export',exact=False).fill(json.dumps(data))
        page.get_by_role('button',name='Check authorships').click()
        expect(page.get_by_text('Matching works · 2 / Skipped · 2')).to_be_visible()
        for reject in ('Namesake control','Ambiguous control'):expect(page.get_by_role('link',name=reject)).to_have_count(0)
    ctx=client();p=home(ctx);p.locator('#student_name').fill(student)
    old=len(revisions);p.locator('#scholar_url').fill(url);p.locator('#scholar_url').blur();changed(p,old)
    for _ in range(160):
        if key and owned(ctx)['profile_data'].get('scholar_url')==url:break
        p.wait_for_timeout(200)
    initial=owned(ctx);assert initial['profile_data']['scholar_url']==url and not initial['profile_data'].get('resume_master')
    panel(p);preview(p);assert owned(ctx)==initial
    row=p.locator('li').filter(has=p.get_by_role('link',name=title))
    row.get_by_role('button').click();assert owned(ctx)==initial
    old=len(revisions);p.get_by_role('button',name='Apply changes').click();changed(p,old)
    saved=owned(ctx);paper=saved['profile_data']['resume_master']['publications'][0]
    assert paper['student_authorship']=={'scholar_id':scholar,'author_id':person,'work_id':prefix+'2'}
    assert paper['title']['value']==title and 'authors' not in paper
    ctx.close();ctx=client();p=home(ctx);expect(p.locator('#student_name')).to_have_value(student)
    panel(p);preview(p);expect(p.get_by_role('button',name='Already in résumé')).to_have_count(1)
    assert owned(ctx)==saved
    p.get_by_role('button',name='Add publication',exact=True).click()
    for label,value in [('Publication title','Synthetic citation with original wording'),('Authors in exact order','Example, B.; Example, A.'),
                        ('Publication URL','https://publisher.example/test-qa'),('DOI',doi.upper())]:
        p.get_by_role('textbox',name=label,exact=True).last.fill(value)
        p.get_by_role('button',name='Confirm '+label,exact=True).last.click()
    old=len(revisions);p.get_by_role('button',name='Apply changes').click();changed(p,old)
    manual=owned(ctx);old_paper=manual['profile_data']['resume_master']['publications'][1]
    assert 'student_authorship' not in old_paper
    p.get_by_role('button',name='Confirm authorship for this existing citation').click()
    assert owned(ctx)==manual
    old=len(revisions);p.get_by_role('button',name='Apply changes').click();changed(p,old)
    linked=owned(ctx);papers=linked['profile_data']['resume_master']['publications'];assert len(papers)==2 and papers[0]==paper
    citation=dict(papers[1]);proof=citation.pop('student_authorship')
    assert citation==old_paper and proof=={'scholar_id':scholar,'author_id':person,'work_id':prefix+'1','linked_by':doi}
    ctx.close();ctx=client();p=home(ctx);panel(p);preview(p);expect(p.get_by_role('button',name='Already in résumé')).to_have_count(2)
    assert owned(ctx)==linked
    print(json.dumps({'site':site,'release_sha':expected,'normal_anonymous_auth':True,'invented_qa_export':True,'matched':2,'skipped':2,'transfer_preserved':True,'no_cloud_write_until_explicit_save':True,
                      'legacy_citation_fields_and_order_unchanged':True,'clean_browser_deduplication':True,'revisions':[initial['revision'],saved['revision'],manual['revision'],linked['revision']],
                      'third_party_network_or_purchases':0,'real_student_observation':False}))
    ctx.close();b.close()
