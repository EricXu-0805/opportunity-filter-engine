"""Exercise a self-created PDF and own real guest, using the first-party published profile form."""
import hashlib
import json
import os
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import verify_public_matching_experience as common


def main():
    expected_fixed = os.environ.get('M17_RESUME_EXPECT_FIXED') == '1'
    first = 'I mapped public habitat survey records using GIS.'
    private = 'Independent purple clock marker'
    reads = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox','--disable-dev-shm-usage'])
        probe = pw.request.new_context()
        release = probe.get(common.site + '/api/health').json()['release_sha']
        assert 'data-release-sha="' + release + '"' in probe.get(common.site+'/about').text()
        def fresh():
            c = common.cold(b)
            def record(r):
                u = urlsplit(r.url)
                if u.hostname == common.db and u.path == '/rest/v1/profiles' and r.ok and r.request.method=='GET':
                    d = r.json()
                    if isinstance(d,list) and d: d=d[0]
                    if isinstance(d,dict) and d.get('profile_data'): reads.append((d['revision'],d['profile_data']))
            c.on('response',record)
            return c
        def read(f):
            start = len(reads)
            c = fresh()
            p = common.home(c)
            expect(p.locator('#student_name')).to_have_value(common.student,timeout=60000)
            for _ in range(100):
                if any(f(d) for _,d in reads[start:]):break
                p.wait_for_timeout(200)
            rows = [(rev,d) for rev,d in reads[start:] if f(d)]
            assert rows, ('own profile did not reach expected state',len(reads)-start)
            return c,p,rows[-1]
        c=fresh()
        p=common.home(c)
        p.locator('#student_name').fill(common.student)
        p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
        p.locator('#major').select_option(label='Integrative Biology')
        p.locator('#grade').select_option(label='Sophomore')
        doc=b.new_page()
        doc.set_content('<h1>Experiences</h1><p>'+first+'</p><p>'+private+'</p>')
        pdf=doc.pdf()
        doc.close()
        p.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'habitat-synthetic.pdf','mimeType':'application/pdf','buffer':pdf})
        expect(p.get_by_role('button',name='Remove file',exact=True)).to_be_visible(timeout=65000)
        p.get_by_role('button',name='Prepare excerpts for review',exact=True).click()
        summary=p.locator('#experience-library summary').filter(has_text=first).first
        expect(summary).to_contain_text('Candidate',ignore_case=True,timeout=35000)
        p.wait_for_timeout(3000)
        c.close()
        c,p,(revision,profile)=read(lambda d:any(e['status']=='candidate' and first in e['text'] for e in d.get('experience_entries',[])))
        raw=profile['resume_text']
        candidate=next(e for e in profile['experience_entries'] if first in e['text'])
        source=candidate['source']
        assert source['signature']==hashlib.sha256(raw.encode()).hexdigest() and raw[source['start']:source['end']]==source['quote'] and private in raw
        baseline,_=common.results(c,False)
        details=p.locator('#experience-library details').filter(has=p.locator('summary',has_text=first)).first
        details.locator('summary').first.click()
        expect(details.locator('textarea')).to_have_value(first)
        details.get_by_role('button',name='Confirm facts',exact=True).click()
        expect(details.locator('summary').first).to_contain_text('Confirmed',ignore_case=True)
        p.wait_for_timeout(3000)
        c.close()
        c,p,(confirmed_revision,profile)=read(lambda d:any(e['status']=='confirmed' and e['text']==first for e in d.get('experience_entries',[])))
        confirmed=next(e for e in profile['experience_entries'] if e['id']==candidate['id'])
        assert confirmed_revision>revision and confirmed['revision']>candidate['revision'] and confirmed['source']==source
        assert profile['resume_text']==raw
        accepted,entry=common.results(c,expected_fixed)
        print(json.dumps({'release_sha':release,'target':common.target,'locally_generated_pdf':True,'complete_sha256_and_exact_quote_valid':True,'confirmed_revision':confirmed_revision,'confirmed_entry_revision':confirmed['revision'],'candidate_scores':baseline,'confirmed_scores':accepted,'match_sent_confirmed_row':bool(entry),'production_pdf_source_missing':not bool(entry)}),flush=True)
        if expected_fixed:
            assert entry['source']=='resume' and entry['text']==first and accepted[0]>baseline[0] and accepted[2]==baseline[2]
        else:
            assert not entry and baseline==accepted
        c.close()
        probe.dispose()
        b.close()

if __name__=='__main__':
    main()
