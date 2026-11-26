"""Research on a named faculty homepage explicitly linked by BU's provost."""
import re

PERSON = "Camilla Schneier"
CAMPUS_PROFILE = "https://www.bu.edu/questrom/profiles/camilla-schneier/"
HOME = "https://camillaschneier.github.io/"
APPOINTMENTS = (
    "https://www.bu.edu/provost/academic-process-policies/faculty-actions/"
    "approved-faculty-appointments-and-promotions-december-2025-april-2026/"
    "approved-faculty-appointments-and-promotions-december-2024-april-2025/"
)


def is_reviewed_home(record: dict, campus_url: str, research_url: str) -> bool:
    return (record.get("id") == "faculty-bu-qst-3cc6c010" and record.get("school") == "bu"
            and record.get("source") == "bu_faculty" and record.get("pi_name") == PERSON
            and record.get("department") == "Questrom School of Business"
            and record.get("source_type") == "faculty_research"
            and record.get("url") == CAMPUS_PROFILE and record.get("source_url") == CAMPUS_PROFILE
            and campus_url == CAMPUS_PROFILE and research_url == HOME)


def read_research(specs: list[dict]) -> None:
    from .ucb_common import fetch_soup

    people = [p for p in specs if p.get("name") == PERSON and p.get("url") == CAMPUS_PROFILE]
    if len(people) != 1 or people[0].get("research_areas"):
        return
    person = people[0]
    roster = fetch_soup(APPOINTMENTS)
    if roster is None or getattr(roster, "_ofe_final_url", None) != APPOINTMENTS:
        return
    # Distinguish the actual appointments list from another page or a challenge.
    section = None
    for school in roster.select("h4.bu_collapsible"):
        heading = school.find_previous("h2")
        if (school.get_text(" ", strip=True) == "Questrom School of Business" and heading
                and heading.get_text(" ", strip=True).startswith("Charles River Campus Appointments,")):
            section = school.find_next_sibling("div", class_="bu_collapsible_section")
            break
    if section is None or not section.select_one("li a[href]"):
        return
    links = [a for a in section.select("li a[href]") if a.get_text(" ", strip=True) == PERSON]
    if len(links) != 1 or links[0]["href"] != HOME:
        person["_checked_research_index"] = HOME
        return
    page = fetch_soup(HOME)
    if page is None or getattr(page, "_ofe_final_url", None) != HOME:
        return
    heading = page.find("h1")
    observed = getattr(page, "_ofe_observed_at", None)
    if heading is None or not observed:
        return
    person["_checked_research_index"] = HOME
    if heading.get_text(" ", strip=True) != PERSON:
        return
    for paragraph in page.select("p"):
        intro = " ".join(paragraph.get_text(" ", strip=True).split())
        if "at Boston University." not in intro:
            continue
        area = re.search(r"\bMy research is in ([^.;!?]{2,180})\.", intro)
        if area:
            person["research_areas"] = area.group(1) + "."
            person["_research_areas_source_url"] = HOME
            person["_research_areas_observed_at"] = observed
            return
