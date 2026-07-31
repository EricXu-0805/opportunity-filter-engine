"""Positive public-data projection helpers shared by API response routes."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import TypeVar
from urllib.parse import unquote, urlsplit

_EMAIL_IN_TEXT_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\."
    r"(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59})(?![\w-])",
    flags=re.IGNORECASE,
)
_UNICODE_EMAIL_IN_TEXT_RE = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@"
    r"(?:[^\W_](?:[^\W_]|-){0,62}\.)+"
    r"[^\W_](?:[^\W_]|-){1,62}(?![\w-])",
    flags=re.UNICODE,
)
_EMAIL_ADDRESS_LITERAL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@"
    r"\[(?:IPV6:)?[0-9A-F:.]{2,128}\](?![\w-])",
    flags=re.IGNORECASE,
)
_CONTACT_AT_DELIMITER_RE = re.compile(
    r"(?<=\w)(?:\s*@\s*|\s*(?:\[|\(|\{)\s*at\s*(?:\]|\)|\})\s*|"
    r"\s*/\s*at\s*/\s*|\s*艾特\s*)(?=\w)",
    flags=re.IGNORECASE,
)
_CONTACT_DOT_DELIMITER_RE = re.compile(
    r"(?<=\w)(?:\s*(?:\[|\(|\{)\s*(?:dot|\.)\s*(?:\]|\)|\})\s*|"
    r"\s*/\s*(?:dot|\.)\s*/\s*|\s*(?:点|。)\s*)(?=\w)",
    flags=re.IGNORECASE,
)
_PLAIN_WORD_DOT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])(?P<local>[A-Z0-9._%+-]+)\s+at\s+"
    r"(?P<first_domain>[A-Z0-9-]+)\s+dot\s+"
    r"(?:[A-Z0-9-]+\s+dot\s+)*"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_PLAIN_WORD_POINT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])(?P<local>[A-Z0-9._%+-]+)\s+at\s+"
    r"(?P<first_domain>[A-Z0-9-]+)\s+point\s+"
    r"(?:[A-Z0-9-]+\s+point\s+)*"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_AT_SIGN_WORD_DOT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+\s*@\s*"
    r"(?:[A-Z0-9-]+\s+(?:dot|point)\s+)+"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_AT_SIGN_SPACED_DOT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+\s*@\s*"
    r"(?:[A-Z0-9-]+\s+\.\s+)+"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_PLAIN_AT_STRONG_DOT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+\s+at\s+"
    r"(?:[A-Z0-9-]+\s*(?:"
    r"(?:\[|\(|\{)\s*(?:dot|\.)\s*(?:\]|\)|\})|"
    r"/\s*(?:dot|\.)\s*/|点|。"
    r")\s*)+"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_PLAIN_AT_SPACED_DOT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])(?P<local>[A-Z0-9._%+-]+)\s+at\s+"
    r"(?:[A-Z0-9-]+\s+\.\s+)+"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_PLAIN_AT_LITERAL_DOT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])(?P<local>[A-Z0-9._%+-]+)\s+at\s+"
    r"(?:[A-Z0-9-]+\.)+"
    r"(?P<tld>(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59}))(?![\w-])",
    flags=re.IGNORECASE,
)
_PLAIN_AT_SENTENCE_WORDS = frozenset({
    "apply", "browse", "check", "contact", "data", "find", "go", "learn",
    "look", "meet", "read", "research", "search", "see", "student", "study",
    "visit", "work",
})
_PLAIN_DOMAIN_ARTICLES = frozenset({
    "a",
    "an",
    "any",
    "some",
    "that",
    "the",
    "this",
})
_CONTACT_CUE_RE = re.compile(r"\b(?:contact|email|e-mail|reach|write)\s+$", re.IGNORECASE)
_NESTED_CONTACT_ESCAPE_RE = re.compile(
    r"%(?:25|40|2e|5b|5d|28|29|7b|7d|2f)",
    flags=re.IGNORECASE,
)
_PERCENT_U_ESCAPE_RE = re.compile(r"%u([0-9A-F]{4})", flags=re.IGNORECASE)
# Every supported hidden-address form must carry an at-sign, an encoded
# delimiter, a standalone ``at`` token, the Chinese delimiter, or a format
# control that can hide that token. Strings without any such marker cannot
# become an email under the bounded decoder, so they are a safe O(1 regex)
# negative path for matcher-wide corpus scans.
_RAW_CONTACT_MARKER_RE = re.compile(
    r"@|%|&|<|艾特|[＠﹫]|(?:ａ|Ａ)(?:ｔ|Ｔ)|"
    r"[\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]",
    flags=re.IGNORECASE,
)
_RAW_PLAIN_AT_RE = re.compile(r"\bat\b", flags=re.IGNORECASE)
_RAW_PLAIN_DOT_RE = re.compile(
    r"\b(?:dot|point)\b|"
    r"\.(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59})(?![\w-])|"
    r"\s\.\s|\+\.\+|[。．﹒․]",
    flags=re.IGNORECASE,
)
_MAX_CONTACT_SCAN_CHARS = 20_000
_MAX_CONTACT_DECODE_ROUNDS = 24
_T = TypeVar("_T")
_PUBLIC_URL_FIELDS = frozenset({
    "application_url",
    "contact_source_url",
    "href",
    "link",
    "official_url",
    "source_url",
    "url",
})

class _DetectionHTMLTextParser(HTMLParser):
    """Extract browser-visible text without trusting markup-shaped regexes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_display_text(value: str) -> str | None:
    """Return parsed display text, or ``None`` if detection cannot be trusted."""

    parser = _DetectionHTMLTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        # Public projection is a safety boundary. A future parser exception
        # must redact the field rather than return uninspected markup.
        return None
    return "".join(parser.parts)


def _contact_detection_view(
    value: str,
) -> tuple[str, str, str, str, str, str, bool]:
    """Return a bounded normalization used only to detect hidden emails.

    The original display value is never percent-decoded. This separate view
    closes common scraper evasions (HTML entities, repeated percent encoding,
    full-width forms, zero-width controls, and ``at``/``dot`` delimiters)
    without rewriting ordinary public text that does not contain a contact.
    """

    text = value
    text = unicodedata.normalize("NFKC", text)
    reached_fixed_point = False
    for _ in range(_MAX_CONTACT_DECODE_ROUNDS):
        legacy_decoded = _PERCENT_U_ESCAPE_RE.sub(
            lambda match: chr(int(match.group(1), 16)),
            text,
        )
        percent_decoded = unquote(legacy_decoded)
        entity_decoded = html.unescape(percent_decoded)
        decoded = unicodedata.normalize("NFKC", entity_decoded)
        if decoded == text:
            reached_fixed_point = True
            break
        text = decoded
    # Some directory pages split an address across presentational tags or
    # comments (``jane<span>@</span>example<span>.</span>edu``). Keep both
    # views: the markup-bearing form catches addresses inside tag attributes,
    # while the display-text form joins characters separated only by markup.
    markup_text = text
    markup_parse_failed = False
    if "<" in text:
        parsed_text = _html_display_text(text)
        if parsed_text is None:
            markup_parse_failed = True
        else:
            text = parsed_text
    markup_format_separator_text = "".join(
        " " if unicodedata.category(character) == "Cf" else character
        for character in markup_text
    )
    markup_text = "".join(
        character
        for character in markup_text
        if unicodedata.category(character) != "Cf"
    )
    format_separator_text = "".join(
        " " if unicodedata.category(character) == "Cf" else character
        for character in text
    )
    text = "".join(
        character
        for character in text
        if unicodedata.category(character) != "Cf"
    )
    explicit_marker_view = text
    text = _CONTACT_AT_DELIMITER_RE.sub("@", text)
    text = _CONTACT_DOT_DELIMITER_RE.sub(".", text)
    format_separator_marker_view = format_separator_text
    format_separator_text = _CONTACT_AT_DELIMITER_RE.sub(
        "@",
        format_separator_text,
    )
    format_separator_text = _CONTACT_DOT_DELIMITER_RE.sub(
        ".",
        format_separator_text,
    )
    unresolved_nested_escape = (
        markup_parse_failed
        or (
            not reached_fixed_point
            and (
                bool(_NESTED_CONTACT_ESCAPE_RE.search(text))
                or "&amp;" in text.casefold()
            )
        )
    )
    return (
        text,
        explicit_marker_view,
        format_separator_text,
        format_separator_marker_view,
        markup_text,
        markup_format_separator_text,
        unresolved_nested_escape,
    )


def contains_embedded_email(value: object) -> bool:
    """Whether a string contains a plain, encoded, or obfuscated email."""

    if not isinstance(value, str):
        return False
    # Never return an unscanned oversized field unchanged. Public projections
    # fail closed here; upstream renderers already impose much smaller limits.
    if len(value) > _MAX_CONTACT_SCAN_CHARS:
        return True
    # The committed corpus contains many long descriptions with an ordinary
    # visible address. Match analysis calls this boundary for every candidate;
    # decoding/NFKC-normalizing those already-obvious strings made a broad
    # profile spend tens of seconds before ranking. Preserve the full evasive
    # decoder for encoded/obfuscated forms, but let the exact same raw regular
    # expressions short-circuit the overwhelmingly common case.
    if (
        _EMAIL_IN_TEXT_RE.search(value)
        or _UNICODE_EMAIL_IN_TEXT_RE.search(value)
        or _EMAIL_ADDRESS_LITERAL_RE.search(value)
    ):
        return True
    if (
        _RAW_CONTACT_MARKER_RE.search(value) is None
        and not (
            _RAW_PLAIN_AT_RE.search(value)
            and _RAW_PLAIN_DOT_RE.search(value)
        )
    ):
        return False
    (
        detection_view,
        explicit_marker_view,
        format_separator_view,
        format_separator_marker_view,
        markup_view,
        markup_format_separator_view,
        unresolved_nested_escape,
    ) = (
        _contact_detection_view(value)
    )
    if unresolved_nested_escape:
        return True

    def plain_match_is_contact(
        match: re.Match[str],
        view: str,
    ) -> bool:
        local = match.group("local").casefold()
        first_domain = (match.groupdict().get("first_domain") or "").casefold()
        prefix = view[max(0, match.start() - 32):match.start()]
        contact_cue = bool(_CONTACT_CUE_RE.search(prefix))
        return bool(
            contact_cue
            or (
                local not in _PLAIN_AT_SENTENCE_WORDS
                and first_domain not in _PLAIN_DOMAIN_ARTICLES
            )
        )

    def view_has_contact(view: str, marker_view: str) -> bool:
        if (
            _EMAIL_IN_TEXT_RE.search(view)
            or _UNICODE_EMAIL_IN_TEXT_RE.search(view)
            or _EMAIL_ADDRESS_LITERAL_RE.search(view)
        ):
            return True
        if any(
            plain_match_is_contact(match, view)
            for match in _PLAIN_WORD_DOT_EMAIL_RE.finditer(view)
        ):
            return True
        # The first-domain article guard above excludes natural phrases such as
        # ``at the Point Reyes``; every other syntactically valid suffix must
        # fail closed instead of depending on an inevitably incomplete TLD list.
        if any(
            plain_match_is_contact(match, view)
            for match in _PLAIN_WORD_POINT_EMAIL_RE.finditer(view)
        ):
            return True
        if any(
            plain_match_is_contact(match, view)
            for match in _PLAIN_AT_LITERAL_DOT_EMAIL_RE.finditer(view)
        ):
            return True
        if any(
            plain_match_is_contact(match, view)
            for match in _PLAIN_AT_SPACED_DOT_EMAIL_RE.finditer(view)
        ):
            return True
        strong_or_mixed_matches = (
            *_AT_SIGN_WORD_DOT_EMAIL_RE.finditer(view),
            *_AT_SIGN_SPACED_DOT_EMAIL_RE.finditer(view),
            *_PLAIN_AT_STRONG_DOT_EMAIL_RE.finditer(marker_view),
        )
        return bool(strong_or_mixed_matches)

    if view_has_contact(detection_view, explicit_marker_view):
        return True
    if view_has_contact(format_separator_view, format_separator_marker_view):
        return True
    if view_has_contact(markup_view, markup_view):
        return True
    if view_has_contact(
        markup_format_separator_view,
        markup_format_separator_view,
    ):
        return True

    # In query/form data, '+' may represent a space. Build a secondary bounded
    # detection-only view instead of using unquote_plus globally, which would
    # corrupt legitimate plus-address local parts in the display value.
    form_marker_view = explicit_marker_view.replace("+", " ")
    form_detection_view = _CONTACT_AT_DELIMITER_RE.sub("@", form_marker_view)
    form_detection_view = _CONTACT_DOT_DELIMITER_RE.sub(".", form_detection_view)
    return view_has_contact(form_detection_view, form_marker_view)


def safe_public_http_url(value: object) -> str | None:
    """Return an absolute browser-safe public URL or ``None``.

    Opportunity links originate in scraped and imported records.  React does
    not neutralize a ``javascript:`` href, so the API projection must enforce
    the scheme boundary before any record reaches a browser.  Query strings and
    fragments are retained because some application portals require them;
    embedded credentials and malformed/whitespace-bearing URLs fail closed.
    """

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or raw != value or any(character.isspace() for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return None
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or contains_embedded_email(raw)
    ):
        return None
    return raw


def _is_public_url_field(key: object) -> bool:
    return bool(
        isinstance(key, str)
        and (
            key.casefold() in _PUBLIC_URL_FIELDS
            or key.casefold().endswith("_url")
        )
    )


def sanitize_public_urls(value: _T) -> _T:
    """Recursively enforce the public http(s)-only link contract."""

    if isinstance(value, list):
        return [sanitize_public_urls(item) for item in value]  # type: ignore[return-value]
    if isinstance(value, tuple):
        return tuple(sanitize_public_urls(item) for item in value)  # type: ignore[return-value]
    if isinstance(value, dict):
        projected = {}
        for key, item in value.items():
            if _is_public_url_field(key):
                safe_url = safe_public_http_url(item)
                if safe_url is not None:
                    projected[key] = safe_url
                continue
            projected[key] = sanitize_public_urls(item)
        return projected  # type: ignore[return-value]
    return value


def redact_embedded_emails(value: _T) -> _T:
    """Recursively remove email addresses hidden inside otherwise-public text.

    Dropping ``contact_email`` fields is insufficient when collectors copy the
    same address into a description, application note, keyword, or URL. The
    internal corpus remains untouched; only the response projection is copied.
    """

    if isinstance(value, str):
        # Span positions in the detection view do not map safely back to the
        # original after decoding and Unicode normalization. Fail closed for
        # the complete field instead of risking a partial contact leak.
        return (  # type: ignore[return-value]
            "[email redacted]" if contains_embedded_email(value) else value
        )
    if isinstance(value, list):
        return [redact_embedded_emails(item) for item in value]  # type: ignore[return-value]
    if isinstance(value, tuple):
        return tuple(redact_embedded_emails(item) for item in value)  # type: ignore[return-value]
    if isinstance(value, dict):
        return {
            key: redact_embedded_emails(item)
            for key, item in value.items()
            if not (isinstance(key, str) and contains_embedded_email(key))
        }  # type: ignore[return-value]
    return value
