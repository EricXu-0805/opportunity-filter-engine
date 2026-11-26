"""Replay M22's department-only false mismatch from the project root."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.matcher.ranker import _topic_alignment_penalty

# Only public matcher input fields are needed. The rendered production
# negative and independently published research areas are in source-check.json.
profile = {"research_interests_text": "machine learning, artificial intelligence, healthcare", "desired_fields": []}
department = "Electrical Engineering and Computer Sciences"
row = {
    "source": "ucb_eecs_faculty", "source_type": "faculty_research",
    "opportunity_type": "research", "record_kind": "faculty_contact",
    "department": department,
}
samples = (
    ("observed-department-only", [department.lower()], 1.0),
    ("short-department-only", ["computer science"], 1.0),
    ("concrete-aligned", ["machine learning", "healthcare analytics"], 1.0),
    ("concrete-unrelated", ["medieval manuscript conservation"], 0.8),
    ("department-plus-concrete-aligned", [department.lower(), "healthcare analytics"], 1.0),
    ("department-plus-concrete-unrelated", [department.lower(), "medieval manuscript conservation"], 0.8),
)
failed = []
for label, keywords, expected in samples:
    multiplier = _topic_alignment_penalty(profile, {**row, "id": label, "keywords": keywords})
    print(json.dumps({"case": label, "keywords": keywords, "actual": multiplier, "expected": expected}))
    if multiplier != expected:
        failed.append(label)
if failed:
    raise SystemExit("Topic-signal expectations failed: " + ", ".join(failed))
