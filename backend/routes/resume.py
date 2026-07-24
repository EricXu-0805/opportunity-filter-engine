from __future__ import annotations

import os
import re

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()

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

    return {
        "username": username,
        "extracted_skills": sorted(skills),
        "topics": sorted(topics),
        "repo_count": len([r for r in repos if not r.get("fork")]),
        "top_repos": repo_names[:10],
    }
