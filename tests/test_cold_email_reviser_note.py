"""M111: a draft the attribution check flags goes back to the reviser with the
confirmed sentence each flagged sentence restates, to be copied exactly; a
sentence that restates none clearly is to be removed. The recorded texts are
the experience paragraphs of the final drafts of the 10/18 production replays
(E5, E6, E10, P4, P5), placed in a fictional email to a fictional contact. The
student is fictional and every model call is a local stub."""
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from tests.experience_fixtures import confirmed_experience

PITCH = "I implemented an FFT-based pitch detector in Python with NumPy and tested it on 20 recorded voice clips from classmates."
FILTER = ("I wrote a spectral subtraction noise-reduction filter in MATLAB for our four-person team's hearing-aid "
          "prototype and measured the signal-to-noise ratio before and after filtering.")
GRADER = "I grade weekly homework for about 60 ECE 210 students and hold one office hour per week."
COURSES = "My coursework includes ECE 210, ECE 310, ECE 313, and ECE 417."
PROFILE = {"name": "Yuxin Chen", "school": "UIUC", "year": "junior", "major": "Electrical Engineering",
           "hard_skills": [{"name": name, "level": "beginner"} for name in ("Python", "MATLAB", "NumPy")],
           "coursework": ["ECE 210", "ECE 310", "ECE 313", "ECE 417"],
           "research_interests_text": "Speech and audio signal processing, noise reduction for hearing technology."}
OPP = {"id": "m111-note", "source_type": "campus_program", "opportunity_type": "research",
       "title": "Hearing Signal Processing", "pi_name": "Pat Lee", "organization": "Test University",
       "keywords": ["noise reduction", "hearing aids", "audiology"],
       "description_raw": "Research on noise reduction and signal processing for hearing aids.",
       "eligibility": {"skills_required": []}, "application": {}, "metadata": {"is_active": True}}

# The experience sentences of each recorded final draft, with the clauses the
# check flagged in the replay and the confirmed sentence each one restates.
RECORDED = {
    "E5": (
        "From August to December 2025, I wrote a spectral subtraction noise-reduction filter in MATLAB for our "
        "four-person team's hearing-aid prototype and measured the signal-to-noise ratio before and after filtering. "
        "From March to May 2026, I implemented an FFT-based pitch detector in Python with NumPy for an ECE 310 course "
        f"project and tested it on 20 recorded voice clips from classmates. {COURSES}",
        [(["From August to December 2025, I wrote a spectral subtraction noise-reduction filter in MATLAB for our "
           "four-person team's hearing-aid prototype"], FILTER),
         (["From March to May 2026, I implemented an FFT-based pitch detector in Python with NumPy for an ECE 310 "
           "course project", "tested it on 20 recorded voice clips from classmates"], PITCH)]),
    "E6": (
        "In a course project, I implemented an FFT-based pitch detector in Python with NumPy and tested it on 20 "
        "recorded voice clips from classmates. For our four-person student team's hearing-aid prototype, I wrote a "
        "spectral subtraction noise-reduction filter in MATLAB and measured the signal-to-noise ratio before and "
        "after filtering. My coursework includes ECE 313 and ECE 417, and I currently grade weekly homework for ECE 210.",
        [(["In a course project, I implemented an FFT-based pitch detector in Python with NumPy",
           "tested it on 20 recorded voice clips from classmates"], PITCH),
         (["For our four-person student team's hearing-aid prototype, I wrote a spectral subtraction noise-reduction "
           "filter in MATLAB", "measured the signal-to-noise ratio before and after filtering"], FILTER)]),
    "E10": (
        "For our four-person team's hearing-aid prototype, I wrote a spectral subtraction noise-reduction filter in "
        "MATLAB and measured the signal-to-noise ratio before and after filtering. In my ECE 310 course project, I "
        "implemented an FFT-based pitch detector in Python with NumPy and tested it on 20 recorded voice clips from "
        f"classmates. {COURSES}",
        [(["For our four-person team's hearing-aid prototype, I wrote a spectral subtraction noise-reduction filter "
           "in MATLAB", "measured the signal-to-noise ratio before and after filtering"], FILTER),
         (["In my ECE 310 course project, I implemented an FFT-based pitch detector in Python with NumPy",
           "tested it on 20 recorded voice clips from classmates"], PITCH)]),
    # The provider cut this draft off; the last sentence starts the pitch entry.
    "P4": (
        "In a four-person team hearing-aid prototype (Aug–Dec 2025), I wrote a spectral subtraction noise-reduction "
        "filter in MATLAB and measured the signal-to-noise ratio before and after filtering. For an ECE 310 course "
        "project, I implemented an FF",
        [(["In a four-person team hearing-aid prototype (Aug–Dec 2025), I wrote a spectral subtraction "
           "noise-reduction filter in MATLAB", "measured the signal-to-noise ratio before and after filtering"], FILTER),
         (["For an ECE 310 course project, I implemented an FF"], PITCH)]),
    "P5": (
        "From August to December 2025, I wrote a spectral subtraction noise-reduction filter in MATLAB for our "
        "four-person student team's hearing-aid prototype and measured the signal-to-noise ratio before and after "
        "filtering. In an ECE 310 course project from March to May 2026, I implemented an FFT-based pitch detector in "
        f"Python with NumPy and tested it on 20 recorded voice clips from classmates. {COURSES}",
        [(["From August to December 2025, I wrote a spectral subtraction noise-reduction filter in MATLAB for our "
           "four-person student team's hearing-aid prototype",
           "measured the signal-to-noise ratio before and after filtering"], FILTER),
         (["In an ECE 310 course project from March to May 2026, I implemented an FFT-based pitch detector in Python "
           "with NumPy", "tested it on 20 recorded voice clips from classmates"], PITCH)]),
}
# What a reviser that copies each named sentence leaves of each paragraph.
COPIED = {
    "E5": f"{FILTER} {PITCH} {COURSES}",
    "E6": f"{PITCH} {FILTER} My coursework includes ECE 313 and ECE 417, and I currently grade weekly homework for ECE 210.",
    "E10": f"{FILTER} {PITCH} {COURSES}",
    "P4": f"{FILTER} {PITCH}",
    "P5": f"{FILTER} {PITCH} {COURSES}",
}


def fact(id, value):
    return {"id": id, "revision": 1, "status": "confirmed", "value": value, "source": {"kind": "manual"}}


def activity(id, kind, title, organization, start, end, entry):
    return {"id": id, "kind": kind, "title": fact(f"{id}-title", title),
            "organization": fact(f"{id}-org", organization), "start": fact(f"{id}-start", start),
            "end": fact(f"{id}-end", end), "details": [{"id": entry, "revision": 1}]}


def evidence(pitch_status="confirmed", extra=()):
    """The replays' shape: each entry belongs to its confirmed activity."""
    data = confirmed_experience([PITCH, FILTER, GRADER, *extra])
    data["entries"][0]["status"] = pitch_status
    data.update(version=2, resume_master={
        "version": 1, "id": "master", "revision": 1, "source_signature": None, "basics": {"links": []},
        "education": [], "publications": [], "skills": [], "other_sections": [], "unmapped_ranges": [],
        "section_order": ["basics", "education", "activities", "publications", "skills"],
        "activities": [
            activity("pitch", "project", "FFT Pitch Detector", "ECE 310 course project, UIUC",
                     "Mar 2026", "May 2026", "experience-0"),
            activity("filter", "project", "Hearing-Aid Noise Reduction Prototype", "Student team project, UIUC",
                     "Aug 2025", "Dec 2025", "experience-1"),
            activity("grader", "employment", "Grader, ECE 210", "Department of Electrical and Computer Engineering, UIUC",
                     "Aug 2026", "Present", "experience-2"),
        ]})
    return data


def email(experience):
    return "\n\n".join([
        "Dear Pat Lee,",
        "I am Yuxin Chen, a junior in Electrical Engineering at UIUC, writing to ask whether you have a research "
        "opening for an undergraduate.",
        "Your work on noise reduction for hearing aids connects to my interest in noise reduction for hearing technology.",
        experience,
        "Do you have any current or upcoming research openings? I can send a resume on request.",
        "Best regards,\nYuxin Chen",
    ])


def draft(case):
    return f"Subject: Research inquiry\n\n{email(RECORDED[case][0])}"


def findings(text, data=None):
    request = ce.ColdEmailRequest(profile=PROFILE, opportunity_id=OPP["id"], experience_evidence=data or evidence(),
                                  engine="ai")
    parts, _selection = ce._experience_parts(request, request.profile.model_dump(), OPP)
    return ce._deterministic_findings(text, ce._build_email_corpus(parts, OPP), parts, OPP)


def replace_line(clauses, excerpt):
    quoted = " and ".join(f'"{clause}"' for clause in clauses)
    return (f"- Replace the sentence containing {quoted} with this confirmed sentence: "
            + json.dumps(excerpt, ensure_ascii=False))


@pytest.mark.parametrize("case", sorted(RECORDED))
def test_the_note_names_the_confirmed_sentence_each_recorded_sentence_restates(case):
    found = findings(draft(case))
    expected = RECORDED[case][1]
    assert found["attribution_clauses"] == [clause for clauses, _excerpt in expected for clause in clauses]
    assert found["attribution_sources"] == [{"clauses": clauses, "excerpt": excerpt} for clauses, excerpt in expected]
    notes = ce._revision_notes(found)
    for clauses, excerpt in expected:
        assert replace_line(clauses, excerpt) in notes.splitlines()
    assert "Restate it with" not in notes and "copy it exactly as its own sentence" in notes


def test_an_unconfirmed_entry_is_never_named():
    found = findings(draft("E5"), evidence(pitch_status="candidate"))
    notes = ce._revision_notes(found)
    assert PITCH not in notes
    assert replace_line(*RECORDED["E5"][1][0]) in notes.splitlines()
    clauses = RECORDED["E5"][1][1][0]
    assert f'- Remove the claims "{clauses[0]}" and "{clauses[1]}".' in notes.splitlines()


def test_an_entry_the_prompt_did_not_show_is_never_named():
    # Eight entries closer to this contact fill the prompt; the pitch and
    # grader entries stay eligible for every check but are not shown.
    closer = [f"I attended signal processing research seminars in week {n}." for n in range(7)]
    data = evidence(extra=closer)
    request = ce.ColdEmailRequest(profile=PROFILE, opportunity_id=OPP["id"], experience_evidence=data, engine="ai")
    parts, selection = ce._experience_parts(request, request.profile.model_dump(), OPP)
    assert PITCH in parts["resume_bullets"] and PITCH not in parts["experience_excerpts"]
    assert len(selection.selected) == 8 and FILTER in parts["experience_excerpts"]
    found = findings(draft("E5"), data)
    notes = ce._revision_notes(found)
    assert PITCH not in notes
    assert replace_line(*RECORDED["E5"][1][0]) in notes.splitlines()
    clauses = RECORDED["E5"][1][1][0]
    assert f'- Remove the claims "{clauses[0]}" and "{clauses[1]}".' in notes.splitlines()


@pytest.mark.parametrize("sentence", [
    # Another entry's activity: the pitch work placed in the filter project.
    "On our four-person team's hearing-aid prototype, I implemented an FFT-based pitch detector in Python with "
    "NumPy and tested it on 20 recorded voice clips from classmates.",
    # Another entry's date.
    "In December 2025, I implemented an FFT-based pitch detector in Python with NumPy and tested it on 20 recorded "
    "voice clips from classmates.",
    # Two entries in one sentence.
    "I wrote a spectral subtraction filter in MATLAB and implemented an FFT-based pitch detector in Python.",
    # Mostly about something no entry states.
    "I tested a deep neural network for real-time speech enhancement on cochlear implant recordings.",
])
def test_a_sentence_that_restates_no_one_entry_is_to_be_removed(sentence):
    found = findings(f"Subject: Research inquiry\n\n{email(sentence)}")
    assert found["attribution_sources"] and all(group["excerpt"] is None for group in found["attribution_sources"])
    notes = ce._revision_notes(found)
    assert "with this confirmed sentence" not in notes
    assert all(excerpt not in notes for excerpt in (PITCH, FILTER, GRADER))
    assert any(line.startswith("- Remove the claim") for line in notes.splitlines())


SPLIT = ("In my ECE 310 course project, I implemented an FFT-based pitch detector in Python with NumPy. In that "
         "project, I tested it on 20 recorded voice clips from classmates.")


def test_an_entry_two_sentences_restate_is_named_once():
    notes = ce._revision_notes(findings(f"Subject: Research inquiry\n\n{email(SPLIT)}")).splitlines()
    first, second = SPLIT.rstrip(".").split(". ")
    assert replace_line([first], PITCH) in notes
    assert (f'- Remove the sentence containing "{second}"; the confirmed sentence named above states it.'
            in notes)


def test_the_contact_wording_never_rewrites_a_quoted_sentence():
    # The contact wording turns "PI" and "professor" into "opportunity contact".
    lab = "I built a MATLAB parser for my PI's hearing study."
    data = evidence(extra=[lab])
    data["resume_master"]["activities"].append(
        activity("study", "research", "Hearing Study Assistant", "Audiology Lab, UIUC", "Jan 2026", "May 2026",
                 "experience-3"))
    clause = "At UIUC, I built a MATLAB parser for my PI's hearing study with my professor"
    found = findings(f"Subject: Research inquiry\n\n{email(clause + '.')}", data)
    line = replace_line([clause], lab)
    assert ce._opportunity_contact_wording(line) != line
    assert line in ce._revision_notes(found, opportunity_contact=True).splitlines()


def _sentence_span(text, clause):
    at = text.index(clause)
    line = text.rfind("\n", 0, at) + 1
    starts = [match.end() for match in re.finditer(r"[.!?]\s+", text[line:at])]
    start = line + (starts[-1] if starts else 0)
    end = re.compile(r"[.!?](?=\s|$)|\n|$").search(text, at + len(clause))
    return start, end.start() if end[0] in ("", "\n") else end.end()


def follow_note(messages):
    """A reviser that does what the note says and nothing else."""
    user = messages[1]["content"]
    text = user.split("CURRENT EMAIL:\n", 1)[1].split("\n\nFix exactly these issues", 1)[0]
    for line in user.splitlines():
        replace = re.match(r'- Replace the sentence containing "(.+?)"(?: and ".+?")* with this confirmed sentence: '
                           r'(".+")$', line)
        remove = re.match(r'- Remove the (?:claims?|sentence containing) "(.+?)"', line)
        if replace:
            start, end = _sentence_span(text, replace[1])
            text = text[:start] + json.loads(replace[2]) + text[end:]
        elif remove:
            start, end = _sentence_span(text, remove[1])
            before, after = text[:start].rstrip(" "), text[end:].lstrip(" ")
            text = before + (" " if before[-1:] not in ("", "\n") and after[:1] not in ("", "\n") else "") + after
    return text


def keep_paraphrasing(messages):
    """A reviser that hands the flagged email back in its own words, as the replays did."""
    return messages[1]["content"].split("CURRENT EMAIL:\n", 1)[1].split("\n\nFix exactly these issues", 1)[0]


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: OPP})
    monkeypatch.setattr(ce, "corpus_version", lambda: "m111-note")
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")

    async def anonymous(_authorization):
        return None

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    return TestClient(app)


def generate(client, monkeypatch, path, case, reviser, calls):
    def provider(messages, **_kwargs):
        if messages[0]["content"].startswith("You are revising"):
            calls.append(messages[1]["content"])
            return reviser(messages)
        return draft(case) if case in RECORDED else f"Subject: Research inquiry\n\n{email(case)}"

    monkeypatch.setattr(ce, "chat_completion", provider)
    response = client.post("/api/cold-email" + (f"/{path}" if path else ""), json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": evidence(), "engine": "ai"})
    assert response.status_code == 200, response.text
    if path == "stream":
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: ") and json.loads(line[6:]).get("stage") == "done")
    return response.json()


@pytest.mark.parametrize("path", ["", "stream"])
@pytest.mark.parametrize("case", sorted(RECORDED))
def test_a_reviser_that_copies_the_named_sentences_serves_each_recorded_draft(client, monkeypatch, path, case):
    calls = []
    out = generate(client, monkeypatch, path, case, follow_note, calls)
    assert (out["method"], out["fallback_reason"]) == ("ai", None)
    assert out["body"] == email(COPIED[case])
    assert len(calls) == 1


def test_a_reviser_that_follows_the_note_states_a_twice_restated_entry_once(client, monkeypatch):
    out = generate(client, monkeypatch, "", SPLIT, follow_note, [])
    assert (out["method"], out["body"]) == ("ai", email(PITCH))


@pytest.mark.parametrize("path", ["", "stream"])
@pytest.mark.parametrize("case", sorted(RECORDED))
def test_a_reviser_that_keeps_paraphrasing_still_falls_back_to_the_template(client, monkeypatch, path, case):
    calls = []
    out = generate(client, monkeypatch, path, case, keep_paraphrasing, calls)
    assert (out["method"], out["fallback_reason"]) == ("template", "fabrication")
    assert len(calls) == 2
    response = client.post("/api/cold-email", json={"profile": PROFILE, "opportunity_id": OPP["id"],
                                                    "experience_evidence": evidence(), "engine": "template"})
    template = response.json()
    assert (template["method"], template["fallback_reason"]) == ("template", None)
    assert (out["subject"], out["body"]) == (template["subject"], template["body"])


def test_the_scope_rule_is_only_in_the_whole_body_refine_prompt(client, monkeypatch):
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "2")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "1")
    systems = []
    body = email(f"{FILTER} {PITCH} {COURSES}")

    def provider(messages, **_kwargs):
        system = messages[0]["content"]
        systems.append(system)
        if system.startswith("You are judging"):
            return '{"winner": 1}'
        if system.startswith("You are a strict reviewer"):
            return '{"verdict": "revise", "revision_notes": "Tighten the opening."}'
        if system.startswith("Edit only the selected text"):
            return json.dumps({"replacement": "Could we talk about an opening?"})
        return body if system.startswith("You are an email editor") else f"Subject: Research inquiry\n\n{body}"

    monkeypatch.setattr(ce, "chat_completion", provider)
    base = {"profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": evidence()}
    for path in ("", "stream", "variants"):
        assert client.post("/api/cold-email" + (f"/{path}" if path else ""), json={**base, "engine": "ai"}).status_code == 200
    ask = "Do you have any current or upcoming research openings?"
    start = len(body[:body.index(ask)].encode("utf-16-le")) // 2
    for extra in ({}, {"selection": {"start_utf16": start, "end_utf16": start + len(ask), "text": ask}}):
        response = client.post("/api/cold-email/refine", json={
            **base, "current_body": body, "subject": "Research inquiry", "instruction": "Make the ask warmer.", **extra})
        assert response.status_code == 200, response.text
    rule = "Change only what the edit instruction asks for and keep every other sentence exactly as it is"
    stages = ("You are judging", "You are a strict reviewer", "You are revising", "Edit only the selected text",
              "You are an email editor")
    for stage in stages:
        assert any(system.startswith(stage) for system in systems), stage
    assert [system.startswith("You are an email editor") for system in systems if rule in system] == [True]
    assert sum(system.startswith("You are an email editor") for system in systems) == 1
