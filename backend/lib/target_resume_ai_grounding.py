"""Conservative EN/ZH claim locks, in addition to token/quantity grounding.

This is not semantic entailment. Sensitive source clauses must remain verbatim
apart from whitespace/case and may move; ambiguous paraphrases are refused for
manual review rather than silently upgrading attribution or publication status.
"""
from __future__ import annotations

import re

NEGATION = re.compile(r"\b(?:not|never|no|without|only)\b|\b\w+n['’]t\b|没有|并非|尚未|从未|未经|仅|只|未|不(?:曾|会|能|是|负责|主导|带领|独立|领导|参与|承担|完成|接受|录用|发表)", re.I)
TEAM = re.compile(r"\b(?:team|teammates?|we|our|collaborat\w*)\b|团队|小组|我们|共同|协作|合作", re.I)
PUBLICATION = re.compile(r"\b(?:submitted|submission|under review|accepted|acceptance|published|publication|preprint|rejected|withdrawn)\b|投稿|提交|审稿|评审|录用|发表|出版|预印本|拒稿|撤稿", re.I)
PERSONAL = re.compile(r"\b(?:i|my|personally|independently)\b|本人|我(?!们)|独立|个人", re.I)
ACTIONS = {
    "lead": r"\b(?:lead|led|leading|leader|leadership|managed|headed)\b|主导|带领|领导|牵头",
    "own": r"\b(?:owned|ownership|responsible)\b|负责|承担",
    "build": r"\b(?:built|build|developed|implemented|created)\b|开发|构建|实现|搭建|完成",
    "design": r"\b(?:designed|design)\b|设计",
    "review": r"\b(?:reviewed|review)\b|审阅|检查",
    "independent": r"\b(?:independently|solely|alone|sole)\b|独立|独自|单独",
}
STAGES = {
    "accepted": r"\b(?:accepted|acceptance)\b|录用",
    "published": r"\b(?:published|publication)\b|发表|出版",
}


def normalized(text):
    return " ".join(text.lower().split()).strip()


def clauses(text):
    return [part.strip() for part in re.split(r"(?<!\d)\.(?!\d)|[!?;。！？；\n]+", text) if part.strip()]


def personal_actions(text):
    found = set()
    for clause in clauses(text):
        if NEGATION.search(clause) or (TEAM.search(clause) and not PERSONAL.search(clause)):
            continue
        # Résumé fragments with no subject are personal claims too.
        for name, pattern in ACTIONS.items():
            if re.search(pattern, clause, re.I):
                found.add(name)
    return found


def publication_stages(text):
    return {name for clause in clauses(text) if not NEGATION.search(clause)
            for name, pattern in STAGES.items() if re.search(pattern, clause, re.I)}


def claim_upgrade_detected(proposed, original):
    if normalized(proposed) == normalized(original):
        return False
    proposed_normal = normalized(proposed)
    # Retain precise qualifiers/attribution, not merely one negation word
    # somewhere else in the new text. This intentionally rejects some valid
    # paraphrases; the original remains available for the student's review.
    for clause in clauses(original):
        if (NEGATION.search(clause) or TEAM.search(clause) or PUBLICATION.search(clause)) and normalized(clause) not in proposed_normal:
            return True
    if personal_actions(proposed) - personal_actions(original):
        return True
    return bool(publication_stages(proposed) - publication_stages(original))
