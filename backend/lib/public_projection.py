"""Positive public-data projection helpers shared by API response routes."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import TypeVar
from urllib.parse import unquote, urlsplit

from src.evidence import inferred_method, record_kind, target_truth

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
    # HTMLParser treats the browser-tolerated ``--!>`` comment closer as data
    # rather than ``handle_comment``. Drop that exact comment-shaped fragment
    # too, otherwise ``jane<!-- guard --!>@example.edu`` stays split in the
    # detection view and can escape public redaction.
    return re.sub(r"<!--.*?--!?>", "", "".join(parser.parts), flags=re.DOTALL)


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

# Deliberately NOT rejected here: a nested absolute URL inside the path or
# query. `https://urldefense.com/v3/__https://profiles.ucsd.edu/...` is one
# real corpus record's only link — a single absolute URL to urldefense.com
# whose path happens to contain another. A rule that refused a second bare
# `http(s)://` would delete it, along with every other mail-gateway rewrite
# and every `?next=` return address. `urlsplit` already decides the one thing
# that matters: which host a click reaches. Two destinations in one field is a
# data-integrity concern, not a link-safety one, and it has no expression here
# that does not also destroy legitimate links.


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


def safe_public_text(value: object) -> str:
    """One corpus text field, cleared for a message we send under our name.

    ``redact_embedded_emails`` already owns what counts as a hidden address —
    encoded, delimiter-obfuscated and split-across-markup shapes included.
    This adds only the coercion a renderer needs, so a title, source or
    organization read straight off a record cannot mail an address the API
    projection would have stripped from that same field. A recognised address
    becomes the shared placeholder rather than an empty string: the row still
    has to appear, and a blank line reads as a record with no title.
    """

    return redact_embedded_emails(str(value or ""))


# Exactly one claim, anchored to the very end of the string: a terminal
# parenthetical saying an application round is OPEN.
#
# Scoped to what this incident actually proved false. "(applications closed)"
# is not a false opening claim — it is the record agreeing with the truth
# envelope, and erasing it would delete a true statement. A standalone
# "(now open)" says nothing about applications. Neither belongs here.
#
# Anchored, so `CS DRP — Directed Reading Program (Computer Science, Winter
# Break) (applications open)` loses the last parenthetical and keeps the
# first. Ordinary parentheses and titles like "Open House" never match at all.
_TERMINAL_LIFECYCLE_SUFFIX_RE = re.compile(
    r"\s*\(\s*applications?\s+open\s*\)\s*$",
    flags=re.IGNORECASE,
)


def neutralize_lifecycle_title(title: object, canonical_record: dict) -> str:
    """Drop a title's "(applications open)" unless the record IS an open listing.

    A title is the one string that reaches a reader with no envelope attached —
    an inbox subject line, a card heading, a link preview. Two real corpus rows
    (`b27723bb1ca91202`, `a22e863a3bd7ce87`) carry no `source_type`, so the
    truth contract answers `record_kind_unverified`, and the very same payload
    then said "applications open" in its title. Both statements shipped
    together.

    The permission is the narrow half: a suffix survives only for a record we
    positively call a listing AND that the truth still calls actionable. Not
    the reason — a row can be unreviewed and separately closed, and the closure
    wins the reason while the kind is what says we never confirmed an
    application exists.

    Deliberately NOT `normalize_title`: that one is a dedupe key and lowercases,
    strips punctuation and collapses whitespace. This removes one bounded
    suffix and touches nothing else, so "Open House", ordinary parentheses and
    a live listing's own suffix all survive untouched.
    """
    text = str(title or "")
    if record_kind(canonical_record) == "listing" and target_truth(canonical_record).actionable:
        return text
    match = _TERMINAL_LIFECYCLE_SUFFIX_RE.search(text)
    # No suffix, no edit. Returned byte-for-byte, leading and trailing
    # whitespace included: an unconditional strip() would quietly rewrite
    # every title in the corpus that this helper has no business touching,
    # which is how a one-record truth fix becomes generic normalization.
    if match is None:
        return text
    # Whatever is left, including nothing. A title that is ONLY the suffix
    # strips to "", and falling back to the original there would hand the
    # reader back the exact claim this function exists to remove — the one
    # shape where a fallback is worst. Inventing a stand-in label ("Untitled
    # opportunity") is not the alternative either: that is a sentence the
    # source never wrote. No corpus row is this shape today.
    return text[:match.start()].rstrip()


def public_target_truth(canonical_record: dict) -> dict:
    """The decision fields a client needs, and nothing behind them.

    ``evidence_source``/``evidence_key``/``evidence_value`` stay server-side:
    they name internal metadata paths, and a browser that branched on
    ``metadata.urap_status`` would couple the UI to one collector's schema.
    The client needs to know *what* it may offer, not which field decided.

    ``verified_at``/``expires_at`` do ship. They are state a student can read
    ("checked three weeks ago") rather than a pointer into our storage, and
    they are the difference between "closed" and "closed, and we last looked in
    July". Either may be null; neither is ever synthesized.
    """
    truth = target_truth(canonical_record)
    return {
        "listing_state": truth.listing_state,
        "reference_only": truth.reference_only,
        "actionable": truth.actionable,
        "accepting_state": truth.accepting_state,
        "reason_code": truth.reason_code,
        "verified_at": truth.verified_at,
        "expires_at": truth.expires_at,
    }


# Metadata keys that fed the truth decision. Once `target_truth` is on the
# payload they are redundant at best and contradictory at worst: a client that
# branched on `metadata.urap_status` would couple itself to one collector's
# schema, and one that read `metadata.is_active` would disagree with the
# envelope the moment a record is closed-but-active — which is the exact shape
# of the 861 rows this contract exists for.
_EVIDENCE_ONLY_METADATA_KEYS = frozenset({
    "is_active",
    "listing_status",
    "urap_status",
    "reference_only",
    # Superseded rather than secret: target_truth.verified_at / .expires_at
    # carry these, and two copies of a timestamp is two things to disagree.
    "last_verified",
    "expires_at",
    # The neutralizer's own bookkeeping. `faculty_availability_status` here is
    # the internal marker the scan writes into metadata — not the top-level
    # field of the same name, which is a deliberate part of the payload and
    # stays. The scan version and the two boolean markers describe how we
    # reached the answer, and a client branching on them would be reading our
    # implementation rather than the contract.
    "faculty_availability_status",
    "faculty_availability_scan_version",
    "faculty_not_accepting_undergraduates_stated",
    "faculty_research_inactive_stated",
    # The publication remediation's own audit trail: which gate stamped this
    # record's papers, when we took the trust back, and the OpenAlex author id
    # the retired rule had resolved. All of it is internal bookkeeping about
    # our process, and one field of it — `prior_author_id` — is an identity
    # claim we have specifically stopped standing behind. The contract a
    # client reads is `publication_attribution_status`, which is already
    # stripped whenever it is not verified; this block must never become the
    # back door that re-publishes what that strip removed.
    "publication_remediation",
    # Which gate chose the papers. Real provenance, but a client cannot
    # re-derive or act on it, and branching on our internal rule version is
    # reading the implementation rather than the contract.
    "works_gate",
})

# Everything that only means something for a confirmed listing. On a record
# whose type nobody has reviewed, each of these is a term of an application we
# have no evidence exists — and a stale client that never learned about
# `record_kind_unverified` renders whichever of them it finds.
_LISTING_ONLY_FIELDS = (
    # When you could apply, and until when.
    "deadline",
    "deadline_is_estimate",
    "is_rolling",
    "posted_date",
    "start_date",
    # What you would get.
    "paid",
    "compensation_details",
    "duration",
    # What it claims to be, and where.
    "opportunity_type",
    "on_campus",
    "remote_option",
    "location",
    "audience",
    # The pitch. Scraped prose from an unreviewed page reads exactly like a
    # posting's — "apply by March 1", "we are recruiting two students" — and a
    # stale client renders it as the description of an opening.
    "description_clean",
    "description_raw",
    # The legacy top-level field, still present on all 26 unreviewed rows and
    # carrying the same pitch ("Open to all majors…", application steps,
    # deadlines). Clearing only the clean/raw pair left the prose reachable
    # through the one field an older client is most likely to render.
    "description",
    # The legacy top-level status. Two of the 26 unreviewed rows still say
    # "open" here, which is the single field an older client is most likely to
    # read as "you can apply" — no truth envelope required.
    "status",
    # The term an opening runs in. Consumers read it as when you would start,
    # which is a term of an application we have no evidence exists.
    "semester",
)
_LISTING_ONLY_METADATA = ("deadline_note",)

# The two fields whose value is an assertion about identity rather than
# display. They are re-bound from the canonical record instead of copied,
# because a payload that disagrees with the record it claims to describe is
# how one target's terms get served under another target's id.
_CANONICAL_IDENTITY_FIELDS = ("id", "source_type")


def project_public_opportunity_payload(payload: dict, canonical_record: dict) -> dict:
    """The single public projection for one opportunity. Nothing else stamps.

    Callers do their own route-specific preparation first — dropping redacted
    fields, choosing card columns, resolving an honest displayed title — and
    then hand the result here. Everything that must be true of EVERY public
    opportunity payload happens in this one function:

      1. a recursive copy-projection through the URL and contact boundaries,
      2. identity re-bound to the canonical record,
      3. the truth envelope and record kind, derived only from ``src.evidence``,
      4. evidence-only metadata removed,
      5. offer terms stripped from a record whose kind was never confirmed,
      6. the application URL cleared on anything non-actionable,
      7. a lifecycle suffix removed from the title unless it is an open listing.

    Copy-on-write is a property of THIS function, not a habit of its callers.
    The previous ``with_public_target_truth`` mutated the dict it was given and
    was safe only because every existing caller happened to pass a freshly
    built one — a precondition no signature stated and no test held anyone to.
    ``sanitize_public_urls``/``redact_embedded_emails`` rebuild every dict,
    list and tuple they walk, so the returned payload shares no mutable
    descendant with either input, and ``canonical_record`` is only ever read.
    """
    if not isinstance(payload, dict):
        # A non-dict payload has nowhere to carry a truth envelope, and
        # returning it unstamped would be a public opportunity with no
        # contract attached. Callers pass dicts; this is the fail-closed edge.
        raise TypeError("public opportunity payload must be a dict")

    # Identity comes from the record, never from the payload. A poisoned or
    # stale `id`/`source_type` would otherwise decide what the client thinks
    # it is looking at, while the truth beside it describes something else.
    # Absent on the canonical side means absent on the wire: 26 real rows
    # carry no `source_type` at all, and preserving a payload's invented one
    # would manufacture the very evidence the truth contract says we lack.
    #
    # Bound BEFORE the projection below, not after. Re-binding afterwards
    # would carry canonical values straight past the very contact and URL
    # boundary this function claims to have applied — and the corpus is
    # exactly where addresses turn up in fields nobody expects them in
    # (`stanford-f0a974ed2bd2` has one as its TITLE). Canonical does not mean
    # clean; it means authoritative about identity.
    prepared = dict(payload)
    for field in _CANONICAL_IDENTITY_FIELDS:
        if field in canonical_record:
            prepared[field] = canonical_record[field]
        else:
            prepared.pop(field, None)

    # Rebuilds every dict, list and tuple it walks, so nothing mutable in the
    # result is shared with `payload` — the shallow `dict()` above is only a
    # scaffold for the identity edit and never reaches the caller.
    projected = redact_embedded_emails(sanitize_public_urls(prepared))

    truth = public_target_truth(canonical_record)
    kind = record_kind(canonical_record)
    projected["target_truth"] = truth
    # Published so an old client can branch on it without re-deriving the
    # source-type table, and so "we could not confirm what this is" is a fact
    # on the wire rather than an inference from an absent field.
    projected["record_kind"] = kind
    # Where the keywords came from, on the wire, for the same reason
    # `publication_attribution_status` is: a client cannot re-derive it, and
    # without it a topic this pipeline INFERRED renders identically to one
    # scraped off the professor's own page. 5% of faculty carry keywords
    # derived from a matched OpenAlex author record, and that match is wrong
    # often enough — common surname, department field family too coarse to
    # separate two people — that presenting them as stated fact is a claim we
    # cannot support. Absent means stated, which is what every non-enriched
    # record has always been.
    keywords_method = inferred_method(canonical_record, "keywords")
    if keywords_method and projected.get("keywords"):
        projected["keywords_attribution"] = "inferred"

    metadata = projected.get("metadata")
    if isinstance(metadata, dict):
        projected["metadata"] = {
            k: v for k, v in metadata.items() if k not in _EVIDENCE_ONLY_METADATA_KEYS
        }

    if kind == "unknown":
        _neutralize_unverified_kind(projected)

    if not truth["actionable"]:
        application = projected.get("application")
        if isinstance(application, dict) and application.get("application_url") is not None:
            projected["application"] = {**application, "application_url": None}

    if "title" in projected:
        projected["title"] = neutralize_lifecycle_title(
            projected["title"], canonical_record,
        )
    return projected


def _neutralize_unverified_kind(projected: dict) -> None:
    """Strip offer terms from a record whose type was never confirmed.

    Redaction rather than labelling, because the label is the part a stale
    bundle ignores. The identity of the record — title, organization, source,
    the URL to read it at — stays: this is still a page worth opening, it is
    just not a listing we will describe as one.

    Keyed on the record's KIND, never on the reason. A row can be both
    unreviewed and explicitly closed, and the closure is the more specific
    fact so it wins the reason — which would let exactly those rows keep their
    deadline, pay and eligibility fields if eligibility were read off the
    reason. The reason decides what we say; the kind decides what we send.
    """
    for field in _LISTING_ONLY_FIELDS:
        projected.pop(field, None)
    # Emptied wholesale rather than filtered key by key. Both objects exist to
    # describe an application — who may make one, what it demands — so on a
    # record that may not have one, every key is out of scope by construction.
    # A blacklist here would have to be extended each time a collector adds a
    # field, and the failure mode of forgetting is that the new field ships.
    #
    # Keyed on the KEY being present, not on the value being a dict: a
    # malformed `application: "apply now: https://…"` is a string that renders
    # as an instruction, and an isinstance guard would wave exactly that
    # through while catching only the well-formed case.
    for field in ("eligibility", "application"):
        if field in projected:
            projected[field] = {}
    metadata = projected.get("metadata")
    if isinstance(metadata, dict):
        projected["metadata"] = {
            k: v for k, v in metadata.items() if k not in _LISTING_ONLY_METADATA
        }
