"""Read the complete static HTML document available to a manual import.

No network, browser rendering, linked-page reads, summaries, or text excerpts.
The caller owns fetch limits and the complete downstream model-input budget.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

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
_NON_BODY = {'head', 'title', 'meta', 'link', 'script', 'style', 'template', 'svg', 'canvas', 'iframe', 'object', 'embed'}
_BLOCKS = {
    'address', 'article', 'aside', 'blockquote', 'caption', 'dd', 'details', 'dialog', 'div',
    'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'header', 'hr', 'legend', 'main', 'nav', 'ol', 'p', 'pre', 'section',
    'summary', 'table', 'tbody', 'thead', 'tfoot', 'ul',
}
# Controls, headings, navigation and no-script notices: never source on their own.
_CHROME = frozenset({'noscript', 'button', 'input', 'label', 'nav', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
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
    r'^(?>(?:loading(?:(?: [\w-]+){1,3}(?:\.+|…|,))?|please wait|'
    r'(?:this|it) (?:may|might|can|could) take (?:a few|several|a couple of) (?:seconds|moments))[.…!,]*\s*)+$',
    re.I,
)
# Titles an ordinary page can carry too: a sign-in page, or a courtesy line a
# real posting may have as its title. They are a wall only when nothing else
# on the page is readable.
_GATE_TITLE = re.compile(
    r'^(?:sign[ -]?in|log[ -]?in)(?:[.!…]+|\s*[-|:–—].*)?$|^one moment,? please[.!…]*$', re.I,
)
_GATE_TEXT = re.compile(
    r'\b(?:sign[ -]?in|log[ -]?in|password|username|verify you are human|checking your browser|'
    r'cookies?|copyright|privacy policy|terms of (?:use|service)|all rights reserved)\b', re.I,
)
# A site can answer our server's address with a bot check while the same URL
# opens normally for the student. Checks print these sentences and load these
# scripts and frames, but an ordinary page can carry them too, so they refuse
# only a page with nothing else to read.
_CHALLENGE_TEXT = re.compile(
    r'\b(?:(?:your|the|this) (?:request|browser|connection) is being (?:verified|checked)|'
    r'verif(?:y|ying) (?:that )?you(?: are|\'re|’re) (?:a )?(?:human|not a (?:ro)?bot)|'
    r'confirm you are (?:a )?human|making sure you(?: are|\'re|’re) not a (?:ro)?bot|'
    r'checking (?:your browser|if the site connection is secure)|'
    r'needs to review the security of your connection|performing security verification|'
    r'(?:incapsula|imperva) incident|'
    r'protected by anubis|ddos protection by|enable js and disable any ad ?blocker)\b',
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


def _hidden(tag: Tag) -> bool:
    return (
        tag.has_attr('hidden')
        or str(tag.get('aria-hidden', '')).lower() == 'true'
        or bool(_HIDDEN_STYLE.search(str(tag.get('style', ''))))
        or (tag.name == 'input' and str(tag.get('type', '')).lower() == 'hidden')
    )


def _visible_in_body(tag: Tag) -> bool:
    return not any(_hidden(item) or item.name in _NON_BODY for item in [tag, *tag.parents] if isinstance(item, Tag))


def _render(node, *, skip: frozenset[str] = frozenset(), list_marker: str | None = None) -> str:
    if isinstance(node, Comment | Declaration | Doctype | ProcessingInstruction):
        return ''
    if isinstance(node, NavigableString):
        return re.sub(r'\s+', ' ', str(node))
    if not isinstance(node, Tag):
        return ''
    name = node.name.lower()
    if name in _NON_BODY or _hidden(node) or name in skip:
        return ''
    if skip and name == 'a' and any(
        parent.name in {'footer', 'header', 'nav'} for parent in node.parents if isinstance(parent, Tag)
    ):
        return ''
    if name == 'br':
        return '\n'
    if name == 'tr':
        cells = node.find_all(['td', 'th'], recursive=False)
        if cells:
            # Join actual cells rather than trimming a trailing delimiter: empty
            # first/last cells are meaningful column positions.
            values = [
                re.sub(r'[\n\t]+', ' ', _clean_text(_render(cell, skip=skip)))
                for cell in cells
            ]
            return '\n' + '\t'.join(values) + '\n'
    if name == 'ol':
        # Assign each direct item's ordinal once. Computing all prior siblings
        # separately for every item makes long source lists quadratic.
        children = list(node.children)
        item_count = sum(isinstance(child, Tag) and child.name == 'li' for child in children)
        step = -1 if node.has_attr('reversed') else 1
        try:
            number = int(node.get('start', item_count if step == -1 else 1))
        except (TypeError, ValueError):
            number = None
        rendered = []
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
            rendered.append(_render(child, skip=skip, list_marker=marker))
        return '\n' + ''.join(rendered) + '\n'
    text = ''.join(_render(child, skip=skip) for child in node.children)
    if name == 'li':
        return '\n' + (list_marker or '- ') + text.strip() + '\n'
    return '\n' + text + '\n' if name in _BLOCKS else text


def _clean_text(text: str) -> str:
    # Collapse source formatting spaces, preserve paragraph/row/cell boundaries.
    lines = [re.sub(r'[^\S\n\t]+', ' ', line).strip(' ') for line in text.splitlines()]
    return '\n'.join(re.sub(r' *\t *', '\t', line) for line in lines if line)


def _has_independent_source(root: Tag, *, forms: bool = False) -> bool:
    """A login form can coexist with source prose; do not reject that page.

    A login form's own text is not source. The bot-check rules count text
    inside forms (``forms``): ASP.NET and SharePoint wrap the whole page,
    posting included, in one form.
    """
    for line in _clean_text(_render(root, skip=_CHROME if forms else _CHROME | {'form'})).splitlines():
        # Login instructions can share a paragraph with a real deadline. Assess
        # sentences separately; a gate phrase must not discard adjacent facts.
        for sentence in re.split(r'(?<=[.!?])\s+|(?<=[;。！？；])\s*', line):
            if (_BLOCKED_PAGE_TITLE.fullmatch(sentence) or _JS_WALL.search(sentence) or _GATE_TEXT.search(sentence)
                    or _CHALLENGE_TEXT.search(sentence) or _LOADING_SHELL.fullmatch(sentence)):
                continue
            if sum(char.isalpha() for char in sentence) >= 12:
                return True
    return False


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
    if not isinstance(html, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in html):
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
        soup = BeautifulSoup(html, 'html.parser')
        title = _meta(soup, 'title') or (soup.title.get_text(' ', strip=True) if soup.title else '')
        meta_summary = _meta(soup, 'description')
        root = soup.body or soup
        titles = [tag.get_text(' ', strip=True) for tag in soup.select('h1') if _visible_in_body(tag)]
        if soup.title is not None:
            titles.append(soup.title.get_text(' ', strip=True))
        blocked = [value for value in titles if _BLOCKED_PAGE_TITLE.fullmatch(value)]
        # Denial/challenge titles and challenge markup are not job content. A
        # sign-in or courtesy title, a password form or a visible challenge box
        # is only a wall when no independent source remains.
        if any(not _GATE_TITLE.fullmatch(value) for value in blocked) or _is_challenge_page(soup):
            raise ImportDocumentError('access_page')
        gate = bool(blocked) or any(
            _visible_in_body(tag) and (
                (tag.name == 'input' and str(tag.get('type', '')).lower() == 'password')
                or tag.get('id') == 'challenge-running'
            ) for tag in root.find_all(['input', 'div', 'section', 'form'])
        )
        if gate and not _has_independent_source(root):
            raise ImportDocumentError('access_page')
        text = _clean_text(_render(root))
        if _ACCESS_SHELL.fullmatch(text) or (
                (_has_challenge_machinery(soup) or _CHALLENGE_TEXT.search(text))
                and not _has_independent_source(root, forms=True)):
            raise ImportDocumentError('access_page')
        # Scripts in the head fill a page as surely as scripts in its body.
        if soup.find('script') is not None and _LOADING_SHELL.fullmatch(text):
            raise ImportDocumentError('javascript_required')
        if _JS_WALL.search(text) and not _has_independent_source(root):
            raise ImportDocumentError('javascript_required')
        if not text.strip():
            if soup.find('script') is not None:
                raise ImportDocumentError('javascript_required')
            raise ImportDocumentError('metadata_only' if title or meta_summary else 'empty_page')
    except ImportDocumentError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise ImportDocumentError('invalid_html') from None
    return {'title': title, 'meta_summary': meta_summary, 'text': text, 'source_kind': 'fetched_html'}
