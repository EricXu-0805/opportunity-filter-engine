"""Verify existing bilingual and two-column PDFs and a long single-column profile in production storage."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from check import confirm_school, expect, home, reads, sessions, sync_playwright, writes

root = Path(__file__).resolve().parents[3]
fixtures = root / 'frontend/src/lib/__fixtures__/resume-pdf'
known = json.loads(Path(__file__).with_name('layout-expected.json').read_text())
out = Path('m11-results')
out.mkdir(exist_ok=True)
receipt = {'time':datetime.now(timezone.utc).isoformat(), 'files':[]}

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    page = home(browser)
    for _ in range(80):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible():
            break
    assert len(sessions) == 1
    confirm_school(page)
    page.locator('#student_name').fill('Synthetic layout check')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    printer = browser.new_page()
    introduction = [
        'Synthetic Student', 'synthetic-layout@example.com', 'EDUCATION', 'Bachelor of Arts, 2024 to 2028',
        'EXPERIENCE', 'Research contributor, Synthetic Lab', 'PROJECTS', 'Independent map of historical stockrooms',
    ]
    paragraphs = [f'Item {n:03d}. I reviewed the synthetic inventory sample and recorded the number of mock objects in the demonstration register.' for n in range(110)]
    tail = ['PUBLICATIONS', 'An invented reference for the parser study (2025)', 'Coursework: Discrete Mathematics; Text Mining',
            'Skills: Python, SQL', 'Final page marker for the synthetic layout acceptance.']
    printer.set_content('<style>p{font:11pt Arial;margin:0 0 3pt}</style>' + ''.join(f'<p>{t}</p>' for t in introduction+paragraphs+tail))
    long_pdf = printer.pdf()
    printer.close()
    cases = [(name, str(fixtures / name)) for name in known]
    cases.append(('long-english.pdf', {'name':'long-english.pdf', 'mimeType':'application/pdf','buffer':long_pdf}))
    for name, file in cases:
        previous = writes[-1] if writes else 0
        page.locator('input[type=file][accept*="pdf"]').first.set_input_files(file)
        expect(page.get_by_text(name, exact=True)).to_be_visible(timeout=55000)
        for _ in range(100):
            page.wait_for_timeout(250)
            if writes and writes[-1] > previous:
                break
        fresh = home(browser, sessions[0])
        expect(fresh.get_by_role('button', name='Remove file', exact=True)).to_be_visible(timeout=55000)
        confirm_school(fresh)
        row = next(r for r in reversed(reads) if r.get('revision',0)>previous and r['profile_data'].get('resume_text'))
        profile = row['profile_data']
        text = profile['resume_text']
        courses = sorted(profile.get('coursework') or [])
        digest = hashlib.sha256(text.encode()).hexdigest()
        if name in known:
            assert digest == known[name]['sha256'], (name, digest, len(text))
            assert courses == sorted(known[name]['courses']), (name, courses)
        else:
            assert len(text)>8000 and text.index('PUBLICATIONS')>8000
            assert all(s in text for s in [introduction[1],introduction[3],introduction[5],introduction[7],tail[1],tail[-1]])
            assert courses == ['Discrete Mathematics','Text Mining']
        for course in courses:
            expect(fresh.get_by_text(course, exact=True).first).to_be_visible()
        receipt['files'].append({'fixture':name,'revision':row['revision'],'chars_in_reopened_profile':len(text),
                                 'sha256':digest,'courses_visible_after_reopen':courses,
                                 'all_old_source_text_fields_matched': name in known,
                                 'tail_publication_and_skills_after_8000': name=='long-english.pdf'})
        page.context.close()
        page = fresh
    receipt['frontend_sha']=page.locator('html').get_attribute('data-release-sha')
    receipt['anonymous_accounts']=len(sessions)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    browser.close()
