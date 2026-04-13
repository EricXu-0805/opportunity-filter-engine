from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.schemas import ColdEmailRequest, ColdEmailResponse, ProfileRequest
from src.recommender.cold_email import generate_cold_email, generate_variants

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


@router.post("/cold-email/variants")
async def generate_email_variants(request: ColdEmailRequest):
    opportunities = _load_opportunities()
    opp = next((o for o in opportunities if o["id"] == request.opportunity_id), None)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    profile_dict = request.profile.model_dump()
    raw_variants = generate_variants(profile_dict, opp)

    recipient_email = opp.get("contact_email", "")

    results = []
    for v in raw_variants:
        subject, body = _extract_subject_and_body(v["text"])
        results.append({
            "id": v["id"],
            "label": v["label"],
            "subject": subject,
            "body": body,
            "recipient_email": recipient_email,
            "mailto_link": _build_mailto_link(recipient_email, subject, body),
        })

    return {"variants": results}


class EmailRefineRequest(BaseModel):
    current_body: str
    instruction: str
    subject: str = ""


@router.post("/cold-email/refine")
async def refine_email(request: EmailRefineRequest):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _local_refine(request.current_body, request.instruction)

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You are an email editor for a student writing cold emails to professors. "
                    "Edit the email according to the user's instruction. "
                    "Return ONLY the edited email body, no explanations."
                )},
                {"role": "user", "content": (
                    f"Current email:\n\n{request.current_body}\n\n"
                    f"Instruction: {request.instruction}\n\n"
                    "Return the edited email body only."
                )},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        edited = resp.choices[0].message.content.strip()
        return {"body": edited, "method": "llm"}
    except Exception as e:
        return _local_refine(request.current_body, request.instruction)


def _local_refine(body: str, instruction: str) -> dict:
    lower = instruction.lower()
    edited = body

    if any(kw in lower for kw in ["formal", "professional"]):
        edited = edited.replace("I would love", "I would greatly appreciate")
        edited = edited.replace("I am a fast learner", "I am committed to continuous professional development")
        edited = edited.replace("Best regards", "Respectfully")
    elif any(kw in lower for kw in ["short", "concise", "brief"]):
        lines = edited.split("\n")
        edited = "\n".join(l for l in lines
                          if "fast learner" not in l and "eager to pick up" not in l)
    elif any(kw in lower for kw in ["enthus", "excit", "energy"]):
        edited = edited.replace("I am very interested", "I am truly excited about")
        edited = edited.replace("I really enjoyed", "I was fascinated by")
        edited = edited.replace("I would love the chance", "I would be thrilled at the opportunity")

    method = "local"
    return {"body": edited, "method": method}
