"""Cold email generation with mailto: link support."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from backend.schemas import ColdEmailRequest, ColdEmailResponse, ProfileRequest
from src.recommender.cold_email import generate_cold_email

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def _load_opportunities() -> list[dict]:
    processed = DATA_DIR / "opportunities.json"
    if processed.exists():
        with open(processed, encoding="utf-8") as f:
            data = json.load(f)
            if data:
                return data

    examples = EXAMPLES_DIR / "sample_opportunities.json"
    if examples.exists():
        with open(examples, encoding="utf-8") as f:
            return json.load(f)

    return []


def _extract_subject_and_body(email_text: str) -> tuple[str, str]:
    """Split the generated email into subject line and body."""
    lines = email_text.strip().split("\n")
    subject = ""
    body_start = 0

    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line[len("Subject:"):].strip()
            body_start = i + 1
            break

    # Skip blank lines between subject and body
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1

    body = "\n".join(lines[body_start:]).strip()
    return subject, body


def _build_mailto_link(to: str, subject: str, body: str) -> str:
    """Build a mailto: link with pre-filled subject and body."""
    params = []
    if subject:
        params.append(f"subject={quote(subject)}")
    if body:
        params.append(f"body={quote(body)}")

    query = "&".join(params)
    return f"mailto:{quote(to)}?{query}" if query else f"mailto:{quote(to)}"


@router.post("/cold-email", response_model=ColdEmailResponse)
async def generate_email(request: ColdEmailRequest):
    """Generate a cold email for a specific opportunity with mailto: link."""
    opportunities = _load_opportunities()
    opp = next((o for o in opportunities if o["id"] == request.opportunity_id), None)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    profile_dict = request.profile.model_dump()
    email_text = generate_cold_email(profile_dict, opp)

    subject, body = _extract_subject_and_body(email_text)

    # Try to find PI email
    recipient_email = ""
    pi_name = opp.get("pi_name", "")
    contact_email = opp.get("contact_email", "")
    if contact_email:
        recipient_email = contact_email

    mailto_link = _build_mailto_link(recipient_email, subject, body)

    return ColdEmailResponse(
        subject=subject,
        body=body,
        recipient_email=recipient_email,
        mailto_link=mailto_link,
    )
