"""Explicit student confirmation for email contract fixtures (never production)."""
def confirmed_experience(texts):
    return {"version": 1, "resume_text": "", "entries": [
        {"id": f"experience-{i}", "revision": 1, "status": "confirmed",
         "text": text, "source": {"kind": "manual"}}
        for i, text in enumerate(texts)
    ]}
