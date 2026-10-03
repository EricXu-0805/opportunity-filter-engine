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
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal

_WHITESPACE_RUN = re.compile(r"\s+")
_WORD = re.compile(r"\w+")


def collapse_whitespace(text: str) -> str:
    """One character per whitespace run, before any clause is parsed.

    A run that contains a line break becomes one line break, so sentence and
    clause boundaries stay where they were; any other run becomes one space.
    Comparison already tokenizes and single-spaces the text, so singly spaced
    input reads as before, and tabs, no-break or doubled spaces read like the
    singly spaced text.
    """
    return _WHITESPACE_RUN.sub(lambda match: "\n" if "\n" in match.group() else " ", text)


# A bound on the work one check may do, counted in characters read wherever the
# check calls ``spend``. Ordinary input uses a small fraction of it. Past it the
# check fails closed: it reports one size finding, so the claim counts as
# unsupported and the caller keeps the original wording.
_WORK_LIMIT = 3_000_000
# One comparison or lookup step, in units of one character read.
_STEP = 100
# What ordinary text needs without counting: subjects followed by an action,
# per clause, and admitted names, per lookup.
_FREE_SUBJECTS = 4
_FREE_NAMES = 4


class _OverLimit(Exception):
    pass


class _Work:
    __slots__ = ("left",)

    def __init__(self) -> None:
        self.left = _WORK_LIMIT

    def spend(self, amount: int) -> None:
        self.left -= amount
        if self.left < 0:
            raise _OverLimit

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
# B46 resume-only research actions. Default email parsing keeps its original
# finite vocabulary; these are inflections, not a research/study synonym map.
_RESUME_RESEARCH_FORMS = {
    'study': ('study', 'studied', 'studying'),
    'research': ('research', 'researched', 'researching'),
    'investigate': ('investigate', 'investigated', 'investigating'),
}
_RESUME_VERBS = {**_VERBS, **{form: lemma for lemma, forms in _RESUME_RESEARCH_FORMS.items() for form in forms}}
_RESUME_VERB_PATTERN = '(?:' + '|'.join(sorted(_RESUME_VERBS, key=len, reverse=True)) + ')'
_SUBJECT_PATTERN = r"(?:my\s+team|our\s+team|the\s+team|my\s+teammates?|my\s+colleagues?|my\s+supervisor|i|we)\b"
_SUBJECT = re.compile(_SUBJECT_PATTERN, re.I)
_ACTION = re.compile(r'^(' + _VERB_PATTERN + r')\b\s*(.*)$', re.I)
_RESUME_ACTION = re.compile(r'^(' + _RESUME_VERB_PATTERN + r')\b\s*(.*)$', re.I)
_SENTENCES = re.compile(r'(?<!\d)\.(?!\d)|[!?;\n]+')
# Resume sentences may end in a course number or metric. A following digit
# keeps a decimal point intact, including .25; email retains its legacy splitter.
_RESUME_SENTENCES = re.compile(r'\.(?!\d)|[!?;\n]+')
_RESUME_EXPLICIT_BOUNDARY = re.compile(r'\s*[,:]\s*(?=' + _SUBJECT_PATTERN + r')', re.I)
_COORDINATED = re.compile(
    r'\s*(?:,\s*)?\b(?:and|but|whereas|while|then|however)\s+'
    r'(?=' + _SUBJECT_PATTERN + r'|(?:(?:did|have|not|never|only|personally|successfully|independently|solely|helped|help|assisted)\s+){0,5}' + _VERB_PATTERN + r'\b|(?:would|will|hope|want|plan)\b)', re.I,
)
_RESUME_COORDINATED = re.compile(_COORDINATED.pattern.replace(_VERB_PATTERN, _RESUME_VERB_PATTERN), re.I)
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
# "In PSYC 238, as part of a four-person team, I helped design ..." states its
# setting before the subject. Only prepositional settings qualify; a reported
# or conditional prefix ("My advisor said I ...", "If I ...") never does.
# Each comma-separated setting is checked on its own, once.
_CONTEXT_SETTING = r'(?:at|in|for|on|during|within|through|while|with|as\s+part\s+of|as\s+a\s+member\s+of)\s+[^,]+'
_CONTEXT_FIRST = re.compile(_CONTEXT_SETTING, re.I)
_CONTEXT_NEXT = re.compile(r'\s*' + _CONTEXT_SETTING, re.I)
_BLANK = re.compile(r'\s*')
# Collaboration, wherever it sits in the clause, qualifies the whole fact. It is
# not an object detail a shortened claim may drop. "for my team" is a
# beneficiary, not a collaborator, and stays an ordinary object phrase.
_TEAM_CONTEXT = re.compile(
    r'\b(?:(?:together\s+)?(?:with|alongside)\s+'
    r'(?:(?:my|our|the|other|a|an|another|fellow|several|one|two|three|four|five|six|\d+)\s+)?'
    r'(?:(?:research|lab|project|fellow)\s+)?'
    r'(?:team(?:mates?)?|colleagues?|classmates?|lab\s*mates?|lab\s+partners?|partners?|students?|peers?|group)'
    r'|(?:with|as\s+(?:part\s+of\s+)?|as\s+a\s+member\s+of\s+)(?:a|an|my|our|the)\s+(?:[\w-]+\s+){0,3}(?:team|group)'
    r'|in\s+a\s+(?:[\w-]+\s+){0,2}(?:team|group)(?:\s+of\s+\w+)?'
    r'|collaboratively|in\s+collaboration\s+with\s+[^,;.!?]+)\b', re.I)
_CARE_QUALIFIER = re.compile(r'\b(not|never|without|only|hardly|barely|rarely)\b[^.!?;\n]*\bcarefully\s*$', re.I)
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
    # Tokens never contain NUL, so a NUL-delimited substring is exactly a
    # contiguous run of whole tokens.
    return bool(needle) and "\0" + "\0".join(needle) + "\0" in "\0" + "\0".join(haystack) + "\0"


@dataclass(frozen=True)
class _Fact:
    actor: str
    action: str
    objects: tuple[str, ...]
    scope: tuple[str, ...]
    negative: bool
    qualifiers: tuple[str, ...]
    entry: int
    clause: str = ""
    # A claim ending in ", reaching X" / ", which ...": the action before the
    # comma plus one fact per recognized participle, tried only when the
    # whole-object reading is unsupported.
    split: tuple = ()


# Reported in place of the claims when a check is past its work limit.
_SIZE_FINDING = _Fact("input", "exceeds the supported size", (), (), False, (), -1)


def _participle(lemma: str) -> str:
    if lemma in {'win', 'debug'}:
        return lemma + lemma[-1] + 'ing'
    return (lemma[:-1] if lemma.endswith('e') else lemma) + 'ing'


_PARTICIPLES = {_participle(lemma): lemma for lemma in _FORMS}
_PAST = {form: lemma for lemma, forms in _FORMS.items() for form in forms[1:]}
_TRAILING = re.compile(
    r',?\s+(?:that|which)\s+(' + '|'.join(sorted(_PAST, key=len, reverse=True)) + r')\b'
    r'|,\s+(' + '|'.join(sorted(_PARTICIPLES, key=len, reverse=True)) + r')\b'
    r'|,\s+(?:which|where)\b', re.I,
)


def _trailing_phrases(objects: str) -> tuple[str, list[tuple[str, str]]] | None:
    """Split "X that reached Y, which Z" into X and [("reach", "Y")].

    A known action's past form after that/which, or its participle after a
    comma, becomes a fact; any other which/where remark is reflection, not an
    attribution claim, and stays with the prose gates. An enumeration
    (", a compiler") never matches, so it is still compared as one ordered
    object and fails closed.
    """
    matches = list(_TRAILING.finditer(objects))
    if not matches:
        return None
    tails = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(objects)
        if match[1] or match[2]:
            lemma = _PAST[match[1].casefold()] if match[1] else _PARTICIPLES[match[2].casefold()]
            tails.append((lemma, objects[match.end():end].strip()))
    return objects[:matches[0].start()], tails


def _actor(subject: str) -> str:
    name = ' '.join(subject.casefold().split())
    if name == 'i':
        return 'personal'
    if name in {'we', 'my team', 'our team'}:
        return 'team'
    return name  # A colleague's action cannot authenticate my own action.


def _action(clause: str, resume: bool = False):
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
    action = (_RESUME_ACTION if resume else _ACTION).match(clause)
    return (action, negative, qualifiers) if action else None


def _context_prefix(text: str) -> bool:
    """``text`` is one or more settings, each opening with a preposition and
    separated by commas, as in "In PSYC 238, as part of a four-person team,"."""
    parts = text.split(",")
    return bool(_CONTEXT_FIRST.fullmatch(parts[0])) and all(
        _CONTEXT_NEXT.fullmatch(part) or (index == len(parts) - 1 and _BLANK.fullmatch(part))
        for index, part in enumerate(parts) if index)


def _care_qualifier(objects: str) -> re.Match | None:
    # A match cannot start before the last sentence mark, so search only after it.
    end = len(objects.rstrip())
    start = max(objects.rfind(mark, 0, end) for mark in ".!?;\n") + 1
    return _CARE_QUALIFIER.search(objects, start)


def _facts(text: str, *, entry: int, source: bool, work: _Work, allow_subjectless_claims: bool = False,
           activity_aliases: _Aliases | None = None) -> list[_Fact]:
    facts = []
    scope: tuple[str, ...] = ()
    label = None
    text = collapse_whitespace(text)
    text = text.replace('’', "'")
    text = re.sub(r"\b(i|we)'ve\b", r'\1 have', text, flags=re.I)
    text = re.sub(r"\b(did|do|does|have|has|had)n['’]t\b", r'\1 not', text, flags=re.I)
    sentences = _RESUME_SENTENCES if allow_subjectless_claims else _SENTENCES
    for sentence in sentences.split(text):
        sentence = sentence.strip(' \t\r\n-•“”\"')
        # A named heading governs the following clauses. Per-clause resolution
        # below permits two explicitly different activities in one sentence.
        if activity_aliases is not None and sentence.endswith(":"):
            scope = _activity_scope(sentence, activity_aliases) or scope
        project = _PROJECT_LABEL.match(sentence) or _PROJECT_PREFIX.match(sentence)
        if project:
            scope = (_activity_scope(project[1], activity_aliases) if activity_aliases is not None else ()) or _tokens(project[1])
            sentence = sentence[project.end():]
            label = None
        field = _LABEL.match(sentence)
        if field:
            label = field[1].casefold(); sentence = sentence[field.end():]
        # A carried actor is local to one sentence, not the next entry or line.
        # Resume bullets may omit I, but only an unlabelled action fragment or
        # an explicit My role field implies personal work. Outcome/Task never
        # turn ambiguous source results into personal evidence. Explicit
        # subjects below still win, including team/colleague coordinated clauses.
        carried = 'personal' if label == 'my role' or ((source or allow_subjectless_claims) and label is None) else None
        clauses = []
        for candidate_clause in (_RESUME_COORDINATED if allow_subjectless_claims else _COORDINATED).split(sentence):
            # Only an already recognized leading fragment permits this local
            # boundary. Do not split number commas or contextual prefixes such
            # as "With my team, I built". Keep every following subject to check.
            if allow_subjectless_claims and _action(candidate_clause.strip(' ,\t“”\"'), True):
                clauses.extend(_RESUME_EXPLICIT_BOUNDARY.split(candidate_clause))
            else:
                clauses.append(candidate_clause)
        for clause in clauses:
            clause = clause.strip(' ,\t“”\"')
            contextual_scope = _activity_scope(clause, activity_aliases) if activity_aliases is not None else ()
            actor = None
            team_context = False
            parsed = _action(clause, True) if allow_subjectless_claims and carried else None
            if parsed:
                actor = carried
            # A contextual "with my team" is not the subject of "I built".
            # Select the subject that actually has a recognized action.
            followed = 0
            for subject in (() if parsed else _SUBJECT.finditer(clause)):
                candidate = _action(clause[subject.end():].lstrip(), allow_subjectless_claims)
                if not candidate:
                    continue
                followed += 1
                if followed > _FREE_SUBJECTS:
                    work.spend(len(clause))
                before = clause[:subject.start()].strip()
                if _CONDITIONAL.search(before) or (source and before and not _TEAM_PREFIX.fullmatch(before)
                        and not _context_prefix(before)
                        and not (activity_aliases is not None and (
                            _only_known_context(before, activity_aliases)
                            or re.fullmatch(r"(?:at|in|for|on|during)\s+[^,]+,?", before, re.I)))):
                    continue
                actor = _actor(subject[0]); parsed = candidate; team_context = bool(_TEAM_CONTEXT.search(before)); break
            if not parsed and carried:
                actor = carried; parsed = _action(clause, allow_subjectless_claims)
            if not parsed:
                carried = None; continue
            action, negative, qualifiers = parsed
            if contextual_scope:
                scope = contextual_scope
            carried = actor
            lemma = (_RESUME_VERBS if allow_subjectless_claims else _VERBS)[action[1].casefold()]
            objects = action[2].strip()
            # Collaboration anywhere in the clause qualifies every part of it,
            # so neither the whole object nor a split part can shed it.
            if team_context or _TEAM_CONTEXT.search(objects):
                qualifiers = [*qualifiers, 'team']
            shape = (actor, negative, scope, contextual_scope, activity_aliases, allow_subjectless_claims, entry, clause)
            main, denied = _object_facts(objects, lemma, qualifiers, *shape)
            trailing = _trailing_phrases(objects)
            split: list[_Fact] = []
            if trailing:
                head, tails = trailing
                parts = [_object_facts(head, lemma, qualifiers, *shape)[0]]
                parts += [_object_facts(text, tail_lemma, qualifiers, *shape)[0] for tail_lemma, text in tails if _tokens(text)]
                split = parts if all(parts) else []
            if source:
                # A source supports both readings of its own sentence.
                facts.extend(fact for fact in (main, denied, *split) if fact)
                continue
            if main:
                facts.append(replace(main, split=tuple(split)))
            if denied:
                facts.append(denied)
    return facts


def _object_facts(objects: str, lemma: str, qualifiers: list[str], actor: str, negative: bool,
                  scope: tuple[str, ...], contextual_scope: tuple[str, ...], activity_aliases: _Aliases | None,
                  allow_subjectless_claims: bool, entry: int, clause: str) -> tuple[_Fact | None, _Fact | None]:
    qualifiers = list(qualifiers)
    local_scope = contextual_scope or scope
    suffix = _PROJECT_SUFFIX.search(objects)
    if suffix:
        local_scope = contextual_scope or _tokens(suffix[1]); objects = objects[:suffix.start()]
    if contextual_scope:
        objects = _without_activity_suffix(objects, activity_aliases)
    objects = collapse_whitespace(_TEAM_CONTEXT.sub(' ', objects))
    # The one neutral editorial suffix used by legacy resume rewrites
    # must not erase a local restriction, including "never carefully"
    # or "without working carefully". A nearby retained source sentence
    # cannot certify a new unrestricted positive assertion.
    if allow_subjectless_claims and (manner := _care_qualifier(objects)):
        qualifiers.append(manner[1].casefold() + '_carefully')
    # "I tested the parser, not the model" cannot support "tested model".
    negated_object = _OBJECT_NEGATION.search(objects)
    tail = objects[negated_object.end():] if negated_object else None
    if negated_object:
        objects = objects[:negated_object.start()]
    if _BOUND.search(objects):
        qualifiers.append('bounded_quantity')
    tokens = _tokens(objects)
    if allow_subjectless_claims and len(tokens) > 1 and re.search(r'(?:^|\s)carefully$', objects, re.I) and not _care_qualifier(objects):
        tokens = tokens[:-1]
    marks = tuple(sorted(set(qualifiers)))
    main = _Fact(actor, lemma, tokens, local_scope, negative, marks, entry, clause) if tokens else None
    denied = _Fact(actor, lemma, _tokens(tail), local_scope, True, marks, entry, clause) if tail and _tokens(tail) else None
    return main, denied


def _same_actor(source: _Fact, claim: _Fact) -> bool:
    return source.actor == claim.actor or (claim.actor == 'the team' and source.actor == 'team')


def _qualifiers_supported(source: _Fact, claim: _Fact) -> bool:
    # A claim may understate: add a collaboration qualifier, or say "I helped
    # build" for a confirmed "built". It may not drop a qualifier, except that
    # "helped" already says the work was shared and so keeps a team credit.
    # Every other qualifier must match exactly.
    added = {*claim.qualifiers} - {*source.qualifiers}
    required = {*source.qualifiers} - ({'team'} if 'help' in claim.qualifiers else set())
    return (required <= {*claim.qualifiers}
            and added <= ({'team', 'help'} if not claim.negative else {'team'}))


# Only the established computational-tool/artifact structures below have an
# attribution-preserving positional alias. An adjective or a general noun must
# never become a tool, and deleting the artifact noun is not a valid shortening.
_RESUME_TOOLS = frozenset({'python', 'matlab'})
_RESUME_ARTIFACTS = frozenset(
    (*kind, artifact)
    for kind in [('ml',), ('machine', 'learning')]
    for artifact in ('model', 'projects', 'exercises')
)
_RESUME_ARTIFACT_ACTIONS = frozenset({'build', 'implement', 'develop', 'create', 'train', 'test', 'evaluate'})


def _resume_legacy_object_form(fact: _Fact) -> tuple[str, ...]:
    """Preserve three verified legacy structures; not a general word bag.

    CS plus a course number is a bounded course identifier, not a generic
    for/in alias. Tool movement keeps the complete computational artifact and
    course context. Analysis for/of applies only to the same EEG recordings.
    Actor, action, quantity qualifiers and project scope remain outside this
    form and still have to match independently.
    """
    objects = fact.objects
    context: tuple[str, ...] = ()
    if len(objects) >= 4 and objects[-3] in {'for', 'in'} and objects[-2] == 'cs' and re.fullmatch(r'[0-9]{2,4}', objects[-1]):
        context = ('in', 'cs', objects[-1]); objects = objects[:-3]
    elif len(objects) >= 5 and objects[-4:-2] == ('during', 'cs') and re.fullmatch(r'[0-9]{2,4}', objects[-2]) and objects[-1] == 'coursework':
        context = ('in', 'cs', objects[-2]); objects = objects[:-4]
    elif objects[-2:] == ('during', 'coursework'):
        context = objects[-2:]; objects = objects[:-2]

    if fact.action in _RESUME_ARTIFACT_ACTIONS and objects and objects[0] in _RESUME_TOOLS and objects[1:] in _RESUME_ARTIFACTS:
        objects = (*objects[1:], 'with', objects[0])
    # The matching with-tool form already has this canonical shape. No other
    # rearrangement or deletion is performed, including exercises -> ML.
    if fact.action == 'write':
        tool = objects[:1] if objects and objects[0] in _RESUME_TOOLS else ()
        rest = objects[len(tool):]
        if rest in {('analysis', 'for', 'eeg', 'recordings'), ('analysis', 'of', 'eeg', 'recordings')}:
            objects = (*tool, 'analysis', 'of', 'eeg', 'recordings')
    return (*objects, *context)


def _resume_object_forms(fact: _Fact) -> tuple[tuple[str, ...], ...]:
    """Exact established structures, retaining originals for explicit denials."""
    objects = fact.objects
    forms = (objects, _resume_legacy_object_form(fact))
    if fact.action != 'analyze':
        return forms
    if len(objects) == 6 and objects[0] in {'measurement', 'measurements'} and objects[1] == 'with' and objects[3] == 'across' and objects[5] == 'sample':
        tool, count = objects[2], objects[4]
    elif len(objects) == 4 and objects[1:3] == ('sample', 'with'):
        count, tool = objects[0], objects[3]
    else:
        return forms
    if not re.fullmatch(r'[0-9]+', count) or not re.fullmatch(r'[a-z][a-z0-9_+#]*', tool) or tool in {'not', 'only', 'and', 'or'}:
        return forms
    return (*forms, (count, 'sample', 'with', tool),
            ('measurements', 'with', tool, 'across', count, 'sample'),
            ('measurement', 'with', tool, 'across', count, 'sample'))


def _resume_source_tool_omission(fact: _Fact) -> tuple[str, ...] | None:
    """One-way removal of a confirmed tool, keeping artifact and full context.

    A negative tool-specific statement cannot support the stronger assertion
    that no work occurred by any method, so this omission is positive-only.
    """
    if fact.negative or fact.action not in _RESUME_ARTIFACT_ACTIONS:
        return None
    objects = _resume_legacy_object_form(fact)
    for artifact in _RESUME_ARTIFACTS:
        if objects[:len(artifact)] != artifact:
            continue
        tail = objects[len(artifact):]
        if len(tail) < 2 or tail[0] != 'with' or tail[1] not in _RESUME_TOOLS:
            continue
        context = tail[2:]
        if context in {(), ('during', 'coursework')} or (len(context) == 3 and context[:2] == ('in', 'cs') and re.fullmatch(r'[0-9]{2,4}', context[2])):
            return (*artifact, *context)
    return None


def _tool_omission_supported(source: _Fact, claim: _Fact) -> bool:
    omitted = _resume_source_tool_omission(source)
    return omitted is not None and omitted in _resume_object_forms(claim)


def _objects_supported(source: _Fact, claim: _Fact, resume: bool) -> bool:
    if source.objects[:len(claim.objects)] == claim.objects:
        return True
    if not resume:
        return False
    source_forms = _resume_object_forms(source)
    if any(left == right for left in source_forms for right in _resume_object_forms(claim)):
        return True
    if _tool_omission_supported(source, claim):
        return True
    # This one established equivalent may safely omit its trailing tool. Keep
    # the count plus sample unit intact; no arbitrary alias-prefix matching.
    return len(claim.objects) == 2 and claim.objects[1] == 'sample' and any(
        objects[:2] == claim.objects for objects in source_forms
    )


def _objects_overlap(claim: _Fact, denial: _Fact, resume: bool) -> bool:
    claims = _resume_object_forms(claim) if resume else (claim.objects,)
    denials = _resume_object_forms(denial) if resume else (denial.objects,)
    return any(_contains(left, right) or _contains(right, left) for left in claims for right in denials)


def _objects_contradicted(source: _Fact, claim: _Fact, denial: _Fact, resume: bool) -> bool:
    if resume and _tool_omission_supported(source, claim):
        # Judge the particular supporting method, not every possible method.
        # A Python denial still vetoes a Python-backed shortened claim, but
        # cannot veto a separately confirmed MATLAB-backed one. A broad denial
        # without a tool still applies to both.
        return (_objects_overlap(source, denial, True)
                or _resume_source_tool_omission(source) in _resume_object_forms(denial))
    return _objects_overlap(claim, denial, resume)



def _support_keys(fact: _Fact, resume: bool) -> set[tuple]:
    """Where a confirmed fact is filed for ``_objects_supported``: its object
    prefixes of up to three tokens and, in résumé mode, its established forms,
    its shortened-tool reading and the leading pair of each form."""
    keys: set[tuple] = {("prefix", fact.objects[:size]) for size in range(1, min(len(fact.objects), 3) + 1)}
    if resume:
        forms = _resume_object_forms(fact)
        keys.update(("form", form) for form in forms)
        keys.update(("pair", form[:2]) for form in forms)
        omitted = _resume_source_tool_omission(fact)
        if omitted is not None:
            keys.add(("form", omitted))
    return keys


def _claim_keys(claim: _Fact, resume: bool) -> list[tuple]:
    """Where the facts that can support ``claim`` are filed (``_support_keys``)."""
    keys: list[tuple] = [("prefix", claim.objects[:3])]
    if resume:
        keys.extend(("form", form) for form in _resume_object_forms(claim))
        if len(claim.objects) == 2 and claim.objects[1] == 'sample':
            keys.append(("pair", claim.objects))
    return keys


def _context_key(context: dict) -> tuple[str, ...]:
    return ("$activity", context["master_id"], context["section"], context["id"])


def _explicit_activity_references(text: str) -> list[str]:
    """Finite named-context forms, including currently unknown/deleted names."""
    references = []
    prefix = re.match(r"^(?:at|in|for|on|during)\s+([^,]+),\s*(?=" + _SUBJECT_PATTERN + r")", text, re.I)
    if prefix:
        references.append(prefix[1])
    # The suffix holds no comma or semicolon and no sentence mark before its
    # closing ones, so it can only start after the last of those.
    body = text[:-1] if text.endswith("\n") else text
    closing = len(body.rstrip(".!?"))
    start = max(text.rfind(","), text.rfind(";"), *(body.rfind(mark, 0, closing) for mark in ".!?")) + 1
    suffix = _ACTIVITY_SUFFIX.search(text, start)
    if suffix:
        candidate = suffix[1].strip()
        # Avoid classifying an ordinary lowercase object/method phrase as a
        # named activity. Institutional labels and explicit years still count.
        if (candidate[:1].isupper() or re.search(r"\b(?:lab|laboratory|university|college|company|institute|project|study|experiment)\b", candidate, re.I)
                or re.fullmatch(r"(?:19|20)\d{2}", candidate)):
            references.append(candidate)
    if text.endswith(":") and re.search(r"\b(?:lab|laboratory|university|college|company|institute|project|study|experiment)\b", text, re.I):
        references.append(text[:-1])
    return references


def _reference_remainder(reference: str, aliases: _Aliases) -> str:
    remaining = _remove_names(" ".join(reference.casefold().split()), aliases.names)
    return re.sub(r"\b(?:in|for|on|during|at|from|to|since|until|the|and)\b|[,()–—-]", " ", remaining).strip()


_ACTIVITY_SUFFIX = re.compile(r"\s+(?:at|in|for|on|during)\s+([^,;.!?]+)[.!?]*$", re.I)
_CONTEXT_LEAD = re.compile(r"\s+(?:in|for|on|during|at|from|since)\s+", re.I)
_CONTEXT_OPENING = re.compile(r"(?:in|for|on|during|at|from|since)\s+", re.I)
_CONTEXT_FILLER = re.compile(r"\b(?:in|for|on|during|at|from|to|since|until|the|and)\b|[,–—-]")
_FILLER_WORDS = frozenset({"in", "for", "on", "during", "at", "from", "to", "since", "until", "the", "and"})


def _word_char(char: str) -> bool:
    # The same characters the pattern class \w matches.
    return char.isalnum() or char == "_"


def _standalone(text: str, name: str, work: _Work):
    """Offsets of ``name`` in ``text`` with no word character directly before or
    after it, left to right and not overlapping, as a regular expression with
    those two lookarounds finds them."""
    start, first = text.find(name), True
    while start != -1:
        if not first:
            work.spend(_STEP)
        first = False
        end = start + len(name)
        if (start == 0 or not _word_char(text[start - 1])) and (end == len(text) or not _word_char(text[end])):
            yield start
            start = text.find(name, end)
        else:
            start = text.find(name, start + 1)


def _occurs(text: str, name: str, work: _Work) -> bool:
    return next(_standalone(text, name, work), None) is not None


class _Names:
    """The admitted names and dates of one check, filed for lookup by word.

    Every word of a name is a whole word of any text the name occurs in, so a
    name is filed under its least common word and only names filed under a word
    of the text are tried, longest first. Replacing a name with a space never
    creates a word, so this also holds while names are removed one by one.
    """

    def __init__(self, names, work: _Work) -> None:
        self.work = work
        ordered = sorted(names, key=len, reverse=True)
        self.rank = {name: rank for rank, name in enumerate(ordered)}
        words = {name: set(_WORD.findall(name)) for name in ordered}
        counts = Counter(word for found in words.values() for word in found)
        self.known = _FILLER_WORDS | set(counts)
        self.filed: dict[str, list[str]] = {}
        self.wordless: list[str] = []
        for name, found in words.items():
            if found:
                self.filed.setdefault(min(found, key=lambda word: (counts[word], word)), []).append(name)
            else:
                self.wordless.append(name)

    def candidates(self, text: str) -> list[str]:
        found = set(_WORD.findall(text))
        names = [*self.wordless, *(name for word in found for name in self.filed.get(word, ()))]
        if len(names) > _FREE_NAMES:
            self.work.spend(_STEP * (len(names) - _FREE_NAMES))
        names.sort(key=self.rank.__getitem__)
        return names


class _Aliases(dict):
    """Admitted name or date -> the activities it can mean, with the shared index."""

    names: _Names


def _remove_names(text: str, names: _Names) -> str:
    """``text`` with each admitted name replaced by a space, longest name first."""
    for name in names.candidates(text):
        if name in text:
            pieces, kept = [], 0
            for start in _standalone(text, name, names.work):
                pieces += (text[kept:start], " ")
                kept = start + len(name)
            if pieces:
                text = "".join(pieces) + text[kept:]
    return text


def _activity_aliases(materials: list[dict]) -> dict[str, set[tuple[str, ...]]]:
    """Exact admitted names/dates only, never inferred roles or synonyms."""
    aliases: dict[str, set[tuple[str, ...]]] = {}
    for material in materials:
        context = material.get("context")
        key = _context_key(context) if context else ("$experience", material["id"], str(material["revision"]))
        excerpt = collapse_whitespace(material["excerpt"])
        for year in re.findall(r"\b(?:in|during|from|to|since|until|year)\s+((?:19|20)\d{2})\b",
                               excerpt, re.I):
            aliases.setdefault(year, set()).add(key)
        if not context:
            # An independent original may itself state its organization/date.
            # It does not acquire another record's project identity or fields.
            for sentence in _SENTENCES.split(excerpt):
                for reference in _explicit_activity_references(sentence.strip()):
                    for value in re.split(r"\s+(?:in|during|from|to|since|until)\s+(?=(?:19|20)\d{2})", reference, flags=re.I):
                        value = " ".join(value.casefold().split()).strip(" ,.")
                        if value:
                            aliases.setdefault(value, set()).add(key)
            continue
        for field, fact in context["fields"].items():
            if field not in {"title", "organization", "school", "start", "end", "date"}:
                continue
            value = " ".join(fact["value"].casefold().split())
            values = [value]
            if field in {"start", "end", "date"}:
                values.extend(re.findall(r"\b(?:19|20)\d{2}\b", value))
            for alias in values:
                if alias:
                    aliases.setdefault(alias, set()).add(key)
    return aliases


def _activity_scope(text: str, aliases: _Aliases) -> tuple[str, ...]:
    normalized = " ".join(text.casefold().split())
    matches = [aliases[alias] for alias in aliases.names.candidates(normalized)
               if _occurs(normalized, alias, aliases.names.work)
               and (not re.fullmatch(r"(?:19|20)\d{2}", alias)
                    or re.search(r"\b(?:in|during|from|to|since|until|year)\s+" + alias + r"\b", normalized))]
    for reference in _explicit_activity_references(text):
        if _reference_remainder(reference, aliases):
            # A partial known name must not authenticate a longer unknown one.
            return ("$activity_unknown_name", " ".join(reference.casefold().split()))
    for year in re.findall(r"\b(?:in|during|from|to|since|until|year)\s+((?:19|20)\d{2})\b", normalized):
        if year not in aliases:
            matches.append({("$activity_unknown_date", year)})
    if not matches:
        return ()
    possible = set.intersection(*matches)
    # A conflicting name/date or a shared ambiguous name cannot authenticate a
    # concrete claim. A second exact field may disambiguate the same title.
    return next(iter(possible)) if len(possible) == 1 else ("$activity_ambiguous",)


def _known_tail(tail: str, aliases: _Aliases) -> bool:
    """Nothing but admitted names, dates and filler words is left in ``tail``."""
    aliases.names.work.spend(4 * len(tail))
    remainder = _remove_names(" ".join(tail.strip(" ,.!?").casefold().split()), aliases.names)
    return not _CONTEXT_FILLER.sub(" ", remainder).strip()


def _only_known_context(text: str, aliases: _Aliases) -> bool:
    """``text`` opens with a preposition followed only by admitted names, dates
    and filler words, as in "at Alpha Lab in 2024"."""
    opening = _CONTEXT_OPENING.match(text)
    return bool(opening) and _known_tail(text[opening.end():], aliases)


def _without_activity_suffix(text: str, aliases: _Aliases) -> str:
    # The core fact object stays ordered. This only removes a trailing explicit
    # known name/date context, e.g. "the parser at Alpha Lab in 2024".
    leads = list(_CONTEXT_LEAD.finditer(text))
    # A word that is neither filler nor part of an admitted name stays in every
    # tail that holds it, so only the leads after the last such word can work.
    first = 0
    for index in range(len(leads) - 1, -1, -1):
        end = leads[index + 1].start() if index + 1 < len(leads) else len(text)
        if not aliases.names.known.issuperset(_WORD.findall(text[leads[index].end():end].casefold())):
            first = index + 1
            break
    for match in leads[first:]:
        if _known_tail(text[match.end():], aliases):
            return text[:match.start()]
    return text

def experience_attribution_violations(
    text: str, evidence: list[str], *, allow_subjectless_claims: bool = False,
    activity_materials: list[dict] | None = None,
) -> list[str]:
    """Return findings for recognized concrete claims without a local source."""
    return sorted({f'unsupported experience attribution: {claim.actor} {claim.action}'
                   for claim in _unsupported_claims(text, evidence, allow_subjectless_claims, activity_materials)})


def unsupported_experience_claims(
    text: str, evidence: list[str], *, allow_subjectless_claims: bool = False,
    activity_materials: list[dict] | None = None,
) -> list[str]:
    """The clauses behind ``experience_attribution_violations``, in text order,
    so a reviser can be told which sentence to restate."""
    clauses = [claim.clause for claim in _unsupported_claims(text, evidence, allow_subjectless_claims, activity_materials)
               if claim is not _SIZE_FINDING]
    return list(dict.fromkeys(clauses))


def _unsupported_claims(
    text: str, evidence: list[str], allow_subjectless_claims: bool, activity_materials: list[dict] | None,
) -> list[_Fact]:
    """Recognized concrete claims without a local source.

    ``evidence`` must be complete, currently eligible confirmed entry texts,
    never target facts, interests, a generated draft or a user edit instruction.
    ``allow_subjectless_claims`` opts resume output into checking unlabelled
    action fragments such as "Built a parser" as personal claims. It does not
    relabel explicit team actors, infer ownership from Outcome fields, or broaden
    general semantics. Resume mode adds only study/research/investigate inflections
    and preserves established legacy
    forms: neutral trailing "carefully", exact analyze/tool/sample structure,
    explicit computational-tool placement, CS course context and EEG analysis
    for/of. These finite structures do not permit arbitrary synonyms or word order.
    Email callers retain their default behavior.
    A missing finding means only this bounded checker did not detect a problem.
    """
    try:
        return _find_unsupported(text, evidence, allow_subjectless_claims, activity_materials, _Work())
    except _OverLimit:
        return [_SIZE_FINDING]


def _find_unsupported(
    text: str, evidence: list[str], allow_subjectless_claims: bool, activity_materials: list[dict] | None,
    work: _Work,
) -> list[_Fact]:
    aliases = None
    if activity_materials is not None:
        aliases = _Aliases(_activity_aliases(activity_materials or []))
        aliases.names = _Names(aliases, work)
    claims = _facts(text, entry=-1, source=False, work=work, allow_subjectless_claims=allow_subjectless_claims,
                    activity_aliases=aliases)
    if not claims:
        return []
    sources = []
    for i, item in enumerate(evidence):
        if not isinstance(item, str):
            continue
        # A source's own explicit relationship disambiguates a shared title.
        # Claims below must resolve against the complete collection instead.
        source_aliases = None
        if aliases is not None:
            source_aliases = _Aliases(aliases)
            if activity_materials and i < len(activity_materials):
                source_aliases.update(_activity_aliases([activity_materials[i]]))
            source_aliases.names = aliases.names
        sources.extend(_facts(item, entry=i, source=True, work=work, allow_subjectless_claims=allow_subjectless_claims,
                              activity_aliases=source_aliases))
    if activity_materials is not None:
        contexts = {i: material.get("context") for i, material in enumerate(activity_materials)}
        sources = [replace(fact, scope=_context_key(contexts[fact.entry]))
                   if contexts.get(fact.entry) and not fact.scope else fact for fact in sources]
        # Existing explicit project names resolve to that same current context;
        # a conflicting explicit name is never silently overwritten.
        sources = [replace(fact, scope=_activity_scope(" ".join(fact.scope), aliases))
                   if fact.scope and fact.scope[0] != "$activity" and _activity_scope(" ".join(fact.scope), aliases)
                   else fact for fact in sources]
        sources = [fact for fact in sources if not (
            contexts.get(fact.entry) and fact.scope and fact.scope[0].startswith("$activity")
            and fact.scope[0] != "$activity_unknown_name"
            and fact.scope != _context_key(contexts[fact.entry]))]
    # A repeated fact supports nothing more. A fact is filed under each object
    # reading ``_objects_supported`` can match, so a claim meets only the facts
    # that share its action, polarity and such a reading, and only its denials.
    filed: dict[tuple, list[_Fact]] = {}
    denials: dict[tuple[str, str], list[_Fact]] = {}
    denial_tokens: Counter = Counter()
    for fact in dict.fromkeys(sources):
        for key in _support_keys(fact, allow_subjectless_claims):
            filed.setdefault((fact.action, fact.negative, key), []).append(fact)
        if fact.negative:
            denials.setdefault((fact.actor, fact.action), []).append(fact)
            denial_tokens[fact.actor, fact.action] += len(fact.objects)

    folded: dict[int, str] = {}

    def fold(fact: _Fact) -> str:
        # Each clause is folded once, however many comparisons read it.
        if id(fact) not in folded:
            folded[id(fact)] = " ".join(fact.clause.casefold().split())
        return folded[id(fact)]

    def supporting_entries(claim: _Fact, within: set[int] | None = None, any_one: bool = False) -> set[int]:
        # An explicit denial of this action/object survives nearby positive
        # team text. Separate named projects do not veto one another.
        vetoes = () if claim.negative else denials.get((claim.actor, claim.action), ())
        # A denial's contradiction depends on the candidate only through a
        # shortened-tool reading, so each reading meets the denials once; scope
        # and entry then decide which denials apply to which candidate.
        readings: dict[tuple[str, ...] | None, tuple[bool, set, set]] = {}
        supported: set[int] = set()
        seen: set[int] = set()
        for key in _claim_keys(claim, allow_subjectless_claims):
            for fact in filed.get((claim.action, claim.negative, key), ()):
                if id(fact) in seen:
                    continue
                seen.add(id(fact))
                work.spend(_STEP + len(claim.objects) + len(fact.objects))
                if not (_same_actor(fact, claim)
                        and (within is None or fact.entry in within)
                        and _qualifiers_supported(fact, claim)
                        and (not claim.scope or fact.scope == claim.scope)
                        # An unclassified proper suffix may be a method/object,
                        # not an activity ("in Rust", "for Open Source"). Its exact
                        # admitted clause remains evidence, without promoting that
                        # unknown phrase into a reusable organization or alias.
                        and (not claim.scope or claim.scope[0] != "$activity_unknown_name"
                             or fold(fact) == fold(claim))
                        # Shortening may drop trailing detail, never promote an object
                        # mentioned only in a method/for-clause into the action itself.
                        and _objects_supported(fact, claim, allow_subjectless_claims)):
                    continue
                if vetoes:
                    reading = fact.objects if allow_subjectless_claims and _tool_omission_supported(fact, claim) else None
                    if reading not in readings:
                        work.spend(len(vetoes) * (_STEP + len(claim.objects)) + denial_tokens[claim.actor, claim.action])
                        found = [other for other in vetoes
                                 if _objects_contradicted(fact, claim, other, allow_subjectless_claims)]
                        readings[reading] = (any(not other.scope for other in found),
                                             {other.scope for other in found}, {other.entry for other in found})
                    unscoped, scopes, entries = readings[reading]
                    if unscoped or fact.scope in scopes or (not fact.scope and fact.entry in entries):
                        continue
                supported.add(fact.entry)
                if any_one:
                    return supported
        return supported

    def supported(claim: _Fact) -> bool:
        if supporting_entries(claim, any_one=True):
            return True
        if not claim.split:
            return False
        # A trailing result must come from the entry that supports the
        # action it is attached to, never from another project.
        head, *tails = claim.split
        entries = supporting_entries(head)
        return bool(entries) and all(supporting_entries(tail, entries, any_one=True) for tail in tails)

    # A repeated claim is decided once.
    decided: dict[_Fact, bool] = {}
    unsupported = []
    for claim in claims:
        if claim not in decided:
            decided[claim] = supported(claim)
        if not decided[claim]:
            unsupported.append(claim)
    return unsupported
