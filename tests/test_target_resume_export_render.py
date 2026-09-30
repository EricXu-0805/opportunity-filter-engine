"""Real standard-v1 binary outputs: Unicode, pagination and editable full fonts."""
from __future__ import annotations

import io
import json
import re
import zipfile
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from lxml import etree

from backend.lib import target_resume_export as renderer
from backend.lib.target_resume_export_schema import ExportError

FIXTURE = Path(__file__).parent / 'fixtures' / 'target-resume-export-golden.json'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'


def sample(text='Student 中文 😀'):
    return {'version': 1, 'template': 'standard-v1', 'locale': 'en', 'page_size': 'letter',
            'sections': [{'kind': 'basics', 'heading': '', 'blocks': [{'lines': [{'role': 'name', 'label': '', 'text': text}]}]}]}


SKILLS = ['Python', 'PyTorch', 'SQL', 'C++', 'Git', 'Linux', 'pandas', 'scikit-learn']


def resume_draft(locale='en', page_size='letter'):
    """The 1,210-character 2026-09-30 stranger-walk draft (target: 1 page) that exported as 2 pages."""
    def block(*lines):
        return {'lines': [{'role': role, 'label': '', 'text': text} for role, text in lines]}
    return {'version': 1, 'template': 'standard-v1', 'locale': locale, 'page_size': page_size, 'sections': [
        {'kind': 'basics', 'heading': '', 'blocks': [block(
            ('name', 'Jordan Avery Lee'), ('email', 'jordan.lee.test@example.com'), ('location', 'Urbana, IL'))]},
        {'kind': 'education', 'heading': '', 'blocks': [block(
            ('school', 'University of Illinois Urbana-Champaign'), ('degree', 'B.S.'), ('field', 'Computer Science'),
            ('end', 'Expected May 2028'), ('experience', 'GPA 3.7/4.0'),
            ('experience', 'Relevant coursework: Data Structures (CS 225), Computer Architecture (CS 233), '
                           'Linear Algebra (MATH 257), Probability & Statistics (STAT 400).'))]},
        {'kind': 'activities', 'heading': '', 'blocks': [
            block(('title', 'Undergraduate Research Assistant'), ('organization', 'Health Imaging Lab (UIUC)'),
                  ('start', 'Jan 2026'), ('end', 'Present'),
                  ('experience', '- Built a PyTorch pipeline that preprocesses 12,000 chest X-ray images and trains a '
                                 'ResNet-18 baseline, reaching 0.87 AUC on a held-out split.'),
                  ('experience', '- Worked with a PhD mentor as part of a four-person team to compare Grad-CAM and '
                                 'integrated-gradients saliency maps; I wrote the evaluation scripts.')),
            block(('title', 'Software Engineering Intern'), ('organization', 'Prairie Analytics'), ('location', 'Champaign, IL'),
                  ('start', 'Jun 2026'), ('end', 'Aug 2026'),
                  ('experience', "- Wrote SQL and Python ETL jobs that cut a nightly report's runtime from 40 minutes to 9 minutes."),
                  ('experience', '- Added unit tests (pytest) for 14 data-validation functions.')),
            block(('title', 'Swahili-English Sentiment Classifier'),
                  ('experience', 'Swahili-English Sentiment Classifier (course project, CS 446) - fine-tuned a multilingual '
                                 'BERT on 3,000 labeled tweets; 78% accuracy vs 71% baseline.')),
            block(('title', 'Campus Bus Tracker'),
                  ('experience', 'Campus Bus Tracker - React + Flask web app used by about 200 students during Fall 2025.'))]},
        {'kind': 'skills', 'heading': '', 'blocks': [block(('skill', skill)) for skill in SKILLS]}]}


ROLE_LABELS = ('School:', 'Degree:', 'Field:', 'Start:', 'End:', 'Organization:', 'Location:', 'Email:',
               '学校:', '学位:', '专业:', '开始:', '结束:', '机构:', '地点:', '邮箱:')


@pytest.mark.parametrize('locale', ['en', 'zh'])
@pytest.mark.parametrize('page_size', ['letter', 'a4'])
def test_short_pdf_reads_as_a_one_page_resume(locale, page_size):
    value = resume_draft(locale, page_size)
    pdf = pdf_reader(renderer.render_export(value, 'pdf'))
    assert len(pdf.pages) == 1
    rows = pdf.pages[0].extract_text().splitlines()
    assert not [row for row in rows if any(label in row for label in ROLE_LABELS)]
    # Title, organization and dates share one row; so do contact details and all skills.
    for left, right in [('Undergraduate Research Assistant · Health Imaging Lab (UIUC)', 'Jan 2026 – Present'),
                        ('Software Engineering Intern · Prairie Analytics · Champaign, IL', 'Jun 2026 – Aug 2026'),
                        ('University of Illinois Urbana-Champaign · B.S. · Computer Science', 'Expected May 2028')]:
        assert [row for row in rows if left in row and right in row and row.index(left) < row.index(right)], rows
    assert 'jordan.lee.test@example.com · Urbana, IL' in rows
    assert (', ' if locale == 'en' else '、').join(SKILLS) in rows


def test_short_docx_reads_as_a_compact_resume():
    from docx import Document
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Emu
    document = Document(io.BytesIO(renderer.render_export(resume_draft(), 'docx')))
    paragraphs = {paragraph.text: paragraph for paragraph in document.paragraphs}
    assert not [text for text in paragraphs if text.startswith(ROLE_LABELS)]
    assert 'jordan.lee.test@example.com · Urbana, IL' in paragraphs
    assert ', '.join(SKILLS) in paragraphs
    entry = paragraphs['Undergraduate Research Assistant · Health Imaging Lab (UIUC)\tJan 2026 – Present']
    stops = entry.paragraph_format.tab_stops
    page = document.sections[0]
    right_margin = Emu(page.page_width - page.left_margin - page.right_margin).twips
    assert [(stop.alignment, stop.position.twips) for stop in stops] == [(WD_TAB_ALIGNMENT.RIGHT, right_margin)]
    assert entry.paragraph_format.keep_with_next  # A role line never ends a page without its first detail.
    assert 'Software Engineering Intern · Prairie Analytics · Champaign, IL\tJun 2026 – Aug 2026' in paragraphs
    assert 'University of Illinois Urbana-Champaign · B.S. · Computer Science\tExpected May 2028' in paragraphs
    heading = paragraphs['Experience']
    assert heading.paragraph_format.keep_with_next
    assert heading._p.pPr.find(f'{{{W}}}pBdr/{{{W}}}bottom') is not None
    assert len(document.paragraphs) == 19  # Was 37: one paragraph per field and per skill.


def contact_projection(contact, page_size='letter'):
    lines = [('name', '', 'Jordan Lee'), *contact]
    return {'version': 1, 'template': 'standard-v1', 'locale': 'en', 'page_size': page_size, 'sections': [
        {'kind': 'basics', 'heading': '', 'blocks': [{'lines': [{'role': role, 'label': label, 'text': text}
                                                                for role, label, text in lines]}]}]}


LINKS = [('GitHub', 'https://github.com/alexandra-garcia0805'), ('LinkedIn', 'https://www.linkedin.com/in/alexandra-garcia-0805'),
         ('Portfolio', 'https://alexandra-garcia.example.dev/projects')]
CONTACTS = [
    # 2026-09-30 review: Letter printed 'LinkedI' / 'n: https://…' and A4 'Link' / 'edIn: https://…'.
    [('email', '', 'jordan@example.com'), ('phone', '', '+1 217 555 0100'), ('location', '', 'Urbana, IL'),
     ('url', 'GitHub', 'https://github.com/jordan'), ('url', 'LinkedIn', 'https://www.linkedin.com/in/jordan')],
    *[[('email', '', email), *([('phone', '', '+1 217 555 0100')] if phone else []), ('location', '', 'Urbana, IL'),
       *[('url', label, url) for label, url in LINKS[:count]]]
      for email in ('jordan@example.com', 'alexandra.garcia0805@illinois.edu') for phone in (False, True) for count in range(4)],
]


@pytest.mark.parametrize('page_size', ['letter', 'a4'])
def test_pdf_contact_row_wraps_between_whole_items_and_keeps_their_links(page_size):
    wrapped = 0
    for contact in CONTACTS:
        pdf = pdf_reader(renderer.render_export(contact_projection(contact, page_size), 'pdf'))
        rows = pdf.pages[0].extract_text().splitlines()[1:]
        wrapped += len(rows) > 1
        # No item is cut inside a word, and a separator ends the line of the item before it.
        items = [f'{label}: {text}' if label else text for _role, label, text in contact]
        assert [item for row in rows for item in row.removesuffix(' ·').split(' · ')] == items, rows
        targets = ['mailto:' + text if role == 'email' else text for role, _label, text in contact if role in ('email', 'url')]
        assert sorted(annotation.get_object()['/A']['/URI'] for annotation in pdf.pages[0]['/Annots']) == sorted(targets), rows
    assert wrapped >= 5


def test_skill_category_lines_keep_their_own_rows():
    # Joining 'Languages: Python, C++' and 'Tools: Git' with ', ' blurred which skill belongs to which list.
    from docx import Document
    for locale, skills, expected in [
        ('en', ['Python', 'SQL', 'Languages: Python, C++, Java', 'Tools: Git, Docker, Linux',
                'Spoken: English (fluent), Mandarin (native)', 'Git', 'Docker'],
         ['Skills', 'Python, SQL', 'Languages: Python, C++, Java', 'Tools: Git, Docker, Linux',
          'Spoken: English (fluent), Mandarin (native)', 'Git, Docker']),
        ('zh', ['编程语言：Python、C++', '工具：Git、Docker', 'Python', 'SQL'], ['技能', '编程语言：Python、C++', '工具：Git、Docker', 'Python、SQL']),
    ]:
        value = {'version': 1, 'template': 'standard-v1', 'locale': locale, 'page_size': 'letter', 'sections': [
            {'kind': 'skills', 'heading': '', 'blocks': [{'lines': [{'role': 'skill', 'label': '', 'text': skill}]} for skill in skills]}]}
        assert pdf_reader(renderer.render_export(value, 'pdf')).pages[0].extract_text().splitlines() == expected
        assert [paragraph.text for paragraph in Document(io.BytesIO(renderer.render_export(value, 'docx'))).paragraphs] == expected


def pdf_reader(data):
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(data), strict=True)


def flat(text):
    return re.sub(r'\s', '', text)


@pytest.mark.parametrize('page_size,dimensions', [('letter', (612, 792)), ('a4', (595.28, 841.89))])
def test_pdf_true_unicode_text_and_page_dimensions(page_size, dimensions):
    value = sample('姓名 Student 中文 😀 <script>& text')
    value['page_size'] = page_size
    data = renderer.render_export(value, 'pdf')
    pdf = pdf_reader(data)
    assert flat('姓名 Student 中文 😀 <script>& text') in flat(pdf.pages[0].extract_text())
    box = pdf.pages[0].mediabox
    assert float(box.width) == pytest.approx(dimensions[0], abs=0.1)
    assert float(box.height) == pytest.approx(dimensions[1], abs=0.1)
    fonts = [f.get_object() for page in pdf.pages for f in page['/Resources']['/Font'].values()]
    assert any(b'D83DDE00' in font['/ToUnicode'].get_object().get_data() for font in fonts if '/ToUnicode' in font)
    assert any('/FontFile2' in font['/DescendantFonts'][0].get_object()['/FontDescriptor'] for font in fonts if '/DescendantFonts' in font)


def test_pdf_long_single_paragraph_and_unbroken_token_keep_tail_and_all_content():
    content = ('English text 中文 paragraph. ' * 1300) + ' LongTokenStart' + 'x' * 3000 + 'LongTokenEnd TAIL结束'
    value = sample('Student')
    value['sections'].append({'kind': 'activities', 'heading': '', 'blocks': [{'lines': [{'role': 'experience', 'label': '', 'text': content}]}]})
    data = renderer.render_export(value, 'pdf')
    pdf = pdf_reader(data)
    extracted = ''.join(page.extract_text() for page in pdf.pages)
    assert len(pdf.pages) > 3
    assert flat(content) in flat(extracted)
    assert 'TAIL结束' in flat(pdf.pages[-1].extract_text())
    assert all(page.extract_text().strip() for page in pdf.pages)


def test_pdf_signed_golden_preserves_selected_order_and_unicode():
    value = json.loads(FIXTURE.read_text())['projection']
    before = deepcopy(value)
    data = renderer.render_export(value, 'pdf')
    extracted = flat(''.join(page.extract_text() for page in pdf_reader(data).pages))
    cursor = 0
    for section in value['sections']:
        for block in section['blocks']:
            for line in block['lines']:
                needle = flat(line['text'])
                cursor = extracted.index(needle, cursor) + len(needle)
    assert value == before
    assert '徐同学😀' in extracted


def embedded_programs(data):
    """(fontTable entry, decrypted font bytes) for each embedded font, in fontTable order."""
    z = zipfile.ZipFile(io.BytesIO(data))
    fonts = etree.fromstring(z.read('word/fontTable.xml'))
    by_id = {node.get('Id'): node for node in etree.fromstring(z.read('word/_rels/fontTable.xml.rels'))}
    result = []
    for node in fonts.findall(f'{{{W}}}font/{{{W}}}embedRegular'):
        rel = by_id[node.get(f'{{{R}}}id')]
        assert rel.get('Type') == R + '/font'
        assert rel.get('TargetMode') is None
        encrypted = bytearray(z.read('word/' + rel.get('Target')))
        key = UUID(node.get(f'{{{W}}}fontKey')).bytes[::-1]
        for i in range(32):
            encrypted[i] ^= key[i % 16]
        result.append((node.getparent(), bytes(encrypted)))
    return result


def test_docx_embedded_font_subsets_relationships_and_editable_unicode():
    from docx import Document
    from fontTools.ttLib import TTFont
    value = sample('  姓名 Student 中文 😀 <script>& text\tline\r\nnext  ')
    value['sections'].append({'kind': 'activities', 'heading': '', 'blocks': [{'lines': [{'role': 'experience', 'label': '', 'text': 'A sentence that can be edited.'}]}]})
    data = renderer.render_export(value, 'docx')
    document = Document(io.BytesIO(data))
    assert '<script>& text' in document.paragraphs[0].text
    assert '\t' in document.paragraphs[0].text and '😀' in document.paragraphs[0].text
    assert document.paragraphs[0].text.count('\n') == 1  # CRLF is one visual break.
    assert document.paragraphs[0].text.startswith('  ') and document.paragraphs[0].text.endswith('  ')
    document.paragraphs[-1].add_run(' Edited after export 中文.')
    modified = io.BytesIO()
    document.save(modified)
    assert Document(io.BytesIO(modified.getvalue())).paragraphs[-1].text.endswith('Edited after export 中文.')
    z = zipfile.ZipFile(io.BytesIO(data))
    embedded = embedded_programs(data)
    assert len(embedded) == 2
    assets = renderer.fonts()
    text = set(map(ord, ''.join(paragraph.text for paragraph in document.paragraphs))) - {9, 10, 13}
    shown = [{point for point in text if point in assets[0].codepoints}, {point for point in text if point not in assets[0].codepoints}]
    for (entry, program), asset, characters in zip(embedded, assets, shown, strict=True):
        assert entry.find(f'{{{W}}}embedRegular').get(f'{{{W}}}subsetted') == '1'
        with TTFont(io.BytesIO(program)) as font:
            assert 'glyf' in font and 'fvar' not in font and font['OS/2'].fsType == 0
            cmap = frozenset(font.getBestCmap())
            # Every character this file sets in the font, never a glyph outside the pinned font.
            assert characters <= cmap <= asset.codepoints
            # OFL: the copyright and licence records travel with the embedded subset.
            assert font['name'].getDebugName(0) and font['name'].getDebugName(13)
    settings = etree.fromstring(z.read('word/settings.xml'))
    assert settings.find(f'{{{W}}}embedTrueTypeFonts').get(f'{{{W}}}val') == 'true'
    assert settings.find(f'{{{W}}}saveSubsetFonts').get(f'{{{W}}}val') == 'false'
    assert not any(name.endswith(('vbaProject.bin', '.html')) for name in z.namelist())


COMMON_HANZI = '的一是了我不人在他有这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日手又行意动方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感'


def test_docx_with_one_chinese_line_stays_small_and_keeps_common_characters_editable():
    from fontTools.ttLib import TTFont
    value = resume_draft()
    value['sections'][-1]['blocks'].append({'lines': [{'role': 'skill', 'label': '', 'text': '中文（母语）'}]})
    data = renderer.render_export(value, 'docx')
    # 11,595,724 bytes in production: the whole 21.7 MB CJK program rode along.
    assert len(data) < 1_000_000
    [(entry, program)] = embedded_programs(data)
    assert entry.get(f'{{{W}}}name') == renderer.fonts()[0].name
    with TTFont(io.BytesIO(program)) as font:
        cmap = frozenset(font.getBestCmap())
    # Text typed later in Word keeps the same face for Latin, CJK punctuation and common hanzi.
    assert set(map(ord, '中文（母语）' + COMMON_HANZI + '，。、；：？！“”《》')) | set(range(0x20, 0x7F)) <= cmap
    assert len(cmap) < len(renderer.fonts()[0].codepoints) / 5


def test_docx_font_table_declares_embedded_cjk_font_for_east_asian_text():
    # Without charset/signature facts Word desktop set the embedded font's CJK
    # text in SimSun, although it used that font for the Latin text.
    from fontTools.ttLib import TTFont
    [(entry, _program)] = embedded_programs(renderer.render_export(sample('张三 Student'), 'docx'))
    with TTFont(renderer.fonts()[0].path) as font:
        os2 = font['OS/2']
    assert [etree.QName(child).localname for child in entry] == ['panose1', 'charset', 'family', 'pitch', 'sig', 'embedRegular']
    values = {etree.QName(child).localname: child for child in entry}
    assert values['charset'].get(f'{{{W}}}val') == '86'  # GB2312
    assert values['family'].get(f'{{{W}}}val') == 'swiss'
    assert values['pitch'].get(f'{{{W}}}val') == 'variable'
    assert values['panose1'].get(f'{{{W}}}val') == '020B0200000000000000'
    signature = {key: values['sig'].get(f'{{{W}}}{key}') for key in ('usb0', 'usb1', 'usb2', 'usb3', 'csb0', 'csb1')}
    assert signature == {'usb0': f'{os2.ulUnicodeRange1:08X}', 'usb1': f'{os2.ulUnicodeRange2:08X}',
                         'usb2': f'{os2.ulUnicodeRange3:08X}', 'usb3': f'{os2.ulUnicodeRange4:08X}',
                         'csb0': f'{os2.ulCodePageRange1:08X}', 'csb1': f'{os2.ulCodePageRange2:08X}'}
    assert int(signature['csb0'], 16) & (1 << 18)  # Simplified Chinese code page.


@pytest.mark.parametrize('output', ['pdf', 'docx'])
@pytest.mark.parametrize('text', ['\U0010ffff', '👩\u200d💻', '👍🏽', '🇺🇸', '☀\ufe0f'])
def test_unsupported_glyph_or_sequence_is_rejected_not_dropped(output, text):
    with pytest.raises(ExportError, match='^unsupported_glyph$'):
        renderer.render_export(sample(text), output)


def test_missing_font_assets_are_safe(monkeypatch, tmp_path):
    renderer.fonts.cache_clear()
    monkeypatch.setattr(renderer, 'FONT_DIRECTORY', tmp_path)
    try:
        with pytest.raises(ExportError, match='^fonts_unavailable$'):
            renderer.render_export(sample(), 'pdf')
    finally:
        renderer.fonts.cache_clear()


def test_renderer_uses_text_not_markup_or_external_fetch(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *_a, **_kw: pytest.fail('export attempted a fetch'))
    value = sample('<img src="https://example.invalid/private"> & entity')
    value['sections'][0]['blocks'][0]['lines'].append({'role': 'url', 'label': '', 'text': 'javascript:alert(1)'})
    for output in ('pdf', 'docx'):
        data = renderer.render_export(value, output)
        if output == 'pdf':
            pdf = pdf_reader(data)
            assert '<imgsrc="https://example.invalid/private">&entity' in flat(pdf.pages[0].extract_text())
            assert not pdf.pages[0].get('/Annots')
        else:
            z = zipfile.ZipFile(io.BytesIO(data))
            xml = z.read('word/document.xml')
            assert b'&lt;img' in xml and b'<img ' not in xml
            assert b'TargetMode="External"' not in z.read('word/_rels/document.xml.rels')


def test_docx_and_pdf_links_preserve_safe_target_as_annotations_only():
    value = sample('Student')
    url = 'https://example.edu/path?q=a&mode=b'
    value['sections'][0]['blocks'][0]['lines'].append({'role': 'url', 'label': 'Portfolio', 'text': url})
    pdf = pdf_reader(renderer.render_export(value, 'pdf'))
    assert any(annotation.get_object()['/A']['/URI'] == url for annotation in pdf.pages[0]['/Annots'])
    z = zipfile.ZipFile(io.BytesIO(renderer.render_export(value, 'docx')))
    relationships = etree.fromstring(z.read('word/_rels/document.xml.rels'))
    assert any(node.get('Target') == url and node.get('TargetMode') == 'External' for node in relationships)
    assert url in ''.join(etree.fromstring(z.read('word/document.xml')).itertext())


def test_output_size_guards_do_not_trim_or_return_partial_files(monkeypatch):
    buffer = renderer.CappedBuffer()
    buffer.seek(renderer.MAX_FILE_BYTES)
    with pytest.raises(ExportError, match='^export_too_large$'):
        buffer.write(b'x')
    monkeypatch.setattr(renderer, 'MAX_FILE_BYTES', 1024)
    with pytest.raises(ExportError, match='^export_too_large$'):
        renderer.render_export(sample(), 'pdf')


def test_pdf_page_limit_refuses_next_page_without_returning_a_partial_file(monkeypatch):
    from fpdf import FPDF
    monkeypatch.setattr(renderer, 'MAX_PDF_PAGES', 2)
    created = []
    original = FPDF.add_page

    def record(pdf, *args, **kwargs):
        result = original(pdf, *args, **kwargs)
        created.append(pdf.page_no())
        return result

    monkeypatch.setattr(FPDF, 'add_page', record)
    value = sample('x\n' * 150)
    before = deepcopy(value)
    with pytest.raises(ExportError, match='^export_too_large$'):
        renderer.render_export(value, 'pdf')
    assert created == [1, 2]  # Page 3 is rejected before FPDF creates it.
    assert value == before


@pytest.mark.parametrize('output', ['pdf', 'docx'])
def test_expired_worker_deadline_stops_before_loading_fonts(monkeypatch, output):
    monkeypatch.setattr(renderer, 'monotonic', lambda: 2.0)
    monkeypatch.setattr(renderer, 'fonts', lambda: pytest.fail('expired work started font loading'))
    with pytest.raises(ExportError, match='^export_timeout$'):
        renderer.render_export(sample(), output, deadline=1.0)


def test_glyph_preflight_checks_deadline_after_bounded_shaping_chunk(monkeypatch):
    import uharfbuzz as hb
    clock, lengths = [0.0], []
    monkeypatch.setattr(renderer, 'monotonic', lambda: clock[0])
    original = hb.shape

    def shape(font, buffer):
        lengths.append(len(buffer.glyph_infos))
        original(font, buffer)
        clock[0] = 2.0

    monkeypatch.setattr(hb, 'shape', shape)
    with pytest.raises(ExportError, match='^export_timeout$'):
        renderer.render_export(sample('x' * 12000), 'pdf', deadline=1.0)
    assert lengths == [renderer.GLYPH_CHECK_CHARS]


def test_pdf_automatic_page_break_checks_deadline_inside_single_paragraph(monkeypatch):
    from fpdf import FPDF
    clock, pages = [0.0], []
    monkeypatch.setattr(renderer, 'monotonic', lambda: clock[0])
    original = FPDF.add_page

    def add_page(pdf, *args, **kwargs):
        result = original(pdf, *args, **kwargs)
        pages.append(pdf.page_no())
        if len(pages) == 2:
            clock[0] = 2.0
        return result

    monkeypatch.setattr(FPDF, 'add_page', add_page)
    with pytest.raises(ExportError, match='^export_timeout$'):
        renderer.render_export(sample('x\n' * 150), 'pdf', deadline=1.0)
    assert pages == [1, 2]


def test_docx_iteration_and_zip_writes_check_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(renderer, 'monotonic', lambda: clock[0])
    original = renderer.font_runs
    seen = []

    def runs(text, assets, deadline=None):
        for index, run in original(text, assets, deadline):
            seen.append(run)
            yield index, run
            clock[0] = 2.0

    monkeypatch.setattr(renderer, 'font_runs', runs)
    with pytest.raises(ExportError, match='^export_timeout$'):
        renderer.render_docx(sample('English😀'), renderer.fonts(), deadline=1.0)
    assert seen == ['English', '😀']
    buffer = renderer.CappedBuffer(deadline=1.0)
    with pytest.raises(ExportError, match='^export_timeout$'):
        buffer.write(b'PK')
    assert buffer.getvalue() == b''


@pytest.mark.parametrize('position', ['heading', 'body'])
def test_wrapped_pdf_first_line_keeps_natural_word_spacing(position):
    value = sample('Student')
    if position == 'heading':
        value['sections'][0]['heading'] = 'Research notes ' + 'x' * 100
    else:
        value['sections'][0]['blocks'][0]['lines'] = [
            {'role': 'other', 'label': 'Additional notes 补充说明', 'text': 'x' * 120},
        ]
    page = pdf_reader(renderer.render_export(value, 'pdf')).pages[0]
    # Read actual text placement. The long following token wraps, leaving a
    # short first row; justification formerly stretched its words across 500pt.
    positions = []
    for operands, operator in page.get_contents().operations:
        if operator == b'Td' and not positions:
            positions.append(float(operands[0]))
        elif operator == b'Tm' and positions:
            positions.append(float(operands[4]))
        elif operator == b'ET' and positions:
            break
    assert len(positions) >= 2
    assert max(positions) - positions[0] < 160, positions


def embedded_fonts(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    fonts = etree.fromstring(z.read('word/fontTable.xml'))
    names = [node.getparent().get(f'{{{W}}}name') for node in fonts.findall(f'{{{W}}}font/{{{W}}}embedRegular')]
    return names, [name for name in z.namelist() if name.startswith('word/fonts/')]


@pytest.mark.parametrize('text,needed', [
    ('Jane Doe — Résumé • “quoted” naïve café €5', ()),
    ('Jane Doe 😀', (1,)),
    ('张三 Student', (0,)),
    ('Jane Doe → α', (0,)),
])
def test_docx_embeds_only_the_fonts_its_text_needs(text, needed):
    value = sample(text)
    value['sections'].append({'kind': 'activities', 'heading': '', 'blocks': [{'lines': [{'role': 'experience', 'label': '', 'text': 'Research assistant.'}]}]})
    data = renderer.render_export(value, 'docx')
    assets = renderer.fonts()
    names, parts = embedded_fonts(data)
    assert names == [assets[index].name for index in needed]
    assert len(parts) == len(needed)
    if not needed:
        # An English résumé stays an email-sized file and names no font the
        # reader would need but does not receive.
        assert len(data) < 100_000
        assert assets[0].name.encode() not in zipfile.ZipFile(io.BytesIO(data)).read('word/document.xml')
    from docx import Document
    assert Document(io.BytesIO(data)).paragraphs[0].text == text
