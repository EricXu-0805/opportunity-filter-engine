"""Read five UCSB IDs and five audited campus programs on the real public site."""
from datetime import datetime, timezone
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

SITE = 'https://joinalab.com'
SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
PHASE = 'after'
EXPECTED_RELEASE = '743e6fa6e6b8d56c39e5c2eb29a92a4fcdc16d7f'
# Positive current IDs, reference-only or closed IDs, and the inactive test ID.
CASES = {
    'ucsb-urca-proj-67fca359b647': ('https://ucsb.my.site.com/urca/s/funding-program/a0WVt00000BbDUbMAN/', 'inactive'),
    'ucsb-urca-proj-e5cbe0e218a7': ('https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000g8VGiUAM/', 'reference_only'),
    'ucsb-urca-proj-7e0212eeb861': ('https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcGFUA0/', 'reference_only'),
    'ucsb-urca-proj-3341fa96421c': ('https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcGPUA0/', 'reference_only'),
    'ucsb-urca-proj-2eb2c063674e': ('https://ucsb.my.site.com/urca/s/funding-program/a0WHt00000HBwJoMAL/', None),
    'ucr-e08f03f0945b': ('https://cnas.ucr.edu/student-research-and-internship-opportunities', 'reference_only'),
    'umd-54542deb3560': ('https://honors.umd.edu/', 'reference_only'),
    'udel-f6a5e4ea0f51': ('https://www.urp.udel.edu/', 'reference_only'),
    'bc-ec4ea5f74178': ('https://www.bc.edu/content/bc-web/research/undergrad-research-opps.html', 'reference_only'),
    'duke-0ad241611979': ('https://focus.duke.edu/', 'listing_closed'),
    'wlu-88e9e20591ba': ('https://mga1.wlu.edu/campusnotices/view/web.php?id=9865&view=web', 'listing_closed'),
}
report={'observed_utc':datetime.now(timezone.utc).isoformat(),'environment':SITE,'phase':PHASE,'cases':[]}
out=Path('evidence');out.mkdir(exist_ok=True)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome')
        context=browser.new_context(locale='en-US')
        page=context.new_page()
        report['render_release']=context.request.get(SITE+'/api/health').json()['release_sha']
        assert report['render_release']==EXPECTED_RELEASE, report['render_release']
        for oid,(url_prefix,fixed_reason) in CASES.items():
            url=SITE+'/opportunities/'+oid
            api=context.request.get(SITE+'/api/opportunities/'+oid,params={'_release_scope':SCOPE},timeout=30000)
            assert api.ok,(oid,api.status)
            detail=api.json();truth=detail['target_truth'];src=detail['source_url'];assert src.startswith(url_prefix)
            res=page.goto(url,wait_until='domcontentloaded',timeout=45000);assert res and res.ok
            page.get_by_role('heading',name=detail['title'],exact=True).first.wait_for(timeout=30000)
            apply=page.get_by_role('link',name='Apply now',exact=True)
            view=page.get_by_role('link',name='View source',exact=True)
            control=apply if truth['actionable'] else view
            control.first.wait_for(timeout=15000)
            sample={'id':oid,'product_url':url,'title':detail['title'],'source_url':src,'frontend_release':page.locator('html').get_attribute('data-release-sha'),
                    'page_http':res.status,'detail_http':api.status,'actionable':truth['actionable'],'reason':truth['reason_code'], 'listing_state':truth['listing_state'],
                    'apply_controls':apply.count(),'view_source_controls':view.count(),'rendered_link':control.first.get_attribute('href'),'deadline':detail.get('deadline'),'is_rolling':detail.get('is_rolling')}
            if oid=='wlu-88e9e20591ba':
                expected_sites=['University of Illinois Chicago','University of Florida','University of Michigan']
                assert detail['organization']=='Washington and Lee University' and detail['school']=='wlu'
                assert all(site in detail['location'] for site in expected_sites)
                body=page.locator('main').first
                text=body.inner_text()
                if detail['title'] not in text:
                    text=page.locator('body').inner_text()
                assert detail['title'] in text and 'Washington and Lee University' in text
                visible_sites=[site for site in expected_sites if site in text]
                fact=page.get_by_test_id('fact-field-location')
                sample['placement']={'program_owner':detail['organization'],'detail_location':detail['location'],'expected_sites':expected_sites,'visible_sites':visible_sites,'location_fact':fact.first.inner_text() if fact.count() and fact.first.is_visible() else None,'all_sites_visible':visible_sites==expected_sites}
                page.screenshot(path=str(out/'dart-live-page.png'),full_page=True)
                (out/'dart-live-page.txt').write_text(text)
            report['cases'].append(sample)
            assert sample['frontend_release']==EXPECTED_RELEASE, (oid,sample['frontend_release'])
            assert sample['rendered_link']==src and sample['apply_controls']==int(truth['actionable']),(oid,sample)
            if PHASE=='after': assert truth['reason_code']==fixed_reason and truth['actionable']==(fixed_reason is None),(oid,sample)
            print(oid,truth['reason_code'],sample['apply_controls'],flush=True)
        browser.close()
    assert len(report['cases'])==11
    dart=report['cases'][-1];assert dart['id']=='wlu-88e9e20591ba'
    report['ten_original_program_controls']='passed'
    report['dart_origin_and_hosts_in_api']='passed'
    report['dart_closed_control']='passed'
    report['dart_placement_visible']='passed' if dart['placement']['all_sites_visible'] else 'not displayed'
    report['result']='passed' if dart['placement']['all_sites_visible'] else 'ten original program checks passed; DART placement absent from visible closed detail'

finally:
    (out/('program-actions-'+PHASE+'.json')).write_text(json.dumps(report,indent=2)+'\n')
