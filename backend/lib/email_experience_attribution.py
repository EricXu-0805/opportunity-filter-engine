"""Bounded English attribution checks on already-confirmed experience entries.

This is not general entailment or a claim that the underlying work happened.
Only a finite set of concrete action clauses is recognized. Facts keep their
entry/clause, actor, explicit project scope and ordered object/quantity phrase;
a vocabulary or number elsewhere in the profile is never supporting evidence.
Unrecognized syntax, pronoun resolution and arbitrary paraphrases are outside
this check. Recognized paraphrases without a local supporting fact fail closed;
the caller can fall back to complete original quotations rather than guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# Inflection only, not a synonym/skills thesaurus. In particular helping,
# testing and building are different assertions, even about the same object.
_FORMS = {
    'build': ('build', 'built'), 'write': ('write', 'wrote', 'written'),
    'develop': ('develop', 'developed'), 'implement': ('implement', 'implemented'),
    'design': ('design', 'designed'), 'create': ('create', 'created'),
    'train': ('train', 'trained'), 'test': ('test', 'tested'),
    'evaluate': ('evaluate', 'evaluated'), 'analyze': ('analyze', 'analyzed', 'analyse', 'analysed'),
    'collect': ('collect', 'collected'), 'process': ('process', 'processed'),
    'change': ('change', 'changed'), 'improve': ('improve', 'improved'), 'increase': ('increase', 'increased'),
    'reduce': ('reduce', 'reduced'), 'achieve': ('achieve', 'achieved'),
    'reach': ('reach', 'reached'), 'lead': ('lead', 'led'),
    'manage': ('manage', 'managed'), 'deploy': ('deploy', 'deployed'),
    'maintain': ('maintain', 'maintained'), 'debug': ('debug', 'debugged'),
    'measure': ('measure', 'measured'), 'publish': ('publish', 'published'),
    'win': ('win', 'won'), 'earn': ('earn', 'earned'),
    'deliver': ('deliver', 'delivered'), 'use': ('use', 'used'),
}
_VERBS = {form: lemma for lemma, forms in _FORMS.items() for form in forms}
_VERB_PATTERN = '(?:' + '|'.join(sorted(_VERBS, key=len, reverse=True)) + ')'
_SUBJECT_PATTERN = r"(?:my\s+team|our\s+team|the\s+team|my\s+teammates?|my\s+colleagues?|my\s+supervisor|i|we)\b"
_SUBJECT = re.compile(_SUBJECT_PATTERN, re.I)
_ACTION = re.compile(r'^(' + _VERB_PATTERN + r')\b\s*(.*)$', re.I)
_SENTENCES = re.compile(r'(?<!\d)\.(?!\d)|[!?;\n]+')
_COORDINATED = re.compile(
    r'\s*(?:,\s*)?\b(?:and|but|whereas|while|then|however)\s+'
    r'(?=' + _SUBJECT_PATTERN + r'|(?:(?:did|have|not|never|only|personally|successfully|independently|solely|helped|help|assisted)\s+){0,5}' + _VERB_PATTERN + r'\b|(?:would|will|hope|want|plan)\b)', re.I,
)
_LABEL = re.compile(r'^(my role|task|method|outcome basis|outcome)\s*:\s*', re.I)
_PROJECT_LABEL = re.compile(r'^((?:project|study|experiment)\s+[^:;.!?\n]{1,80})\s*:\s*', re.I)
_PROJECT_PREFIX = re.compile(r'^(?:in|for|on|during)\s+((?:the\s+)?(?:project|study|experiment)\s+[^,;:.!?\n]{1,80}),\s*', re.I)
_PROJECT_SUFFIX = re.compile(r'\s+(?:in|for|on|during)\s+((?:the\s+)?(?:project|study|experiment)\s+[\w -]{1,80})\s*$', re.I)
_CONDITIONAL = re.compile(r'\b(?:if|unless|whether|would|could|might|hope to|plan to|want to)\b', re.I)
_AUXILIARY = re.compile(r"^(?:have|has|had|did|do|does)\s+", re.I)
_NEGATION = re.compile(r'^(?:not|never)\s+', re.I)
_MODIFIER = re.compile(r'^(personally|successfully|only|independently|solely|alone|single-handedly|helped|help|assisted)\s+(?:to\s+)?', re.I)
_OBJECT_NEGATION = re.compile(r'\s*,?\s+\b(?:but\s+not|not|rather\s+than|instead\s+of)\s+', re.I)
_TOKEN = re.compile(r'[+-]?\d+(?:\.\d+)?|[a-z][a-z0-9_+#]*|%', re.I)
_TEAM_PREFIX = re.compile(r'^(?:working\s+)?with\s+(?:my|our|the)\s+team,?$', re.I)
_BOUND = re.compile(r'\b(?:at\s+(?:most|least)|or\s+(?:less|more)|roughly|approximately|about|up\s+to|more\s+than|less\s+than)\b', re.I)
_UNITS = {'samples': 'sample', 'records': 'record', 'users': 'user', 'participants': 'participant',
          'patients': 'patient', 'models': 'model', 'tests': 'test', 'papers': 'paper',
          'hours': 'hour', 'minutes': 'minute', 'seconds': 'second'}


def _tokens(text: str) -> tuple[str, ...]:
    text = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', text.casefold())
    text = re.sub(r'(?:%|\bpercent(?:age)?)\s+points?\b', ' pct_points', text)
    text = re.sub(r'\bpercent(?:age)?\b', '%', text)
    text = re.sub(r'(?<=\d)\s*(?:x|times)\b', ' times', text)
    values = []
    for token in _TOKEN.findall(text):
        if token in {'a', 'an', 'the'}:
            continue
        if token[0].isdigit() or token[0] in '+-':
            token = format(Decimal(token).normalize(), 'f')
        values.append(_UNITS.get(token, token))
    return tuple(values)


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    # Ordered, contiguous facts. A bag of shared keywords would let a metric
    # from the next project or the next object authenticate this assertion.
    return bool(needle) and any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


@dataclass(frozen=True)
class _Fact:
    actor: str
    action: str
    objects: tuple[str, ...]
    scope: tuple[str, ...]
    negative: bool
    qualifiers: tuple[str, ...]
    entry: int


def _actor(subject: str) -> str:
    name = ' '.join(subject.casefold().split())
    if name == 'i':
        return 'personal'
    if name in {'we', 'my team', 'our team'}:
        return 'team'
    return name  # A colleague's action cannot authenticate my own action.


def _action(clause: str):
    negative = False
    qualifiers = []
    for _ in range(6):
        auxiliary = _AUXILIARY.match(clause)
        negation = _NEGATION.match(clause)
        modifier = _MODIFIER.match(clause)
        if auxiliary:
            clause = clause[auxiliary.end():]
        elif negation:
            negative = True; clause = clause[negation.end():]
        elif modifier:
            word = modifier[1].casefold()
            if word in {'help', 'helped', 'assisted'}:
                qualifiers.append('help')
            elif word in {'independently', 'solely', 'alone', 'single-handedly'}:
                qualifiers.append('independent')
            clause = clause[modifier.end():]
        else:
            break
    action = _ACTION.match(clause)
    return (action, negative, qualifiers) if action else None


def _facts(text: str, *, entry: int, source: bool) -> list[_Fact]:
    facts = []
    scope: tuple[str, ...] = ()
    label = None
    text = text.replace('’', "'")
    text = re.sub(r"\b(i|we)'ve\b", r'\1 have', text, flags=re.I)
    text = re.sub(r"\b(did|do|does|have|has|had)n['’]t\b", r'\1 not', text, flags=re.I)
    for sentence in _SENTENCES.split(text):
        sentence = sentence.strip(' \t\r\n-•“”\"')
        project = _PROJECT_LABEL.match(sentence) or _PROJECT_PREFIX.match(sentence)
        if project:
            scope = _tokens(project[1]); sentence = sentence[project.end():]
            label = None
        field = _LABEL.match(sentence)
        if field:
            label = field[1].casefold(); sentence = sentence[field.end():]
        # A carried actor is local to one sentence, not the next entry or line.
        carried = 'personal' if label == 'my role' or (source and label is None) else None
        for clause in _COORDINATED.split(sentence):
            clause = clause.strip(' ,\t“”\"')
            actor = None
            parsed = None
            # A contextual "with my team" is not the subject of "I built".
            # Select the subject that actually has a recognized action.
            for subject in _SUBJECT.finditer(clause):
                candidate = _action(clause[subject.end():].lstrip())
                if not candidate:
                    continue
                before = clause[:subject.start()].strip()
                if _CONDITIONAL.search(before) or (source and before and not _TEAM_PREFIX.fullmatch(before)):
                    continue
                actor = _actor(subject[0]); parsed = candidate; break
            if not parsed and carried:
                actor = carried; parsed = _action(clause)
            if not parsed:
                carried = None; continue
            action, negative, qualifiers = parsed
            carried = actor
            objects = action[2].strip()
            local_scope = scope
            suffix = _PROJECT_SUFFIX.search(objects)
            if suffix:
                local_scope = _tokens(suffix[1]); objects = objects[:suffix.start()]
            # "I tested the parser, not the model" cannot support "tested model".
            negated_object = _OBJECT_NEGATION.search(objects)
            tail = objects[negated_object.end():] if negated_object else None
            if negated_object:
                objects = objects[:negated_object.start()]
            if _BOUND.search(objects):
                qualifiers.append('bounded_quantity')
            tokens = _tokens(objects)
            if tokens:
                facts.append(_Fact(actor, _VERBS[action[1].casefold()], tokens, local_scope, negative, tuple(sorted(set(qualifiers))), entry))
            if tail and _tokens(tail):
                facts.append(_Fact(actor, _VERBS[action[1].casefold()], _tokens(tail), local_scope, True, tuple(sorted(set(qualifiers))), entry))
    return facts


def _same_actor(source: _Fact, claim: _Fact) -> bool:
    return source.actor == claim.actor or (claim.actor == 'the team' and source.actor == 'team')


def experience_attribution_violations(text: str, evidence: list[str]) -> list[str]:
    """Return findings for recognized concrete claims without a local source.

    ``evidence`` must be complete, currently eligible confirmed entry texts,
    never target facts, interests, a generated draft or a user edit instruction.
    A missing finding means only this bounded checker did not detect a problem.
    """
    sources = [fact for i, item in enumerate(evidence) if isinstance(item, str)
               for fact in _facts(item, entry=i, source=True)]
    findings = set()
    for claim in _facts(text, entry=-1, source=False):
        candidates = [fact for fact in sources if _same_actor(fact, claim)
                      and fact.action == claim.action and fact.negative == claim.negative
                      and fact.qualifiers == claim.qualifiers
                      and (not claim.scope or fact.scope == claim.scope)
                      # Shortening may drop trailing detail, never promote an object
                      # mentioned only in a method/for-clause into the action itself.
                      and fact.objects[:len(claim.objects)] == claim.objects]
        supported = False
        for fact in candidates:
            # An explicit denial of this action/object survives nearby positive
            # team text. Separate named projects do not veto one another.
            contradicted = not claim.negative and any(
                other.negative and other.actor == claim.actor and other.action == claim.action
                and (other.entry == fact.entry or not other.scope or other.scope == fact.scope)
                and (not other.scope or not fact.scope or other.scope == fact.scope)
                and (_contains(claim.objects, other.objects) or _contains(other.objects, claim.objects))
                for other in sources
            )
            if not contradicted:
                supported = True; break
        if not supported:
            findings.add(f'unsupported experience attribution: {claim.actor} {claim.action}')
    return sorted(findings)
