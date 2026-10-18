"""Bounded M32 claim checks: genuine evidence is not a license to overstate."""

import pytest

from backend.lib.email_claims import skill_level_violations, unchosen_paper_claims, unsupported_action_claims
from backend.lib.email_contact_context import paper_reading_sentence


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


READ = "I have read the full text of your paper “Grounded Models” (2025)."


def test_confirmed_reading_sentence_is_exempt_only_as_its_single_exact_occurrence():
    body = f"Dear Pat Lee,\n\n{READ}\n\nCould we talk?"
    assert unsupported_action_claims(body) == ["unsupported completed-reading claim"]
    assert unsupported_action_claims(body, confirmed_reading_sentence=READ) == []
    assert unsupported_action_claims(READ + " " + READ, confirmed_reading_sentence=READ)
    other = READ.replace("Grounded Models", "Another Paper")
    assert unsupported_action_claims(other, confirmed_reading_sentence=READ)
    assert unsupported_action_claims(READ + " I read your recent articles.", confirmed_reading_sentence=READ)


# M129: reading the whole paper, going through it, or reading its abstract is
# a reading claim too; a whole field, a lab or an abstract idea is not.
@pytest.mark.parametrize("text", [
    "After reading your whole paper, I have a question.", "I have read the abstract of your paper as well.",
    "I read your whole paper.", "Having read your whole article, I am curious.",
    "I have carefully read through your whole work.", "I've read the abstract of this paper.",
    "I read the abstracts of your recent papers.", "I went through your entire paper.",
    "I have gone through your whole article.", "After going through your full paper, I wondered.",
    "I went through the full text of your paper.", "I went through the abstract of your work.",
    "I went through your paper.",
])
def test_whole_paper_and_abstract_reading_are_completed_reading(text):
    assert unsupported_action_claims(text) == ["unsupported completed-reading claim"]


@pytest.mark.parametrize("text", [
    "I have read about the whole field.", "I studied your entire lab website.", "I read an abstract idea.",
    "I read the abstract submitted to the conference.", "I went through a study abroad program.",
    "I went through the whole research process.", "I went through the entire application.",
    "Your entire lab works on this.", "I am interested in the abstract of your paper.",
    "I would like to read your whole paper.", "I will go through your entire paper.",
    "I have not read the abstract of your paper.", "If I read your whole paper, I could ask more.",
])
def test_whole_and_abstract_phrases_that_claim_no_reading_are_accepted(text):
    assert unsupported_action_claims(text) == []


def _confirmed(level):
    return paper_reading_sentence({"paper_reading": {"level": level, "title": "Grounded Models", "year": 2025}}) if level else None


WHOLE = "After reading your whole paper, I have a question about its method."
ABSTRACT_TOO = "I have read the abstract of your paper as well."


@pytest.mark.parametrize("level,claim", [
    (None, WHOLE), (None, ABSTRACT_TOO), ("title_only", WHOLE), ("title_only", ABSTRACT_TOO), ("abstract", WHOLE),
])
def test_a_reading_claim_above_the_confirmed_level_is_refused(level, claim):
    sentence = _confirmed(level)
    body = f"Dear Pat Lee,\n\n{sentence or ''} {claim}\n\nCould we talk?"
    assert unsupported_action_claims(body, confirmed_reading_sentence=sentence) == ["unsupported completed-reading claim"]


@pytest.mark.parametrize("level,claim", [
    ("abstract", ABSTRACT_TOO), ("full_text", WHOLE), ("full_text", ABSTRACT_TOO),
    ("full_text", "I went through your entire article."), ("full_text", "After reading the paper, I have a question."),
])
def test_a_reading_claim_about_the_paper_at_or_below_the_confirmed_level_is_accepted(level, claim):
    sentence = _confirmed(level)
    assert unsupported_action_claims(f"Dear Pat Lee,\n\n{sentence} {claim}\n\nCould we talk?",
                                     confirmed_reading_sentence=sentence) == []


@pytest.mark.parametrize("claim", [
    "I read your recent paper.", "I read your papers.", "I went through your whole work.",
    "I read the abstracts of your papers.", "After reading your paper I read your recent articles.",
])
def test_full_text_confirmation_never_covers_another_paper_or_a_body_of_work(claim):
    sentence = _confirmed("full_text")
    assert unsupported_action_claims(f"{sentence} {claim}", confirmed_reading_sentence=sentence)
    # Repeated or reworded, the confirmed sentence authorizes nothing.
    assert unsupported_action_claims(f"{sentence} {sentence} {WHOLE}", confirmed_reading_sentence=sentence)
    assert unsupported_action_claims(f"{sentence[:-1]} {WHOLE}", confirmed_reading_sentence=sentence)


def test_confirmed_reading_exemption_never_covers_an_attachment_claim():
    exempted = READ + " I have attached my CV."
    assert unsupported_action_claims(exempted, confirmed_reading_sentence=exempted) == ["unsupported attachment claim"]


# M33 (owner decision 2026-10-12): a reply may not quote the full title of a
# verified paper the student did not choose, unless the student supplied it.
TITLES = ["Grounded Models for Robot Planning", "Sparse Nets", "Learning What’s Next — A Survey?", "Consent & Causation"]
UNCHOSEN = ["names a paper the student did not choose"]


@pytest.mark.parametrize("text", [
    'Your recent paper "Grounded Models for Robot Planning" (2026) is on this topic.',
    "Your paper “grounded  models for robot planning.” is on this topic.",
    "Your paper ‘Grounded Models for Robot\nPlanning,’ is on this topic.",
    "Your paper 'Grounded Models for Robot Planning' is on this topic.",
    'Your survey "Learning What\'s Next - A Survey?" is on this topic.',
])
def test_a_quoted_full_title_the_student_did_not_choose_is_rejected(text):
    assert unchosen_paper_claims(text, TITLES) == UNCHOSEN


@pytest.mark.parametrize("text", [
    # Unquoted, partial or longer quotations, a title under three words, and a
    # reaction to a paper are outside the rule (reactions are left to the prompt).
    "Grounded models for robot planning is close to my interests.",
    'Your paper "Grounded Models" is on this topic.',
    'The phrase "Grounded Models for Robot Planning and Control" is not that title.',
    "The lab's Grounded Models for Robot Planning' line is not a quotation.",
    'Your paper "Sparse Nets" is on this topic.',
    # "&" has no letter or digit, so this title has two words.
    'Your paper "Consent & Causation" is on this topic.',
    "Your paper caught my attention.", "I was impressed by your recent paper.",
])
def test_anything_but_a_quoted_full_title_of_three_words_is_outside_the_rule(text):
    assert unchosen_paper_claims(text, TITLES) == []


@pytest.mark.parametrize("student_text", [
    "Reproduced the experiments of “Grounded Models for Robot Planning” in PyTorch.",
    "grounded models for robot planning",
    "Mention your paper 'GROUNDED MODELS FOR ROBOT PLANNING'.",
])
def test_a_title_the_student_supplied_may_be_quoted(student_text):
    text = 'Your paper "Grounded Models for Robot Planning" is on this topic.'
    assert unchosen_paper_claims(text, TITLES, student_text=student_text) == []
    assert unchosen_paper_claims(text, TITLES, student_text="robot planning") == UNCHOSEN


def test_only_the_chosen_paper_may_be_quoted():
    chosen = TITLES[0]
    read = "I have read the abstract of your paper “Grounded Models for Robot Planning” (2026)."
    assert unchosen_paper_claims(read, TITLES, chosen_title=chosen) == []
    assert unchosen_paper_claims(read + " I mean “Grounded Models for Robot Planning”.", TITLES,
                                 chosen_title=chosen) == []
    other = read + " Your survey “Learning What’s Next – A Survey?” is related."
    assert unchosen_paper_claims(other, TITLES, chosen_title=chosen) == UNCHOSEN
    assert unchosen_paper_claims(other, TITLES, chosen_title=chosen, student_text="Learning What's Next - A Survey") == []
    assert unchosen_paper_claims(read, TITLES) == UNCHOSEN
    # A title inside the chosen one's quotation is not quoted by it; one quoted whole is.
    assert unchosen_paper_claims(read, ["Models for Robot Planning", chosen], chosen_title=chosen) == []
    assert unchosen_paper_claims(read, ["Models for Robot Planning", chosen],
                                 chosen_title="Models for Robot Planning") == UNCHOSEN


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


def test_a_title_inside_the_chosen_title_does_not_count():
    inner = TITLES[0]
    titles = [inner, f'Author response for "{inner}"', f"“{inner}”: A Reply"]
    for chosen in titles[1:]:
        read = f"I have read the abstract of your paper “{chosen}” (2026)."
        assert unchosen_paper_claims(read, titles, chosen_title=chosen) == []
        # Compared after the same normalisation as every title.
        assert unchosen_paper_claims(read.upper().replace('"', "“"), titles, chosen_title=chosen) == []
        # The inner title quoted on its own still counts.
        assert unchosen_paper_claims(f"{read} Your paper “{inner}” is related.", titles, chosen_title=chosen) == UNCHOSEN
    # With the inner paper chosen, the outer title quoted whole is another paper.
    read = f"I have read the abstract of your paper “{inner}” (2026)."
    assert unchosen_paper_claims(read, titles, chosen_title=inner) == []
    assert unchosen_paper_claims(f"{read} Your “{titles[1]}” is related.", titles, chosen_title=inner) == UNCHOSEN
