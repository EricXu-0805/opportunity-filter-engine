"""Exercise a self-created PDF and own real guest, using the first-party published profile form."""
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import verify_public_matching_experience as common


def matching(c, expect_entry=None):
    p=common.home(c)
    expect(p.locator('#student_name')).to_have_value(common.student,timeout=60000)
    p.get_by_role('button',name='Generate Matches',exact=True).click()
    p.wait_for_url('**/results**',timeout=85000)
    p.get_by_role('tab',name=re.compile(r'^All(?:\s|$)')).first.click()
    def searched(r):
        return (urlsplit(r.url).path=='/api/matches/view' and r.ok
                and r.request.post_data_json['profile']['name']==common.student
                and r.request.post_data_json['view'].get('search_query')==common.public_title)
    with p.expect_response(searched,timeout=125000) as seen:
        p.get_by_placeholder('Search by title, org, description, research area...').fill(common.public_title)
    response=seen.value
    req=response.request.post_data_json['profile']
    item=next(r for r in response.json()['results'] if r['opportunity_id']==common.target)
    assert 'resume_text' not in req and 'Independent purple clock marker' not in json.dumps(req)
    rows=req.get('match_experiences',[])
    if expect_entry:
        reference='pdf:'+hashlib.sha256(expect_entry['id'].encode()).hexdigest()
        assert expect_entry['source']['signature'] not in json.dumps(req)
        assert rows==[{'id':reference,'revision':expect_entry['revision'],'text':expect_entry['text'],'source':'resume','status':'confirmed'}]
        assert item['experience_basis']=={'entry_id':reference,'revision':expect_entry['revision'],'method':'GIS','target_source':'research_area'}
        p.get_by_text('Experience used for this match · GIS').click()
        expect(p.get_by_text(expect_entry['text'],exact=True)).to_be_visible()
        expect(p.get_by_text('Current résumé · Confirmed by you',exact=False)).to_be_visible()
    else:
        assert not rows and not item.get('experience_basis')
    p.close()
    return [item['final_score'],item['readiness_score'],item['eligibility_score']],next(iter(rows),None)


def main():
    expected_fixed = os.environ.get('M17_RESUME_EXPECT_FIXED') == '1'
    first = 'I mapped public habitat survey records using GIS.'
    private = 'Independent purple clock marker'
    reads = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox','--disable-dev-shm-usage'])
        probe = pw.request.new_context()
        release = probe.get(common.site + '/api/health').json()['release_sha']
        assert release==os.environ['OFE_EXPECTED_SITE_SHA']
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
        def upload_own_pdf(page, marker):
            document = b.new_page()
            document.set_content('<h1>Experiences</h1><p>' + first + '</p><p>' + marker + '</p>')
            pdf = document.pdf()
            document.close()
            page.locator('input[type=file][accept*="pdf"]').first.set_input_files(
                {'name': 'habitat-synthetic.pdf', 'mimeType': 'application/pdf', 'buffer': pdf}
            )
            expect(page.get_by_role('button', name='Remove file', exact=True)).to_be_visible(timeout=65000)
        upload_own_pdf(p, private)
        p.get_by_role('button',name='Prepare excerpts for review',exact=True).click()
        summary=p.locator('#experience-library summary').filter(has_text=first).first
        expect(summary).to_contain_text('Needs confirmation',ignore_case=True,timeout=35000)
        p.wait_for_timeout(3000)
        c.close()
        c,p,(revision,profile)=read(lambda d:any(e['status']=='candidate' and first in e['text'] for e in d.get('experience_entries',[])))
        raw=profile['resume_text']
        candidate=next(e for e in profile['experience_entries'] if first in e['text'])
        source=candidate['source']
        assert source['signature']==hashlib.sha256(raw.encode()).hexdigest() and raw[source['start']:source['end']]==source['quote'] and private in raw
        baseline,_=matching(c)
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
        accepted,entry=matching(c,confirmed if expected_fixed else None)
        print(json.dumps({'release_sha':release,'target':common.target,'locally_generated_pdf':True,'complete_sha256_and_exact_quote_valid':True,'confirmed_revision':confirmed_revision,'confirmed_entry_revision':confirmed['revision'],'candidate_scores':baseline,'confirmed_scores':accepted,'match_sent_confirmed_row':bool(entry),'production_pdf_source_missing':not bool(entry)}),flush=True)
        if expected_fixed:
            assert entry['source']=='resume' and entry['text']==first and accepted[0]>baseline[0] and accepted[2]==baseline[2]
            details=p.locator('#experience-library details').filter(has=p.locator('summary',has_text=first)).first
            details.locator('summary').first.click()
            details.get_by_role('button',name='Do not use',exact=True).click()
            expect(details.locator('summary').first).to_contain_text('excluded',ignore_case=True)
            p.wait_for_timeout(3000)
            c.close()
            c,p,(final_revision,_)=read(lambda d:any(e['id']==candidate['id'] and e['status']=='rejected' for e in d.get('experience_entries',[])))
            final,_=matching(c)
            assert final==baseline and final_revision>confirmed_revision
            print(json.dumps({'release_sha':release,'withdrawn_production_scores':final,'withdrawn_own_revision':final_revision}),flush=True)
            if os.environ.get('M17_VERIFY_PDF_REPLACEMENT') == '1':
                details = p.locator('#experience-library details').filter(has=p.locator('summary', has_text=first)).first
                if not details.evaluate('(element) => element.open'):
                    details.locator('summary').click()
                details.get_by_role('button', name='Confirm facts', exact=True).click()
                expect(details.locator('summary')).to_contain_text('Confirmed', ignore_case=True)
                p.wait_for_timeout(2500)
                c.close()
                def reconfirmed(profile):
                    return any(e['id'] == candidate['id'] and e['status'] == 'confirmed'
                               and e['revision'] > confirmed['revision'] for e in profile.get('experience_entries', []))
                c, p, (reconfirmed_revision, current_profile) = read(reconfirmed)
                assert reconfirmed_revision > final_revision
                old_entry = next(e for e in current_profile['experience_entries'] if e['id'] == candidate['id'])
                restored_scores, _ = matching(c, old_entry)
                assert restored_scores == accepted
                next_marker = 'Separate green survey marker, a student-owned replacement PDF'
                upload_own_pdf(p, next_marker)
                p.wait_for_timeout(3000)
                c.close()
                def replaced(profile):
                    current = profile.get('resume_text') or ''
                    return first in current and next_marker in current and private not in current
                c, p, (new_revision, current_profile) = read(replaced)
                new_raw = current_profile['resume_text']
                new_signature = hashlib.sha256(new_raw.encode()).hexdigest()
                assert new_signature != source['signature'] and new_revision > reconfirmed_revision
                after_replacement, _ = matching(c)
                assert after_replacement == baseline
                print(json.dumps({'release_sha': release, 'reconfirmed_own_revision': reconfirmed_revision,
                                  'replacement_own_revision': new_revision, 'identical_statement_in_both_files': True,
                                  'different_complete_signatures': True, 'old_confirmed_entry_used_after_replacement': False,
                                  'scores_when_reconfirmed': restored_scores, 'scores_after_replacement': after_replacement}),
                      flush=True)
        else:
            assert not entry and baseline==accepted
        c.close()
        final_backend = probe.get(common.site + '/api/health').json()['release_sha']
        final_frontend = probe.get(common.site + '/about').text()
        assert final_backend == release and 'data-release-sha="' + release + '"' in final_frontend
        print(json.dumps({'stable_frontend_and_backend': release, 'used_synthetic_pdf_only': True}), flush=True)
        probe.dispose()
        b.close()

if __name__=='__main__':
    main()
