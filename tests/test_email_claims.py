"""Bounded M32 claim checks: genuine evidence is not a license to overstate."""

import pytest

from backend.lib.email_claims import skill_level_violations, unsupported_action_claims


@pytest.mark.parametrize("text", [
    "I have attached my CV.", "I've enclosed my resume.", "I attached my résumé.",
    "I am attaching my transcript.", "Please find attached my CV.",
    "Attached is my resume.", "My CV is attached.", "Resume attached.",
    "Please see the enclosed portfolio.", "My transcript has been attached.",
    "I read your paper.", "I've carefully read your recent paper.",
    "I reviewed your publications.", "I have studied your research.",
    "After reading your paper, I would like to learn more.",
    "Having reviewed your recent work, I am interested in learning more.",
    "I read the full text of your paper.", "I finished reading your paper before writing.",
    "After carefully reading your paper, I have a question.", "I have read through your recent paper.",
    "I included my resume as an attachment.", "My resume has been included with this email.",
])
def test_unsupported_completed_actions(text):
    assert unsupported_action_claims(text)


@pytest.mark.parametrize("text", [
    "I have not attached my CV.", "I haven't attached my resume.", "No resume is attached.",
    "I have no resume attached.", "My CV is not attached.",
    "I can attach my CV on request.", "I will attach my CV.",
    "I would be happy to share my resume upon request.", "Your attached paper caught my attention.",
    "I have not read your paper.", "I haven't reviewed your article.",
    "I would like to read your paper.", "If I read your paper, I could ask a more specific question.",
    "I will write again after reading your paper.", "Your paper caught my attention.",
    "I read about your work on your lab website.", "I read your lab description.",
    "I am interested in your paper's abstract.",
    "I attached a force sensor to the robotic arm.", "I enclosed the detector in a protective casing.",
    "I have not finished reading your paper.", "I will finish reading your paper.",
    "After carefully reading your paper, I will write again.",
    "I will write again after having read your paper.",
    "I can include my resume as an attachment on request.", "My resume has not been included with this email.",
])
def test_negation_future_and_metadata_reference_are_not_completed_actions(text):
    assert unsupported_action_claims(text) == []


@pytest.mark.parametrize("text,levels", [
    ("I have experience with Python.", {"Python": "beginner"}),
    ("I have hands-on experience with Python.", {"Python": "beginner"}),
    ("I'm proficient in Python.", {"Python": "beginner"}),
    ("My expertise is in Python.", {"Python": "experienced"}),
    ("I am an expert in Python.", {"Python": "experienced"}),
    ("I have strong proficiency in Python.", {"Python": "experienced"}),
    ("I am an experienced Python programmer.", {"Python": "beginner"}),
    ("I have Python experience.", {"Python": "beginner"}),
    ("I have Python expertise.", {"Python": "experienced"}),
    ("My Python skills are advanced.", {"Python": "experienced"}),
    ("I am expert in C++.", {"C++": "beginner"}),
    ("I am proficient in Node.js.", {"Node.js": "beginner"}),
    ("I have experience with Python and PyTorch.", {"Python": "expert", "PyTorch": "beginner"}),
    ("I am expert in Python and have experience with Rust.", {"Python": "expert", "Rust": "beginner"}),
    ("I am an expert in robotics.", {}),
    ("I have experience with C++.", {"C": "expert", "C++": "beginner"}),
    ("I have experience with C#.", {"C": "expert", "C#": "beginner"}),
])
def test_skill_levels_cannot_be_upgraded(text, levels):
    assert skill_level_violations(text, levels)


@pytest.mark.parametrize("text,levels", [
    ("I have experience with Python.", {"Python": "experienced"}),
    ("I am proficient in Python.", {"Python": "experienced"}),
    ("I am an expert in Python.", {"Python": "expert"}),
    ("I have foundational exposure to Python.", {"Python": "beginner"}),
    ("I have no experience with Python.", {"Python": "beginner"}),
    ("I am not an expert in Python.", {"Python": "beginner"}),
    ("I hope to become an expert in Python.", {"Python": "beginner"}),
    ("Your expertise in Python interests me.", {"Python": "beginner"}),
    ("I hope to learn from your experience with Python.", {"Python": "beginner"}),
    ("I built a Python parser.", {"Python": "beginner"}),
    ("One example of my experience: Built a Python parser.", {"Python": "beginner"}),
    ("I have experience with Python, not Rust.", {"Python": "experienced", "Rust": "beginner"}),
    ("I am expert in Python and have foundational exposure to Rust.", {"Python": "expert", "Rust": "beginner"}),
    ("I am expert in Python and a beginner in Rust.", {"Python": "expert", "Rust": "beginner"}),
    ("I have experience with Python and hope to learn Rust.", {"Python": "experienced", "Rust": "beginner"}),
    ("I have experience with Python, with basic knowledge of Rust.", {"Python": "experienced", "Rust": "beginner"}),
    ("I have experience with Python and introductory coursework in Rust.", {"Python": "experienced", "Rust": "beginner"}),
    ("I am expert in Python and not experienced in Rust.", {"Python": "expert", "Rust": "beginner"}),
    ("I have experience with C++.", {"C": "beginner", "C++": "experienced"}),
    ("I have experience with C#.", {"C": "beginner", "C#": "experienced"}),
])
def test_levels_do_not_grade_project_actions_or_borrow_other_speakers(text, levels):
    assert skill_level_violations(text, levels) == []
