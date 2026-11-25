"""Apply identity-checked corrections to older individual faculty profiles."""
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.contact_instructions import contact_instruction_pages, same_source_page

from .deactivate_stale_faculty import deactivate_deceased_faculty, deactivate_retired_title_faculty


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

    @property
    def reviewed_on(self) -> date:
        return self.reviewed_at.date()


# The source runner finished reading the six identity-checked destinations at 12:01:59 UTC.
_NOV_25 = datetime(2026, 11, 25, 12, 2, tzinfo=UTC)
_SBU_CS = "https://www.cs.stonybrook.edu/people/index.html"
_SBU_GEO = "https://www.stonybrook.edu/geosciences/people/faculty.html"
_SBU_GEO_REVIEW = datetime(2026, 11, 25, 17, 19, tzinfo=UTC)
REVIEWS = {
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
    "faculty-umd-math-1516d149": ProfileReview(
        "umd", "Department of Mathematics", "Shiferaw Berhanu", "https://www-math.umd.edu/people/faculty/item/1694-sberhanu.html",
        "https://www-math.umd.edu/signage-directory-faculty/2025-sberhanu.html",
        "https://www-math.umd.edu/people/faculty.html", _NOV_25),
    "faculty-umd-phys-5e8e0edd": ProfileReview(
        "umd", "Department of Physics", "Elizabeth Beise", "https://umdphysics.umd.edu/people/faculty/current/item/43-beise.html",
        "https://umdphysics.umd.edu/directory/faculty/emeritus/beise.html",
        "https://umdphysics.umd.edu/people/faculty/emeritus.html", _NOV_25, "Professor Emerita"),
}


def _old_page_restored(row: dict, review: ProfileReview) -> bool:
    """A later successful read of this person's exact old URL can restore the link."""
    for page in contact_instruction_pages(row):
        receipt = page.get("receipt") or {}
        if (receipt.get("status") in {"captured", "empty"}
                and same_source_page(page["requested_source_url"], review.previous_url)
                and same_source_page(receipt["source_url"], review.previous_url)
                and datetime.fromisoformat(receipt["attempted_at"]) > review.reviewed_at):
            return True
    return False


def apply_reviewed_faculty_profile(row: dict, selected=None, *, today: date | None = None) -> bool:
    """Correct a known URL or appointment while a reset record still claims it."""
    review = REVIEWS.get(row.get("id"))
    if not review or (today or date.today()) < review.reviewed_on:
        return False
    if (row.get("school") != review.school or row.get("department") != review.department
            or row.get("source") != f"{review.school}_faculty"
            or row.get("source_type") != "faculty_research" or row.get("pi_name") != review.name
            or row.get("url") not in (review.previous_url, review.profile_url)
            or (selected and not selected(review.school))):
        return False
    metadata = row.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("is_active") is False:
        return False
    update_url = row["url"] == review.previous_url and not _old_page_restored(row, review)
    # Even a successful fetch of a restored URL establishes the address only.
    # An old directory title cannot overturn the appointment on the reviewed
    # emeritus roster and profile. A different appointment URL is outside this review.
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
        metadata["faculty_profile_review"]["previous_title"] = metadata.get("faculty_title")
        metadata["faculty_title"] = review.title
        deactivate_deceased_faculty([row], today=review.reviewed_on)
        deactivate_retired_title_faculty([row], today=review.reviewed_on)
    return True


def apply_reviewed_faculty_profiles(rows: list[dict], selected=None, *, today: date | None = None) -> int:
    return sum(apply_reviewed_faculty_profile(row, selected, today=today) for row in rows)
