"""Read the complete static HTML document available to a manual import.

No network, browser rendering, linked-page reads, summaries, or text excerpts.
The caller owns fetch limits and the complete downstream model-input budget.
"""
from __future__ import annotations

import re
from itertools import islice

from bs4 import BeautifulSoup, CData, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag
from bs4.builder._htmlparser import BeautifulSoupHTMLParser, HTMLParserTreeBuilder

from ..contact_instructions import _BLOCKED_PAGE_TITLE

_REASONS = {
    'invalid_html': 'Invalid HTML source.',
    'unsupported_content_type': 'Unsupported source content type.',
    'empty_page': 'The fetched page has no readable content.',
    'metadata_only': 'The fetched page contains metadata but no readable body.',
    'access_page': 'The fetched page is an access or sign-in page.',
    'javascript_required': 'The fetched page contains no readable static source.',
    'too_large': 'The source exceeds the supported input limit.',
}
# An imported URL can return any page up to the fetch limit. Every pass below
# reads it in time linear in its size, and these limits bound that size. A
# page past one is refused whole as too large, never read in part, so a limit
# cannot change how a page that is read is classified.
MAX_NODES = 30_000            # tags, text runs and comments the parser builds
MAX_DEPTH = 512               # tags open at once
MAX_TEXT_CHARS = 1_000_000    # characters of each text built from the page
MAX_PARSE_EVENTS = 300_000    # tags, attributes and text pieces html.parser reads
MAX_TAG_ATTRIBUTES = 10_000   # attributes in one tag
_NON_BODY = {'head', 'title', 'meta', 'link', 'script', 'style', 'template', 'svg', 'canvas', 'iframe', 'object', 'embed'}
_BLOCKS = {
    'address', 'article', 'aside', 'blockquote', 'caption', 'dd', 'details', 'dialog', 'div',
    'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'header', 'hr', 'legend', 'main', 'nav', 'ol', 'p', 'pre', 'section',
    'summary', 'table', 'tbody', 'thead', 'tfoot', 'ul',
}
# Controls, headings, navigation and no-script notices: never source on their own.
_CHROME = frozenset({'noscript', 'button', 'input', 'label', 'nav', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
_CHROME_AND_FORMS = _CHROME | {'form'}
_LINK_CHROME = frozenset({'footer', 'header', 'nav'})
_GATE_BOXES = frozenset({'input', 'div', 'section', 'form'})
# get_text reads these string classes and no others (not comments or script).
_TEXT_TYPES = (NavigableString, CData)
_UNRENDERED = (Comment, Declaration, Doctype, ProcessingInstruction)
_SPACE_RUN = re.compile(r'\s+')
_SURROGATE = re.compile('[\ud800-\udfff]')
_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+|(?<=[;。！？；])\s*')
# A tag's name and the attributes after it, as html.parser's locatetagend reads them.
_TAG_NAME = re.compile(r'[a-zA-Z][^\t\n\r\f />]*[\t\n\r\f /]*')
_TAG_ATTRIBUTE = re.compile(
    r'(?<=[\'"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*'
    r'(?:[\t\n\r\f ]*=[\t\n\r\f ]*(?:\'[^\']*\'|"[^"]*"|(?![\'"])[^>\t\n\r\f ]*))?[\t\n\r\f /]*'
)
_CELL = object()
_HIDDEN_STYLE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!important\s*)?(?:;|$)', re.I)
_JS_WALL = re.compile(
    r'\b(?:enable|turn on|activate)\s+(?:your\s+)?javascript\b|'
    r'\bjavascript\s+(?:is\s+)?(?:disabled|not enabled)\b|'
    r'\b(?:requires?|needs?)\s+javascript\s+to\s+(?:run|load|display|view|use|access)\b|'
    r'\bjavascript\s+(?:is\s+)?required\s+(?:to\s+(?:run|load|display|view|use|access)|'
    r'for\s+(?:this|the)\s+(?:page|site|app|application))\b|'
    r'\b(?:this|the)\s+(?:page|site|app|application|browser)\s+(?:requires?|needs?)\s+javascript\b',
    re.I,
)
_ACCESS_SHELL = re.compile(
    r'^(?:please\s+)?(?:verify (?:you are|that you are) (?:a )?human|access denied|permission denied|'
    r'checking your browser(?: before (?:continuing|proceeding))?|'
    r'(?:sign[ -]?in|log[ -]?in) to (?:continue|view (?:this|the) (?:page|content)|access (?:this|the) (?:page|content)))'
    r'[.!…\s]*$', re.I,
)
# A page its scripts have yet to fill: nothing but loading lines. Not source,
# and not a bot check either; the posting appears once the scripts run.
# Each line is matched atomically. A run of "loading" words splits into lines
# many ways, and retrying every split took exponential time on page text.
_LOADING_SHELL = re.compile(
    r'^(?>(?:loading(?:(?: [\w-]+){1,3}(?:\.+|…|,))?|please wait(?: a (?:moment|second|few seconds))?|'
    r'(?:this|it) (?:may|might|can|could) take (?:a few|several|a couple of) (?:seconds|moments))[.…!,]*\s*)+$',
    re.I,
)
# Blocked titles an ordinary page can carry too (_BLOCKED_PAGE_TITLE). A
# sign-in title is a wall only when nothing else on the page is readable.
_SIGN_IN_TITLE = re.compile(r'^(?:sign[ -]?in|log[ -]?in)(?:[.!…]*\s*[-|:–—].*|[.!…]+)?$', re.I)
# A courtesy line, a stock check name, and the long check heading when the
# words after it name no site ("... before continuing to the application form")
# are check titles a real posting can carry. Each is one bot-check signal
# among the others (see _CHALLENGE_TEXT). The long heading with nothing, an
# address or "the website" after it is DDoS-Guard's or Cloudflare's, and it
# refuses the page outright.
_CHECK_TITLE = re.compile(
    r'^(?:(?:one moment,? please|(?:human|bot) verification|checking your browser)[.!…]*|'
    r'checking your browser before (?:accessing|continuing|proceeding)\b'
    r'(?!(?: (?:to )?(?:[\w-]+(?:\.[\w-]+)+|(?:the|this) (?:web)?site))?[.!…]*$).*)$',
    re.I,
)
_GATE_TEXT = re.compile(
    r'\b(?:sign[ -]?in|log[ -]?in|password|username|verify you are human|checking your browser|'
    r'cookies?|copyright|privacy policy|terms of (?:use|service)|all rights reserved)\b', re.I,
)
# A site can answer our server's address with a bot check while the same URL
# opens normally for the student. Checks print these sentences and footer
# lines and load these scripts and frames, but an ordinary page can carry them
# too, so they refuse only a page with nothing else to read (see
# read_import_document). Words may be split by any whitespace: PerimeterX
# breaks its sentence with <br>.
_CHALLENGE_TEXT = re.compile(
    r'\b(?:(?:your|the|this)\s+(?:request|browser|connection)\s+is\s+being\s+(?:verified|checked)|'
    r'(?:verif(?:y|ying|ies)|checking|confirm(?:ing)?|making\s+sure)\s+(?:that\s+)?you(?:\s+are|\'re|’re)\s+'
    r'(?:a\s+)?(?:human|not\s+a\s+(?:ro)?bot)|'
    r'checking\s+(?:your\s+browser|if\s+the\s+site\s+connection\s+is\s+secure)|'
    r'needs\s+to\s+review\s+the\s+security\s+of\s+your\s+connection|performing\s+security\s+verification|'
    r'(?:incapsula|imperva)\s+incident|'
    r'protected\s+by\s+anubis|ddos\s+protection\s+by|enable\s+js\s+and\s+disable\s+any\s+ad\s?blocker|'
    # Cloudflare's older check and captcha pages, its block page and its 2025 check.
    r'this\s+process\s+is\s+automatic|your\s+browser\s+will\s+redirect\s+to\s+your\s+requested\s+content|'
    r'please\s+allow\s+up\s+to\s+\d+\s+seconds|complete\s+the\s+security\s+check|proves\s+you\s+are\s+(?:a\s+)?human|'
    r'(?:uses|is\s+using)\s+a\s+security\s+service\s+to\s+protect|you\s+have\s+been\s+blocked|'
    # Footer lines: Cloudflare's Ray ID and credit, PerimeterX's reference id.
    r'ray\s+id:?\s*[0-9a-f]{16}|performance\s+(?:&|and)\s+security\s+by\s+cloudflare|'
    r'reference\s+id:?\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\b',
    re.I,
)
# Cloudflare's challenge-platform script is left out: Cloudflare adds it to
# ordinary pages too, and its challenge page has the refused title or text.
_CHALLENGE_SOURCE = re.compile(r'captcha-delivery\.com', re.I)
# Imperva also loads this script on ordinary pages it protects; only its frame is a challenge.
_CHALLENGE_FRAME = re.compile(r'/_Incapsula_Resource\b', re.I)
# Only a vendor's bot-check page carries these ids, scripts and redirects, so
# they refuse it whatever title and explanation it shows around them. Ids a
# site can use for itself (challenge-form, challenge-running, px-captcha) are
# not among them.
_CHALLENGE_PAGE_IDS = {'cf-challenge-running', 'anubis_challenge', 'wsidchk-form'}
_CHALLENGE_PAGE_SOURCE = re.compile(r'/\.within\.website/x/cmd/anubis/|/\.well-known/sgcaptcha\b', re.I)
# Cloudflare's challenge form posts back with this token in its action.
_CF_CHALLENGE_ACTION = re.compile(r'[?&]__cf_chl_')


class ImportDocumentError(ValueError):
    """Stable failure code; exception text never echoes the source."""

    def __init__(self, reason: str):
        self.reason = reason if reason in _REASONS else 'invalid_html'
        super().__init__(_REASONS[self.reason])


class _ClosedVoidTags:
    """The void tags bs4's html.parser builder closed itself, by name.

    bs4 keeps them in a list and searches it on every end tag, so a page of
    <br> tags followed by end tags parsed in quadratic time. Counts answer the
    same questions in constant time.
    """

    def __init__(self):
        self._counts: dict[str, int] = {}

    def __contains__(self, name) -> bool:
        return self._counts.get(name, 0) > 0

    def append(self, name) -> None:
        self._counts[name] = self._counts.get(name, 0) + 1

    def remove(self, name) -> None:
        if not self._counts.get(name):
            raise ValueError(name)
        self._counts[name] -= 1


class _HTMLParser(BeautifulSoupHTMLParser):
    """html.parser for one page, its own work held to the limits.

    It reads each '<' or '&' that opens nothing as a text piece of its own:
    5 MB of them took 3.2 s. It finds where a tag ends with one regular
    expression whose memory grows by about 320 bytes for each attribute it
    passes: one 5 MB tag of 'a ' took 806 MB, start tag or end tag alike.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.already_closed_empty_element = _ClosedVoidTags()
        self._events = 0

    def _read(self, pieces):
        self._events += pieces
        if self._events > MAX_PARSE_EVENTS:
            raise ImportDocumentError('too_large')

    def _count_attributes(self, start):
        # One attribute at a time, before html.parser's expression walks them all.
        rawdata = self.rawdata
        name = _TAG_NAME.match(rawdata, start)
        if name is None:
            return
        position, count = name.end(), 0
        while attribute := _TAG_ATTRIBUTE.match(rawdata, position):
            count += 1
            if count > MAX_TAG_ATTRIBUTES:
                raise ImportDocumentError('too_large')
            position = attribute.end()
        self._read(count)

    def check_for_whole_start_tag(self, i):
        self._count_attributes(i + 1)
        return super().check_for_whole_start_tag(i)

    def parse_endtag(self, i):
        self._count_attributes(i + 2)
        return super().parse_endtag(i)

    def handle_starttag(self, tag, attrs, handle_empty_element=True):
        self._read(1)
        super().handle_starttag(tag, attrs, handle_empty_element)

    def handle_endtag(self, tag, check_already_closed=True):
        self._read(1)
        super().handle_endtag(tag, check_already_closed)

    def handle_data(self, data):
        self._read(1)
        super().handle_data(data)


class _TreeBuilder(HTMLParserTreeBuilder):
    def feed(self, markup, _parser_class=_HTMLParser):
        super().feed(markup, _parser_class=_parser_class)

    def set_up_substitutions(self, tag) -> bool:
        # bs4 readies a <meta> charset for re-encoding the page, searching its
        # content in time quadratic in its line breaks. Nothing re-encodes it.
        return False


class _Soup(BeautifulSoup):
    """bs4's html.parser tree of a page, built in linear time within the limits."""

    _nodes = 0

    def reset(self):
        self._nodes = 0
        super().reset()

    def _built(self):
        self._nodes += 1
        if self._nodes > MAX_NODES:
            raise ImportDocumentError('too_large')

    def handle_starttag(self, *args, **kwargs):
        tag = super().handle_starttag(*args, **kwargs)
        self._built()
        # The stack starts with the document itself.
        if len(self.tagStack) > MAX_DEPTH + 1:
            raise ImportDocumentError('too_large')
        return tag

    def object_was_parsed(self, *args, **kwargs):
        self._built()
        super().object_was_parsed(*args, **kwargs)

    def _linkage_fixer(self, el):
        # bs4 relinks the last descendant of a node something was inserted
        # into, walking up through every ancestor to do it. html.parser only
        # appends to nodes still open, where that walk finds nothing to relink,
        # yet it ran for every text run after a child: depth times runs.
        return


def parse_import_html(html: str) -> BeautifulSoup:
    """Parse a page the way html.parser does, refusing one past the limits as too_large."""
    return _Soup(html, builder=_TreeBuilder())


def _hidden(tag: Tag) -> bool:
    return (
        tag.has_attr('hidden')
        or str(tag.get('aria-hidden', '')).lower() == 'true'
        or bool(_HIDDEN_STYLE.search(str(tag.get('style', ''))))
        or (tag.name == 'input' and str(tag.get('type', '')).lower() == 'hidden')
    )


def _scan(soup: BeautifulSoup, root: Tag) -> tuple[list[str], bool]:
    """The text of each visible <h1>, and whether root holds a visible sign-in or challenge box.

    One pass from the top: a tag is visible when neither it nor any tag above
    it is hidden or outside the body. Heading text is cut from one list of the
    strings inside visible headings, so an <h1> inside another is not read
    again; all heading text together must fit in MAX_TEXT_CHARS.
    """
    strings: list[str] = []
    ends = [0]
    ranges: list[list[int]] = []
    gate = False
    frames = [(iter(soup.contents), False, root is soup, False, None)]
    while frames:
        children, hidden, in_root, in_heading, slot = frames[-1]
        node = next(children, None)
        if node is None:
            frames.pop()
            if slot is not None:
                ranges[slot][1] = len(strings)
            continue
        if isinstance(node, Tag):
            name = node.name
            node_hidden = hidden or name in _NON_BODY or _hidden(node)
            if (in_root and not node_hidden and name in _GATE_BOXES
                    and ((name == 'input' and str(node.get('type', '')).lower() == 'password')
                         or node.get('id') == 'challenge-running')):
                gate = True
            heading = None
            if name == 'h1' and not node_hidden:
                heading = len(ranges)
                ranges.append([len(strings), len(strings)])
            frames.append((iter(node.contents), node_hidden, in_root or node is root,
                           in_heading or heading is not None, heading))
        elif in_heading and type(node) in _TEXT_TYPES:
            text = node.strip()
            if text:
                strings.append(text)
                ends.append(ends[-1] + len(text))
    if sum(ends[end] - ends[start] + end - start - 1 for start, end in ranges if end > start) > MAX_TEXT_CHARS:
        raise ImportDocumentError('too_large')
    return [' '.join(strings[start:end]) for start, end in ranges], gate


class _TextWriter:
    """Text built from a page, held under MAX_TEXT_CHARS.

    A list item's text loses its leading and trailing whitespace: what leads
    is dropped as it arrives and what trails is popped when the item closes,
    so items nested to any depth are trimmed in one pass.
    """

    __slots__ = ('pieces', 'size', 'lstrip')

    def __init__(self):
        self.pieces: list[str] = []
        self.size = 0
        self.lstrip = False

    def write(self, text: str) -> None:
        self.size += len(text)
        if self.size > MAX_TEXT_CHARS:
            raise ImportDocumentError('too_large')
        if self.lstrip:
            text = text.lstrip()
            if not text:
                return
            self.lstrip = False
        if text:
            self.pieces.append(text)

    def open_item(self, marker: str) -> int:
        self.write('\n' + marker)
        self.lstrip = True
        return len(self.pieces)

    def close_item(self, start: int) -> None:
        self.lstrip = False
        pieces = self.pieces
        while len(pieces) > start:
            last = pieces[-1].rstrip()
            if last:
                pieces[-1] = last
                break
            pieces.pop()
        self.write('\n')

    def open_cell(self):
        saved = self.pieces, self.lstrip
        self.pieces, self.lstrip = [], False
        return saved

    def close_cell(self, saved) -> str:
        # A cell's value sits on its row's line, so its line breaks, tabs and
        # spaces each read as one space between its words.
        value = ' '.join(''.join(self.pieces).split())
        self.pieces, self.lstrip = saved
        return value


def _ol_items(node: Tag):
    """An ordered list's children, each <li> with its number."""
    # Assign each direct item's ordinal once. Computing all prior siblings
    # separately for every item makes long source lists quadratic.
    children = node.contents
    item_count = sum(isinstance(child, Tag) and child.name == 'li' for child in children)
    step = -1 if node.has_attr('reversed') else 1
    try:
        number = int(node.get('start', item_count if step == -1 else 1))
    except (TypeError, ValueError):
        number = None
    for child in children:
        marker = None
        if isinstance(child, Tag) and child.name == 'li':
            if number is not None:
                try:
                    number = int(child.get('value', number))
                except (TypeError, ValueError):
                    # Preserve the previous stable fallback: once an
                    # ordinal is invalid, later items use bullet markers.
                    number = None
            marker = f'{number}. ' if number is not None else '- '
            if number is not None:
                number += step
        yield child, marker


def _flat_cells(cells: list[Tag]):
    for index, cell in enumerate(cells):
        if index:
            yield _CELL, None
        yield cell, None


def _render_text(root: Tag, skip: frozenset[str] = frozenset()) -> str:
    """The readable text under root, in one pass.

    Blocks and list items sit on their own lines and a table row is one line
    of tab-separated cells. Hidden tags, tags outside the body and tags named
    in skip are left out with everything inside them; with skip, so are links
    in a header, footer or nav. A table inside a cell keeps its words only.
    """
    writer = _TextWriter()
    # Each frame: (children with their list markers, how it closes, what the
    # close needs, whether a header/footer/nav is above them, inside a cell).
    frames = [[iter(((root, None),)), None, None, any(tag.name in _LINK_CHROME for tag in root.parents), False]]
    while frames:
        frame = frames[-1]
        item = next(frame[0], None)
        if item is None:
            frames.pop()
            close = frame[1]
            if close == 'block':
                writer.write('\n')
            elif close == 'item':
                writer.close_item(frame[2])
            elif close == 'cell':
                saved, values = frame[2]
                values.append(writer.close_cell(saved))
            elif close == 'row':
                writer.write('\t'.join(frame[2]))
                writer.write('\n')
            continue
        node, marker = item
        if node is _CELL:
            writer.write('\t')
            continue
        if marker is _CELL:
            frames.append([iter(((node, None),)), 'cell', (writer.open_cell(), frame[2]), frame[3], True])
            continue
        if not isinstance(node, Tag):
            if not isinstance(node, _UNRENDERED):
                writer.write(_SPACE_RUN.sub(' ', node))
            continue
        name = node.name.lower()
        if name in _NON_BODY or name in skip or _hidden(node):
            continue
        if skip and name == 'a' and frame[3]:
            continue
        if name == 'br':
            writer.write('\n')
            continue
        below = frame[3] or node.name in _LINK_CHROME
        in_cell = frame[4]
        if name == 'tr':
            cells = [child for child in node.contents if isinstance(child, Tag) and child.name in ('td', 'th')]
            if cells:
                writer.write('\n')
                if in_cell:
                    frames.append([_flat_cells(cells), 'block', None, below, True])
                else:
                    frames.append([((cell, _CELL) for cell in cells), 'row', [], below, False])
                continue
        if name == 'ol':
            writer.write('\n')
            frames.append([_ol_items(node), 'block', None, below, in_cell])
            continue
        children = ((child, None) for child in node.contents)
        if name == 'li':
            frames.append([children, 'item', writer.open_item(marker or '- '), below, in_cell])
        elif name in _BLOCKS:
            writer.write('\n')
            frames.append([children, 'block', None, below, in_cell])
        else:
            frames.append([children, None, None, below, in_cell])
    return _clean_text(''.join(writer.pieces))


def _clean_text(text: str) -> str:
    # Collapse source formatting spaces, preserve paragraph/row/cell boundaries.
    lines = [re.sub(r'[^\S\n\t]+', ' ', line).strip(' ') for line in text.splitlines()]
    return '\n'.join(re.sub(r' *\t *', '\t', line) for line in lines if line)


def _one_line(check: re.Match) -> str:
    return check.group().replace('\n', ' ')


def _sentences(root: Tag, *, forms: bool):
    """The sentences of root's text that the wall rules weigh, chrome left out.

    Login instructions can share a paragraph with a real deadline, so each
    sentence is weighed alone; a gate phrase must not discard adjacent facts.
    Only a bot-check sentence (_CHALLENGE_TEXT) is read across lines: PerimeterX
    breaks its sentence over two with <br>, and both halves are the check.
    """
    text = _CHALLENGE_TEXT.sub(_one_line, _render_text(root, _CHROME if forms else _CHROME_AND_FORMS))
    for line in text.splitlines():
        yield from _SENTENCE_BREAK.split(line)


def _discounted(sentence: str) -> bool:
    """A sentence a wall prints: a blocked title, a sign-in, script, bot-check or loading line."""
    return bool(_BLOCKED_PAGE_TITLE.fullmatch(sentence) or _JS_WALL.search(sentence) or _GATE_TEXT.search(sentence)
                or _CHALLENGE_TEXT.search(sentence) or _LOADING_SHELL.fullmatch(sentence))


def _has_independent_source(root: Tag, *, forms: bool = False) -> bool:
    """A login form can coexist with source prose; do not reject that page.

    A login form's own text is not source. The bot-check rules count text
    inside forms (``forms``): ASP.NET and SharePoint wrap the whole page,
    posting included, in one form.
    """
    for sentence in _sentences(root, forms=forms):
        # Letters are counted first, in C and stopping at 12, so a page of
        # short sentences is not matched against every rule.
        if len(list(islice(filter(str.isalpha, sentence), 12))) == 12 and not _discounted(sentence):
            return True
    return False


def _has_other_text(root: Tag) -> bool:
    """Whether root shows anything a bot check does not, however short.

    A sparse posting's list items and table cells are too short to be
    independent source but are not what a check prints; its heading, buttons,
    check sentences, loading lines and footer ids are. Form text counts.
    """
    return any(any(map(str.isalnum, sentence)) and not _discounted(sentence)
               for sentence in _sentences(root, forms=True))


def _address(tag: Tag) -> str:
    if tag.name == 'meta':
        return str(tag.get('content', '')) if str(tag.get('http-equiv', '')).lower() == 'refresh' else ''
    return str(tag.get('action' if tag.name == 'form' else 'src') or '')


def _is_challenge_page(soup: BeautifulSoup) -> bool:
    """Vendor bot-check markup, visible or not."""
    return (
        soup.find(id=lambda value: value in _CHALLENGE_PAGE_IDS) is not None
        or soup.find('form', id='challenge-form', action=_CF_CHALLENGE_ACTION) is not None
        or any(_CHALLENGE_PAGE_SOURCE.search(_address(tag)) for tag in soup.find_all(['script', 'form', 'meta']))
    )


def _has_challenge_machinery(soup: BeautifulSoup) -> bool:
    """Bot-check scripts, frames and redirects an ordinary page can also load."""
    return any(
        _CHALLENGE_SOURCE.search(_address(tag)) or (tag.name == 'iframe' and _CHALLENGE_FRAME.search(_address(tag)))
        for tag in soup.find_all(['script', 'iframe', 'form', 'meta'])
    )


def _meta(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find('meta', attrs={'property': f'og:{key}'})
    if tag is None and key == 'description':
        tag = soup.find('meta', attrs={'name': 'description'})
    return str(tag.get('content', '')).strip() if tag is not None else ''


def extract_import_document(html: str, *, content_type: str | None = None) -> dict:
    """Return all readable text in the fetched HTML, or a fixed safe failure.

    Text represents this response's static DOM only. It does not include linked
    documents, image text, iframes, rendered scripts or computed CSS visibility.
    Metadata is returned separately and never used to stand in for body text.
    """
    return read_import_document(html, content_type=content_type)[0]


def read_import_document(html: str, *, content_type: str | None = None) -> tuple[dict, BeautifulSoup]:
    """extract_import_document's result and the parsed page, for other readers of the same page."""
    if not isinstance(html, str) or _SURROGATE.search(html):
        raise ImportDocumentError('invalid_html')
    if content_type is not None:
        if not isinstance(content_type, str):
            raise ImportDocumentError('unsupported_content_type')
        mime = content_type.partition(';')[0].strip().lower()
        if mime and mime not in {'text/html', 'application/xhtml+xml'}:
            raise ImportDocumentError('unsupported_content_type')
    if '\x00' in html or html.lstrip('\ufeff \t\r\n').startswith(('%PDF-', '\x89PNG', 'GIF87a', 'GIF89a', 'PK\x03\x04')):
        raise ImportDocumentError('unsupported_content_type')
    if not html.strip():
        raise ImportDocumentError('empty_page')
    try:
        soup = parse_import_html(html)
        title = _meta(soup, 'title') or (soup.title.get_text(' ', strip=True) if soup.title else '')
        meta_summary = _meta(soup, 'description')
        root = soup.body or soup
        titles, gate_box = _scan(soup, root)
        if soup.title is not None:
            titles.append(soup.title.get_text(' ', strip=True))
        blocked = [value for value in titles if _BLOCKED_PAGE_TITLE.fullmatch(value)]
        sign_in = [value for value in blocked if _SIGN_IN_TITLE.fullmatch(value)]
        check_title = [value for value in blocked if _CHECK_TITLE.fullmatch(value)]
        # Denial/challenge titles and challenge markup are not job content. A
        # sign-in title, a password form or a visible challenge box is only a
        # wall when no independent source remains; a check title a posting can
        # carry is weighed with the other check signals below.
        if len(sign_in) + len(check_title) < len(blocked) or _is_challenge_page(soup):
            raise ImportDocumentError('access_page')
        independent: dict[bool, bool] = {}

        def has_independent_source(*, forms: bool = False) -> bool:
            if forms not in independent:
                independent[forms] = _has_independent_source(root, forms=forms)
            return independent[forms]

        if (sign_in or gate_box) and not has_independent_source():
            raise ImportDocumentError('access_page')
        text = _render_text(root)
        # Bot-check signals: a check title, check scripts or frames, and each
        # check sentence or footer line, two at most. Any refuses a page with
        # no independent source when nothing else is left to read; one beside
        # a sparse posting's short list or table does not, two do.
        signals = (bool(check_title) + _has_challenge_machinery(soup)
                   + len(list(islice(_CHALLENGE_TEXT.finditer(text), 2))))
        if _ACCESS_SHELL.fullmatch(text) or (
                signals and not has_independent_source(forms=True) and (signals > 1 or not _has_other_text(root))):
            raise ImportDocumentError('access_page')
        # Scripts in the head fill a page as surely as scripts in its body.
        if soup.find('script') is not None and _LOADING_SHELL.fullmatch(text):
            raise ImportDocumentError('javascript_required')
        if _JS_WALL.search(text) and not has_independent_source():
            raise ImportDocumentError('javascript_required')
        if not text.strip():
            if soup.find('script') is not None:
                raise ImportDocumentError('javascript_required')
            raise ImportDocumentError('metadata_only' if title or meta_summary else 'empty_page')
    except ImportDocumentError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise ImportDocumentError('invalid_html') from None
    return {'title': title, 'meta_summary': meta_summary, 'text': text, 'source_kind': 'fetched_html'}, soup
