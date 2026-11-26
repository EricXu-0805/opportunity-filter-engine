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

    @property
    def reviewed_on(self) -> date:
        return self.reviewed_at.date()


# The source runner finished reading the six identity-checked destinations at 12:01:59 UTC.
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


_MSU_MGI_DIRECTORY = "https://directory.natsci.msu.edu/Directory/Directory/Department/26"

REVIEWS = {
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
    "faculty-msu-mgi-5ca9b09b": ProfileReview(
        "msu", "Department of Microbiology, Genetics and Immunology", "Kathleen A Hoag",
        _MSU_MGI_DIRECTORY, _MSU_MGI_DIRECTORY,
        "https://bld.natsci.msu.edu/news/dr-kathy-hoag-retires-after-25-years-at-the-BLD-Program.aspx",
        datetime(2026, 11, 26, 15, 48, tzinfo=UTC),
        title="Professor Emeritum", previous_title="Professor"),
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
    "faculty-tamu-inta-c32e8252": ProfileReview(
        "tamu", "Department of International Affairs", "John Schuessler", "https://bush.tamu.edu/faculty/jschuessler",
        "https://bush.tamu.edu/directory/john-schuessler/",
        "https://bush.tamu.edu/directory/john-schuessler/", _NOV_25),
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
    for page in contact_instruction_pages(row):
        receipt = page.get("receipt") or {}
        if (receipt.get("status") in {"captured", "empty"}
                and same_source_page(page["requested_source_url"], review.previous_url)
                and same_source_page(receipt["source_url"], review.previous_url)
                and datetime.fromisoformat(receipt["attempted_at"]) > review.reviewed_at):
            return True
    return False


def _matches_review(row: dict, review: ProfileReview) -> bool:
    return (
        row.get("school") == review.school and row.get("department") == review.department
        and row.get("source") == f"{review.school}_faculty" and row.get("source_type") == "faculty_research"
        and row.get("pi_name") == review.name and row.get("url") in (review.previous_url, review.profile_url)
    )


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
                or old.get("deactivation_reason") not in ("retired_title", "trainee_title")):
            return
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
    if review.previous_title is not None and (metadata.get("faculty_title") or "") != review.previous_title:
        return False
    update_url = (row["url"] == review.previous_url and review.previous_url != review.profile_url
                  and not _old_page_restored(row, review))
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
    if not update_url and not review.title:
        return False
    if update_url:
        row["url"] = review.profile_url
        if row.get("source_url") == review.previous_url:
            row["source_url"] = review.profile_url
        application = row.get("application")
        if isinstance(application, dict) and application.get("application_url") == review.previous_url:
            application["application_url"] = review.profile_url
    metadata["faculty_profile_review"] = {
        "previous_url": review.previous_url, "source_url": review.roster_url,
        "reviewed_on": review.reviewed_on.isoformat(),
    }
    if review.title:
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
        metadata["faculty_title"] = review.title
        if classify_title:
            deactivate_deceased_faculty([row], today=review.reviewed_on)
            deactivate_retired_title_faculty([row], today=review.reviewed_on)
            deactivate_trainee_faculty([row], today=review.reviewed_on)
    return True


def apply_reviewed_faculty_profiles(rows: list[dict], selected=None, *, today: date | None = None,
                                  classify_title: bool = True) -> int:
    return sum(apply_reviewed_faculty_profile(row, selected, today=today, classify_title=classify_title)
               for row in rows)
