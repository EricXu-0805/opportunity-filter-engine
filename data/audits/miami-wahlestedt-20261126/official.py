"""Read the university's two named destinations and the saved public Chemistry detail."""
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from playwright.sync_api import sync_playwright, TimeoutError

BASE = 'https://joinalab.com'
SAVED = 'faculty-miami-chem-a0149798'
SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
PAGES = {
    'institutional_profile': 'https://scholarship.miami.edu/esploro/profile/claes_wahlestedt',
    'graduate_faculty': 'https://med.miami.edu/graduate-studies/doctoral-programs/biochemistry-and-molecular-biology/faculty-profiles',
    'chemistry_roster': 'https://chemistry.as.miami.edu/people/faculty/index.html',
}

def main():
    result = {'at': datetime.now(timezone.utc).isoformat(), 'id': SAVED, 'sources': {}}
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        context = chromium.new_context(locale='en-US')
        page = context.new_page()
        def health():
            r=context.request.get(BASE+'/api/health')
            return r.json()['release_sha'] if r.ok else r.status
        result['backend_before'] = health()
        detail=context.request.get(BASE+'/api/opportunities/'+SAVED,params={'_release_scope':SCOPE})
        data=detail.json()
        result['saved'] = {'http':detail.status, 'id':data.get('id'), 'name':data.get('pi_name'),
                           'role':(data.get('metadata') or {}).get('faculty_title'),
                           'has_public_profile': bool(data.get('url')), 'has_public_source': bool(data.get('source_url')),
                           'actionable': (data.get('target_truth') or {}).get('actionable')}
        assert result['saved']['id']==SAVED
        for label, url in PAGES.items():
            evidence={'url':url}; result['sources'][label]=evidence
            try:
                res=page.goto(url,wait_until='domcontentloaded',timeout=50000)
                evidence['http']=res.status if res else None
                h=page.get_by_role('heading',name=re.compile(r'Claes\s+(?:R\.?\s+)?Wahlestedt',re.I)).first
                try:
                    h.wait_for(state='visible',timeout=22000)
                    evidence['visible_name']=h.inner_text()
                    evidence['bio_section']=h.evaluate("""start => {
                      let n=start.parentElement;
                      for(let i=0;n&&i<5;i++,n=n.parentElement){
                        const t=n.innerText||'';
                        if(t.length>12000) break;
                        if(/Professor of Chemistry\s*\(Secondary\)/i.test(t))
                          return {secondary_chemistry:true, primary_psychiatry:/Professor of Psychiatry and Behavioral Sciences/i.test(t)};
                      }
                      return {secondary_chemistry:false};
                    }""")
                except TimeoutError:
                    evidence['visible_name']=None
                evidence['browser_title']=page.title()
                text=page.locator('body').inner_text(timeout=10000)
                evidence['named_in_visible_text']=bool(re.search(r'Claes\s+(?:R\.?\s+)?Wahlestedt',text,re.I))
                evidence['psychiatry_in_named_portal']=label=='institutional_profile' and bool(evidence['visible_name']) and 'Psychiatry' in text
                evidence['final_host']=page.evaluate('location.hostname')
            except Exception as exc:
                evidence['failure']=type(exc).__name__
        result['backend_after'] = health()
        chromium.close()
    result['verified_personal_destination']=bool(result['sources']['institutional_profile'].get('visible_name'))
    result['verified_chemistry_appointment']=bool(result['sources']['graduate_faculty'].get('bio_section',{}).get('secondary_chemistry'))
    Path('wahlestedt-official.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result, indent=2))
if __name__=='__main__':
    main()
