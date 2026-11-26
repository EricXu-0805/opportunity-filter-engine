"""Upload a mixed and an image-only synthetic PDF through the first-party profile screen."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from check import confirm_school, expect, home, reads, sessions, sync_playwright

warning='Some pages have no readable text. Check the original PDF for missing content before using the extracted text.'
failure='No readable text was found. Use a PDF with selectable text; your saved résumé has not been replaced.'
marker='Visible text on synthetic page one.'
drawing='<svg width="120" height="80"><rect x="5" y="5" width="90" height="45" fill="navy"/></svg>'
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    page=home(browser)
    for _ in range(80):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible(): break
    assert len(sessions)==1
    confirm_school(page)
    page.locator('#student_name').fill('Synthetic mixed page check')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    doc=browser.new_page()
    doc.set_content('<div style="break-after:page"><p>'+marker+'</p><p>Coursework: Linear Algebra</p></div>'+drawing)
    mixed=doc.pdf()
    doc.set_content(drawing)
    empty=doc.pdf()
    doc.close()
    picker=page.locator('input[type=file][accept*="pdf"]').first
    picker.set_input_files({'name':'mixed-pages.pdf','mimeType':'application/pdf','buffer':mixed})
    expect(page.get_by_text(warning,exact=True)).to_be_visible(timeout=55000)
    expect(page.get_by_text('Linear Algebra',exact=True).first).to_be_visible()
    page.wait_for_timeout(2500)
    fresh=home(browser,sessions[0])
    expect(fresh.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    confirm_school(fresh)
    expect(fresh.get_by_text('Linear Algebra',exact=True).first).to_be_visible()
    prior=next(row for row in reversed(reads) if marker in row['profile_data'].get('resume_text',''))
    stored=prior['profile_data']
    digest=stored.get('resume_incomplete_digest')
    fixed=os.environ.get('PDF_ACCEPTANCE_MODE')=='fixed'
    if fixed:
        from hashlib import sha256
        assert digest==sha256(stored['resume_text'].encode()).hexdigest()
        expect(fresh.get_by_text(warning,exact=True)).to_be_visible(timeout=15000)
    warning_on_reopen=fresh.get_by_text(warning,exact=True).is_visible()

    picker=fresh.locator('input[type=file][accept*="pdf"]').first
    picker.set_input_files({'name':'image-only.pdf','mimeType':'application/pdf','buffer':empty})
    expect(fresh.get_by_text(failure,exact=True)).to_be_visible(timeout=55000)
    expect(fresh.get_by_role('button',name='Try again',exact=True)).to_be_visible()
    again=home(browser,sessions[0])
    expect(again.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    confirm_school(again)
    current=next(row for row in reversed(reads) if marker in row['profile_data'].get('resume_text',''))
    assert prior['revision']==current['revision']
    assert current['profile_data']['coursework']==['Linear Algebra']
    assert current['profile_data'].get('resume_incomplete_digest')==digest
    replacement_clears=False
    if fixed:
        expect(again.get_by_text(warning,exact=True)).to_be_visible()
        readable=browser.new_page()
        readable.set_content('<p>Complete synthetic replacement.</p><p>Coursework: Computer Vision</p>')
        replacement=readable.pdf();readable.close()
        again.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'all-readable.pdf','mimeType':'application/pdf','buffer':replacement})
        expect(again.get_by_text('Computer Vision',exact=True).first).to_be_visible()
        again.wait_for_timeout(2500)
        final=home(browser,sessions[0])
        expect(final.get_by_text('Computer Vision',exact=True).first).to_be_visible(timeout=35000)
        end=next(r for r in reversed(reads) if 'Complete synthetic replacement' in r['profile_data'].get('resume_text',''))
        assert end['revision']>current['revision'] and end['profile_data'].get('resume_incomplete_digest') is None
        expect(final.get_by_text(warning,exact=True)).to_have_count(0)
        replacement_clears=True
    receipt={'complete_replacement_clears_warning':replacement_clears,'utc':datetime.now(timezone.utc).isoformat(),'site':'https://joinalab.com','frontend_sha':page.locator('html').get_attribute('data-release-sha'),'mixed_warning_after_upload':warning,'mixed_warning_visible_after_reopening_same_saved_profile':warning_on_reopen,'image_only_error':failure,'saved_revision_before_and_after':[prior['revision'],current['revision']],'earlier_source_and_course_retained':True}
    out=Path('m11-results')
    out.mkdir(exist_ok=True)
    (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    browser.close()
