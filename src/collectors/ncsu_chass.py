"""Read CHASS retirement only where its public staff taxonomy and faculty card agree."""

from __future__ import annotations

import re
from collections import defaultdict

from . import faculty_graph, ucb_common

FACULTY_URL = "https://chass.ncsu.edu/group/faculty/"
FACULTY_TERM = 11847
# CHASS uses one retirement term per academic unit. A separate faculty or staff
# term is positive evidence of another role, even when this appointment ended.
CURRENT_FACULTY_TERMS = {11937, 11970}  # CRDM doctoral and linguistics faculty
RETIRED_TERMS = {11866, 11869, 11895, 11872, 11967, 11915, 12186, 11927, 11945, 11936}
# Only single appointments attested on the college's retirement directories.
# Mixed titles (e.g. Professor and Vice Provost Emeritus) remain as listed.
RETIRED_TITLES = frozenset({
    "Assoc Professor Emeritus", "Assoc. Professor Emerita", "Associate Professor Emerita", "Associate Professor Emeritus",
    "Distinguished Professor Emerita", "Emerita", "Emerita Associate Professor", "Emerita Professor",
    "Emerita Senior Lecturer", "Emeritus", "Emeritus Associate Professor", "Emeritus Distinguished Professor",
    "Emeritus Faculty", "Emeritus Professor", "Emeritus Teaching Associate Professor", "Lecturer Emerita",
    "Professor Emerita", "Professor Emeritus", "Professor Emeritus, Film Studies", "Retiree",
    "Senior Lecturer Emerita", "Senior Lecturer Emeritus", "Teaching Assistant Professor Emerita",
    "Teaching Associate Professor Emeritus", "Unpaid Emeritus",
})


# Reviewed original faculty contacts, keyed by the immutable college CMS post ID.
# Unreviewed cross-appointments and name discrepancies keep their normal WP path.
REVIEWED_PROFILES = {
    89827: ("agcroasm", "Anita Croasmun"),
    89828: ("alchedia", "Jim Alchediak"),
    89831: ("casmith5", "Craig Smith"),
    89834: ("ddejoy", "Daniel DeJoy"),
    89845: ("jkeyton", "Joann Keyton"),
    89846: ("jkiwanu", "James Kiwanuka-Tondo"),
    89859: ("nhsnow", "Nancy Snow"),
    89861: ("pcaple", "Patricia Caple"),
    89864: ("rleonard", "Becky Leonard"),
    89866: ("schrag", "Robert Schrag"),
    89868: ("sstein", "Sarah Stein"),
    89871: ("wjj", "William Jordan"),
    89874: ("dsphilli", "Dean Phillips"),
    90506: ("abaker", "Anne Baker"),
    90509: ("agardner", "Angela Davis-Gardner"),
    90831: ("baines", "Barbara Baines"),
    90832: ("bateman", "Robert Bateman"),
    90833: ("bcpittma", "Beryl Pittman"),
    90847: ("charlott", "Charlotte Gross"),
    90853: ("covingto", "David Covington"),
    90857: ("daorgero", "Devin Orgeron"),
    90859: ("djreavis", "Dick Reavis"),
    90861: ("dllaux", "Dorianne Laux"),
    90868: ("engahh", "Antony Harrison"),
    90871: ("gaitens", "Judi Gaitens"),
    90874: ("gomez", "Joseph Gomez"),
    90883: ("jbalaba", "John Balaban"),
    90886: ("jferster", "Judith Ferster"),
    90895: ("jont", "Jon Thompson"),
    90896: ("josmall", "Judy Small"),
    90910: ("leila", "Leila May"),
    90913: ("lsmith", "Lee Smith"),
    90915: ("macketha", "Lucinda MacKethan"),
    90918: ("mfking", "Margaret King"),
    90923: ("mhthuent", "Mary Thuente"),
    90924: ("mhunt", "Marvin Hunt"),
    90928: ("morillo", "John Morillo"),
    90932: ("pacolby", "Paul Colby"),
    90938: ("prioli", "Carmine Prioli"),
    90942: ("rckeg", "Robert Kochersberger"),
    90949: ("sdicks", "Stan Dicks"),
    90957: ("smoot", "Jeanne Smoot"),
    90958: ("ssetzer", "Sharon Setzer"),
    90959: ("stein", "Allen Stein"),
    90960: ("tenshi", "John Kessel"),
    90966: ("west", "Harry West"),
    90968: ("wjramm", "Wanda Ramm"),
    90984: ("achekhov", "Vladimir Bilenkin"),
    90997: ("dsbeckma", "Diane Beckman"),
    91001: ("etai", "Eika Tai"),
    91002: ("fljpm", "John Mertz"),
    91005: ("glmathew", "Gary Mathews"),
    91010: ("istern", "Irwin Stern"),
    91020: ("jshaesel", "Jillian Haeseler"),
    91024: ("kent", "E Lioret"),
    91029: ("lamfll", "Larysa Mykyta"),
    91036: ("mbell", "Martine Bell"),
    91042: ("mmmagill", "Michele Magill"),
    91045: ("msdarrah", "Michele Darrah"),
    91062: ("tkhovers", "Turi Hoversten"),
    91064: ("tpbrody", "Toby Brody"),
    91067: ("wittma", "Mary Witt"),
    91069: ("yrollins", "Yvonne Rollins"),
    91161: ("ajdhi", "Alexander De Grand"),
    91162: ("ajlavopa", "Anthony LaVopa"),
    91164: ("banker", "James Banker"),
    91180: ("edsssl", "Edith Sylla"),
    91249: ("slspenc2", "Stephanie Spencer"),
    91265: ("wcharri2", "William Harris"),
    91339: ("dvphi", "A. Donald VandeVeer"),
    91349: ("levin", "Hal Levin"),
    91354: ("mjpendle", "Michael Pendlebury"),
    91356: ("n51ls801", "David Austin"),
    91388: ("djgillan", "Doug Gillan"),
    91390: ("dogray", "Denis Gray"),
    91392: ("dwmartin", "David Martin"),
    91396: ("erchul", "William Erchul"),
    91398: ("halbers", "Amy Halberstadt"),
    91404: ("jjmichae", "Joan Michael"),
    91409: ("jwkalat", "James Kalat"),
    91411: ("kklein", "Kitty Klein"),
    91414: ("lbward", "Lynne Baker-Ward"),
    91417: ("mark-wilson", "Mark Wilson"),
    91425: ("remitche", "Roger Mitchell"),
    91431: ("schulte", "Ann Schulte"),
    91434: ("tmhess", "Thomas Hess"),
    91438: ("wogalter", "Michael Wogalter"),
    91490: ("jgilbert", "John Gilbert"),
    91516: ("soroos", "Marvin Soroos"),
    91589: ("acdavis", "Adam Davis"),
    91594: ("atkinson", "Maxine Atkinson"),
    91598: ("clifford", "William Clifford"),
    91606: ("duckpond", "Michael Schwalbe"),
    91627: ("mazahn", "Margaret Zahn"),
    91656: ("ted", "Theodore Greenstein"),
    91663: ("tlparcel", "Toby Parcel"),
    91667: ("twallace", "Tim Wallace"),
    91669: ("vmaldige", "Virginia Aldige"),
    91670: ("wrs", "William Smith"),
    91698: ("wewormsl", "William Wormsley"),
    96395: ("jherkert", "Joseph Herkert"),
}


def _retirement_group_only(person: dict) -> bool:
    groups = set(person.get("group") or [])
    return FACULTY_TERM in groups and bool(groups & RETIRED_TERMS) and groups <= RETIRED_TERMS | {FACULTY_TERM}


def _reviewed_candidate(person: dict) -> bool:
    identity = REVIEWED_PROFILES.get(person.get("id"))
    if not identity:
        return False
    slug, _ = identity
    return person.get("link") == f"https://chass.ncsu.edu/people/{slug}/"


def current_faculty(records: list[dict]) -> list[dict]:
    if not any(isinstance(person, dict) and _reviewed_candidate(person) for person in records):
        return records

    roster = ucb_common.fetch_soup(FACULTY_URL, bounded=True)
    cards = defaultdict(list)
    if roster is not None:
        for card in roster.select(".person-card"):
            name = card.select_one("a.name[href]")
            title = card.select_one("p.title")
            if name is not None and title is not None:
                cards[name["href"]].append((" ".join(name.stripped_strings), " ".join(title.stripped_strings)))

    reported = {person.get("link") for person in records if isinstance(person, dict)}
    missing = cards.keys() - reported
    if missing:
        faculty_graph._cover("partial_render_rows", len(missing))

    current = []
    for person in records:
        faculty_graph._cover("raw_roster_rows")
        if not isinstance(person, dict):
            faculty_graph._cover("unparsed_rows")
            continue
        if _reviewed_candidate(person):
            matched = cards.get(person.get("link"), [])
            if len(matched) != 1 or not matched[0][1]:
                # An unreadable card cannot reopen an archived contact or
                # authorize this unit to retire somebody on absence.
                faculty_graph._cover("unparsed_rows")
                continue
            card_name, rank = matched[0]
            wp_title = person.get("title")
            if isinstance(wp_title, dict):
                wp_title = wp_title.get("rendered")
            source_name = faculty_graph._wp_text(wp_title or "")
            reviewed_name = REVIEWED_PROFILES[person["id"]][1]
            names = {" ".join(n.split()).casefold() for n in (card_name, source_name, reviewed_name)}
            if len(names) != 1:
                faculty_graph._cover("ambiguous_rows")
                continue
            if _retirement_group_only(person) and rank in RETIRED_TITLES:
                faculty_graph._cover("classified_nonfaculty_rows")
                continue
            # The Faculty label alone already included these retirees. A new
            # faculty appointment needs a current role or a second faculty unit.
            current_group = CURRENT_FACULTY_TERMS.intersection(person.get("group") or [])
            current_rank = (re.search(r"\b(?:Professor|Lecturer|Instructor)\b", rank, re.I)
                            and not re.search(r"emerit|retir|former|memoriam", rank, re.I))
            if not current_group and not current_rank:
                faculty_graph._cover("ambiguous_rows")
                continue
        faculty_graph._cover("parsed_faculty_rows")
        current.append(person)
    return current
