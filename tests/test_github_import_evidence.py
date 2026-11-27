"""GitHub-imported skills carry the repo field that named them (M12).

Owner facts rule: a fact is shown as the source's words only when the source
states it. A topic like "machine-learning" states no library, so it may not
become PyTorch; and every skill the import does return says which repo, and
which field of it, it came from.

GitHub is never called: production shares one 60-an-hour unauthenticated
budget, so the client is replaced with a canned response.
"""

import asyncio

import pytest

from backend.routes import resume as resume_module


@pytest.fixture
def github_returns(monkeypatch):
    calls: list[str] = []

    def install(repos: list[dict] | dict, status: int = 200):
        class _Resp:
            status_code = status
            headers: dict = {}

            @staticmethod
            def json():
                return repos

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                calls.append(url)
                return _Resp()

        monkeypatch.setattr(resume_module.httpx, "AsyncClient", lambda **kw: _Client())
        return calls

    resume_module._github_cache.clear()
    yield install
    resume_module._github_cache.clear()


def _import(username: str = "octocat") -> dict:
    return asyncio.run(resume_module.parse_github_profile(username))


def test_a_subject_topic_names_no_library(github_returns):
    github_returns([
        {"name": "thesis", "language": None, "fork": False,
         "topics": ["machine-learning", "deep-learning", "data-science"]},
    ])
    body = _import()
    assert body["extracted_skills"] == []
    assert body["skill_evidence"] == []
    # The topics themselves are still reported; only the invented tools go.
    assert body["topics"] == ["data-science", "deep-learning", "machine-learning"]


def test_a_topic_that_names_the_tool_is_kept_with_its_repo(github_returns):
    github_returns([
        {"name": "vision", "language": None, "fork": False,
         "topics": ["machine-learning", "pytorch"]},
    ])
    body = _import()
    assert body["extracted_skills"] == ["PyTorch"]
    assert body["skill_evidence"] == [
        {"skill": "PyTorch", "repo": "vision", "field": "topic", "value": "pytorch"},
    ]


def test_a_language_says_which_repo_and_which_value(github_returns):
    github_returns([
        {"name": "engine", "language": "Jupyter Notebook", "fork": False, "topics": []},
        {"name": "cli", "language": "Rust", "fork": False, "topics": []},
        {"name": "someone-elses", "language": "Go", "fork": True, "topics": ["docker"]},
    ])
    body = _import()
    # GitHub's own word is kept as the value, so a mapped skill (Jupyter
    # Notebook -> Python) shows what it was inferred from.
    assert body["skill_evidence"] == [
        {"skill": "Python", "repo": "engine", "field": "language", "value": "Jupyter Notebook"},
        {"skill": "Rust", "repo": "cli", "field": "language", "value": "Rust"},
    ]
    assert body["extracted_skills"] == ["Python", "Rust"]


def test_every_extracted_skill_has_evidence_from_the_first_repo_that_named_it(github_returns):
    calls = github_returns([
        {"name": "newest", "language": "Python", "fork": False, "topics": ["Docker"]},
        {"name": "older", "language": "Python", "fork": False, "topics": ["docker", "react"]},
    ])
    body = _import()
    assert [e["skill"] for e in body["skill_evidence"]] == body["extracted_skills"]
    by_skill = {e["skill"]: e for e in body["skill_evidence"]}
    assert by_skill["Python"] == {
        "skill": "Python", "repo": "newest", "field": "language", "value": "Python",
    }
    assert by_skill["Docker"] == {
        "skill": "Docker", "repo": "newest", "field": "topic", "value": "Docker",
    }
    assert by_skill["React"]["repo"] == "older"
    assert len(calls) == 1


def _pull(repo="lab/vision", author="Student", pull_id=123):
    return {"id": pull_id, "number": 8, "user": {"login": author}, "title": "Measure crop growth",
            "base": {"repo": {"full_name": repo, "private": False}},
            "head": {"repo": {"full_name": "Student/vision", "private": False}}}


def test_public_pull_uses_its_author_and_full_repository_not_fork_ownership(github_returns):
    calls = github_returns(_pull())
    result = asyncio.run(resume_module.github_pull_contribution("student", "lab", "vision", 8))
    assert result == {"id": "github-pr:123", "source": {"kind": "github", "repository": "lab/vision",
                      "head_repository": "Student/vision", "author": "Student", "number": 8,
                      "title": "Measure crop growth"}}
    assert asyncio.run(resume_module.github_pull_contribution("STUDENT", "Lab", "vision", 8)) == result
    assert calls == ["https://api.github.com/repos/lab/vision/pulls/8"]
    github_returns(_pull(repo="other/vision", pull_id=456))
    other = asyncio.run(resume_module.github_pull_contribution("Student", "other", "vision", 8))
    assert other["id"] != result["id"]
    assert other["source"]["repository"] == "other/vision"


def test_user_does_not_inherit_a_teammates_contribution(github_returns):
    github_returns(_pull(author="Teammate"))
    with pytest.raises(resume_module.HTTPException) as exc:
        asyncio.run(resume_module.github_pull_contribution("Student", "lab", "vision", 8))
    assert exc.value.status_code == 422


def test_github_private_base_and_missing_public_head(github_returns):
    pull = _pull()
    pull["base"]["repo"]["private"] = True
    github_returns(pull)
    with pytest.raises(resume_module.HTTPException) as exc:
        asyncio.run(resume_module.github_pull_contribution("student", "lab", "vision", 8))
    assert exc.value.status_code == 404
    resume_module._github_cache.clear()  # the refusal is remembered for a few minutes
    pull["base"]["repo"]["private"] = False
    pull["head"]["repo"] = None
    assert asyncio.run(resume_module.github_pull_contribution("student", "lab", "vision", 8))["source"]["head_repository"] is None


def test_imported_experience_requires_confirmation_in_both_writing_paths(github_returns):
    from backend.lib.experience_evidence import select_experience
    from backend.lib.target_resume_ai_validation import active, validate_entries
    from backend.schemas import ExperienceEvidence, SelectedExperience

    github_returns(_pull())
    receipt = asyncio.run(resume_module.github_pull_contribution("student", "lab", "vision", 8))
    entry = {**receipt, "revision": 1, "status": "candidate", "text": _IMPORTED}
    for status in ("candidate", "confirmed", "rejected", "withdrawn"):
        entry["status"] = status
        validate_entries([entry])
        assert active(entry, "", "") is (status == "confirmed")
        model = ExperienceEvidence(version=1, resume_text="", entries=[entry])
        selected = select_experience(model, {}).selected
        assert bool(selected) is (status == "confirmed")
        if selected:
            assert SelectedExperience.model_validate(selected[0]).source == model.entries[0].source


# An imported pull request in the writing paths (owner decision 2026-11-27):
# nothing uses it before the student confirms that item, and its source is the
# GitHub account the student entered, never verified evidence.

_SOURCE = {"kind": "github", "repository": "lab/vision", "head_repository": "Student/vision",
           "number": 8, "author": "Student", "title": "Measure crop growth"}
_IMPORTED = "I opened pull request #8 in lab/vision (“Measure crop growth”)."
_IMPORTED_ZH = "我在 lab/vision 发起了第 8 号拉取请求《Measure crop growth》。"
_REWRITTEN = "I trained a speech recognition model in PyTorch that reached 97% accuracy on 40 speakers."
_UNVERIFIED = "experience_github_account_unverified"


def _library(status="confirmed", text=_IMPORTED, source=None):
    return {"version": 2, "resume_master": None, "resume_text": "", "entries": [
        {"id": "github-pr:123", "revision": 2, "status": status, "text": text, "source": source or dict(_SOURCE)}]}


@pytest.fixture
def draft(monkeypatch):
    """A draft from the real route, with every message a model would have been sent."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.routes import cold_email as ce
    from tests.test_cold_email_template_rules import FACULTY, PROFILE

    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {FACULTY["id"]: dict(FACULTY)})

    async def anonymous(_authorization):
        return None

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    client = TestClient(app)

    def write(evidence, engine, reply=None):
        sent: list[str] = []
        monkeypatch.setattr(ce, "is_configured", lambda: engine == "ai")

        # No reply: the route falls back to its template after the model was asked.
        def model(messages, **_k):
            sent.extend(message["content"] for message in messages)
            return reply

        monkeypatch.setattr(ce, "chat_completion", model)
        response = client.post("/api/cold-email", json={
            "profile": PROFILE, "opportunity_id": FACULTY["id"], "engine": engine, "experience_evidence": evidence})
        assert response.status_code == 200, response.text
        assert bool(sent) is (engine == "ai")
        return response.json(), "\n".join(sent)

    return write


@pytest.mark.parametrize("engine", ["template", "ai"])
@pytest.mark.parametrize("status", ["candidate", "rejected", "withdrawn"])
def test_an_import_the_student_has_not_confirmed_reaches_no_draft_and_no_model(draft, engine, status):
    out, sent = draft(_library(status), engine)
    assert "lab/vision" not in out["body"] and "lab/vision" not in sent
    assert out["experience_usage"]["selected"] == []
    assert out["experience_usage"]["excluded"] == [{"id": "github-pr:123", "revision": 2, "reason": status}]


@pytest.mark.parametrize("engine", ["template", "ai"])
def test_a_draft_that_uses_a_confirmed_import_is_marked_for_the_students_review(draft, engine):
    out, sent = draft(_library(), engine)
    usage = out["experience_usage"]
    assert _IMPORTED in out["body"]
    assert usage["selected"][0]["source"] == _SOURCE
    assert usage["needs_review"] is True and _UNVERIFIED in usage["notices"]
    if engine == "ai":
        student = sent[sent.index("STUDENT:"):]
        assert _IMPORTED in student
        assert "the account's ownership was not verified" in student


def test_a_draft_the_model_wrote_from_a_confirmed_import_is_marked_too(draft, monkeypatch):
    # One draft and no critique pass: the stand-in model gives every call the same answer.
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    reply = ("Subject: Research inquiry\n\nDear Professor Lee,\n\nI am a junior in Electrical Engineering at UIUC. "
             f"{_IMPORTED}\n\nWould you have 15 minutes for a conversation?\n\nBest regards,\nAudit Student")
    out, _sent = draft(_library(), "ai", reply=reply)
    usage = out["experience_usage"]
    assert out["method"] == "ai" and _IMPORTED in out["body"]
    assert usage["selected"][0]["source"] == _SOURCE
    assert usage["needs_review"] is True and _UNVERIFIED in usage["notices"]


@pytest.mark.parametrize("engine", ["template", "ai"])
def test_the_same_sentence_typed_by_the_student_is_not_marked(draft, engine):
    out, sent = draft(_library(source={"kind": "manual"}), engine)
    usage = out["experience_usage"]
    assert _IMPORTED in out["body"]
    assert usage["needs_review"] is False and _UNVERIFIED not in usage["notices"]
    assert "ownership was not verified" not in sent


@pytest.mark.parametrize("engine", ["template", "ai"])
def test_a_rewritten_sentence_no_longer_carries_the_pull_request_as_its_source(draft, engine):
    out, sent = draft(_library(text=_REWRITTEN), engine)
    usage = out["experience_usage"]
    assert _REWRITTEN in out["body"]
    assert usage["selected"][0]["source"] == {"kind": "manual"}
    assert usage["needs_review"] is False and _UNVERIFIED not in usage["notices"]
    assert "lab/vision" not in sent and "Measure crop growth" not in sent


def test_a_local_edit_of_a_draft_that_reworded_the_pull_request_keeps_the_review_mark():
    from backend.lib.experience_evidence import select_experience
    from backend.schemas import ExperienceEvidence

    def usage(body, **entry):
        return select_experience(ExperienceEvidence(**_library(**entry)), {}).local_usage(body)

    # What an AI draft does with the entry; a local edit only sees the body.
    reworded = "My pull request to Lab/Vision added a crop growth measure."
    marked = usage(reworded)
    assert marked["selected"] == []
    assert marked["needs_review"] is True and marked["notices"] == [_UNVERIFIED]
    assert usage(f"As I wrote: {_IMPORTED}")["notices"] == [_UNVERIFIED]
    for clear in (usage("I added a crop growth measure to an open-source project."),
                  usage(reworded, source={"kind": "manual"}), usage(reworded, text=_REWRITTEN),
                  usage(reworded, status="candidate")):
        assert clear["notices"] == []
    assert usage(reworded, source={"kind": "manual"})["needs_review"] is False


def test_the_pull_request_stays_the_source_only_while_the_text_names_it():
    from backend.lib.github_contribution import GitHubPullSource, names_pull

    source = GitHubPullSource(**_SOURCE)
    for text in (_IMPORTED, _IMPORTED_ZH, "In LAB/Vision I opened pull request 8, which adds a growth measure."):
        assert names_pull(text, source), text
    for text in (_REWRITTEN, "I opened pull request #8.", "I contributed to lab/vision.",
                 "I opened pull request #80 in lab/vision.", "I opened 18 pull requests in lab/vision."):
        assert not names_pull(text, source), text


def test_matching_reads_an_import_only_after_the_student_confirmed_it():
    from src.matcher.experience_fit import confirmed_methods

    row = {"id": "github-pr:123", "revision": 2, "source": "github",
           "text": "I opened pull request #8 in lab/vision. I built Python tools for it."}
    for status in ("candidate", "rejected", "withdrawn"):
        assert confirmed_methods([{**row, "status": status}]) == {}
    assert confirmed_methods([{**row, "status": "confirmed"}])["python"]["entry_id"] == "github-pr:123"


# The pull-request lookup draws on the same 60 GitHub requests an hour as the
# skills import (review f-account F3): what GitHub said about a pull request
# is remembered whoever asks, and one visitor's lookups stop well short of 60.

_GITHUB_REQUESTS_AN_HOUR = 60  # GitHub's limit for requests without a token, per egress address.


def _lookup(username="Student", repo="vision", number=8):
    try:
        return asyncio.run(resume_module.github_pull_contribution(username, "lab", repo, number))
    except resume_module.HTTPException as refused:
        return refused.status_code


def test_a_pull_request_github_cannot_find_is_asked_for_once(github_returns):
    calls = github_returns({"message": "Not Found"}, status=404)
    assert [_lookup(), _lookup(), _lookup("Teammate")] == [404, 404, 404]
    assert calls == ["https://api.github.com/repos/lab/vision/pulls/8"]
    assert _lookup(number=9) == 404
    assert len(calls) == 2


def test_a_private_repository_is_refused_from_the_first_answer(github_returns):
    pull = _pull()
    pull["base"]["repo"]["private"] = True
    calls = github_returns(pull)
    assert [_lookup(), _lookup()] == [404, 404]
    assert len(calls) == 1


def test_a_wrong_account_is_refused_from_what_github_already_said(github_returns):
    calls = github_returns(_pull(author="Teammate"))
    assert [_lookup(), _lookup(), _lookup("another-student")] == [422, 422, 422]
    # The author's own lookup needs no second request either.
    assert _lookup("teammate")["source"]["author"] == "Teammate"
    assert len(calls) == 1


def test_a_missing_pull_request_is_asked_for_again_sooner_than_a_found_one(github_returns, monkeypatch):
    from types import SimpleNamespace

    clock = [1000.0]
    monkeypatch.setattr(resume_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = github_returns({"message": "Not Found"}, status=404)
    assert _lookup() == 404
    clock[0] += resume_module._GITHUB_MISS_TTL_SECONDS - 1
    assert _lookup() == 404 and len(calls) == 1
    clock[0] += 2
    github_returns(_pull())
    # The student made the repository public or fixed the link in the meantime.
    assert _lookup()["id"] == "github-pr:123"
    assert resume_module._GITHUB_MISS_TTL_SECONDS < resume_module._GITHUB_CACHE_TTL_SECONDS
    clock[0] += resume_module._GITHUB_MISS_TTL_SECONDS + 1
    github_returns({"message": "Not Found"}, status=404)
    assert _lookup()["id"] == "github-pr:123"


@pytest.mark.parametrize("status, answer", [(403, 429), (429, 429), (500, 502)])
def test_an_answer_that_says_nothing_about_the_pull_request_is_not_remembered(github_returns, status, answer):
    calls = github_returns({"message": "try later"}, status=status)
    assert [_lookup(), _lookup()] == [answer, answer]
    assert len(calls) == 2
    github_returns(_pull())
    assert _lookup()["id"] == "github-pr:123"


def test_one_visitor_cannot_spend_the_hours_github_requests(github_returns, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from backend import main

    clock = [1_800_000_000.0]
    monkeypatch.setattr(main, "RATE_LIMIT_DISABLED", False)
    monkeypatch.setattr(main, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(main, "_last_purge", clock[0])
    main._rate_buckets.clear()
    calls = github_returns({"message": "Not Found"}, status=404)
    client = TestClient(main.app)
    try:
        # A hundred different links, one every seven seconds: never ten in a minute.
        answers = []
        for number in range(1, 101):
            answers.append(client.get(f"/api/resume/github/student/pull/lab/vision/{number}",
                                      headers={"x-forwarded-for": "9.9.9.9"}).status_code)
            clock[0] += 7
        assert 0 < len(calls) <= _GITHUB_REQUESTS_AN_HOUR // 3
        assert answers.count(404) == len(calls) and answers.count(429) == 100 - len(calls)
        # The skills import is the same budget and the same visitor.
        spent = len(calls)
        assert client.get("/api/resume/github/student", headers={"x-forwarded-for": "9.9.9.9"}).status_code == 429
        assert len(calls) == spent
        # Everyone else is still served.
        assert client.get("/api/resume/github/student/pull/lab/vision/1",
                          headers={"x-forwarded-for": "8.8.8.8"}).status_code == 404
    finally:
        main._rate_buckets.clear()


def test_an_answer_from_the_cache_does_not_spend_the_visitors_github_requests(github_returns, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from backend import main

    clock = [1_800_000_000.0]
    monkeypatch.setattr(main, "RATE_LIMIT_DISABLED", False)
    monkeypatch.setattr(main, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(main, "_last_purge", clock[0])
    monkeypatch.setattr(resume_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    main._rate_buckets.clear()
    calls = github_returns(_pull())
    client = TestClient(main.app)
    try:
        # One address, the same pull request looked up every minute for half an
        # hour: a shared campus address, or a student who reloads the page.
        answers = []
        for _ in range(30):
            answers.append(client.get("/api/resume/github/student/pull/lab/vision/8",
                                      headers={"x-forwarded-for": "9.9.9.9"}).status_code)
            clock[0] += 60
        assert answers == [200] * 30
        assert len(calls) == 2  # Asked again once, when the first answer was fifteen minutes old.
        # Arrivals are still counted by the minute, whatever the cache holds.
        burst = [client.get("/api/resume/github/student/pull/lab/vision/8",
                            headers={"x-forwarded-for": "9.9.9.9"}).status_code for _ in range(12)]
        assert burst == [200] * 10 + [429] * 2
        assert len(calls) == 3  # The second answer had just turned fifteen minutes old.
    finally:
        main._rate_buckets.clear()
