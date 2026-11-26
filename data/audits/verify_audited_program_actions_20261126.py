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
    'wlu-88e9e20591ba': ('https://mga1.wlu.edu/campusnotices/view/web.php?id=9865&view=web', 'listing_closed'),
    'duke-0ad241611979': ('https://focus.duke.edu/', 'listing_closed'),
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
                displayed=page.get_by_text('The 2026 host labs were at the University of Illinois Chicago',exact=False).first
                displayed.wait_for(state='visible',timeout=15000)
                record_text=displayed.inner_text(); assert all(site in record_text for site in expected_sites)
                fact=page.get_by_test_id('fact-field-location')
                sample['placement']={'program_owner':detail['organization'],'detail_location':detail['location'],'visible_host_text':record_text,'location_fact':fact.inner_text() if fact.count() and fact.first.is_visible() else None,'apply_controls':apply.count()}
            report['cases'].append(sample)
            assert sample['frontend_release']==EXPECTED_RELEASE, (oid,sample['frontend_release'])
            assert sample['rendered_link']==src and sample['apply_controls']==int(truth['actionable']),(oid,sample)
            if PHASE=='after': assert truth['reason_code']==fixed_reason and truth['actionable']==(fixed_reason is None),(oid,sample)
            print(oid,truth['reason_code'],sample['apply_controls'],flush=True)
        browser.close()
    report['result']='passed'
finally:
    (out/('program-actions-'+PHASE+'.json')).write_text(json.dumps(report,indent=2)+'\n')
