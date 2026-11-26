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

    def install(repos: list[dict]):
        class _Resp:
            status_code = 200
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
    pull["base"]["repo"]["private"] = False
    pull["head"]["repo"] = None
    assert asyncio.run(resume_module.github_pull_contribution("student", "lab", "vision", 8))["source"]["head_repository"] is None


def test_imported_experience_requires_confirmation_in_both_writing_paths(github_returns):
    from backend.lib.experience_evidence import select_experience
    from backend.lib.target_resume_ai_validation import active, validate_entries
    from backend.schemas import ExperienceEvidence, SelectedExperience

    github_returns(_pull())
    receipt = asyncio.run(resume_module.github_pull_contribution("student", "lab", "vision", 8))
    entry = {**receipt, "revision": 1, "status": "candidate", "text": "I opened a pull request in lab/vision."}
    for status in ("candidate", "confirmed", "rejected", "withdrawn"):
        entry["status"] = status
        validate_entries([entry])
        assert active(entry, "", "") is (status == "confirmed")
        model = ExperienceEvidence(version=1, resume_text="", entries=[entry])
        selected = select_experience(model, {}).selected
        assert bool(selected) is (status == "confirmed")
        if selected:
            assert SelectedExperience.model_validate(selected[0]).source == model.entries[0].source
