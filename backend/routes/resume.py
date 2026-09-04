from __future__ import annotations

import os
import re
import time

import httpx
from fastapi import APIRouter, HTTPException

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
_GITHUB_CACHE_MAX_ENTRIES = 512
_github_cache: dict[str, tuple[float, dict]] = {}

GITHUB_LANG_TO_SKILL = {
    "Python": "Python", "Java": "Java", "C++": "C++", "C": "C",
    "C#": "C#", "JavaScript": "JavaScript", "TypeScript": "TypeScript",
    "Rust": "Rust", "Go": "Go", "Kotlin": "Kotlin", "Swift": "Swift",
    "Ruby": "Ruby", "PHP": "PHP", "R": "R", "MATLAB": "MATLAB",
    "Shell": "Bash", "Jupyter Notebook": "Python", "HTML": "HTML/CSS",
    "CSS": "HTML/CSS", "Dockerfile": "Docker",
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

    skills: set[str] = set()
    topics: set[str] = set()
    repo_names: list[str] = []

    for repo in repos:
        if repo.get("fork"):
            continue
        lang = repo.get("language")
        if lang and lang in GITHUB_LANG_TO_SKILL:
            skills.add(GITHUB_LANG_TO_SKILL[lang])
        for topic in repo.get("topics", []):
            topics.add(topic)
        repo_names.append(repo.get("name", ""))

    topic_skill_map = {
        "machine-learning": "PyTorch", "deep-learning": "PyTorch",
        "react": "React", "nextjs": "Next.js", "vue": "Vue",
        "flask": "Flask", "django": "Django", "fastapi": "FastAPI",
        "docker": "Docker", "kubernetes": "Kubernetes",
        "aws": "AWS", "tensorflow": "TensorFlow",
        "pytorch": "PyTorch", "opencv": "OpenCV",
        "data-science": "pandas", "pandas": "pandas",
    }
    for t in topics:
        mapped = topic_skill_map.get(t.lower())
        if mapped:
            skills.add(mapped)

    payload = {
        "username": username,
        "extracted_skills": sorted(skills),
        "topics": sorted(topics),
        "repo_count": len([r for r in repos if not r.get("fork")]),
        "top_repos": repo_names[:10],
    }
    if len(_github_cache) >= _GITHUB_CACHE_MAX_ENTRIES:
        oldest = min(_github_cache, key=lambda key: _github_cache[key][0])
        _github_cache.pop(oldest, None)
    _github_cache[username.lower()] = (now, payload)
    return payload
