"""Keep later UChicago Summer Lab recruitment notices independent of the reviewed 2027 terms."""
import re

from src.normalizers.deadlines import parse_to_date
from src.program_windows import DSI_IDS, DSI_WINDOW, reviewed_window

_COHORT = re.compile(
    r"\b(?:applications? for (?:the )?(?:summer(?: lab)?\s+)|"
    r"(?:details for|apply for) (?:the )?summer\s+|(?:DSI )?Summer Lab\s+)(20\d{2})\b", re.I,
)
_ARCHIVE = re.compile(r"\b(?:archive[d]?|alumni|past (?:programs?|cohorts?|events?)|related news)\b", re.I)
_CLOSE = re.compile(
    r"\bapplication(?:s)? (?:deadline(?: is)?|(?:will )?close(?:s)?(?: on)?)\s*:?\s*"
    r"([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2})\b", re.I,
)


def read_notice(soup) -> dict | None:
    """Read recruitment copy from the school's main content, stopping before archives."""
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
    if main is None:
        return None
    candidates = []
    closed = []
    deadlines = []
    for block in main.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = " ".join(block.stripped_strings)
        if block.name.startswith("h") and _ARCHIVE.search(text):
            break
        if _ARCHIVE.search(text) or not text or len(text) > 500:
            continue
        # A single paragraph can finish the old class and introduce its successor.
        for sentence in re.split(r"(?<=[.!?;])\s+|,\s+(?=(?:applications?|details) for)", text, flags=re.I):
            group = closed if re.search(r"\b(?:closed|concluded|ended)\b", sentence, re.I) else candidates
            group.extend((int(year), sentence) for year in _COHORT.findall(sentence))
        close = _CLOSE.search(text)
        if close and (day := parse_to_date(close.group(1))):
            deadlines.append((day, text))
    if not candidates:
        candidates = closed
    years = sorted({year for year, _ in candidates})
    if not years or years[-1] < DSI_WINDOW.closes_on.year:
        return None
    # When two application notices coexist, neither has an exclusive closing date.
    notice = {"years": years, "text": " ".join(dict.fromkeys(text for _, text in candidates))[:1000]}
    applicable = [(day, text) for day, text in deadlines if day.year == years[-1]]
    if len(years) == 1 and len({day for day, _ in applicable}) == 1:
        day, text = applicable[0]
        notice.update(deadline=day.isoformat(), deadline_note=text)
    return notice


def apply_notice(record: dict, notice: dict | None) -> None:
    if record.get("id") != DSI_IDS[0] or not isinstance(notice, dict) or reviewed_window(record) is not DSI_WINDOW:
        return
    # An updated program configuration can supply its own new terms.
    meta = record["metadata"]
    years, text = notice.get("years"), notice.get("text")
    if not isinstance(text, str) or not text or not isinstance(years, list) or not years:
        return
    if not all(type(year) is int for year in years):
        return
    notice = dict(notice)
    notice.setdefault("observed_at", meta.get("last_verified"))
    meta["dsi_application_notice"] = notice
    if max(years) == DSI_WINDOW.closes_on.year:
        return
    note = notice.get("deadline_note")
    if note is not None and not isinstance(note, str):
        return
    if note and note not in text:
        text += " " + note
    record.update(description=text, description_raw=text, description_clean=text,
                  deadline=notice.get("deadline"), deadline_is_estimate=False if notice.get("deadline") else None,
                  is_rolling=False, paid="unknown", compensation_details="")
    record["eligibility"].update(preferred_year=[], citizenship_required=None, international_friendly="unknown",
                                 work_auth_notes="", eligibility_text_raw="")
    meta["deadline_note"] = notice.get("deadline_note", "")


def retain_notice(previous: dict, incoming: dict) -> None:
    if incoming.get("id") != DSI_IDS[0] or incoming.get("url") != previous.get("url"):
        return
    if "dsi_application_notice" not in incoming["metadata"]:
        apply_notice(incoming, previous.get("metadata", {}).get("dsi_application_notice"))
