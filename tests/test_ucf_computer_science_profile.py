from copy import deepcopy

from src.collectors import faculty_graph
from src.collectors.schools.ucf_faculty import SCHOOL
from src.normalizers.reviewed_faculty_profiles import REVIEWS, apply_reviewed_faculty_profile

ORIGINAL = "faculty-ucf-cs-edfc1c62"
CS = next(dept for dept in SCHOOL["departments"] if dept["short"] == "CS")


def person(name, url):
    return faculty_graph._normalize(SCHOOL, CS, faculty_graph.faculty(name, url=url, title="Lecturer"))


def test_both_reviewed_spellings_and_the_college_personal_page_keep_the_saved_record():
    review = REVIEWS[ORIGINAL]
    for name in (review.name, "Ali Alkinoon"):
        row = person(name, review.previous_url)
        previous_application = row["application"]["application_url"]
        assert row["id"] == ORIGINAL and apply_reviewed_faculty_profile(row)
        assert row["url"] == row["source_url"] == review.profile_url
        assert row["application"]["application_url"] == previous_application
        assert not apply_reviewed_faculty_profile(row)
    direct = person("Ali Alkinoon", review.profile_url)
    assert direct["id"] == ORIGINAL and direct["url"] == review.profile_url


def test_unreviewed_same_name_and_other_people_keep_their_own_urls():
    review = REVIEWS[ORIGINAL]
    different_person = person("Ali Alkinoon", "https://www.cecs.ucf.edu/faculty/another-person/")
    assert different_person["id"] != ORIGINAL
    old = person("Ali Al Kinoon", review.previous_url)
    for field, value in (("pi_name", "Different Person"), ("url", "https://www.cecs.ucf.edu/new-page/")):
        row = {**deepcopy(old), field: value}
        assert not apply_reviewed_faculty_profile(row)
        assert row[field] == value
