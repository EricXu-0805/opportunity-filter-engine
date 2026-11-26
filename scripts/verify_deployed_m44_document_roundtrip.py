"""Exercise mobile résumé export with an owner's synthetic bilingual long activity."""
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from pypdf import PdfReader
from playwright.sync_api import expect, sync_playwright
import verify_public_matching_experience as shared
from verify_deployed_m39_supplement import TITLE, stable_read, tab

OUT=Path(os.environ['OFE_M44_DIR'])
OUT.mkdir(exist_ok=True)
sentences=[f'Row {n:03d} 记录{n:03d}：我核对合成表格的标签。I reviewed the sample labels.' for n in range(1,89)]
long_text='\n'.join(sentences)
assert len(long_text)<6000
canon=lambda s:re.sub(r'\s+','',s)
def docx_text(path):
    with zipfile.ZipFile(path) as file:
        root=ET.fromstring(file.read('word/document.xml'))
    return ''.join(elem.text or '' for elem in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
def assert_lines(text):
    condensed=canon(text)
    for line in sentences:
        assert condensed.count(canon(line))==1, line[:10]
    assert [condensed.index(canon(line)) for line in sentences]==sorted(condensed.index(canon(line)) for line in sentences)
    assert TITLE in text and 'profile_signature' not in text and shared.target not in text
def main():
    receipt={'started_at':datetime.now(timezone.utc).isoformat(),'steps':[],'release':shared.release,'source_rows':len(sentences),'characters':len(long_text),'target':shared.target,'external_messages':0}
    def stage(t):
        receipt['steps'].append(t)
        (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    with sync_playwright() as pw:
        chrome=pw.chromium.launch(channel='chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        req=pw.request.new_context()
        def same():
            assert req.get(shared.site+'/api/health').json()['release_sha']==shared.release
            assert f'data-release-sha="{shared.release}"' in req.get(shared.site+'/about').text()
        same()
        c=shared.cold(chrome)
        def writes(route):
            r=route.request;u=urlsplit(r.url)
            if r.method=='POST' and u.hostname=='joinalab.com' and u.path=='/api/resume/full-target/export':
                assert TITLE in r.post_data and 'Row 088' in r.post_data
                return route.continue_()
            return shared.guard(route)
        c.route('**/*',writes)
        p=shared.home(c);p.set_viewport_size({'width':390,'height':844})
        p.locator('#student_name').fill(shared.student)
        p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
        p.locator('#major').select_option(label='Integrative Biology')
        p.locator('#grade').select_option(label='Sophomore')
        editor=p.get_by_test_id('resume-master-editor')
        editor.locator(':scope > summary').click()
        editor.get_by_role('button',name='Add experience or project').click()
        editor.get_by_label('Role / project title',exact=True).fill(TITLE)
        editor.get_by_role('button',name='Confirm Role / project title').click()
        with p.expect_response(lambda x:urlsplit(x.url).path=='/rest/v1/rpc/commit_profile_patch_cas' and x.ok and TITLE in x.request.post_data,timeout=60000):
            editor.get_by_role('button',name='Apply changes').click()
        stage('confirmed_named_activity_on_mobile')
        a,d=tab(c);a.set_viewport_size({'width':390,'height':844})
        d.get_by_role('button',name='Add experience details').click()
        pan=d.get_by_test_id('resume-supplement-panel')
        pan.get_by_label('Project or experience in your master résumé').select_option(label=TITLE)
        pan.get_by_label('What was the task?').fill(long_text)
        pan.get_by_label('Include task',exact=True).check()
        pan.get_by_label('I confirm the selected information is accurate.').check()
        with a.expect_response(lambda x:urlsplit(x.url).path=='/rest/v1/rpc/commit_profile_patch_cas' and x.ok and 'Row 088' in x.request.post_data,timeout=60000):
            pan.get_by_role('button',name='Confirm and add to my master résumé').click()
        c2=shared.cold(chrome);c2.route('**/*',writes)
        h,(rev,data)=stable_read(c2)
        assert len(data['experience_entries'])==1 and long_text in data['experience_entries'][0]['text']
        receipt['confirmed_profile_revision']=rev
        stage('88_lines_saved_and_read_from_production')
        a,d=tab(c2);a.set_viewport_size({'width':390,'height':844})
        d.get_by_role('button',name='Create from confirmed master').click()
        ctrl=d.get_by_role('region',name='Export current résumé')
        ctrl.get_by_label('Section headings language').select_option('zh')
        ctrl.get_by_label('Paper size').select_option('a4')
        outputs={}
        for fmt,label in [('pdf','PDF'),('docx','Word')]:
            with a.expect_download(timeout=90000) as dl,a.expect_response(lambda x:urlsplit(x.url).path=='/api/resume/full-target/export',timeout=90000) as response:
                ctrl.get_by_role('button',name='Export '+label,exact=True).click()
            assert response.value.ok and dl.value.failure() is None
            path=OUT/('original.'+fmt)
            dl.value.save_as(path)
            if fmt=='pdf':
                pdf=PdfReader(str(path));pages=[page.extract_text() for page in pdf.pages]
                assert len(pages)>1
                assert all(abs(float(pg.mediabox.width)-595.28)<2 and abs(float(pg.mediabox.height)-841.89)<2 for pg in pdf.pages)
                assert_lines(' '.join(pages))
                receipt['original_pdf_row_range_per_page']=[[min(rows),max(rows)] if rows else [] for rows in (list(map(int,re.findall(r'Row\s*(\d{3})',txt))) for txt in pages)]
            else:assert_lines(docx_text(path))
            outputs[fmt]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size,'status':response.value.status}
            receipt['downloads']=outputs;stage('download_'+fmt+'_complete_and_in_order')
        same()
        receipt['formal_browser_flow_passed']=True;stage('source_remained_on_one_release')
        chrome.close()
if __name__=='__main__':main()
