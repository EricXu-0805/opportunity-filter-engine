"""Read the Cell Biology department's roster and individual pages for existing medical-school IDs."""

import re
from collections import defaultdict

from . import faculty_graph, jhu_som_appointments, ucb_common

ROSTER = "https://cellbio.jhmi.edu/faculty/"
DEPARTMENT = "School of Medicine — Cell Biology"
# The provider path and the department's independently reviewed person page
# bind the old opportunity ID even when one of the two names is abbreviated.
PROFILES = {
    "faculty-jhu-som-02c5982c": ("takanari-inoue/2777432", "takanari-inoue-ph-d", "Takanari Inoue"),
    "faculty-jhu-som-05ef94af": ("douglas-robinson/2776993", "douglas-robinson-ph-d", "Douglas Robinson"),
    "faculty-jhu-som-11652663": ("peter-n-devreotes/2777350", "peter-n-devreotes-ph-d", "Peter N. Devreotes"),
    "faculty-jhu-som-15c6a28f": ("susan-michaelis/2777068", "susan-michaelis-ph-d", "Susan Michaelis"),
    "faculty-jhu-som-24e2bd99": ("arja-ray/4247491", "arja-ray-ph-d", "Arja Ray"),
    "faculty-jhu-som-30d887bb": ("michael-piacentino/2777533", "michael-piacentino-ph-d", "Michael Piacentino"),
    "faculty-jhu-som-35be438a": ("andrew-ewald/2777835", "andrew-ewald-ph-d", "Andrew Ewald"),
    "faculty-jhu-som-41623747": ("miho-iijima/2777438", "miho-iijima-ph-d", "Miho Iijima"),
    "faculty-jhu-som-4218f1bf": ("yuchuan-miao/4161602", "yuchuan-miao-ph-d", "Yuchuan Miao"),
    "faculty-jhu-som-5c729543": ("veena-padmanaban/6780879", "veena-padmanaban-ph-d", "Veena Padmanaban"),
    "faculty-jhu-som-68b281ec": ("erika-matunis/2777801", "erika-matunis-ph-d", "Erika Matunis"),
    "faculty-jhu-som-898be331": ("hiromi-sesaki/2777385", "hiromi-sesaki-ph-d", "Hiromi Sesaki"),
    "faculty-jhu-som-96645a98": ("mikala-egeblad/2777581", "mikala-egeblad-ph-d", "Mikala Egeblad"),
    "faculty-jhu-som-98c0914a": ("peter-espenshade/2777257", "peter-espenshade-ph-d", "Peter Espenshade"),
    "faculty-jhu-som-9e3ae0d0": ("ryuya-fukunaga/2777655", "ryuya-fukunaga-ph-d", "Ryuya Fukunaga"),
    "faculty-jhu-som-b3dd22f4": ("shigeki-watanabe/2777904", "shigeki-watanabe-ph-d", "Shigeki Watanabe"),
    "faculty-jhu-som-b7693f4f": ("jian-liu/2777354", "jian-liu-ph-d", "Jian Liu"),
    "faculty-jhu-som-d8a53d64": ("stephen-j-gould/2777555", "stephen-gould-ph-d", "Stephen Gould"),
    "faculty-jhu-som-d97f19c5": ("debbie-j-andrew/2777793", "deborah-andrew-ph-d", "Deborah Andrew"),
}

# These source names refer to independently verified, unchanged provider identities.
STORED_NAMES = {"faculty-jhu-som-d97f19c5": "Debbie J. Andrew", "faculty-jhu-som-d8a53d64": "Stephen J. Gould"}


def _seed_row(row):
    pair = PROFILES.get(row.get("id"))
    return (pair and row.get("department") == DEPARTMENT and row.get("source") == "jhu_faculty"
            and row.get("pi_name") == STORED_NAMES.get(row["id"], pair[2])
            and row.get("url") == f"https://profiles.hopkinsmedicine.org/provider/{pair[0]}")


def _profile_url(pair):
    return f"https://cellbio.jhmi.edu/people/{pair[1]}/"


def _name(label):
    return label.get_text(" ", strip=True).partition(",")[0].strip() if label else ""


def _current_title(raw, section):
    # A retired directorship is separate from an ongoing distinguished professorship.
    # Quote one current professorial appointment using the university's wording.
    for part in raw.split(" / "):
        if (re.search(r"\bprofessor\b", part, re.IGNORECASE)
                and not re.search(r"\b(?:former|retired|emerit\w*|adjunct|visiting)\b", part, re.IGNORECASE)):
            if section == "Primary":
                return part
    if section == "Emeritus" and re.fullmatch(r"Professor Emerit(?:us|a)", raw, re.IGNORECASE):
        return raw
    return ""


def observe(records):
    candidates = [r for r in records if _seed_row(r)]
    if not candidates or faculty_graph._source_budget_spent():
        return 0
    soup = ucb_common.fetch_soup(ROSTER, timeout=10, max_retries=1)
    if soup is None or soup._ofe_final_url != ROSTER:
        return 0
    cards = defaultdict(list)
    for card in soup.select(".pendari_people_grid_item"):
        anchor = card.select_one(".info h3 a[href]")
        if anchor:
            cards[anchor["href"]].append(card)
    seen = soup._ofe_observed_at
    count = 0
    for row in candidates:
        if faculty_graph._source_budget_spent():
            break
        pair = PROFILES[row["id"]]
        url = _profile_url(pair)
        if len(cards[url]) != 1:
            continue
        card = cards[url][0]
        name = _name(card.select_one(".info h3 a"))
        position = card.select_one(".info .title")
        if not position:
            continue
        raw = position.get_text(" ", strip=True)
        classes = card.get("class", [])
        section = None
        if "primary-faculty" in classes:
            section = "Primary"
        elif "faculty-emeritus-emerita" in classes:
            section = "Emeritus"
        title = _current_title(raw, section)
        if name != pair[2] or not title:
            jhu_som_appointments.withhold_changed_appointment(row)
            continue
        person = ucb_common.fetch_soup(url, timeout=8, max_retries=1)
        if person is None:
            continue
        heading = person.select_one("h1")
        individual_position = person.select_one(".person-page .title")
        if heading is None or individual_position is None:
            continue
        if (person._ofe_final_url != url or _name(heading) != name
                or individual_position.get_text(" ", strip=True) != raw):
            jhu_som_appointments.withhold_changed_appointment(row)
            continue
        jhu_som_appointments.apply_observation(row, {
            "profile": url, "source": ROSTER, "title": title, "name": row["pi_name"],
            "listed_name": name, "listed_title": raw, "section": section,
            "checked_on": seen[:10], "profile_observed_at": person._ofe_observed_at,
        }, seen)
        count += 1
    return count


def preserve_observation(previous, incoming):
    pair = PROFILES.get(incoming.get("id"))
    if pair:
        jhu_som_appointments.preserve_observation(
            previous, incoming, seed_row=_seed_row, department=DEPARTMENT,
            roster=ROSTER, profile=_profile_url(pair),
        )
