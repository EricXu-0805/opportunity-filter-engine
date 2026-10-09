"""Text-only standard-v1 PDF/DOCX renderers using pinned local font assets.

No user markup, remote resources, source material, or current profile is read.
Both outputs keep the submitted section/block/line order and current wording.
standard-v1 sets each block as a résumé entry: its leading title/organization
fields share one row, with their dates at the right margin, and contact details
and single skills each share one row. Field roles are layout, not printed labels.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from time import monotonic
from urllib.parse import quote, urlsplit
from uuid import uuid4

from backend.lib.target_resume_export_schema import JS_WHITESPACE, MAX_FILE_BYTES, ExportError

FONT_DIRECTORY = Path(__file__).resolve().parents[1] / 'assets' / 'resume-fonts'
FONT_FILES = ('NotoSansCJKsc-Regular.ttf', 'NotoEmoji-Regular.ttf')
MAX_PDF_PAGES = 100
GLYPH_CHECK_CHARS = 4096


def check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ExportError('export_timeout')

HEADINGS = {
    'en': {'basics': '', 'education': 'Education', 'activities': 'Experience', 'publications': 'Publications', 'skills': 'Skills', 'other': 'Additional information'},
    'zh': {'basics': '', 'education': '教育经历', 'activities': '项目与经历', 'publications': '论文与发表', 'skills': '技能', 'other': '其他信息'},
}
# A résumé shows 'Expected May 2028', not 'End: Expected May 2028'. Only a DOI
# number needs its name, and a start date alone would read as a single date.
LABELS = {'en': {'doi': 'DOI', 'start': 'Start'}, 'zh': {'doi': 'DOI', 'start': '开始'}}
HEAD_ROLES = frozenset(('title', 'organization', 'location', 'school', 'degree', 'field', 'authors', 'venue'))
DATE_ROLES = frozenset(('start', 'end', 'date'))
SEPARATOR = ' · '
LIST_SEPARATOR = {'en': ', ', 'zh': '、'}
LIST_MARKS = re.compile(r'[:：,，、;；\r\n\t]')  # A skill line with these is a list of its own.
DATE_COLUMNS = 36  # Longer date text stays in its row instead of the right margin.
# Dates sit at the right margin of a one-line row only: a PDF cell there drops
# line breaks, and in the DOCX any tab in the row jumps to that margin's tab stop.
DATE_BREAKS = frozenset('\r\n\t')
PDF_STYLES = {'name': (18, 8), 'heading': (12, 6), 'body': (10.5, 5.3)}
PAGE_SLACK = 1e-6  # mm. The same heights summed in another order can round apart.
DOCX_SIZES = {'name': 18, 'heading': 12, 'body': 10.5}


@dataclass(frozen=True)
class FontAsset:
    path: Path
    name: str
    data: bytes
    codepoints: frozenset[int]
    # fontTable children before embedRegular, in schema order: (tag, attributes).
    declaration: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def font_declaration(font):
    """What Word reads to use an embedded font for a script.

    Without charset and code-page signature, Word desktop used the embedded CJK
    font for Latin text but set the Chinese text in SimSun.
    """
    os2, panose = font['OS/2'], font['OS/2'].panose
    digits = (panose.bFamilyType, panose.bSerifStyle, panose.bWeight, panose.bProportion, panose.bContrast,
              panose.bStrokeVariation, panose.bArmStyle, panose.bLetterForm, panose.bMidline, panose.bXHeight)
    ranges = (os2.ulUnicodeRange1, os2.ulUnicodeRange2, os2.ulUnicodeRange3, os2.ulUnicodeRange4,
              os2.ulCodePageRange1, os2.ulCodePageRange2)
    return (('panose1', (('val', ''.join(f'{digit:02X}' for digit in digits)),)),
            ('charset', (('val', '86' if os2.ulCodePageRange1 & (1 << 18) else '00'),)),  # 86: GB2312
            ('family', (('val', 'swiss' if panose.bFamilyType == 2 and panose.bSerifStyle >= 11 else 'auto'),)),
            ('pitch', (('val', 'fixed' if font['post'].isFixedPitch else 'variable'),)),
            ('sig', tuple(zip(('usb0', 'usb1', 'usb2', 'usb3', 'csb0', 'csb1'),
                              (f'{value:08X}' for value in ranges), strict=True))))


@lru_cache(maxsize=1)
def fonts() -> tuple[FontAsset, FontAsset]:
    try:
        from fontTools.ttLib import TTFont
        result = []
        for filename in FONT_FILES:
            path = FONT_DIRECTORY / filename
            data = path.read_bytes()
            with TTFont(io.BytesIO(data)) as font:
                # DOCX embeds subsets of these static glyf fonts for editing.
                # Preview/print-only and restricted fonts are unsuitable.
                if 'glyf' not in font or 'fvar' in font or (font['OS/2'].fsType & 0x0006):
                    raise ExportError('fonts_unavailable')
                name = font['name'].getDebugName(1)
                if not name or not font.getBestCmap():
                    raise ExportError('fonts_unavailable')
                result.append(FontAsset(path, name, data, frozenset(font.getBestCmap()), font_declaration(font)))
        return tuple(result)
    except ExportError:
        raise
    except Exception:
        raise ExportError('fonts_unavailable') from None


def font_runs(text: str, assets: tuple[FontAsset, FontAsset], deadline=None):
    """Fallback by supported glyph; never silently output .notdef boxes.

    standard-v1 supports individual monochrome emoji. Compound emoji/IVS
    sequences need an independently verified shaping-and-extraction contract;
    reject them intact until then, rather than deleting joiners/modifiers.
    """
    current, buffer = None, []
    for offset, char in enumerate(text):
        if offset % 1024 == 0:
            check_deadline(deadline)
        point = ord(char)
        if (point in (0x200D, 0x20E3, 0xFE0E, 0xFE0F) or 0x1F3FB <= point <= 0x1F3FF
                or 0x1F1E6 <= point <= 0x1F1FF or 0xE0020 <= point <= 0xE007F or 0xE0100 <= point <= 0xE01EF):
            raise ExportError('unsupported_glyph')
        index = 0 if char in '\r\n\t' or point in assets[0].codepoints else 1 if point in assets[1].codepoints else None
        if index is None:
            raise ExportError('unsupported_glyph')
        if current is not None and index != current:
            yield current, ''.join(buffer)
            buffer = []
        current = index
        buffer.append(char)
    if buffer:
        yield current, ''.join(buffer)


def heading(section, locale):
    return section['heading'] or HEADINGS[locale][section['kind']]


def labelled(text, label):
    return f'{label}: {text}' if label else text


def line_text(line, locale, title=''):
    """Explicit labels stay unless they repeat the section heading."""
    label = line['label'] if line['label'] != title else ''
    return labelled(line['text'], label or (LABELS[locale]['doi'] if line['role'] == 'doi' else ''))


@dataclass(frozen=True)
class Paragraph:
    """One rendered paragraph: (text, safe link) pieces, and dates set at the right margin."""
    style: str  # name, heading or body
    pieces: tuple[tuple[str, str | None], ...]
    right: str = ''
    keep: bool = False  # Keep with the next paragraph.
    end: bool = False  # Last paragraph of a block.

    @property
    def text(self) -> str:
        return ''.join(text for text, _link in self.pieces) + self.right


def blank(text):
    return not text.strip(JS_WHITESPACE)


def joined(pieces, separator):
    result = []
    for piece in pieces:
        result += [(separator, None), piece] if result else [piece]
    return tuple(result)


def date_text(lines, locale, title):
    roles, texts = [line['role'] for line in lines], [line_text(line, locale, title) for line in lines]
    if roles == ['start', 'end']:
        return f'{texts[0]} – {texts[1]}'
    return labelled(texts[0], LABELS[locale]['start']) if roles == ['start'] else SEPARATOR.join(texts)


def entry(lines, locale, title):
    """A block's leading head fields share one row, with the dates that follow them at its right."""
    index, head, dates = 0, [], []
    while index < len(lines) and lines[index]['role'] in HEAD_ROLES:
        head += [] if blank(lines[index]['text']) else [(line_text(lines[index], locale, title), None)]
        index += 1
    while index < len(lines) and lines[index]['role'] in DATE_ROLES:
        dates += [] if blank(lines[index]['text']) else [lines[index]]
        index += 1
    rest, result = lines[index:], []
    if head or dates:
        right = date_text(dates, locale, title) if dates else ''
        if head and right and not DATE_BREAKS & set(right + ''.join(text for text, _link in head)) \
                and sum(2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in right) <= DATE_COLUMNS:
            result.append(Paragraph('body', joined(head, SEPARATOR), right, keep=bool(rest)))
        else:
            result.append(Paragraph('body', joined(head + ([(right, None)] if right else []), SEPARATOR), keep=bool(rest)))
    result += [Paragraph('name' if line['role'] == 'name' else 'body', ((line_text(line, locale, title), safe_link(line)),))
               for line in rest]
    return result[:-1] + [replace(result[-1], end=True)] if result else []


def section_units(section, locale, title):
    """Contact details and single skills join one row; other blocks are entries.
    A skill line that is itself a list ('Tools: Git, Docker') keeps its own row."""
    for block in section['blocks']:
        if section['kind'] == 'basics':
            yield from (('name' if line['role'] == 'name' else 'row', line) for line in block['lines']
                        if line['role'] == 'name' or not blank(line['text']))
        elif section['kind'] == 'skills' and all(line['role'] == 'skill' for line in block['lines']):
            yield from (('line' if LIST_MARKS.search(line_text(line, locale, title)) else 'row', line)
                        for line in block['lines'] if not blank(line['text']))
        else:
            yield 'entry', block['lines']


def layout(projection):
    """Paragraphs in submitted order. Glyph checks, PDF and DOCX all use this text."""
    locale, result = projection['locale'], []
    for section in projection['sections']:
        title = heading(section, locale)
        if title:
            result.append(Paragraph('heading', ((title, None),), keep=True))
        separator = LIST_SEPARATOR[locale] if section['kind'] == 'skills' else SEPARATOR
        for kind, group in groupby(section_units(section, locale, title), key=itemgetter(0)):
            items = [item for _kind, item in group]
            if kind == 'row':
                pieces = [(line_text(line, locale, title), safe_link(line)) for line in items]
                result.append(Paragraph('body', joined(pieces, separator), end=True))
            elif kind == 'name':
                result += [Paragraph('name', ((line_text(line, locale, title), None),)) for line in items]
            elif kind == 'line':
                result += [Paragraph('body', ((line_text(line, locale, title), None),)) for line in items]
                result[-1] = replace(result[-1], end=True)
            else:
                for lines in items:
                    result += entry(lines, locale, title)
    return result


def validate_glyphs(projection, assets, deadline=None):
    import uharfbuzz as hb
    hb_fonts = [hb.Font(hb.Face(asset.data)) for asset in assets]
    for paragraph in layout(projection):
        check_deadline(deadline)
        for index, run in font_runs(paragraph.text, assets, deadline):
            for part in re.split(r'[\r\n\t]', run):
                # Bounded preflight chunks only. The actual renderer still
                # receives the full original paragraph, without truncation.
                for start in range(0, len(part), GLYPH_CHECK_CHARS):
                    check_deadline(deadline)
                    buffer = hb.Buffer()
                    buffer.add_str(part[start:start + GLYPH_CHECK_CHARS])
                    buffer.guess_segment_properties()
                    hb.shape(hb_fonts[index], buffer)
                    check_deadline(deadline)
                    if any(info.codepoint == 0 for info in buffer.glyph_infos):
                        raise ExportError('unsupported_glyph')


def safe_link(line):
    """Only explicit ordinary links become annotations; never fetch a URL."""
    value = line['text']
    if not value or any(char.isspace() or ord(char) < 0x20 for char in value):
        return None
    if line['role'] == 'email' and re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value):
        return 'mailto:' + quote(value, safe='@.+-_')
    if line['role'] == 'doi' and re.fullmatch(r'10\.\d{4,9}/[^\s]+', value):
        return 'https://doi.org/' + quote(value, safe='/.:()-_')
    if line['role'] not in ('url', 'doi'):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return None
        _port = parsed.port  # Reject malformed port values without exposing them.
        if any(char in value for char in '<>"\\'):
            return None
        return value
    except ValueError:
        return None


def render_pdf(projection, assets, deadline=None):
    from fpdf import FPDF
    from fpdf.enums import MethodReturnValue, XPos, YPos

    class BoundedPDF(FPDF):
        def add_page(self, *args, **kwargs):
            check_deadline(deadline)
            if self.page_no() >= MAX_PDF_PAGES:
                raise ExportError('export_too_large')
            return super().add_page(*args, **kwargs)

    check_deadline(deadline)
    pdf = BoundedPDF(format='Letter' if projection['page_size'] == 'letter' else 'A4')
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_title('Resume')
    pdf.set_author('')
    pdf.add_font('ResumeSans', fname=str(assets[0].path))
    check_deadline(deadline)
    pdf.add_font('ResumeEmoji', fname=str(assets[1].path))
    check_deadline(deadline)
    pdf.set_fallback_fonts(['ResumeEmoji'], exact_match=False)
    pdf.set_text_shaping(True)
    pdf.add_page()
    pdf.set_text_color(20, 28, 39)
    pdf.set_draw_color(176, 184, 194)
    pdf.set_line_width(0.25)

    def plain(text):
        # CRLF is one visual break; native PDF text has no tab control.
        # This is layout only: the signed projection is never changed.
        return text.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '    ')

    def fits(text):
        """Whether write() sets text in the rest of this line. write() measures
        each character alone and cuts a first word that does not fit there."""
        room = pdf.w - pdf.r_margin - pdf.get_x() - 2 * pdf.c_margin
        for char in text:
            room -= pdf.get_string_width(char)
            if room < 0:
                return False
        return True

    def above(item, index):
        return 3 if item.style == 'heading' and index else 0

    def below(item):
        return 1.8 if item.style == 'heading' else 2.6 if item.end else 0.6

    items, rows = layout(projection), []
    for item in items:
        check_deadline(deadline)
        size, leading = PDF_STYLES[item.style]
        pdf.set_font('ResumeSans', size=size)
        text, right = plain(''.join(piece for piece, _link in item.pieces)), plain(item.right)
        width = pdf.epw - pdf.get_string_width(right) - 4 if right else 0
        height = pdf.multi_cell(width, leading, text, align='L', dry_run=True, output=MethodReturnValue.HEIGHT)
        if right and height > 2 * leading:
            # Dates beside a long head would squeeze it: they end its row instead.
            text, right, width = text + SEPARATOR + right, '', 0
            height = pdf.multi_cell(0, leading, text, align='L', dry_run=True, output=MethodReturnValue.HEIGHT)
        rows.append((text, right, width, height))
    # The room each row needs left on its page, counted from the gap above it:
    # all of a heading, role row or row with dates at its right; else its first
    # line. A heading or role row also needs the gap below it and what the next
    # row needs, or only that row's first line when no page can hold it all.
    room = pdf.page_break_trigger - pdf.t_margin
    needs, firsts = [0.0] * len(items), [0.0] * len(items)
    for index in reversed(range(len(items))):
        item, (_text, right, _width, height) = items[index], rows[index]
        firsts[index] = above(item, index) + PDF_STYLES[item.style][1]
        needs[index] = above(item, index) + height if item.keep or right else firsts[index]
        if item.keep and index + 1 < len(items):
            whole = needs[index] + below(item) + needs[index + 1]
            needs[index] = whole if whole <= room else needs[index] + below(item) + firsts[index + 1]

    for index, (item, (text, right, width, _height)) in enumerate(zip(items, rows, strict=True)):
        check_deadline(deadline)
        size, leading = PDF_STYLES[item.style]
        pdf.set_font('ResumeSans', size=size)
        # Keep a heading or role row with the line after it: move it to the next
        # page when the rest of this one cannot hold what it needs and an empty
        # page can. A row after one of those stays: that row's move already
        # reserved it, or its first line when the two exceed a page.
        if (item.keep or right) and not (index and items[index - 1].keep) and pdf.get_y() > pdf.t_margin \
                and pdf.will_page_break(needs[index] + PAGE_SLACK) and needs[index] <= room:
            pdf.add_page()
        elif above(item, index):
            pdf.ln(above(item, index))
        links = [link for _piece, link in item.pieces if link]
        if links and len(item.pieces) > 1:
            # A row alternates items and separators (joined()). It breaks between
            # items, never inside one, and a separator ends the line it follows.
            gap = ''
            for position in range(0, len(item.pieces), 2):
                piece, link = item.pieces[position]
                separator = item.pieces[position + 1][0] if position + 1 < len(item.pieces) else ''
                piece, tail = plain(piece), separator.rstrip()
                if position and not fits(gap + piece.split('\n')[0] + tail):
                    pdf.ln(leading)
                elif gap:
                    pdf.write(leading, gap)
                pdf.write(leading, piece, link=link or '')
                if tail:
                    pdf.write(leading, tail)
                gap = separator[len(tail):]
            pdf.ln(leading)
        else:
            top = pdf.get_y()
            pdf.multi_cell(width, leading, text, align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT, link=links[0] if links else '')
            if right:
                bottom = pdf.get_y()
                pdf.set_xy(pdf.l_margin, top)
                pdf.cell(0, leading, right, align='R')
                pdf.set_xy(pdf.l_margin, bottom)
        check_deadline(deadline)
        if item.style == 'heading':
            pdf.line(pdf.l_margin, pdf.get_y() + 0.4, pdf.l_margin + pdf.epw, pdf.get_y() + 0.4)
        pdf.ln(below(item))
    check_deadline(deadline)
    data = bytes(pdf.output())
    check_deadline(deadline)
    if len(data) > MAX_FILE_BYTES:
        raise ExportError('export_too_large')
    return data


class CappedBuffer(io.BytesIO):
    def __init__(self, deadline=None):
        super().__init__()
        self.deadline = deadline

    def write(self, data):
        check_deadline(self.deadline)
        if self.tell() + len(data) > MAX_FILE_BYTES:
            raise ExportError('export_too_large')
        return super().write(data)


def portable(point: int) -> bool:
    # Latin, Latin-1/Extended and general punctuation: every standard Word or
    # LibreOffice template font renders these without an embedded font.
    return point <= 0x024F or 0x2000 <= point <= 0x206F or point == 0x20AC


def docx_codepoints(paragraphs, assets, deadline=None) -> tuple[set[int], set[int]]:
    """The characters each bundled font sets in this DOCX, using font_runs' choice."""
    used = (set(), set())
    for paragraph in paragraphs:
        for offset, char in enumerate(paragraph.text):
            if offset % 1024 == 0:
                check_deadline(deadline)
            point = ord(char)
            used[0 if char in '\r\n\t' or point in assets[0].codepoints else 1].add(point)
    return used


LATIN = frozenset(filter(portable, range(0x20, 0x20AD)))
# The start of the CT_Settings sequence (ECMA-376 Part 1, 17.15.1.78), through the font settings set here.
SETTINGS_START = ('writeProtection', 'view', 'zoom', 'removePersonalInformation', 'removeDateAndTime',
                  'doNotDisplayPageBoundaries', 'displayBackgroundShape', 'printPostScriptOverText',
                  'printFractionalCharacterWidth', 'printFormsData', 'embedTrueTypeFonts', 'embedSystemFonts',
                  'saveSubsetFonts')


@lru_cache(maxsize=1)
def common_chinese() -> frozenset[int]:
    """GB2312 symbols and level-1 hanzi: what editing Chinese text most often adds."""
    points = set()
    for row in (*range(0xA1, 0xAA), *range(0xB0, 0xD8)):
        for cell in range(0xA1, 0xFF):
            try:
                points.add(ord(bytes((row, cell)).decode('gb2312')))
            except UnicodeDecodeError:
                pass
    return frozenset(points)


def embedded_codepoints(index, used) -> frozenset[int]:
    """What one embedded font carries: this file's characters, plus Latin and,
    with East Asian text, common Chinese for the text font, so later edits keep
    its face. Characters outside it fall back to an installed font (Word desktop
    chose Microsoft YaHei), never to missing-glyph boxes.
    """
    if index:
        return frozenset(used)
    east_asian = any(unicodedata.east_asian_width(chr(point)) in 'WF' for point in used)
    return frozenset(used) | LATIN | (common_chinese() if east_asian else frozenset())


@lru_cache(maxsize=8)
def font_subset(asset: FontAsset, codepoints: frozenset[int]) -> bytes:
    """A glyf subset of one pinned font. The whole CJK program is 21.7 MB, so
    embedding it made any Word file with one Chinese line about 11.6 MB."""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    options = subset.Options()
    options.layout_features = ['ccmp', 'kern', 'liga', 'calt', 'mark', 'mkmk']
    options.name_IDs, options.name_languages, options.name_legacy = ['*'], ['*'], True  # OFL notices stay.
    options.notdef_outline = True
    options.prune_unicode_ranges = False
    options.recalc_timestamp = False
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=codepoints & asset.codepoints)
    with TTFont(io.BytesIO(asset.data), recalcTimestamp=False) as font:
        subsetter.subset(font)
        output = io.BytesIO()
        font.save(output)
    return output.getvalue()


def embed_docx_fonts(document, programs, deadline=None):
    """Embed (asset, subset program) pairs, declared the way Word describes fonts."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    table = document.part.part_related_by(RT.FONT_TABLE)
    # fontTable is a generic OPC Part in python-docx; do not depend on a
    # private loaded XML object that may not exist across versions.
    from lxml import etree
    root = etree.fromstring(table.blob, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    for index, (asset, program) in enumerate(programs):
        check_deadline(deadline)
        key = uuid4()
        font_bytes = bytearray(program)
        mask = key.bytes[::-1]
        for offset in range(32):
            font_bytes[offset] ^= mask[offset % 16]
        part = Part(PackURI(f'/word/fonts/resume-{index}.odttf'),
                    'application/vnd.openxmlformats-officedocument.obfuscatedFont', bytes(font_bytes), document.part.package)
        rid = table.relate_to(part, RT.FONT)
        matches = root.findall(qn('w:font'))
        for old in matches:
            if old.get(qn('w:name')) == asset.name:
                root.remove(old)
        font = OxmlElement('w:font')
        font.set(qn('w:name'), asset.name)
        for tag, attributes in asset.declaration:
            node = OxmlElement('w:' + tag)
            for name, value in attributes:
                node.set(qn('w:' + name), value)
            font.append(node)
        embedded = OxmlElement('w:embedRegular')
        embedded.set(qn('r:id'), rid)
        embedded.set(qn('w:fontKey'), '{' + str(key).upper() + '}')
        embedded.set(qn('w:subsetted'), '1')
        font.append(embedded)
        root.append(font)
    table._blob = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    settings = document.settings.element
    # Saved from Word for Mac with saveSubsetFonts false, a 0.8 MB export became 6.2 MB of whole
    # system fonts; with true, 49 KB.
    for tag, value in [('embedTrueTypeFonts', 'true'), ('saveSubsetFonts', 'true')]:
        node = settings.find(qn('w:' + tag))
        if node is None:
            node = OxmlElement('w:' + tag)
            earlier = {qn('w:' + name) for name in SETTINGS_START[:SETTINGS_START.index(tag)]}
            previous = [child for child in settings if child.tag in earlier]
            if previous:
                previous[-1].addnext(node)
            else:
                settings.insert(0, node)
        node.set(qn('w:val'), value)


def render_docx(projection, assets, deadline=None):
    from docx import Document
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Emu, Inches, Mm, Pt, RGBColor

    check_deadline(deadline)
    paragraphs = layout(projection)
    used = docx_codepoints(paragraphs, assets, deadline)
    # Latin-only text keeps the template's standard fonts and embeds none.
    needed = (any(not portable(point) for point in used[0]), bool(used[1]))
    names = [asset.name if need else None for asset, need in zip(assets, needed, strict=True)]
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = (Inches(8.5), Inches(11)) if projection['page_size'] == 'letter' else (Mm(210), Mm(297))
    section.top_margin = section.bottom_margin = Mm(16)
    section.left_margin = section.right_margin = Mm(18)
    right_margin = Emu(section.page_width - section.left_margin - section.right_margin)
    normal = document.styles['Normal']
    if names[0]:
        normal.font.name = names[0]
        normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), names[0])
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(20, 28, 39)
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.widow_control = True
    # Section titles use Heading 1, so the file has an outline to navigate. The template's
    # Heading 1 is a 14 pt bold blue theme font; the titles keep the body font.
    heading_style = document.styles['Heading 1']
    heading_style.element.remove(heading_style.element.get_or_add_rPr())
    heading_style.font.size = Pt(DOCX_SIZES['heading'])
    for key in ('author', 'last_modified_by', 'subject', 'comments', 'keywords', 'category', 'description'):
        if hasattr(document.core_properties, key):
            setattr(document.core_properties, key, '')
    document.core_properties.title = 'Resume'

    def add_text(paragraph, text, size=10.5, link=None):
        parent = paragraph._p
        if link:
            hyperlink = OxmlElement('w:hyperlink')
            hyperlink.set(qn('r:id'), document.part.relate_to(link, RT.HYPERLINK, is_external=True))
            parent.append(hyperlink)
            parent = hyperlink
        for index, value in font_runs(text, assets, deadline):
            check_deadline(deadline)
            # python-docx maps CR and LF separately; treat CRLF as one
            # visual break while leaving the signed input untouched.
            run = paragraph.add_run(value.replace('\r\n', '\n').replace('\r', '\n'))
            if names[index]:
                run.font.name = names[index]
                run._r.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), names[index])
            run.font.size = Pt(size)
            if link:
                parent.append(run._r)

    def add_rule(paragraph):
        # Added before other properties, which python-docx then orders around it.
        border, bottom = OxmlElement('w:pBdr'), OxmlElement('w:bottom')
        for name, value in (('val', 'single'), ('sz', '4'), ('space', '1'), ('color', 'B0B8C2')):
            bottom.set(qn('w:' + name), value)
        border.append(bottom)
        paragraph._p.get_or_add_pPr().append(border)

    for item in paragraphs:
        check_deadline(deadline)
        paragraph = document.add_paragraph(style=heading_style if item.style == 'heading' else None)
        layout_format = paragraph.paragraph_format
        if item.style == 'heading':
            add_rule(paragraph)
            layout_format.space_before = Pt(10)
            layout_format.space_after = Pt(4)
        else:
            # Whole long paragraphs must remain splittable over pages.
            layout_format.keep_together = False
            layout_format.space_after = Pt(6 if item.end else 3)
        layout_format.keep_with_next = item.keep
        for text, link in item.pieces:
            add_text(paragraph, text, DOCX_SIZES[item.style], link)
        if item.right:
            layout_format.tab_stops.add_tab_stop(right_margin, WD_TAB_ALIGNMENT.RIGHT)
            add_text(paragraph, '\t' + item.right, DOCX_SIZES[item.style])
    if any(needed):
        programs = []
        for index, asset in enumerate(assets):
            if needed[index]:
                check_deadline(deadline)
                programs.append((asset, font_subset(asset, embedded_codepoints(index, used[index]))))
        embed_docx_fonts(document, programs, deadline)
    output = CappedBuffer(deadline)
    document.save(output)
    check_deadline(deadline)
    return output.getvalue()


def render_export(projection, output_format, *, deadline=None):
    try:
        check_deadline(deadline)
        assets = fonts()
        check_deadline(deadline)
        validate_glyphs(projection, assets, deadline)
        return render_pdf(projection, assets, deadline) if output_format == 'pdf' else render_docx(projection, assets, deadline)
    except ExportError:
        raise
    except (ImportError, FileNotFoundError):
        raise ExportError('fonts_unavailable') from None
    except Exception:
        raise ExportError('export_failed') from None
