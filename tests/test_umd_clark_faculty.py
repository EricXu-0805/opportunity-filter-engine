from datetime import UTC, datetime

from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.umd_faculty import SCHOOL


def test_clark_reads_the_underlying_appointment_only_after_a_leadership_title():
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "BIOE")
    cfg = dept["scrape"]

    def card(name, *titles, email=None):
        heading = "".join(f"<h3>{title}</h3>" for title in titles)
        contact = f'<a href="mailto:{email}">{email}</a>' if email else ""
        return (
            f'<div class="faculty_row"><div class="field-directory-name-title-wrapper">'
            f'<a href="/clark/faculty/{name}">{name}, Ada</a></div><div class="title-wrapper">{heading}</div>'
            f'<div class="contact-wrapper">{contact}</div></div>'
        )

    html = "".join((
        card("Roe", "Interim Department Chair", "Professor", email="roe@umd.edu"),
        card("Lee", "Director of a Research Center", "Faculty Fellow", "Associate Professor"),
        card("Ngo", "Professor and Department Chair", "Visiting professor at another university"),
        card("Vale", "Director", "Affiliate Faculty", "Professor of an external university"),
        card("Wu", "Laboratory Director", "Associate Professor Emeritus"),
        card("Park", "Adjunct Professor", "Professor at another university"),
        card("Reed", "Post-Doc", "Lecturer"),
        card("Frost", "Dean", "Department administrator"),
        card("Fox", "Laboratory Director", "Postdoctoral Associate", "Professor in a prior job"),
        card("Quinn", "Postdoctoral Researcher and Lab Director", "Professor in a prior job"),
    ))
    soup = BeautifulSoup(html, "html.parser")
    soup._ofe_requested_url = cfg["url"] + "&page=2"
    soup._ofe_final_url = soup._ofe_requested_url
    soup._ofe_observed_at = datetime.now(UTC).isoformat()
    rows = faculty_graph._parse_cards(soup, cfg["selectors"], cfg["url"], ladder_filter=cfg["ladder_filter"],
                                      name_flip=True, contact_page_url=soup._ofe_requested_url)
    assert {p["name"]: p["title"] for p in rows} == {
        "Ada Roe": "Professor", "Ada Lee": "Associate Professor", "Ada Ngo": "Professor and Department Chair",
    }
    assert {p["name"]: p.get("email") for p in rows} == {"Ada Roe": "roe@umd.edu", "Ada Lee": None, "Ada Ngo": None}
    assert rows[0]["_contact_claim"]["metadata"]["contact_source_url"] == soup._ofe_final_url
