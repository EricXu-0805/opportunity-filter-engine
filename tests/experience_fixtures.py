"""Explicit student confirmation for email contract fixtures (never production)."""
import hashlib


def confirmed_experience(texts):
    return {"version": 1, "resume_text": "", "entries": [
        {"id": f"experience-{i}", "revision": 1, "status": "confirmed",
         "text": text, "source": {"kind": "manual"}}
        for i, text in enumerate(texts)
    ]}


def resume_line_experience(resume_text, *, unconfirmed=()):
    """One confirmed entry per printed line, as the PDF import proposes them."""
    signature = hashlib.sha256(resume_text.encode()).hexdigest()
    entries, start = [], 0
    for line in resume_text.split("\n"):
        end = start + len(line)
        if line.strip():
            entries.append({"id": f"line-{start}", "revision": 1,
                            "status": "rejected" if line in unconfirmed else "confirmed", "text": line,
                            "source": {"kind": "resume", "signature": signature, "quote": line,
                                       "start": start, "end": end}})
        start = end + 1
    return {"version": 1, "resume_text": resume_text, "entries": entries}
