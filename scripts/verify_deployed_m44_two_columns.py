"""Check two visually separate project blocks and their source quotes in a self-authored PDF."""
import hashlib
import html
import io
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader
import verify_public_matching_experience as shared
from verify_deployed_m39_supplement import stable_read

LEFT=['Skills','Python','Languages','English','课程：统计']
RIGHT=['Projects','Orchard counter exercise','I checked 18 synthetic count labels.', 'Beacon field map exercise','My team reviewed 29 synthetic map rows.']
def normalize(t):return re.sub(r'\s+','',t).casefold()
def main():
    with sync_playwright() as pw:
        b=pw.chromium.launch(channel='chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        req=pw.request.new_context();release=shared.release
        def ver():
            assert req.get(shared.site+'/api/health').json()['release_sha']==release
            assert f'data-release-sha="{release}"' in req.get(shared.site+'/about').text()
        ver()
        pdfpage=b.new_page()
        def section(items):
            return '<section>'+''.join('<p>'+html.escape(s)+'</p>' for s in items)+'</section>'
        pdfpage.set_content("""<meta charset="utf-8"><style>@page{margin:12mm}body{font:12pt sans-serif}main{display:grid;grid-template-columns:28% 65%;column-gap:7%}p{margin:0 0 12pt}</style>
        <h1>Coursework and projects</h1><main>"""+section(LEFT)+section(RIGHT)+'</main>')
        boxes=pdfpage.locator('section').evaluate_all('(els)=>els.map(e=>{const b=e.getBoundingClientRect();return [b.left,b.right,b.top]})')
        assert boxes[0][1]<boxes[1][0] and boxes[0][2]==boxes[1][2]
        pdf=pdfpage.pdf(format='A4',prefer_css_page_size=True);pdfpage.close()
        assert len(PdfReader(io.BytesIO(pdf)).pages)==1
        c=shared.cold(b);p=shared.home(c);p.set_viewport_size({'width':390,'height':844})
        p.locator('#student_name').fill(shared.student);p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
        p.locator('#major').select_option(label='Integrative Biology');p.locator('#grade').select_option(label='Freshman')
        with p.expect_response(lambda r:urlsplit(r.url).path=='/rest/v1/rpc/commit_profile_patch_cas' and r.ok and 'Beacon field map' in r.request.post_data,timeout=60000):
            p.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'two-column-qa.pdf','mimeType':'application/pdf','buffer':pdf})
        expect(p.get_by_role('button',name='Remove file')).to_be_visible()
        c2=shared.cold(b);p2,(rv,data)=stable_read(c2)
        raw=data['resume_text'];source_lines=[v.strip() for v in raw.splitlines() if v.strip()]
        receipt={'release':release,'pdf_sha256':hashlib.sha256(pdf).hexdigest(),'first_party_anonymous_signup':bool(shared.auth),'profile_revision_after_upload':rv,'visual_columns_disjoint':True,'synthetic_input_pages':1,'source_lines':source_lines,'extracted_sha256':hashlib.sha256(raw.encode()).hexdigest(),'first_row_statuses':[]}
        path=Path(os.environ['OFE_M44_COLUMNS_RECEIPT']);path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        flat=normalize(raw)
        assert all(flat.count(normalize(s))==1 for s in LEFT+RIGHT)
        for block in [LEFT,RIGHT]:
            positions=[flat.index(normalize(t)) for t in block]
            assert positions==sorted(positions)
        assert not any(any(normalize(left) in normalize(line) for left in LEFT) and any(normalize(right) in normalize(line) for right in RIGHT) for line in source_lines)
        p2.get_by_text('View complete current résumé source',exact=True).click()
        expect(p2.locator('#resume-master pre').first).to_have_text(raw)
        p2.get_by_role('button',name='Prepare excerpts for review').click()
        for text in (RIGHT[2],RIGHT[4]):
            summary=p2.locator('#experience-library summary').filter(has_text=text).first
            expect(summary).to_contain_text('Needs confirmation',ignore_case=True,timeout=30000)
        c3=shared.cold(b);p3,(rv3,data3)=stable_read(c3)
        entries=data3.get('experience_entries',[])
        for i,original in enumerate([RIGHT[2],RIGHT[4]]):
            hits=[e for e in entries if original in e['text']]
            assert len(hits)==1
            e=hits[0]
            assert e['status']=='candidate'
            assert [x for x in (RIGHT[2],RIGHT[4]) if x in e['text']]==[original]
            s=e['source'];assert s['kind']=='resume' and s['signature']==receipt['extracted_sha256'] and raw[s['start']:s['end']]==s['quote']
            receipt['first_row_statuses'].append({'source':s['kind'],'status':e['status'],'original_quote_matches':True,'leading_or_team':('personal','team')[i]})
        receipt.update({'raw_source_view_verified':True,'no_evidence_crossed_between_projects':True,'no_unconfirmed_experience_promoted':True,'second_revision':rv3,'regular_view_width':390})
        ver();path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');b.close()
if __name__=='__main__':main()
