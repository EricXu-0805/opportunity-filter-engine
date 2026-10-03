"""Conservative EN/ZH claim locks, in addition to token/quantity grounding.

This is not semantic entailment. Sensitive source clauses must remain verbatim
apart from whitespace/case and may move; ambiguous paraphrases are refused for
manual review rather than silently upgrading attribution or publication status.
"""
from __future__ import annotations

import re

from backend.lib.email_experience_attribution import (
    collapse_whitespace,
    experience_attribution_violations,
)

# Bump independently of the wire/pipeline version when source checks change.
SOURCE_CHECK_VERSION = "target-resume-source-checks-v4"

# Ordinary entries stay below this ceiling: at 6000 characters, English bullets
# give about 80 clauses, Chinese prose about 130 and very short Chinese
# sentences about 330. A long list of short items separated by '；' or ';' can
# pass it. Past the ceiling the check fails closed (an upgrade is reported), so
# the caller keeps the original.
_MAX_CLAUSES = 400

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
    # A negated first clause must not exempt an affirmative claim after an
    # explicit contrast: "not accepted, but later accepted" is two claims.
    # Keep this a bounded EN/ZH rule, not a general semantic parser. Splitting
    # also permits truthful "did not lead, but reviewed" clauses to reorder.
    boundaries = (
        r"(?<!\d)\.(?!\d)|[!?;。！？；\n]+"
        r"|[，,]?\s*\b(?:but|however|nevertheless)\b\s*[,，]?\s*"
        # A bare 'yet' can be temporal ('not yet accepted'), not a contrast.
        r"|[，,]\s*\byet\b\s*[,，]?\s*"
        r"|[，,]?\s*(?:但是|但|然而|不过|卻|却)\s*[,，]?\s*"
    )
    return [part.strip() for part in re.split(boundaries, text, flags=re.I) if part.strip()]


def personal_actions(text, clause_list=None):
    found = set()
    for clause in (clauses(text) if clause_list is None else clause_list):
        if NEGATION.search(clause) or (TEAM.search(clause) and not PERSONAL.search(clause)):
            continue
        # Résumé fragments with no subject are personal claims too.
        for name, pattern in ACTIONS.items():
            if re.search(pattern, clause, re.I):
                found.add(name)
    return found


def publication_stages(text, clause_list=None):
    return {name for clause in (clauses(text) if clause_list is None else clause_list) if not NEGATION.search(clause)
            for name, pattern in STAGES.items() if re.search(pattern, clause, re.I)}


def claim_upgrade_detected(proposed, original):
    proposed, original = collapse_whitespace(proposed), collapse_whitespace(original)
    if normalized(proposed) == normalized(original):
        return False
    proposed_normal = normalized(proposed)
    proposed_clauses, original_clauses = clauses(proposed), clauses(original)
    # Fail closed when either side is past the clause ceiling: an unverifiable
    # rewrite keeps the original rather than being approved unchecked.
    if len(proposed_clauses) > _MAX_CLAUSES or len(original_clauses) > _MAX_CLAUSES:
        return True
    # Retain precise qualifiers/attribution, not merely one negation word
    # somewhere else in the new text. This intentionally rejects some valid
    # paraphrases; the original remains available for the student's review.
    for clause in original_clauses:
        if (NEGATION.search(clause) or TEAM.search(clause) or PUBLICATION.search(clause)) and normalized(clause) not in proposed_normal:
            return True
    if personal_actions(proposed, proposed_clauses) - personal_actions(original, original_clauses):
        return True
    if publication_stages(proposed, proposed_clauses) - publication_stages(original, original_clauses):
        return True
    # Compare only this original entry. A shared keyword or number in another
    # project, the target, or editable wording cannot establish who did what.
    # Resume bullets commonly omit "I"; opt into that finite English grammar
    # without changing the email checker's default treatment of fragments.
    return bool(experience_attribution_violations(proposed, [original], allow_subjectless_claims=True))


def supported_claim_upgrade_detected(proposed, originals):
    """Finite checks over explicit source entries; never collapse their attribution.

    Shared activity membership permits consulting selected entries, not moving a
    number, action, actor or qualifier between their clauses. Ambiguous syntax
    remains outside this finite EN/ZH checker and is not a semantic guarantee.
    """
    if len(originals) == 1:
        return claim_upgrade_detected(proposed, originals[0])
    proposed = collapse_whitespace(proposed)
    originals = [collapse_whitespace(original) for original in originals]
    proposed_normal = normalized(proposed)
    proposed_clauses = clauses(proposed)
    original_clauses = [clauses(original) for original in originals]
    # Fail closed when any side is past the clause ceiling (see claim_upgrade_detected).
    if len(proposed_clauses) > _MAX_CLAUSES or any(len(parts) > _MAX_CLAUSES for parts in original_clauses):
        return True
    for parts in original_clauses:
        for clause in parts:
            if (NEGATION.search(clause) or TEAM.search(clause) or PUBLICATION.search(clause)) and normalized(clause) not in proposed_normal:
                return True
    if personal_actions(proposed, proposed_clauses) - set().union(*(personal_actions(o, parts) for o, parts in zip(originals, original_clauses, strict=True))):
        return True
    if publication_stages(proposed, proposed_clauses) - set().union(*(publication_stages(o, parts) for o, parts in zip(originals, original_clauses, strict=True))):
        return True
    # The structural path proves only the closed surface forms below, preserving
    # the complete actor/action/object/quantity text for each separate clause.
    # No zero-findings fallback for multiple sources: an unrecognized action
    # must not borrow a number/object from the next entry. Unknown paraphrases
    # stay available as originals for manual review, rather than being approved.
    return not supported_surface_forms(proposed, originals)


# Inflections and one explicit execution alias, not a skills/semantic thesaurus.
_SURFACE_VERBS = {
    'write': 'write', 'wrote': 'write', 'written': 'write',
    'build': 'build', 'built': 'build', 'develop': 'develop', 'developed': 'develop',
    'implement': 'implement', 'implemented': 'implement', 'create': 'create', 'created': 'create',
    'analyze': 'analyze', 'analyzed': 'analyze', 'analyse': 'analyze', 'analysed': 'analyze',
    'test': 'test', 'tested': 'test', 'evaluate': 'evaluate', 'evaluated': 'evaluate',
    'collect': 'collect', 'collected': 'collect', 'process': 'process', 'processed': 'process',
    'measure': 'measure', 'measured': 'measure', 'design': 'design', 'designed': 'design',
    'run': 'execute', 'ran': 'execute', 'execute': 'execute', 'executed': 'execute',
}
_SURFACE_ACTION = '|'.join(sorted(_SURFACE_VERBS, key=len, reverse=True))
_SURFACE_ACTOR = r'(?:my team|our team|the team|we|i)'


def supported_surface_forms(proposed, originals):
    """Match complete source clauses under bounded method placement/inflections.

    A tool prefix is recognized only when an explicitly stated single-token
    method exists in the selected sources; each resulting full clause must still
    match one source clause. A tool from another clause cannot authenticate it.
    Unknown changed syntax fails closed; exact source clauses remain available.
    """
    tools = set()
    for source in originals:
        tools.update(match.casefold() for match in re.findall(r'\b(?:using|with) ([a-z][a-z0-9+#.-]*)\b', source, re.I))
        tools.update(match.casefold() for match in re.findall(r'\b(?:use|used) ([a-z][a-z0-9+#.-]*) to\b', source, re.I))

    def forms(value):
        values = []
        for sentence in re.split(r'(?<!\d)\.(?!\d)|[!?;。！？；\n]+', value):
            actor = 'i'
            for part in re.split(r'\s+(?:and|then)\s+(?=(?:' + _SURFACE_ACTOR + r'\s+)?(?:' + _SURFACE_ACTION + r')\b)', sentence, flags=re.I):
                clause = normalized(part).strip(' ,')
                if not clause:
                    continue
                clause = re.sub(r'^my role:\s*', '', clause)
                subject = re.match(r'^(' + _SURFACE_ACTOR + r')\s+', clause)
                if subject:
                    actor = subject[1]; clause = clause[subject.end():]
                method = re.fullmatch(r'(?:use|used) ([a-z][a-z0-9+#.-]*) to (' + _SURFACE_ACTION + r') (.+)', clause)
                if method:
                    clause = f'{method[2]} {method[3]} using {method[1]}'
                match = re.fullmatch(r'(' + _SURFACE_ACTION + r') (.+)', clause)
                if not match:
                    values.append(('exact', actor, clause)); continue
                action, objects = _SURFACE_VERBS[match[1]], match[2]
                first, separator, rest = objects.partition(' ')
                if separator and first in tools:
                    objects = f'{rest} using {first}'
                # with/using are equivalent only in the explicit trailing-method
                # slot. Complete object text and every quantity remain unchanged.
                # A tool has no space, so only the text after the last ' with '
                # can name it.
                head, separator, tool = objects.rpartition(' with ')
                if separator and tool in tools:
                    objects = head + ' using ' + tool
                values.append((action, actor, objects))
        return values

    permitted = set()
    for source in originals:
        for action, actor, objects in forms(source):
            permitted.add((action, actor, objects))
            head, separator, tool = objects.rpartition(' using ')
            if action != 'exact' and separator and tool in tools:
                permitted.add((action, actor, head))
    proposed_forms = forms(proposed)
    return bool(proposed_forms) and all(item in permitted for item in proposed_forms)
