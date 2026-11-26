"""Read the Snyder department's appointments for its matched School of Medicine IDs."""

from collections import defaultdict

from . import ucb_common

ROSTER = "https://neuroscience.jhu.edu/research/faculty"
DEPARTMENT = "School of Medicine — Neuroscience"
# The medical school's provider IDs and the department's independent profile
# IDs are stable even when the professor's title or appointment section changes.
PROFILES = {
    "faculty-jhu-som-fa1fa91f": ("ernst-niebur/2777939", 62),
    "faculty-jhu-som-ba3abad3": ("seth-blackshaw/2777521", 7),
    "faculty-jhu-som-ab46342e": ("daeyeol-lee/2777422", 146),
    "faculty-jhu-som-630567cb": ("james-knierim/2777079", 43),
    "faculty-jhu-som-cc6cce97": ("hey-kyoung-lee/2777024", 49),
    "faculty-jhu-som-51253ecf": ("tomomi-karigo/2777265", 161),
    "faculty-jhu-som-64b89987": ("xinzhong-dong/2777316", 24),
    "faculty-jhu-som-709759ad": ("angelika-doetzlhofer/2777085", 22),
    "faculty-jhu-som-45000a8f": ("hyungbae-kwon/2777810", 143),
    "faculty-jhu-som-308f9d80": ("loyal-goff/2777811", 114),
    "faculty-jhu-som-db2d0079": ("maya-opendak/2777060", 158),
    "faculty-jhu-som-4b65eadd": ("patricia-janak/2777017", 113),
    "faculty-jhu-som-0571117d": ("veit-stuphorn/2777894", 86),
}


def _seed_row(row):
    pair = PROFILES.get(row.get("id"))
    return (pair and row.get("department") == DEPARTMENT and row.get("source") == "jhu_faculty"
            and row.get("url") == f"https://profiles.hopkinsmedicine.org/provider/{pair[0]}")


def _set_title(row, title):
    metadata = row["metadata"]
    old = f'Faculty research profile for {metadata["faculty_title"]} {row["pi_name"]}'
    new = f'Faculty research profile for {title + " " if title else ""}{row["pi_name"]}'
    for key in ("description", "description_clean"):
        if isinstance(row.get(key), str):
            row[key] = row[key].replace(old, new, 1)
    metadata["faculty_title"] = title
    if not title and isinstance(row.get("title"), str):
        row["title"] = row["title"].removeprefix("Prof. ")


def _withhold_changed_appointment(row):
    _set_title(row, "")
    row["metadata"]["faculty_title_read_status"] = "department_card_changed"


def _apply(row, receipt, seen):
    _set_title(row, receipt["title"])
    metadata = row["metadata"]
    metadata.pop("faculty_title_read_status", None)
    row.update(url=receipt["profile"], source_url=receipt["profile"])
    # The directory establishes the listing and quoted position. The remaining
    # medical-school seed fields still have no new individual-page verification.
    metadata.update(faculty_title_observation=receipt.copy(),
                    verification_scope="curated", listing_seen_on_source=True,
                    last_seen_at=seen, last_verified=None)


def observe(records) -> int:
    candidates = [r for r in records if _seed_row(r)]
    if not candidates:
        return 0
    soup = ucb_common.fetch_soup(ROSTER)
    if soup is None or soup._ofe_final_url != ROSTER:
        return 0
    by_path = defaultdict(list)
    for card in soup.select("ul.facultylist > li[data-type]"):
        link = card.select_one("a[href^='/research/faculty/']")
        if link:
            by_path[link["href"]].append(card)
    seen = soup._ofe_observed_at
    observed = 0
    for row in candidates:
        profile_id = PROFILES[row["id"]][1]
        cards = by_path[f"/research/faculty/{profile_id}"]
        if len(cards) != 1:
            continue
        card = cards[0]
        label = card.select_one(".infocontainer > .name")
        position = card.select_one(".infocontainer > .name + span")
        if not label or not position:
            continue
        if label.get_text(strip=True).partition(",")[0].strip() != row["pi_name"]:
            _withhold_changed_appointment(row)
            continue
        # A second line can be an administrative office; after a semicolon
        # Blackshaw's card names his distinct UCSD Ophthalmology appointment.
        line = next(position.stripped_strings, "")
        if not line.startswith("Position: "):
            continue
        title = " ".join(line.removeprefix("Position: ").partition(";")[0].split())
        section = card["data-type"]
        if (section not in {"Primary", "Adjunct"} or "professor of neuroscience" not in title.casefold()
                or ("adjunct" in title.casefold()) != (section == "Adjunct")
                or any(term in title.casefold() for term in ("emerit", "former", "retired", "visiting"))):
            # This known card changed. A different role or person must not
            # inherit the department link or the medical seed's old title.
            _withhold_changed_appointment(row)
            continue
        profile_url = f"{ROSTER}/{profile_id}"
        profile = ucb_common.fetch_soup(profile_url, timeout=8, max_retries=1)
        if profile is None:
            continue
        if profile._ofe_final_url != profile_url:
            _withhold_changed_appointment(row)
            continue
        identity = profile.select_one('meta[property="og:title"][content]')
        position = profile.select_one(".textcontentcontainer .subtitle")
        if identity is None or position is None:
            continue
        quoted = next(position.stripped_strings, "").partition(";")[0]
        if (identity["content"].strip() != row["pi_name"]
                or " ".join(quoted.split()) != title):
            _withhold_changed_appointment(row)
            continue
        _apply(row, {"profile": profile_url, "source": ROSTER,
                     "title": title, "name": row["pi_name"], "section": section,
                     "checked_on": seen[:10], "profile_observed_at": profile._ofe_observed_at}, seen)
        observed += 1
    return observed


def preserve_observation(previous, incoming):
    """A file-only fallback must keep the dated department evidence on this person."""
    if not _seed_row(incoming) or previous.get("pi_name") != incoming.get("pi_name"):
        return
    if incoming["metadata"].get("faculty_title_read_status") == "department_card_changed":
        return
    metadata = previous.get("metadata") or {}
    if _seed_row(previous) and metadata.get("faculty_title_read_status") == "department_card_changed":
        _withhold_changed_appointment(incoming)
        return
    receipt = metadata.get("faculty_title_observation") or {}
    profile = f'{ROSTER}/{PROFILES[incoming["id"]][1]}'
    if (previous.get("department") == DEPARTMENT and previous.get("url") == profile
            and previous.get("source_url") in (profile, ROSTER) and receipt.get("source") == ROSTER
            and receipt.get("profile") == profile and receipt.get("name") == incoming["pi_name"]
            and receipt.get("title") == metadata.get("faculty_title") and metadata.get("last_seen_at")
            and incoming["metadata"].get("verification_scope") == "curated"
            and not incoming["metadata"].get("listing_seen_on_source")):
        _apply(incoming, receipt, metadata["last_seen_at"])
