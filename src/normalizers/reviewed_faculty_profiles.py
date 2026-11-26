"""Apply identity-checked corrections to older individual faculty profiles."""
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.contact_instructions import contact_instruction_pages, same_source_page
from src.evidence import DEPARTMENT_FIELD_METHOD, inferred_method, is_retired_title, stamp_inferred

from .deactivate_stale_faculty import (
    deactivate_deceased_faculty,
    deactivate_retired_title_faculty,
    deactivate_trainee_faculty,
)


@dataclass(frozen=True)
class ProfileReview:
    school: str
    department: str
    name: str
    previous_url: str
    profile_url: str
    roster_url: str
    reviewed_at: datetime
    title: str | None = None
    previous_title: str | None = None
    previous_department_label: str | None = None
    previous_is_directory: bool = False
    previous_name: str | None = None
    outside_unit_ladder: bool = False
    other_verified_names: tuple[str, ...] = ()
    appointment_summary: str | None = None
    independently_verified_profile: bool = False
    secondary_record_id: str | None = None
    staff_directory_reference: bool = False
    staff_title_zh: str | None = None

    @property
    def reviewed_on(self) -> date:
        return self.reviewed_at.date()


# The source runner finished reading the six identity-checked destinations at 12:01:59 UTC.
_OUTSIDE_UNIT_LADDER = "outside_unit_ladder"
_NOV_25 = datetime(2026, 11, 25, 12, 2, tzinfo=UTC)
_SBU_CS = "https://www.cs.stonybrook.edu/people/index.html"
_SBU_GEO = "https://www.stonybrook.edu/geosciences/people/faculty.html"
_SBU_GEO_REVIEW = datetime(2026, 11, 25, 17, 19, tzinfo=UTC)


def _vt_che(name: str, profile_path: str, title: str) -> ProfileReview:
    # The roster card links to the person but omits rank outside enrichment runs.
    # Only that exact, unranked row can inherit the title on the reviewed profile.
    profile = f"https://che.vt.edu/People/{profile_path}"
    return ProfileReview(
        "vt", "Department of Chemical Engineering", name, profile, profile, profile,
        datetime(2026, 11, 26, 8, 42, tzinfo=UTC),
        title=title, previous_title="",
    )


def _umd_math_directory_profile(name: str, profile: str) -> ProfileReview:
    return ProfileReview(
        "umd", "Department of Mathematics", name, "https://www-math.umd.edu/people/faculty.html",
        f"https://www-math.umd.edu/signage-directory-faculty/{profile}.html",
        "https://www-math.umd.edu/signage-directory-faculty.html",
        datetime(2026, 11, 26, 12, 51, tzinfo=UTC), previous_is_directory=True,
    )


def _gatech_arch_emeritus(name: str, slug: str, previous_title: str, title: str) -> ProfileReview:
    profile = f"https://arch.gatech.edu/people/{slug}"
    return ProfileReview(
        "gatech", "School of Architecture", name, profile, profile, "https://arch.gatech.edu/people",
        datetime(2026, 11, 26, 15, 37, tzinfo=UTC), title=title, previous_title=previous_title,
    )


_MSU_WALTON = "https://directory.natsci.msu.edu/directory/Profiles/Person/104350"
_MSU_WILSON = "https://directory.natsci.msu.edu/directory/Profiles/Person/103481"
_MSU_MGI_DIRECTORY = "https://directory.natsci.msu.edu/Directory/Directory/Department/26"

def _ucsd_nano(name: str, previous_name: str, jacobs_id: int) -> ProfileReview:
    return ProfileReview(
        "ucsd", "Department of NanoEngineering", name,
        f"http://jacobsschool.ucsd.edu/faculty/faculty_bios/index.sfe?fmp_recid={jacobs_id}",
        f"https://jacobsschool.ucsd.edu/faculty/profile?id={jacobs_id}",
        "https://nanoengineering.ucsd.edu/fac/nanoe-faculty", datetime(2026, 11, 26, 17, 12, tzinfo=UTC),
        title="Professor Emeritus", previous_title="", previous_name=previous_name,
    )


def _ucsd_nano_adjunct(name: str, old_url: str, jacobs_id: int, *, previous_name: str | None = None) -> ProfileReview:
    return ProfileReview(
        "ucsd", "Department of NanoEngineering", name, old_url,
        f"https://jacobsschool.ucsd.edu/faculty/profile?id={jacobs_id}",
        "https://www.nanoengineering.ucsd.edu/index.php/fac", datetime(2026, 11, 26, 17, 35, tzinfo=UTC),
        title="Adjunct Professor", previous_title="", previous_name=previous_name, outside_unit_ladder=True,
    )


REVIEWS = {
    # The department still labels this card "Professor". His March 2026 CV
    # names Mechanical Engineering among his emeritus appointments from 2024.
    "faculty-udel-me-4b7217c7": ProfileReview(
        "udel", "Department of Mechanical Engineering", "John Gillespie Jr.",
        "https://me.udel.edu/faculty/john-w-gillespie-jr/",
        "https://me.udel.edu/faculty/john-w-gillespie-jr/",
        "https://me.udel.edu/wp-content/uploads/2022/07/3-5-2026_Current-JWG-CV.pdf",
        datetime(2026, 11, 26, 21, 35, tzinfo=UTC),
        title="Professor Emeritus", previous_title="Professor",
        appointment_summary="John Gillespie Jr. is a professor emeritus of mechanical engineering at the University of Delaware."),
    # Keep the former school's own named appointment as historical provenance.
    # The ordinary directory pass owns whether this old Georgia Tech ID is active.
    "faculty-gatech-arch-3a9c2373": ProfileReview(
        "gatech", "School of Architecture", "Elisa Dainese", "https://arch.gatech.edu/people/elisa-dainese",
        "https://arch.gatech.edu/feature/news-elisa-dainese-appointed-assistant-professor",
        "https://arch.gatech.edu/people", datetime(2026, 11, 26, 15, 41, tzinfo=UTC),
        previous_title="Assistant Professor"),
    "faculty-gatech-arch-e98bc4d9": _gatech_arch_emeritus(
        "Ellen Dunham-Jones", "ellen-dunham-jones", "Professor; Director, MS in Urban Design Program",
        "Professor Emeritus"),
    "faculty-gatech-arch-196687bf": _gatech_arch_emeritus(
        "W. Jude LeBlanc", "w-jude-leblanc", "Associate Professor", "Associate Professor Emeritus"),
    "faculty-gatech-itm-21b8dd50": ProfileReview(
        "gatech", "Information Technology Management (Scheller College of Business)", "Han Zhang",
        "https://www.scheller.gatech.edu/directory/faculty/zhang/index.html",
        "https://www.scheller.gatech.edu/directory/emeritus/zhang/index.html",
        "https://www.scheller.gatech.edu/directory/index.json", datetime(2026, 11, 26, 15, 26, tzinfo=UTC),
        title="Professor Emeritus", previous_title="Steven A. Denning Professor in Technology & Management"),
    "faculty-msu-mgi-6af109e0": ProfileReview(
        "msu", "Department of Microbiology, Genetics and Immunology", "Debbie Walton",
        _MSU_MGI_DIRECTORY, _MSU_WALTON, _MSU_WALTON, datetime(2026, 11, 26, 20, 42, tzinfo=UTC),
        title="Executive Assistant to the Chair and Communications Manager",
        previous_title="Executive Assistant to the Chair", previous_is_directory=True,
        outside_unit_ladder=True, staff_directory_reference=True, staff_title_zh="系主任行政助理兼传播事务经理",
        appointment_summary="Michigan State lists Debbie Walton as Executive Assistant to the Chair and "
                            "Communications Manager for the Department of Microbiology, Genetics and Immunology.",
    ),
    "faculty-msu-bmb-350c8c60": ProfileReview(
        "msu", "Department of Biochemistry and Molecular Biology", "John E. Wilson",
        "https://directory.natsci.msu.edu/Directory/Directory/Department/6", _MSU_WILSON,
        "https://bmb.natsci.msu.edu/_assets/files/alumni-and-friends/bmbmag04.pdf",
        datetime(2026, 11, 26, 20, 43, tzinfo=UTC), title="Professor Emeritus",
        previous_title="Barnett Rosenberg Chair", previous_is_directory=True,
        appointment_summary="Michigan State lists John E. Wilson as Professor Emeritus in Biochemistry "
                            "and Molecular Biology.",
    ),
    "faculty-msu-mgi-5ca9b09b": ProfileReview(
        "msu", "Department of Microbiology, Genetics and Immunology", "Kathleen A Hoag",
        _MSU_MGI_DIRECTORY, _MSU_MGI_DIRECTORY,
        "https://bld.natsci.msu.edu/news/dr-kathy-hoag-retires-after-25-years-at-the-BLD-Program.aspx",
        datetime(2026, 11, 26, 15, 48, tzinfo=UTC),
        title="Professor Emeritum", previous_title="Professor"),
    "faculty-ucsd-nano-2aa92754": _ucsd_nano_adjunct("Darren Lipomi", "https://www.lipomigroup.org/", 345),
    "faculty-ucsd-nano-04ac1d79": _ucsd_nano_adjunct("Ying Shirley Meng", "http://smeng.ucsd.edu/", 284,
                                                    previous_name="Shirley Meng"),
    "faculty-ucsd-nano-27240933": _ucsd_nano_adjunct("Sheng Xu", "http://xugroup.eng.ucsd.edu/", 387),
    "faculty-ucsd-nano-25a6d469": _ucsd_nano("Sadik Esener", "Esener", 31),
    "faculty-ucsd-nano-dc9e3de3": _ucsd_nano("Michael Heller", "Mike Heller", 1),
    "faculty-pitt-cs-0a7196f1": ProfileReview(
        "pitt", "Department of Computer Science", "Erin Walker",
        "https://www.cs.pitt.edu/people/full-time-faculty/erin-walker",
        "https://www.sci.pitt.edu/people/erin-walker",
        "https://www.sci.pitt.edu/sites/default/files/inline-images/PDFs/SCI_2025_Research_Report-compressed.pdf#page=15",
        datetime(2026, 11, 26, 20, 30, tzinfo=UTC),
        title="Associate Dean for Research, Professor, Department of Computer Science, Intelligent Systems Program, "
              "Research Scientist, Learning Research & Development Center",
        previous_title="Associate Professor; Research Scientist, LRDC; Associate Dean for Research, SCI",
        appointment_summary="Erin Walker is a Professor in the Department of Computer Science and Associate Dean "
                            "for Research in Pitt’s School of Computing and Information."),
    "faculty-pitt-ling-14fc90c7": ProfileReview(
        "pitt", "Department of Linguistics", "Charles Perfetti",
        "http://www.pitt.edu/~perfetti/charles-perfetti.htm",
        "https://www.psychology.pitt.edu/people/charles-perfetti-phd",
        "https://lrdc.pitt.edu/departments-and-services/communications-news-media/"
        "enduring-legacy-distinguished-university-professor-and-former-lrdc-director-charles-perfetti-retire",
        datetime(2026, 11, 26, 19, 12, tzinfo=UTC),
        title="Retired Distinguished University Professor of Psychology",
        previous_title="Professor of psychology and linguistics", independently_verified_profile=True,
        appointment_summary="Pitt reports that Charles Perfetti retired from the university on January 31, 2026."),
    "faculty-pitt-ling-00bb851a": ProfileReview(
        "pitt", "Department of Linguistics", "Natasha Tokowicz",
        "https://psychology.pitt.edu/people/natasha-tokowicz-phd",
        "https://psychology.pitt.edu/people/natasha-tokowicz-phd",
        "https://www.provost.pitt.edu/people/natasha-tokowicz",
        datetime(2026, 11, 26, 19, 12, tzinfo=UTC),
        title="Professor of Psychology and Linguistics", previous_title="Associate Professor, Department of Psychology",
        independently_verified_profile=True,
        appointment_summary="Natasha Tokowicz is a professor of psychology and linguistics at Pitt."),
    "faculty-pitt-ling-b87b919a": ProfileReview(
        "pitt", "Department of Linguistics", "Lori Levin",
        "https://www.cmu.edu/dietrich/linguistics/faculty/lori-levin.html",
        "https://www.lti.cmu.edu/people/faculty/levin-lori.html",
        "https://www.lti.cmu.edu/people/faculty/levin-lori.html",
        datetime(2026, 11, 26, 19, 8, tzinfo=UTC),
        title="Affiliated faculty in Linguistics (Pitt) · Research Professor (Carnegie Mellon)",
        previous_title="Associate Professor, Carnegie Mellon",
        independently_verified_profile=True, appointment_summary="Pitt lists Lori Levin as affiliated faculty in Linguistics. "
                            "Levin is a research professor in Carnegie Mellon's Language Technologies Institute."),
    "faculty-pitt-ling-84c5021c": ProfileReview(
        "pitt", "Department of Linguistics", "Mandy Simons",
        "https://www.cmu.edu/dietrich/linguistics/faculty/mandy-simons.html",
        "https://www.cmu.edu/dietrich/philosophy/people/faculty/simons.html",
        "https://www.cmu.edu/dietrich/philosophy/people/faculty/simons.html",
        datetime(2026, 11, 26, 19, 8, tzinfo=UTC),
        title="Adjunct in Linguistics (Pitt) · Professor of Philosophy (Carnegie Mellon)",
        previous_title="Professor of philosophy, Carnegie Mellon",
        independently_verified_profile=True, appointment_summary="Mandy Simons is a professor of philosophy at Carnegie Mellon "
                            "with an adjunct appointment in Linguistics at Pitt."),
    "faculty-pitt-ling-e0bda033": ProfileReview(
        "pitt", "Department of Linguistics", "Kate Stanton",
        "https://www.philosophy.pitt.edu/person/kate-stanton",
        "https://philosophy.pitt.edu/people/kstanton", "https://philosophy.pitt.edu/people/kstanton",
        datetime(2026, 11, 26, 19, 8, tzinfo=UTC),
        title="Associate Professor of Philosophy · Secondary appointment in Linguistics",
        previous_title="Assistant Professor, Philosophy &",
        independently_verified_profile=True, appointment_summary="Kate Stanton is an associate professor of philosophy at Pitt "
                            "with a secondary appointment in Linguistics."),
    "faculty-pitt-ling-0dbe04f3": ProfileReview(
        "pitt", "Department of Linguistics", "Amanda Godley",
        "https://www.education.pitt.edu/people/profile.aspx?f=amandagodley%20",
        "https://www.education.pitt.edu/faculty/directory/amanda-godley/",
        "https://www.education.pitt.edu/wp-content/uploads/2023/06/Amanda-Godley-CV.pdf",
        datetime(2026, 11, 26, 19, 40, tzinfo=UTC),
        title="Professor of Teaching, Learning and Leading · Secondary appointment in Linguistics",
        previous_title="Associate Professor, English Education and", independently_verified_profile=True,
        appointment_summary="Pitt lists Amanda Godley as a professor in the School of Education "
                            "with a secondary appointment in Linguistics."),
    "faculty-pitt-ling-84276229": ProfileReview(
        "pitt", "Department of Linguistics", "Richard Donato",
        "https://www.education.pitt.edu/people/profile.aspx?f=RichardDonato%20",
        "https://www.iise.pitt.edu/people/richard-donato", "https://www.app.education.pitt.edu/people/faculty",
        datetime(2026, 11, 26, 19, 40, tzinfo=UTC), title="Emeritus Faculty, School of Education",
        previous_title="Professor of foreign language education,", independently_verified_profile=True,
        appointment_summary="Pitt's School of Education identifies Richard Donato as emeritus faculty."),
    "faculty-pitt-phil-2930bf5f": ProfileReview(
        "pitt", "Department of Philosophy", "Kate Stanton", "https://www.philosophy.pitt.edu/people",
        "https://www.philosophy.pitt.edu/people/kstanton", "https://www.philosophy.pitt.edu/people/kstanton",
        datetime(2026, 11, 26, 19, 24, tzinfo=UTC),
        title="Associate Professor of Philosophy and Admissions Director (Spring 2027) · Secondary appointment in Linguistics",
        previous_title="Associate Professor of Philosophy and Admissions Director (Spring 2027)",
        previous_is_directory=True, independently_verified_profile=True, secondary_record_id="faculty-pitt-ling-e0bda033"),
    "faculty-duke-nurs-36cb4f9e": ProfileReview(
        "duke", "School of Nursing", "Lisa S. Lewis", "https://scholars.duke.edu/person/lisa.lewis",
        "https://dukeahead.duke.edu/profile/lisa-lewis",
        "https://nursing.duke.edu/sites/default/files/documents/Duke%20Nursing%20Magazine%20Fall-Winter%202026.pdf#page=21",
        datetime(2026, 11, 26, 19, 8, tzinfo=UTC),
        title="Retired Associate Clinical Professor", previous_title="Associate Professor",
        independently_verified_profile=True, appointment_summary="Duke's School of Nursing lists Lisa S. Lewis among its retiring faculty in 2026."),
    "faculty-vt-che-be391032": _vt_che("Donald Baird",
        "faculty/Baird.html", "Professor Emeritus"),
    "faculty-vt-che-762a80d6": _vt_che("David Cox",
        "faculty/Cox.html", "Professor Emeritus"),
    "faculty-vt-che-8d99f667": _vt_che("Ted Oyama",
        "faculty/Oyama.html", "Professor Emeritus"),
    "faculty-vt-che-23e0354e": _vt_che("Gary Whiting",
        "faculty/Whiting.html", "Joseph H. Collie Professor Emeritus"),
    "faculty-vt-che-2b84e643": _vt_che("Qiang Gao",
        "postdoctoral-researchers/qiang-gao.html", "Postdoctoral researchers"),
    "faculty-vt-che-b0225752": _vt_che("Fangxi Wang",
        "postdoctoral-researchers/fangxi-wang.html", "Postdoctoral researcher"),
    "faculty-vt-che-e1d3b3cb": ProfileReview(
        "vt", "Department of Chemical Engineering", "Julia Ross",
        "https://che.vt.edu/People/faculty/Ross.html",
        "https://www.provost.vt.edu/who_we_are/julie-ross-bio.html",
        "https://che.vt.edu/People/faculty.html",
        datetime(2026, 11, 26, 16, 15, 3, tzinfo=UTC)),
    "faculty-utexas-neuro-ed6d4734": ProfileReview(
        "utexas", "Department of Neuroscience", "Harold Zakon",
        "https://neuroscience.utexas.edu/directory/harold-zakon",
        "https://research.utexas.edu/profiles/harold-zakon",
        "https://catalog.utexas.edu/graduate/gsc-committees/",
        datetime(2026, 11, 25, 21, 35, 18, tzinfo=UTC), previous_department_label="Neuroscience"),
    "faculty-sbu-geo-07129e92": ProfileReview(
        "sbu", "Department of Geosciences", "Gilbert Hanson",
        "https://www.stonybrook.edu/commcms/geosciences/people/_faculty/hanson.php",
        "https://www.stonybrook.edu/geosciences/about/long-island-geologists/gilbert-hanson.html",
        _SBU_GEO, _SBU_GEO_REVIEW, "In Memoriam — Distinguished Professor Emeritus"),
    "faculty-sbu-geo-d49b7576": ProfileReview(
        "sbu", "Department of Geosciences", "Scott McLennan",
        "https://www.stonybrook.edu/commcms/geosciences/people/_faculty/mclennan.php",
        "https://www.stonybrook.edu/geosciences/people/faculty_profiles/scott-mclennan.html",
        _SBU_GEO, _SBU_GEO_REVIEW, "Distinguished Professor Emeritus"),
    "faculty-osu-fabe-1abc04a0": ProfileReview(
        "osu", "Department of Food, Agricultural and Biological Engineering", "S. Dee Jepsen",
        "https://fabe.osu.edu/our-people/s-dee-jepsen", "https://agsafety.osu.edu/people/dee-jepsen-phd",
        "https://agsafety.osu.edu/people", _NOV_25),
    "faculty-sbu-cs-7c922688": ProfileReview(
        "sbu", "Department of Computer Science", "Paola Cascante-Bonilla",
        "https://www.cs.stonybrook.edu/people/faculty/paolacascante-bonilla",
        "https://researchconnect.stonybrook.edu/en/persons/paola-cascante-bonilla/",
        _SBU_CS, _NOV_25),
    "faculty-sbu-cs-890dcd54": ProfileReview(
        "sbu", "Department of Computer Science", "Ting Wang", "https://www.cs.stonybrook.edu/people/faculty/tingwang",
        "https://alps-lab.github.io/", _SBU_CS, _NOV_25),
    "faculty-tamu-ece-d96cfd82": ProfileReview(
        "tamu", "Department of Electrical and Computer Engineering", "Serap Savari",
        "https://engineering.tamu.edu/electrical/profiles/ssavari.html",
        "https://catalog.tamu.edu/graduate/colleges-schools-interdisciplinary/engineering/electrical-computer/"
        "#faculty:~:text=Savari%2C%20Serap%20A%2C%20Associate%20Professor",
        "https://catalog.tamu.edu/graduate/colleges-schools-interdisciplinary/engineering/electrical-computer/#faculty",
        datetime(2026, 11, 26, 17, 42, tzinfo=UTC)),
    "faculty-tamu-inta-c32e8252": ProfileReview(
        "tamu", "Department of International Affairs", "John Schuessler", "https://bush.tamu.edu/faculty/jschuessler",
        "https://bush.tamu.edu/directory/john-schuessler/",
        "https://bush.tamu.edu/directory/john-schuessler/", _NOV_25),
    "faculty-ucf-cs-edfc1c62": ProfileReview(
        "ucf", "Department of Computer Science", "Ali Al Kinoon",
        "http://www.cs.ucf.edu/person/alialkinoon/", "https://www.cecs.ucf.edu/faculty/alialkinoon/",
        "https://www.cecs.ucf.edu/faculty/alialkinoon/", datetime(2026, 11, 26, 18, 23, tzinfo=UTC),
        other_verified_names=("Ali Alkinoon",)),
    "faculty-umd-math-0f940cb3": _umd_math_directory_profile("Uri Bader", "2138-bader-uri"),
    "faculty-umd-math-36800e3a": _umd_math_directory_profile("Henri Berestycki", "2050-berestycki-henri"),
    "faculty-umd-math-dcee82bf": _umd_math_directory_profile("Giovanni Forni", "1261-gforni"),
    "faculty-umd-math-90a4b94e": _umd_math_directory_profile("David H. Hamilton", "1285-dhh"),
    "faculty-umd-math-9eb3e2a4": _umd_math_directory_profile("Or Hershkovits", "2175-hershkovits-or"),
    "faculty-umd-math-93280e3c": _umd_math_directory_profile("Bogdan Zavyalov", "2172-zavyalov"),
    "faculty-umd-math-0300a4bb": ProfileReview(
        "umd", "Department of Mathematics", "James A. Yorke", "http://yorke.umd.edu/",
        "https://ipst.umd.edu/people/james-a-yorke", "https://www-math.umd.edu/people/faculty.html",
        datetime(2026, 11, 26, 12, 46, tzinfo=UTC)),
    "faculty-umd-math-1516d149": ProfileReview(
        "umd", "Department of Mathematics", "Shiferaw Berhanu", "https://www-math.umd.edu/people/faculty/item/1694-sberhanu.html",
        "https://www-math.umd.edu/signage-directory-faculty/2025-sberhanu.html",
        "https://www-math.umd.edu/people/faculty.html", _NOV_25),
    # The individual directory lists Faculty Type "Emeriti"; the department
    # spells out "Professor Emerita in History". Keep her research appointment.
    "faculty-ucsc-hist-d64a8110": ProfileReview(
        "ucsc", "Department of History", "Gail B Hershatter",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=gbhers",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=gbhers",
        "https://directory.ucsc.edu/cd_detail?guid=G001719517",
        datetime(2026, 11, 25, 17, 40, tzinfo=UTC),
        title="Research Professor and Distinguished Professor of History Emerita",
        previous_title="Research Professor and Distinguished Professor of History Emer."),
    "faculty-ucsc-envs-c7e85a3f": ProfileReview(
        "ucsc", "Department of Environmental Studies", "Gregory S Gilbert",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=ggilbert",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=ggilbert",
        "https://envs.ucsc.edu/people/faculty/",
        datetime(2026, 11, 25, 19, 8, tzinfo=UTC),
        title="Distinguished Professor Emeritus; Director of UCSC Forest Ecology Research Plot",
        previous_title="Distinguished Professor"),
    "faculty-ucsc-lit-f8043691": ProfileReview(
        "ucsc", "Department of Literature", "Jody Greene",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=jgreene",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=jgreene",
        "https://campusdirectory.ucsc.edu/cd_detail?uid=jgreene",
        datetime(2026, 11, 25, 18, 2, tzinfo=UTC),
        title="Professor Emeritx of Literature; Founding Director, Teaching and Learning Center",
        previous_title="Professor of Literature"),
    "faculty-umd-phys-5e8e0edd": ProfileReview(
        "umd", "Department of Physics", "Elizabeth Beise", "https://umdphysics.umd.edu/people/faculty/current/item/43-beise.html",
        "https://umdphysics.umd.edu/directory/faculty/emeritus/beise.html",
        "https://umdphysics.umd.edu/people/faculty/emeritus.html", _NOV_25, "Professor Emerita"),
}


def _old_page_restored(row: dict, review: ProfileReview) -> bool:
    """A later successful read of this person's exact old URL can restore the link."""
    # A department roster may continue to verify contact details for a person.
    # Its successful read cannot make it their individual profile.
    if review.previous_is_directory:
        return False
    pages = contact_instruction_pages(row)
    # Older shards may have padding only on the stored address while the fetch
    # recorded the clean URL. Recheck the existing identity-bound receipt on
    # that address; never rewrite the historical fetch observation.
    if not pages and row["url"] != row["url"].strip(" \t\r\n\f"):
        clean_row = dict(row, url=row["url"].strip(" \t\r\n\f"))
        if row.get("source_url") == row["url"]:
            clean_row["source_url"] = clean_row["url"]
        pages = contact_instruction_pages(clean_row)
    for page in pages:
        receipt = page.get("receipt") or {}
        if (receipt.get("status") in {"captured", "empty"}
                and same_source_page(page["requested_source_url"].strip(" \t\r\n\f"), review.previous_url)
                and same_source_page(receipt["source_url"].strip(" \t\r\n\f"), review.previous_url)
                and datetime.fromisoformat(receipt["attempted_at"]) > review.reviewed_at):
            return True
    return False


def _matches_review(row: dict, review: ProfileReview, *, also_urls: tuple[str, ...] = ()) -> bool:
    return (
        row.get("school") == review.school and row.get("department") == review.department
        and row.get("source") == f"{review.school}_faculty" and row.get("source_type") == "faculty_research"
        and (row.get("pi_name") in (review.name, *review.other_verified_names)
             or (review.previous_name is not None and row.get("pi_name") == review.previous_name))
        and isinstance(row.get("url"), str) and row["url"].strip(" \t\r\n\f") in (review.previous_url, review.profile_url, *also_urls)
    )


def _restore_reviewed_name(row: dict, review: ProfileReview) -> None:
    if not (review.previous_name or review.outside_unit_ladder):
        return
    previous_name = review.previous_name or review.name
    if row.get("pi_name") != previous_name:
        return
    row["pi_name"] = review.name
    if row.get("title", "").startswith(previous_name + " — "):
        row["title"] = review.name + row["title"][len(previous_name):]
    # Replace only this collector's unranked boilerplate. Other material,
    # including reviewed research text and evidence, stays in its own field.
    old_text = (f"Faculty research profile for {previous_name} in the {review.department} at {row.get('organization')}. "
                "Contact this faculty member to ask whether undergraduate research opportunities are currently available.")
    new_text = f"{review.name} is listed as {review.title} in the {review.department} at {row.get('organization')}."
    for fields, key in ((row, "description_clean"), (row, "description_raw"),
                        (row.get("eligibility") or {}, "eligibility_text_raw")):
        if fields.get(key) == old_text:
            fields[key] = new_text


def reviewed_department_staff_role(row: dict) -> dict[str, str] | None:
    """Publish a staff role only while the same saved person and reviewed source still agree."""
    review = REVIEWS.get(row.get("id"))
    if not review or not review.staff_directory_reference or not review.staff_title_zh or not review.title:
        return None
    metadata = row.get("metadata") or {}
    receipt = metadata.get("faculty_profile_review") or {}
    if (row.get("source_type") == "campus_department" and row.get("source") == f"{review.school}_faculty"
            and row.get("school") == review.school and row.get("department") == review.department
            and row.get("pi_name") == review.name and row.get("url") == review.profile_url
            and (row.get("source_url") or row.get("url")) == review.profile_url
            and metadata.get("is_active") is False and metadata.get("reference_only") is True
            and metadata.get("deactivation_reason") == _OUTSIDE_UNIT_LADDER and metadata.get("faculty_title") == review.title
            and isinstance(receipt, dict) and receipt.get("source_url") == review.roster_url
            and receipt.get("reviewed_on") == review.reviewed_on.isoformat()):
        return {"en": review.title, "zh": review.staff_title_zh}
    return None


def reviewed_primary_appointment(group: list[dict]) -> dict | None:
    """Prefer a confirmed primary appointment when two current roles share one person's profile."""
    if len(group) != 2:
        return None
    first, second = group
    for primary, secondary in ((first, second), (second, first)):
        review = REVIEWS.get(primary.get("id"))
        if not review or not review.secondary_record_id or secondary.get("id") != review.secondary_record_id:
            continue
        appointments = ((primary, review), (secondary, REVIEWS[review.secondary_record_id]))
        # The two rosters use www/non-www spellings for the same verified person.
        profiles = tuple(appointment.profile_url for _, appointment in appointments)
        if all(_matches_review(row, appointment, also_urls=profiles) and (row.get("metadata") or {}).get("faculty_title")
               in (appointment.previous_title, appointment.title) for row, appointment in appointments):
            return primary
    return None


def carry_forward_reviewed_appointment(previous: dict, incoming: dict) -> None:
    """Keep the last verified appointment when the same roster emits a rank-less card."""
    review = REVIEWS.get(incoming.get("id"))
    if (not review or review.previous_title != "" or previous.get("id") != incoming.get("id")
            or not _matches_review(previous, review) or not _matches_review(incoming, review)):
        return
    old = previous.get("metadata") or {}
    new = incoming.get("metadata") or {}
    old_title = old.get("faculty_title")
    if not old_title or new.get("faculty_title") not in (None, "", old_title) or new.get("is_active") is False:
        return
    if old.get("is_active") is False:
        prior_review = old.get("faculty_profile_review") or {}
        if (old_title != review.title or prior_review.get("source_url") != review.roster_url
                or prior_review.get("reviewed_on") != review.reviewed_on.isoformat()
                or old.get("deactivation_reason") not in ("retired_title", "trainee_title", _OUTSIDE_UNIT_LADDER)):
            return
        _restore_reviewed_name(incoming, review)
        new.update(is_active=False, deactivated_at=old.get("deactivated_at"),
                   deactivation_reason=old["deactivation_reason"], faculty_profile_review=prior_review.copy())
    elif (old.get("last_seen_at") or "")[:10] < review.reviewed_on.isoformat():
        return
    new["faculty_title"] = old_title


def apply_reviewed_faculty_profile(row: dict, selected=None, *, today: date | None = None,
                                 classify_title: bool = True) -> bool:
    """Correct a known URL or appointment while a reset record still claims it."""
    review = REVIEWS.get(row.get("id"))
    if (not review or (today or date.today()) < review.reviewed_on or not _matches_review(row, review)
            or (selected and not selected(review.school))):
        return False
    metadata = row.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("is_active") is False:
        return False
    matches_title = review.previous_title is None or (metadata.get("faculty_title") or "") == review.previous_title
    if not matches_title and not review.independently_verified_profile:
        return False
    # An old laboratory website can still belong to the person without
    # verifying their current appointment in this university's ladder roster.
    original_url = row["url"]
    clean_url = original_url.strip(" \t\r\n\f")
    destination = clean_url
    if (clean_url == review.previous_url and clean_url != review.profile_url
            and (review.outside_unit_ladder or not _old_page_restored(row, review))):
        destination = review.profile_url
    update_url = original_url != destination
    update_title = matches_title and review.title
    # Even a successful fetch of a restored URL establishes the address only.
    # An old directory title cannot overturn the appointment on the reviewed
    # emeritus roster and profile. A different appointment URL is outside this review.
    # The replacement profile identifies this as its department. Drop the old
    # label when replacing its source, preserving independently read research.
    label = review.previous_department_label
    if update_url and label and metadata.get("research_areas_raw") == label:
        if row.get("keywords") == [label] and not inferred_method(row, "keywords"):
            stamp_inferred(metadata, "keywords", DEPARTMENT_FIELD_METHOD)
        metadata["research_areas_raw"] = ""
        metadata.pop("research_areas_verified_at", None)
    if not update_url and not update_title:
        return False
    if update_url:
        row["url"] = destination
        if row.get("source_url") in (original_url, review.previous_url):
            row["source_url"] = destination
        application = row.get("application")
        if isinstance(application, dict) and application.get("application_url") in (original_url, review.previous_url):
            application["application_url"] = destination
    metadata["faculty_profile_review"] = {
        "previous_url": review.previous_url, "source_url": review.roster_url,
        "reviewed_on": review.reviewed_on.isoformat(),
    }
    _restore_reviewed_name(row, review)
    if update_title:
        previous_title = metadata.get("faculty_title")
        metadata["faculty_profile_review"]["previous_title"] = previous_title
        if previous_title and is_retired_title(review.title) and row.get("organization"):
            # Older generated invitations optionally include a research-areas sentence.
            intro = (f"Research opportunity with {previous_title} {review.name} in the {review.department} "
                     f"at {row['organization']}.")
            invitation = " Contact the professor directly to inquire about undergraduate research positions in their lab."
            corrected = f"{row['organization']} lists {review.name} as {review.title} in {review.department}."
            for target, field in ((row, "description_clean"), (row, "description_raw"),
                                  (row.get("eligibility") or {}, "eligibility_text_raw")):
                text = target.get(field)
                if isinstance(text, str) and text.startswith(intro) and text.endswith(invitation):
                    research = text[len(intro):-len(invitation)]
                    if not research or research.startswith(" Research areas: "):
                        target[field] = corrected + research
        if review.appointment_summary and row.get("organization"):
            original = (f"Faculty research profile for {review.previous_title} {review.name} "
                        f"in the {review.department} at {row['organization']}. "
                        "Contact this faculty member to ask whether undergraduate research opportunities "
                        "are currently available.")
            for target, field in ((row, "description_clean"), (row, "description_raw"),
                                  (row.get("eligibility") or {}, "eligibility_text_raw")):
                if target.get(field) == original:
                    target[field] = review.appointment_summary
        metadata["faculty_title"] = review.title
        if review.outside_unit_ladder:
            # This is the policy of the reviewed unit, not a reason to archive
            # this person's other appointments or adjuncts across the corpus.
            metadata.update(is_active=False, deactivated_at=review.reviewed_on.isoformat(),
                            deactivation_reason=_OUTSIDE_UNIT_LADDER)
            if review.staff_directory_reference:
                # Keep this official staff biography on its saved ID. A faculty
                # source type would generate a research profile on the public page.
                row.update(source_type="campus_department", source_url=review.profile_url, contact_email=None)
                metadata["reference_only"] = True
                application = row.get("application")
                if isinstance(application, dict):
                    application.update(contact_method="website", application_url=None)
        elif classify_title:
            deactivate_deceased_faculty([row], today=review.reviewed_on)
            deactivate_retired_title_faculty([row], today=review.reviewed_on)
            deactivate_trainee_faculty([row], today=review.reviewed_on)
    return True


def apply_reviewed_faculty_profiles(rows: list[dict], selected=None, *, today: date | None = None,
                                  classify_title: bool = True) -> int:
    return sum(apply_reviewed_faculty_profile(row, selected, today=today, classify_title=classify_title)
               for row in rows)
