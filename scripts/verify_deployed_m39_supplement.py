"""Check the public target résumé editor with one purpose-created synthetic guest."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect, Error
import verify_public_matching_experience as shared

TARGET = shared.site + '/opportunities/' + shared.target
TITLE = 'Campus sensor audit exercise'
TASK = 'I logged a sample of fictional sensor readings and checked their labels.'
OMITTED = 'My team piloted a synthetic dashboard.'
stamp = lambda: datetime.now(timezone.utc).isoformat()
report = {'started': stamp(), 'release_expected': shared.release, 'target': shared.target, 'completed': [], 'profile_revisions': [], 'observed_target_model_calls': 0, 'external_messages_sent': 0}
def step(tag):
    report['completed'].append(tag)
    print('verified', tag, flush=True)
def tab(c):
    p = c.new_page()
    p.goto(TARGET,wait_until='domcontentloaded')
    p.get_by_role('button', name='Renovate resume', exact=True).click(timeout=60000)
    dialog = p.get_by_role('dialog', name='Target résumé', exact=True)
    expect(dialog.get_by_role('button',name='Add experience details')).to_be_enabled(timeout=45000)
    return p,dialog
def own_context(c):
    def capture(r):
        path=urlsplit(r.url).path
        if path=='/rest/v1/rpc/commit_profile_patch_cas' and r.ok:
            data=r.json()
            if data.get('status')=='applied':
                report['profile_revisions'].append(data['revision'])
        elif path=='/api/tailor':
            report['observed_target_model_calls']+=1
    c.on('response',capture)
def stable_read(c):
    prefs=[]
    def receive(r):
        u=urlsplit(r.url)
        if u.hostname != shared.db or u.path != '/rest/v1/profiles' or not r.ok: return
        try:
            d=r.json()
            if isinstance(d,list) and d: d=d[0]
            if isinstance(d,dict) and isinstance(d.get('profile_data'),dict):
                prefs.append((d['revision'],d['profile_data']))
        except Error:
            pass
    c.on('response',receive)
    p=shared.home(c)
    expect(p.locator('#student_name')).to_have_value(shared.student,timeout=60000)
    for _ in range(80):
        if prefs: break
        p.wait_for_timeout(250)
    assert prefs,'missing profile readback'
    return p,prefs[-1]
def verify_downstream(browser, ctx, original_form):
    """Read the real editor, save an owned target document and inspect its actual exports."""
    import hashlib
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    from pypdf import PdfReader
    def scoped(route):
        req=route.request
        path=urlsplit(req.url)
        if req.method=='POST' and path.hostname==shared.db and path.path=='/rest/v1/rpc/commit_target_resume_with_provenance_cas':
            data=req.post_data_json
            assert data['p_expected_owner']==shared.auth[0]['user']['id'] and data['p_opportunity_id']==shared.target and TITLE in req.post_data
            return route.continue_()
        if req.method=='POST' and path.hostname=='joinalab.com' and path.path=='/api/resume/full-target/export':
            assert TITLE in (req.post_data or '') and OMITTED not in (req.post_data or '')
            return route.continue_()
        return shared.guard(route)
    def enable(c):
        c.route('**/*',scoped)
    def lines(d):
        return d.locator('[data-testid^="target-block-"] textarea').evaluate_all('(xs)=>xs.map(x=>x.value)')
    def save(p,d,expected):
        with p.expect_response(lambda r: urlsplit(r.url).path=='/rest/v1/rpc/commit_target_resume_with_provenance_cas',timeout=60000) as sent:
            d.get_by_role('button',name='Save target draft',exact=True).click()
        res=sent.value
        assert res.ok and res.json().get('revision')==expected and res.json()['status']=='saved',(res.status,res.json().get('status'))
        expect(d.get_by_text('Saved version '+str(expected),exact=True)).to_be_visible(timeout=45000)
    def export(p,d,fmt,keep_task):
        control=d.get_by_role('region', name='Export current résumé')
        with p.expect_download(timeout=65000) as file, p.expect_response(lambda r: urlsplit(r.url).path=='/api/resume/full-target/export', timeout=65000) as fetched:
            control.get_by_role('button', name='Export '+('Word' if fmt=='docx' else 'PDF'),exact=True).click()
        asset=file.value
        assert fetched.value.ok and asset.failure() is None
        raw=Path(asset.path()).read_bytes()
        if fmt=='pdf':
            pdf=PdfReader(io.BytesIO(raw))
            assert len(pdf.pages)==1
            text=' '.join(pg.extract_text() for pg in pdf.pages)
        else:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                tree=ET.fromstring(z.read('word/document.xml'))
            text=' '.join(node.text or '' for node in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        flattened=' '.join(text.split())
        assert TITLE in flattened and (TASK in flattened)==keep_task and OMITTED not in flattened
        assert all(s not in flattened for s in ('profile_signature',shared.target,'Change records'))
        return {'format':fmt,'http':fetched.value.status,'included_selected_answer':keep_task,'excluded_unselected_answer':True,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    enable(ctx)
    p,d=tab(ctx)
    d.get_by_role('button',name='Create from confirmed master').click(timeout=60000)
    expect(d.get_by_role('button',name='Save target draft')).to_be_visible(timeout=45000)
    assert TASK in ' '.join(lines(d)) and OMITTED not in ' '.join(lines(d))
    save(p,d,1)
    report['exports']=[export(p,d,fmt,True) for fmt in ('pdf','docx')]
    step('confirmed_supplement_is_in_cloud_target_resume_version_1_and_downloaded_pdf_word')
    p.close()
    entry=original_form.locator('#experience-library details').filter(has=original_form.locator('summary',has_text='I logged a sample')).first
    entry.locator('summary').first.click()
    with original_form.expect_response(lambda r:urlsplit(r.url).path=='/rest/v1/rpc/commit_profile_patch_cas' and r.ok,timeout=60000):
        entry.get_by_role('button',name='Do not use',exact=True).click()
    clean=shared.cold(browser);enable(clean);_,(revision,withdrawn)=stable_read(clean)
    assert withdrawn['experience_entries'][0]['status']=='rejected'
    p,d=tab(clean)
    expect(d.get_by_text('Saved version 1',exact=True)).to_be_visible(timeout=60000)
    assert TASK in ' '.join(lines(d))
    d.get_by_role('button',name='Rebuild from current confirmed master').click()
    d.get_by_role('button',name='Create new draft',exact=True).click()
    expect(d.get_by_text('Unsaved local edits',exact=True)).to_be_visible(timeout=45000)
    assert TITLE in ' '.join(lines(d)) and TASK not in ' '.join(lines(d)) and OMITTED not in ' '.join(lines(d))
    save(p,d,2)
    report['exports'].extend(export(p,d,fmt,False) for fmt in ('pdf','docx'))
    clean.close()
    again=shared.cold(browser);enable(again)
    p,d=tab(again)
    expect(d.get_by_text('Saved version 2',exact=True)).to_be_visible(timeout=60000)
    assert TITLE in ' '.join(lines(d)) and TASK not in ' '.join(lines(d))
    report['saved_target_versions']=[1,2]
    report['withdrawn_profile_revision']=revision
    step('original_version_retained_until_rebuilt_and_withdrawn_source_absent_from_new_draft_and_both_exports')
    again.close()

def run():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        check=pw.request.new_context()
        def versions():
            a=check.get(shared.site+'/api/health',timeout=45000).json()['release_sha']
            assert f'data-release-sha="{a}"' in check.get(shared.site+'/about',timeout=45000).text() and a==shared.release
            return a
        report['initial_release']=versions()
        c=shared.cold(browser); own_context(c); home=shared.home(c)
        home.locator('#student_name').fill(shared.student)
        home.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
        home.locator('#major').select_option(label='Integrative Biology')
        home.locator('#grade').select_option(label='Sophomore')
        editor=home.get_by_test_id('resume-master-editor')
        editor.locator(':scope > summary').click()
        editor.get_by_role('button', name='Add experience or project').click()
        editor.get_by_label('Role / project title',exact=True).fill(TITLE)
        editor.get_by_role('button', name='Confirm Role / project title').click()
        with home.expect_response(lambda r: urlsplit(r.url).path=='/rest/v1/rpc/commit_profile_patch_cas' and r.ok and TITLE in (r.request.post_data or ''),timeout=60000):
            editor.get_by_role('button', name='Apply changes').click()
        c2=shared.cold(browser);p0,(rv,baseline)=stable_read(c2)
        assert baseline['resume_master']['activities'][0]['title']['value']==TITLE
        assert baseline['resume_master']['activities'][0]['title']['status']=='confirmed'
        assert not baseline.get('experience_entries')
        c2.close()
        step('self_created_visitor_manual_project_confirmed_and_cloud_read_back')
        p1,dlg=tab(c)
        dlg.get_by_role('button', name='Add experience details').click()
        pan=dlg.get_by_test_id('resume-supplement-panel')
        pan.get_by_label('Project or experience in your master résumé').select_option(label=TITLE)
        pan.get_by_label('What was the task?').fill(TASK)
        pan.get_by_label('Include task',exact=True).check()
        other_label=pan.locator('textarea').nth(3)
        other_label.fill(OMITTED)
        step('unsubmitted_task_entered')
        p2,other=tab(c)
        expect(other.get_by_role('button',name='Add experience details')).to_have_attribute('aria-expanded','false')
        other.get_by_role('button',name='Add experience details').click()
        expect(other.get_by_label('What was the task?')).to_have_value('')
        p2.close()
        step('another_tab_does_not_take_open_answers')
        dlg.get_by_role('button',name='Close target résumé').click()
        expect(dlg).to_have_count(0)
        p1.get_by_role('button', name='Renovate resume', exact=True).click()
        recovered=p1.get_by_test_id('resume-supplement-panel')
        expect(recovered.get_by_test_id('supplement-recovery-review')).to_be_visible(timeout=45000)
        expect(recovered.get_by_label('What was the task?')).to_have_value(TASK)
        expect(recovered.locator('textarea').nth(3)).to_have_value(OMITTED)
        expect(recovered.get_by_label('Project or experience in your master résumé')).to_have_value(baseline['resume_master']['activities'][0]['id'])
        button=recovered.get_by_role('button',name='Confirm and add to my master résumé')
        expect(button).to_be_disabled()
        c3=shared.cold(browser);p3,(rr,before)=stable_read(c3);c3.close()
        assert rr==rv and not before.get('experience_entries')
        step('closing_then_reopening_restores_selected_project_and_unsubmitted_answers_without_cloud_write')
        recovered.get_by_label('I reviewed the current activity and profile, and confirm the selected information is accurate.').check()
        with p1.expect_response(lambda r: urlsplit(r.url).path=='/rest/v1/rpc/commit_profile_patch_cas' and r.ok and TASK in (r.request.post_data or ''),timeout=60000):
            button.click()
        expect(recovered.get_by_role('button',name='Added to master résumé')).to_be_visible(timeout=60000)
        c4=shared.cold(browser);p4,(ra,after)=stable_read(c4)
        entries=after['experience_entries'];assert len(entries)==1 and TASK in entries[0]['text'] and OMITTED not in json.dumps(after)
        activity=after['resume_master']['activities'][0];assert activity['details']==[{'id':entries[0]['id'],'revision':entries[0]['revision']}]
        assert ra==rr+1
        step('explicit_reconfirmation_writes_only_the_selected_answer_and_links_the_same_project')
        verify_downstream(browser,c4,p4)
        report['guest_signup_returned']=bool(shared.auth)
        report['cloud_versions']=[rv,rr,ra]
        report['final_release']=versions()
        report['passed']=True
        c4.close();c.close();browser.close()
if __name__=='__main__':
    try:run()
    finally:
        report['finished']=stamp()
        Path(os.environ.get('OFE_M39_RESULT','/tmp/ofe-m39-production-result.json')).write_text(json.dumps(report,indent=2)+'\n')
