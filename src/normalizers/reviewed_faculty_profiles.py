"""Apply identity-checked corrections to older individual faculty profiles."""
from dataclasses import dataclass
from datetime import date

from .deactivate_stale_faculty import deactivate_retired_title_faculty


@dataclass(frozen=True)
class ProfileReview:
    school: str
    department: str
    name: str
    previous_url: str
    profile_url: str
    roster_url: str
    reviewed_on: date
    title: str | None = None


_NOV_25 = date(2026, 11, 25)
_SBU_CS = "https://www.cs.stonybrook.edu/people/index.html"
REVIEWS = {
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


def apply_reviewed_faculty_profile(row: dict, selected=None, *, today: date | None = None) -> bool:
    """Apply a matching review. A newer sighting or a different record wins."""
    review = REVIEWS.get(row.get("id"))
    if not review or (today or date.today()) < review.reviewed_on:
        return False
    if (row.get("school") != review.school or row.get("department") != review.department
            or row.get("source") != f"{review.school}_faculty"
            or row.get("source_type") != "faculty_research" or row.get("pi_name") != review.name
            or row.get("url") != review.previous_url or (selected and not selected(review.school))):
        return False
    metadata = row.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("is_active") is False:
        return False
    try:
        seen = date.fromisoformat(str(metadata.get("last_seen_at") or "")[:10])
        verified = date.fromisoformat(str(metadata["last_verified"])[:10]) if metadata.get("last_verified") else seen
    except ValueError:
        return False
    if max(seen, verified) >= review.reviewed_on:
        # A later observation of the same old address can establish that it
        # works again or that the person has a new appointment.
        return False
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
        deactivate_retired_title_faculty([row], today=review.reviewed_on)
    return True


def apply_reviewed_faculty_profiles(rows: list[dict], selected=None, *, today: date | None = None) -> int:
    return sum(apply_reviewed_faculty_profile(row, selected, today=today) for row in rows)
