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
