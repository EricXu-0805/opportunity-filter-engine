"""Normal production guest, paste failure before network, and the owner's synthetic legacy browser record."""
import json
import os
import uuid
from urllib.parse import urlsplit
from playwright.sync_api import expect,sync_playwright
from verify_public_matching_experience import cold,home,auth,site

src='Synthetic campus archive assistantship. Keep the source text including the ending.\nLocation and pay have not been provided.\nEnd of old private source.'
typed=src+'\nThis new sentence is a proposed edit, not a saved revision.'
title='Private source QA — fictional campus archive'
local_id='custom-'+str(uuid.uuid4())
legacy={'id':local_id,'imported_at':'2026-09-15T08:00:00Z','opportunity':{'source':'text_parser','source_url':'','url':'','title':title,
        'organization':'Fictional Campus Archive','description_raw':src,'extra_fields':{'needs_manual_review':True,'description_source':'pasted_text'}}}
count=0
def simulate_offline(route):
    global count
    assert route.request.post_data_json=={'text':typed}
    count+=1
    route.abort('internetdisconnected')

with sync_playwright() as w:
    expected=os.environ['OFE_EXPECTED_SITE_SHA']
    check=w.request.new_context();assert check.get(site+'/api/health').json()['release_sha']==expected
    assert 'data-release-sha="'+expected+'"' in check.get(site+'/about').text();check.dispose()
    b=w.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    c=cold(b);c.route('**/api/import-text',simulate_offline)
    p=home(c);assert auth[0]['user']['is_anonymous']
    p.goto(site+'/import',wait_until='domcontentloaded')
    assert urlsplit(p.url).path=='/resources'
    p.get_by_role('tab',name='By text',exact=True).click()
    box=p.get_by_placeholder('Paste the full posting, email forward, or any description of the opportunity.',exact=False)
    box.fill(typed);p.get_by_role('button',name='Extract with AI').click()
    for _ in range(70):
        if count==1:break
        p.wait_for_timeout(100)
    assert count==1;expect(box).to_have_value(typed)
    # Exercise a second explicit retry; no request is forwarded to a paid service.
    p.get_by_role('button',name='Extract with AI').click()
    for _ in range(70):
        if count==2:break
        p.wait_for_timeout(100)
    assert count==2;expect(box).to_have_value(typed)
    assert p.evaluate("() => JSON.parse(localStorage.getItem('ofe_custom_imports')||'[]').length")==0
    # Represents an existing item owned by this new QA guest, deliberately supplied
    # at the old browser storage boundary. Do not claim live model extraction.
    p.evaluate("v=>localStorage.setItem('ofe_custom_imports',JSON.stringify([v]))",legacy)
    p.goto(site+'/favorites',wait_until='domcontentloaded')
    expect(p.get_by_role('heading',name=title)).to_be_visible(timeout=60000)
    p.get_by_role('button',name='Review save to account').click()
    expect(p.get_by_text('Sign in to save or view account copies. A guest session is not enough.',exact=True).first).to_be_visible(timeout=30000)
    assert p.get_by_role('button',name='Save to account',exact=True).count()==0
    p.close();p=c.new_page();p.goto(site+'/favorites',wait_until='domcontentloaded')
    expect(p.get_by_role('heading',name=title)).to_be_visible(timeout=60000)
    assert p.evaluate("() => JSON.parse(localStorage.getItem('ofe_custom_imports'))")==[legacy]
    expect(p.get_by_text('1 saved',exact=True)).to_be_visible(timeout=20000)
    expect(p.get_by_text("You haven't starred any opportunities yet.",exact=True)).to_have_count(0)
    p.goto(site+'/dashboard',wait_until='domcontentloaded')
    summary=p.get_by_test_id('saved-summary')
    expect(summary).to_have_attribute('data-state','ready',timeout=60000)
    expect(summary.locator('p').first).to_have_text('1')
    print(json.dumps({'release':expected,'site':site,'anonymous_first_party_account':True,'legacy_import_routes_to_resources':True,
                      'paid_model_and_external_network_submissions':0,'controlled_offline_parse_attempts':count,'full_proposed_input_retained':True,
                      'old_record_seeded_on_own_browser':True,'reopened_same_id_and_identical_legacy_source':True,
                      'guest_account_save_requires_sign_in':True,'account_record_created':False,'real_model_extraction_tested':False,
                      'reopened_favorites_counts_one_local_record':True,'dashboard_counts_one_local_record':True,
                      'nonanonymous_cloud_count_path_tested_on_production':False}))
    c.close();b.close()
