"""Tests for the JSON-directory faculty collector (AHS + Social Work + Gies).

All network is monkeypatched: the collector's value is in the faculty-vs-staff
filtering, department routing, and keyword hygiene, which these exercise on
representative API payloads."""
from __future__ import annotations

import src.collectors.uiuc_json_faculty as j
from src.collectors.uiuc_faculty import _is_junk_keyword


def _wigg_person(name, email, job_type, office, keywords=None, title="Associate Professor"):
    return {
        "fullName": name,
        "email": email,
        "profileUrl": f"https://ahs.illinois.edu/directory/profile/{email.split('@')[0]}",
        "primaryTitle": title,
        "primaryOffice": office,
        "keywords": keywords or [],
        "jobProfiles": [{"jobType": job_type, "office": office, "title": title}],
    }


def test_clean_keywords_dedups_case_insensitive_preserving_order():
    out = j._clean_keywords(["Gut Microbiota", "gut microbiota", "Microbiome"], "fallback")
    assert out == ["Gut Microbiota", "Microbiome"]


def test_clean_keywords_drops_population_noise_keeps_real_areas():
    out = j._clean_keywords(
        ["Physical Activity", "Older Adults", "Middle-Aged", "USA", "Dance Program"],
        "kinesiology",
    )
    assert out == ["Physical Activity", "Dance Program"]


def test_clean_keywords_drops_lc_call_numbers_keeps_alphanumeric_areas():
    out = j._clean_keywords(
        ["RA0421 Public health", "RC0321 Neuroscience", "p53", "CD4", "3D Printing"],
        "fallback",
    )
    assert out == ["p53", "CD4", "3D Printing"]


def test_clean_keywords_falls_back_when_empty():
    assert j._clean_keywords([], "social work") == ["social work"]
    assert j._clean_keywords(["USA", "Adults"], "social work") == ["social work"]


def test_clean_keywords_caps_at_eight():
    assert len(j._clean_keywords([f"Area {i}" for i in range(20)], "x")) == 8


def test_wigg_keeps_only_faculty_job_type(monkeypatch):
    payload = {"people": [
        _wigg_person("Jane Prof", "jprof@illinois.edu", "Faculty",
                     "Department of Health and Kinesiology", ["Skeletal Muscle"]),
        _wigg_person("Stan Staff", "sstaff@illinois.edu", "Staff",
                     "Business Affairs", []),
        _wigg_person("Nora None", "nnone@illinois.edu", "None", "Office of the Dean", []),
    ]}
    monkeypatch.setattr(j, "_fetch_json", lambda url: payload)
    recs = j.fetch_ahs()
    assert len(recs) == 1
    assert recs[0]["pi_name"] == "Jane Prof"
    assert recs[0]["source"] == "uiuc_faculty"
    assert recs[0]["contact_email"] == "jprof@illinois.edu"


def test_ahs_routes_office_to_academic_department():
    assert j._ahs_dept_and_majors("Department of Health and Kinesiology")[0] == \
        "Department of Health and Kinesiology"
    assert j._ahs_dept_and_majors("Speech and Hearing Science")[0] == \
        "Department of Speech and Hearing Science"
    # No comma in the recreation department (a comma broad field fails to strip).
    assert "," not in j._ahs_dept_and_majors("Recreation, Sport and Tourism")[0]
    assert j._ahs_dept_and_majors("Division of Disability Resources")[0] == \
        "College of Applied Health Sciences"


def test_gies_title_filter_keeps_faculty_drops_students_and_staff(monkeypatch):
    payload = {"items": [
        {"fullnamefirst": "Real Professor", "fullname": "Professor, Real",
         "email": "rp@illinois.edu", "title": "Associate Professor of Finance",
         "department": "Finance", "externalurlwithpath": "https://x/rp"},
        {"fullnamefirst": "Phd Student", "fullname": "Student, Phd",
         "email": "ps@illinois.edu", "title": "PhD Student in Finance",
         "department": "Finance", "externalurlwithpath": "https://x/ps"},
        {"fullnamefirst": "Post Doc", "fullname": "Doc, Post",
         "email": "pd@illinois.edu", "title": "Postdoctoral Research Associate of Finance",
         "department": "Finance", "externalurlwithpath": "https://x/pd"},
        {"fullnamefirst": "Office Staff", "fullname": "Staff, Office",
         "email": "os@illinois.edu", "title": "Office Support Specialist",
         "department": "Accountancy", "externalurlwithpath": "https://x/os"},
        {"fullnamefirst": "Empty Title", "fullname": "Title, Empty",
         "email": "et@illinois.edu", "title": "",
         "department": "Finance", "externalurlwithpath": "https://x/et"},
    ]}
    monkeypatch.setattr(j, "_fetch_json", lambda url: payload)
    monkeypatch.setattr(j, "_fetch_soup", lambda url: None)
    monkeypatch.setattr(j.time, "sleep", lambda *a: None)
    recs = j.fetch_gies()
    assert [r["pi_name"] for r in recs] == ["Real Professor"]
    assert recs[0]["department"] == "Department of Finance"


def test_gies_broad_keywords_are_not_junk(monkeypatch):
    """Regression: 'business administration' is nav-furniture the keyword DQ
    rejects, so Business Administration must anchor on a clean broad field."""
    payload = {"items": [
        {"fullnamefirst": "BA Prof", "fullname": "Prof, BA", "email": "ba@illinois.edu",
         "title": "Professor of Business Administration",
         "department": "Business Administration", "externalurlwithpath": "https://x/ba"},
        {"fullnamefirst": "Fin Prof", "fullname": "Prof, Fin", "email": "fin@illinois.edu",
         "title": "Professor of Finance", "department": "Finance",
         "externalurlwithpath": "https://x/fin"},
    ]}
    monkeypatch.setattr(j, "_fetch_json", lambda url: payload)
    monkeypatch.setattr(j, "_fetch_soup", lambda url: None)
    monkeypatch.setattr(j.time, "sleep", lambda *a: None)
    recs = j.fetch_gies()
    for r in recs:
        for kw in r["keywords"]:
            assert not _is_junk_keyword(kw), f"{r['pi_name']} has junk keyword {kw!r}"


def test_gies_straggler_department_falls_back(monkeypatch):
    payload = {"items": [
        {"fullnamefirst": "Lib Prof", "fullname": "Prof, Lib", "email": "lp@illinois.edu",
         "title": "Associate Professor", "department": "Business and Economics Library",
         "externalurlwithpath": "https://x/lp"},
    ]}
    monkeypatch.setattr(j, "_fetch_json", lambda url: payload)
    monkeypatch.setattr(j, "_fetch_soup", lambda url: None)
    monkeypatch.setattr(j.time, "sleep", lambda *a: None)
    recs = j.fetch_gies()
    assert len(recs) == 1
    assert recs[0]["department"] == "Department of Business Administration"


def test_gies_enriches_from_profile_research_interests(monkeypatch):
    """Each Gies profile's Research Interests (comma-joined, under sub-labels)
    enrich the record; a profile with none keeps the dept broad field."""
    from bs4 import BeautifulSoup
    payload = {"items": [
        {"fullnamefirst": "Ops Prof", "fullname": "Prof, Ops", "email": "op@illinois.edu",
         "title": "Professor of Business Administration", "department": "Business Administration",
         "externalurlwithpath": "https://giesbusiness.illinois.edu/profile/ops-prof"},
        {"fullnamefirst": "Bare Prof", "fullname": "Prof, Bare", "email": "bp@illinois.edu",
         "title": "Professor of Finance", "department": "Finance",
         "externalurlwithpath": "https://giesbusiness.illinois.edu/profile/bare-prof"},
    ]}
    profiles = {
        "https://giesbusiness.illinois.edu/profile/ops-prof": BeautifulSoup(
            "<h3>Research Interests</h3><p>Methods:\nMachine learning, optimization\n"
            "Applications:\nSupply chain management</p>", "html.parser"),
        "https://giesbusiness.illinois.edu/profile/bare-prof": BeautifulSoup(
            "<h3>Biography</h3><p>Teaches finance.</p>", "html.parser"),
    }
    monkeypatch.setattr(j, "_fetch_json", lambda url: payload)
    monkeypatch.setattr(j, "_fetch_soup", lambda url: profiles.get(url))
    monkeypatch.setattr(j.time, "sleep", lambda *a: None)
    recs = j.fetch_gies()
    ops = next(r for r in recs if r["pi_name"] == "Ops Prof")
    assert ops["keywords"] == ["Machine learning", "optimization", "Supply chain management"]
    bare = next(r for r in recs if r["pi_name"] == "Bare Prof")
    assert bare["keywords"] == ["finance"]  # no Research Interests -> dept broad field


def test_normalized_record_uses_api_keywords_not_scrape(monkeypatch):
    """The structured API keywords flow straight through normalize_faculty
    (no per-profile fetch), so a niche area the keyword bank lacks survives."""
    payload = {"people": [
        _wigg_person("Vocal Researcher", "vr@illinois.edu", "Faculty",
                     "Department of Speech and Hearing Science",
                     ["Vocal Fatigue", "Room Acoustics"]),
    ]}
    monkeypatch.setattr(j, "_fetch_json", lambda url: payload)
    rec = j.fetch_ahs()[0]
    assert "Vocal Fatigue" in rec["keywords"]
    assert rec["department"] == "Department of Speech and Hearing Science"
    assert rec["eligibility"]["majors"]  # routed majors present


def test_education_routes_office_to_department():
    assert j._education_dept_and_majors("Educational Psychology")[0] == \
        "Department of Educational Psychology"
    assert j._education_dept_and_majors("Curriculum & Instruction")[0] == \
        "Department of Curriculum and Instruction"
    assert j._education_dept_and_majors("Special Education")[0] == \
        "Department of Special Education"
    assert j._education_dept_and_majors("Education Policy, Organization & Leadership")[0] == \
        "Department of Education Policy, Organization & Leadership"
    assert j._education_dept_and_majors("Bureau of Educational Research")[0] == "College of Education"
