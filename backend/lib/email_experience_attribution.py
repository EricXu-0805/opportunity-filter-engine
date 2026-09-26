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
# Resume sentences may end in a course number or metric. A following digit
# keeps a decimal point intact, including .25; email retains its legacy splitter.
_RESUME_SENTENCES = re.compile(r'\.(?!\d)|[!?;\n]+')
_RESUME_EXPLICIT_BOUNDARY = re.compile(r'\s*[,:]\s*(?=' + _SUBJECT_PATTERN + r')', re.I)
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


def _facts(text: str, *, entry: int, source: bool, allow_subjectless_claims: bool = False) -> list[_Fact]:
    facts = []
    scope: tuple[str, ...] = ()
    label = None
    text = text.replace('’', "'")
    text = re.sub(r"\b(i|we)'ve\b", r'\1 have', text, flags=re.I)
    text = re.sub(r"\b(did|do|does|have|has|had)n['’]t\b", r'\1 not', text, flags=re.I)
    sentences = _RESUME_SENTENCES if allow_subjectless_claims else _SENTENCES
    for sentence in sentences.split(text):
        sentence = sentence.strip(' \t\r\n-•“”\"')
        project = _PROJECT_LABEL.match(sentence) or _PROJECT_PREFIX.match(sentence)
        if project:
            scope = _tokens(project[1]); sentence = sentence[project.end():]
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
        for candidate_clause in _COORDINATED.split(sentence):
            # Only an already recognized leading fragment permits this local
            # boundary. Do not split number commas or contextual prefixes such
            # as "With my team, I built". Keep every following subject to check.
            if allow_subjectless_claims and _action(candidate_clause.strip(' ,\t“”\"')):
                clauses.extend(_RESUME_EXPLICIT_BOUNDARY.split(candidate_clause))
            else:
                clauses.append(candidate_clause)
        for clause in clauses:
            clause = clause.strip(' ,\t“”\"')
            actor = None
            parsed = _action(clause) if allow_subjectless_claims and carried else None
            if parsed:
                actor = carried
            # A contextual "with my team" is not the subject of "I built".
            # Select the subject that actually has a recognized action.
            for subject in (() if parsed else _SUBJECT.finditer(clause)):
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
            # The one neutral editorial suffix used by legacy resume rewrites
            # must not erase a local restriction, including "never carefully"
            # or "without working carefully". A nearby retained source sentence
            # cannot certify a new unrestricted positive assertion.
            if allow_subjectless_claims and (manner := _CARE_QUALIFIER.search(objects)):
                qualifiers.append(manner[1].casefold() + '_carefully')
            # "I tested the parser, not the model" cannot support "tested model".
            negated_object = _OBJECT_NEGATION.search(objects)
            tail = objects[negated_object.end():] if negated_object else None
            if negated_object:
                objects = objects[:negated_object.start()]
            if _BOUND.search(objects):
                qualifiers.append('bounded_quantity')
            tokens = _tokens(objects)
            if allow_subjectless_claims and len(tokens) > 1 and re.search(r'(?:^|\s)carefully$', objects, re.I) and not _CARE_QUALIFIER.search(objects):
                tokens = tokens[:-1]
            if tokens:
                facts.append(_Fact(actor, _VERBS[action[1].casefold()], tokens, local_scope, negative, tuple(sorted(set(qualifiers))), entry))
            if tail and _tokens(tail):
                facts.append(_Fact(actor, _VERBS[action[1].casefold()], _tokens(tail), local_scope, True, tuple(sorted(set(qualifiers))), entry))
    return facts


def _same_actor(source: _Fact, claim: _Fact) -> bool:
    return source.actor == claim.actor or (claim.actor == 'the team' and source.actor == 'team')


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


def experience_attribution_violations(
    text: str, evidence: list[str], *, allow_subjectless_claims: bool = False,
) -> list[str]:
    """Return findings for recognized concrete claims without a local source.

    ``evidence`` must be complete, currently eligible confirmed entry texts,
    never target facts, interests, a generated draft or a user edit instruction.
    ``allow_subjectless_claims`` opts resume output into checking unlabelled
    action fragments such as "Built a parser" as personal claims. It does not
    relabel explicit team actors, infer ownership from Outcome fields, or broaden
    the finite action vocabulary. Resume mode also preserves established legacy
    forms: neutral trailing "carefully", exact analyze/tool/sample structure,
    explicit computational-tool placement, CS course context and EEG analysis
    for/of. These finite structures do not permit arbitrary synonyms or word order.
    Email callers retain their default behavior.
    A missing finding means only this bounded checker did not detect a problem.
    """
    sources = [fact for i, item in enumerate(evidence) if isinstance(item, str)
               for fact in _facts(item, entry=i, source=True, allow_subjectless_claims=allow_subjectless_claims)]
    findings = set()
    for claim in _facts(text, entry=-1, source=False, allow_subjectless_claims=allow_subjectless_claims):
        candidates = [fact for fact in sources if _same_actor(fact, claim)
                      and fact.action == claim.action and fact.negative == claim.negative
                      and fact.qualifiers == claim.qualifiers
                      and (not claim.scope or fact.scope == claim.scope)
                      # Shortening may drop trailing detail, never promote an object
                      # mentioned only in a method/for-clause into the action itself.
                      and _objects_supported(fact, claim, allow_subjectless_claims)]
        supported = False
        for fact in candidates:
            # An explicit denial of this action/object survives nearby positive
            # team text. Separate named projects do not veto one another.
            contradicted = not claim.negative and any(
                other.negative and other.actor == claim.actor and other.action == claim.action
                and (other.entry == fact.entry or not other.scope or other.scope == fact.scope)
                and (not other.scope or not fact.scope or other.scope == fact.scope)
                and _objects_contradicted(fact, claim, other, allow_subjectless_claims)
                for other in sources
            )
            if not contradicted:
                supported = True; break
        if not supported:
            findings.add(f'unsupported experience attribution: {claim.actor} {claim.action}')
    return sorted(findings)
