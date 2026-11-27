from __future__ import annotations

import os
import re
import time

import httpx
from fastapi import APIRouter, HTTPException

from backend.lib.github_contribution import GITHUB_LOGIN, GitHubPullSource, valid_repository

router = APIRouter()

# Unauthenticated GitHub allows 60 requests an hour for the whole service —
# one Render egress IP — and GITHUB_TOKEN is optional and set nowhere, so that
# is the live budget. `_billable_class` returns None for a GET, so this route
# draws on no global ceiling either; the per-IP bucket alone is not one, which
# is exactly why the LLM and email classes have global buckets. Once GitHub
# answers 403 every other student's profile step shows "GitHub import failed"
# for the rest of the hour, with their GitHub-derived skills quietly missing
# from the profile that feeds matching.
#
# The same username was re-fetched on every call. A short cache makes a
# re-import, a second device and a page revisit free, which is most of the
# traffic a profile step generates.
_GITHUB_CACHE_TTL_SECONDS = 900
# A pull request GitHub does not show is remembered too, as the refusal it
# earned: each retry of the same link used to cost another request. Shorter,
# because the student may be making the repository public.
_GITHUB_MISS_TTL_SECONDS = 300
_GITHUB_CACHE_MAX_ENTRIES = 512
_github_cache: dict[str, tuple[float, dict | str]] = {}

GITHUB_LANG_TO_SKILL = {
    "Python": "Python", "Java": "Java", "C++": "C++", "C": "C",
    "C#": "C#", "JavaScript": "JavaScript", "TypeScript": "TypeScript",
    "Rust": "Rust", "Go": "Go", "Kotlin": "Kotlin", "Swift": "Swift",
    "Ruby": "Ruby", "PHP": "PHP", "R": "R", "MATLAB": "MATLAB",
    "Shell": "Bash", "Jupyter Notebook": "Python", "HTML": "HTML/CSS",
    "CSS": "HTML/CSS", "Dockerfile": "Docker",
}

# A topic counts only where it NAMES the tool. "machine-learning",
# "deep-learning" and "data-science" say what a repo is about, not what it is
# built with: mapping them to PyTorch and pandas put a library on the profile
# that no repo states, and the import showed it as found on GitHub.
GITHUB_TOPIC_TO_SKILL = {
    "react": "React", "nextjs": "Next.js", "vue": "Vue",
    "flask": "Flask", "django": "Django", "fastapi": "FastAPI",
    "docker": "Docker", "kubernetes": "Kubernetes",
    "aws": "AWS", "tensorflow": "TensorFlow",
    "pytorch": "PyTorch", "opencv": "OpenCV", "pandas": "pandas",
}


@router.get("/resume/github/{username}")
async def parse_github_profile(username: str):
    if not re.match(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$", username):
        raise HTTPException(status_code=400, detail="Invalid GitHub username format")

    now = time.monotonic()
    cached = _github_cache.get(username.lower())
    if cached and now - cached[0] < _GITHUB_CACHE_TTL_SECONDS:
        return cached[1]

    headers = {"Accept": "application/vnd.github.v3+json"}
    gh_token = os.environ.get("GITHUB_TOKEN")
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            resp = await client.get(
                f"https://api.github.com/users/{username}/repos",
                params={"per_page": 30, "sort": "updated"},
                headers=headers,
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="GitHub user not found")
            if resp.status_code == 403:
                reset = resp.headers.get("X-RateLimit-Reset", "")
                detail = "GitHub API rate limit exceeded"
                if reset:
                    detail += f" (resets at unix ts {reset})"
                raise HTTPException(status_code=429, detail=detail)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="GitHub API error")
            repos = resp.json()
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail="GitHub API timeout") from e

    topics: set[str] = set()
    repo_names: list[str] = []
    # Each skill keeps the repo field that named it — the first one, in
    # GitHub's most-recently-updated order — so the form can show the student
    # what GitHub actually says instead of a bare skill name.
    evidence: dict[str, dict[str, str]] = {}

    for repo in repos:
        if repo.get("fork"):
            continue
        name = repo.get("name", "")
        lang = repo.get("language")
        skill = GITHUB_LANG_TO_SKILL.get(lang) if lang else None
        if skill:
            evidence.setdefault(skill, {
                "skill": skill, "repo": name, "field": "language", "value": lang,
            })
        for topic in repo.get("topics", []):
            topics.add(topic)
            skill = GITHUB_TOPIC_TO_SKILL.get(topic.lower())
            if skill:
                evidence.setdefault(skill, {
                    "skill": skill, "repo": name, "field": "topic", "value": topic,
                })
        repo_names.append(name)

    payload = {
        "username": username,
        "extracted_skills": sorted(evidence),
        "skill_evidence": [evidence[skill] for skill in sorted(evidence)],
        "topics": sorted(topics),
        "repo_count": len([r for r in repos if not r.get("fork")]),
        "top_repos": repo_names[:10],
    }
    return _remember(username.lower(), payload, now)


def _remember(key: str, payload: dict | str, now: float) -> dict | str:
    if len(_github_cache) >= _GITHUB_CACHE_MAX_ENTRIES:
        oldest = min(_github_cache, key=lambda item: _github_cache[item][0])
        _github_cache.pop(oldest, None)
    _github_cache[key] = (now, payload)
    return payload


@router.get("/resume/github/{username}/pull/{owner}/{repository}/{number}")
async def github_pull_contribution(username: str, owner: str, repository: str, number: int):
    full_name = f"{owner}/{repository}"
    if (len(username) > 39 or not re.fullmatch(GITHUB_LOGIN, username)
            or not valid_repository(full_name) or not 0 < number <= 9007199254740991):
        raise HTTPException(400, "Invalid GitHub profile or pull request")
    # GitHub's answer is about the pull request, whoever asks, so it is kept
    # under the pull request and the author is compared on every lookup.
    key = f"{full_name}/{number}".lower()
    now = time.monotonic()
    cached = _github_cache.get(key)
    if cached and now - cached[0] < (_GITHUB_CACHE_TTL_SECONDS if isinstance(cached[1], dict)
                                     else _GITHUB_MISS_TTL_SECONDS):
        found = cached[1]
    else:
        # Only public evidence is eligible, including when the service happens
        # to have a token for its existing skills endpoint.
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{full_name}/pulls/{number}",
                    headers={"Accept": "application/vnd.github+json"},
                )
        except httpx.RequestError as exc:
            raise HTTPException(502, "GitHub could not be reached") from exc
        if response.status_code in (403, 429):
            raise HTTPException(429, "GitHub request unavailable; try again later")
        if response.status_code in (301, 302, 307, 308, 404):
            found = "Use the current URL of a public pull request"
        elif response.status_code != 200:
            raise HTTPException(502, "GitHub API error")
        else:
            try:
                pull = response.json()
                base = pull["base"]["repo"]
                head = pull["head"]["repo"]  # May be null after the contributor deletes their fork.
                if (base["private"] is not False or base["full_name"].lower() != full_name.lower()
                        or pull["number"] != number):
                    found = "Public pull request does not match this repository"
                else:
                    source = GitHubPullSource(
                        kind="github", repository=base["full_name"],
                        head_repository=head["full_name"] if head and head.get("private") is False else None,
                        number=number, author=pull["user"]["login"], title=pull["title"])
                    pull_id = pull["id"]
                    if type(pull_id) is not int or not 0 < pull_id <= 9007199254740991:
                        raise ValueError("invalid pull request id")
                    found = {"id": f"github-pr:{pull_id}", "source": source.model_dump()}
            except (KeyError, AttributeError, TypeError, ValueError) as exc:
                raise HTTPException(502, "GitHub returned incomplete pull request evidence") from exc
        _remember(key, found, now)
    if isinstance(found, str):
        raise HTTPException(404, found)
    if found["source"]["author"].lower() != username.lower():
        raise HTTPException(422, "Pull request author does not match the entered GitHub profile")
    return found
