"""Conservative EN/ZH claim locks, in addition to token/quantity grounding.

This is not semantic entailment. Sensitive source clauses must remain verbatim
apart from whitespace/case and may move; ambiguous paraphrases are refused for
manual review rather than silently upgrading attribution or publication status.
"""
from __future__ import annotations

import re

from backend.lib.email_experience_attribution import (
    _TEAM_CONTEXT,
    _facts,
    _objects_overlap,
    _tokens,
    _unsupported_claims,
    experience_attribution_violations,
)

# Bump independently of the wire/pipeline version when source checks change.
SOURCE_CHECK_VERSION = "target-resume-source-checks-v3"

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
    if publication_stages(proposed) - publication_stages(original):
        return True
    # Compare only this original entry. A shared keyword or number in another
    # project, the target, or editable wording cannot establish who did what.
    # Resume bullets commonly omit "I"; opt into that finite English grammar
    # without changing the email checker's default treatment of fragments.
    return bool(experience_attribution_violations(proposed, [original], allow_subjectless_claims=True))


HELP = re.compile(r"\b(?:help|helped|helping|helps|assist|assisted|assisting|assists)\b|协助|帮助|辅助", re.I)
# A clause appended to mirror a posting states relevance, not something the
# student did: "..., applying computational modeling", "..., building hands-on
# laboratory experience". Allowed only when the original already says it.
RELEVANCE_PADDING = re.compile(
    r"[,，;；]\s*(?:thereby\s+|while\s+)?"
    r"(?:applying|demonstrating|showcasing|highlighting|(?:directly\s+)?relevant\s+to|contributing\s+to"
    r"|(?:building|gaining|developing|strengthening)\b[^,;.]*\b(?:experience|skills?|expertise)\b)"
    r"|[，,]\s*(?:体现|展现|展示)了?|[，,]\s*(?:积累|锻炼|提升)了?[^，,。；;]*(?:经验|能力|技能)|为[^，,。；;]*奠定",
    re.I)


# The same padding, phrased as a trailing clause after the complete original
# ("..., supporting the lab's aims", "..., enabling future work", "，培养了科研能力").
# These words also start real actions, so they count only when appended to an
# original that is otherwise carried whole.
APPENDED_RELEVANCE = re.compile(
    r"[,，;；]\s*(?:thereby\s+|while\s+)?(?P<word>supporting|enabling|strengthening|building|developing|gaining"
    r"|highlighting|reflecting|(?:directly\s+)?relevant\s+to|applicable\s+to|useful\s+for)\b"
    r"|(?:[,，;；]\s*|\s+)(?P<focus>with\s+a\s+focus\s+on)\b"
    r"|[，,；;]\s*(?P<zh>培养|提升|锻炼)"
    r"|[，,；;]?\s*(?P<base>为[^，,。；;]*打下[^，,。；;]*基础)"
    r"|[，,；;]\s*(?P<related>与[^，,。；;]*相关)",
    re.I)
# Self-assessed quality is not something the original says the student did.
QUALITY = re.compile(
    r"\b(?:clear(?:ly)?|robust(?:ly)?|efficient(?:ly)?|effective(?:ly)?|comprehensive(?:ly)?|successful(?:ly)?"
    r"|significant(?:ly)?|substantial(?:ly)?|novel|innovative|rigorous(?:ly)?|thorough(?:ly)?|high-quality"
    r"|scalable|reliable|sophisticated|state-of-the-art|cutting-edge|extensive(?:ly)?|impactful)\b"
    r"|高质量|高效|清晰|全面|深入|创新|显著|成功|出色|优秀|严谨", re.I)
_NOT_PREPOSITION = r"(?!(?:for|in|during|at|within|on|with|to)\b)"
# A named setting the student worked in ("for a research project", "during CS
# 225 coursework", "为课题组的项目"). A new one is a new fact about the work.
SETTING = re.compile(
    r"\b(?:for|in|during|at|within)\s+(?:(?:a|an|the|my|our)\s+)?(?:" + _NOT_PREPOSITION + r"[\w'’-]+\s+){0,4}?"
    r"(?:projects?|study|studies|lab|laboratory|coursework|course|class|internship|competition|hackathon|program|company)\b"
    r"|(?:在|为|于)[^，,。；;在为于]{0,20}?(?:项目|课题|实验室|课程|课堂|公司|实习|比赛|竞赛)", re.I)
_CJK = re.compile(r"[\u4e00-\u9fff]")
# "did not build", "never led", "没有主导": a denial of the action that follows.
# A bare 不/未 is not one: 不断 (keep on), 不同 (different), 不少 (many), 未来.
DENIAL = re.compile(
    r"\b(?:not|never|no)\b|\b\w+n['’]t\b|没有|并非|尚未|从未|未(?!来|知)"
    r"|不(?:曾|会|能|是|负责|主导|带领|独立|领导|参与|承担|完成|开发|构建|实现|搭建|设计|审阅|检查|独自|单独)", re.I)
_TEAM_OWNER = re.compile(r"\b(?:my|our)\s+(?:team|teammates?|group|colleagues?)\b", re.I)
_OBJECT_END = re.compile(
    r"\s+(?:and|then|while|as|in|for|with|using|on|at|during|to)\b|[,，、;；。.!?！？:：]|并|和|及|以及", re.I)
_OBJECT_TAIL = frozenset({"in", "for", "on", "with", "without", "during", "at", "as", "of", "using", "via", "by",
                          "from", "to", "across", "into", "within", "through", "under", "and", "reaching",
                          "achieving", "not", "no", "never", "did", "which", "that", "including", "except"})
# Commas and brackets end an object; the parser's tokens have lost them.
_OBJECT_BREAK = re.compile(r"(?<!\d)[,，]|[,，](?!\d)|[;；:：()（）\[\]]")
_SETTING_LEAD = re.compile(r"^(?:(?:for|in|during|at|within)\s+(?:(?:a|an|the)\s+)?|[在为于])")
LEADERSHIP = ("lead", "own", "independent")


def _team_marked(text):
    return bool(TEAM.search(text) or _TEAM_CONTEXT.search(text))


def _team_attributed(clause):
    # "My team built" names the team as the actor; "my" there is not the student.
    return _team_marked(clause) and not PERSONAL.search(_TEAM_OWNER.sub(" ", clause))


def _action_objects(clause, after=0, before=None):
    """(action family, object words) for each ACTIONS verb in ``clause``, EN or ZH."""
    pairs = set()
    for name, pattern in ACTIONS.items():
        for match in re.finditer(pattern, clause, re.I):
            if match.start() < after or (before is not None and match.start() >= before):
                continue
            rest = re.sub(r"^\s*(?:了|过)?", "", clause[match.end():])
            words = re.sub(r"\b(?:a|an|the|its|their)\b", " ", _OBJECT_END.split(rest, maxsplit=1)[0].lower())
            if words.split():
                pairs.add((name, " ".join(words.split())))
    return pairs


def _moved_claims(proposed, original):
    """An action+object the original gives to the team or denies, now asserted as the student's."""
    team, denied, affirmed = set(), set(), set()
    for clause in clauses(original):
        denial = DENIAL.search(clause)
        if denial:
            denied |= _action_objects(clause, after=denial.start())
        # What a clause says before its denial is still asserted.
        (team if _team_attributed(clause) else affirmed).update(
            _action_objects(clause, before=denial.start() if denial else None))
    found = []
    for clause in clauses(proposed):
        denial = DENIAL.search(clause)
        pairs = _action_objects(clause, before=denial.start() if denial else None)
        if not _team_attributed(clause) and pairs & (team - affirmed):
            found.append("team_result_claimed")
        if pairs & (denied - affirmed):
            found.append("denied_action_asserted")
    return found


def _object_core(fact):
    """The object noun phrase before its first comma, bracket or tail word."""
    objects, limit = fact.objects, len(fact.objects)
    stream = _tokens(fact.clause)
    start = next((i for i in range(len(stream) - limit + 1) if stream[i:i + limit] == objects), None)
    if start is not None:
        count = 0
        for segment in _OBJECT_BREAK.split(fact.clause)[:-1]:
            count += len(_tokens(segment))
            if start < count < start + limit:
                limit = count - start
                break
    core = []
    for token in objects[:limit]:
        if token in _OBJECT_TAIL:
            break
        core.append(token)
    return tuple(core)


def _object_head(core):
    head = core[-1] if core else ""
    return head[:-1] if len(head) > 3 and head.endswith("s") else head


def _participle(token):
    return len(token) > 4 and token.endswith(("ing", "ed"))


def _heads(core):
    # Without its comma, "a sensor rig supporting 4 experiments" may end at "rig".
    return {_object_head(core)} | {_object_head(core[:i]) for i in range(1, len(core)) if _participle(core[i])}


def _abbreviates(core, other):
    head = _object_head(core)
    return len(head) >= 2 and head.isalpha() and "".join(token[0] for token in other).endswith(head)


def _same_object(core, cores):
    """A head the source names, spells out ("app"/"application") or abbreviates ("CNN")."""
    for other in cores:
        for head in _heads(core):
            for source_head in _heads(other):
                short, long = sorted((head, source_head), key=len)
                if head == source_head or (len(short) >= 3 and long.startswith(short)):
                    return True
        if _abbreviates(core, other) or _abbreviates(other, core):
            return True
    return False


def _head_dropped(core, cores):
    """"a web app mockup" -> "a web app": the shortened object ends before the source's head."""
    return bool(core) and core not in cores and any(
        len(other) > len(core) and other[:len(core)] == core and not _participle(other[len(core)])
        for other in cores)


def _parsed_claim_findings(proposed, original):
    """Hard findings among EN claims the attribution parser reads but cannot support.

    The parser names actor, action, polarity and ordered object for both texts,
    so a claim whose object the original denies, gives to the team, attaches a
    number to or names differently is a changed fact, not a paraphrase. A claim
    the parser cannot relate to any source fact stays with the review.
    """
    sources = _facts(original, entry=0, source=True, allow_subjectless_claims=True)
    found = []
    # The parser accepts a shortened object as dropped detail; dropping the
    # head noun ("a web app mockup" -> "a web app") names a different thing.
    for claim in _facts(proposed, entry=-1, source=False, allow_subjectless_claims=True):
        cores = {_object_core(fact) for fact in sources
                 if fact.action == claim.action and fact.actor == claim.actor and not fact.negative}
        if not claim.negative and _head_dropped(_object_core(claim), cores):
            found.append("object_changed")
    for claim in _unsupported_claims(proposed, [original], True, None):
        if claim.negative:
            continue
        same = [fact for fact in sources if fact.action == claim.action and _objects_overlap(claim, fact, True)]
        if any(fact.negative for fact in same):
            found.append("denied_action_asserted")
        if claim.actor == "personal" and not {"team", "help"} & set(claim.qualifiers) and any(
                not fact.negative and (fact.actor in {"team", "the team"} or "team" in fact.qualifiers)
                for fact in same):
            found.append("team_result_claimed")
        core = _object_core(claim)
        head = _object_head(core)
        numbers = {token for token in claim.objects if token[0].isdigit()}
        placed = [fact for fact in sources if fact.action == claim.action and _object_head(_object_core(fact)) == head]
        if placed and numbers & {token for fact in sources for token in fact.objects} - {
                token for fact in placed for token in fact.objects}:
            found.append("quantity_moved")
        cores = {_object_core(fact) for fact in sources
                 if fact.action == claim.action and fact.actor == claim.actor and not fact.negative}
        # A spelled-out or abbreviated head is a paraphrase for the review.
        if cores and not _same_object(core, cores):
            found.append("object_changed")
    return found


def _setting_in(setting, original_normal):
    """"at the Smith Lab" restates "in the Smith Lab": same setting, another preposition."""
    if setting in original_normal:
        return True
    place = _SETTING_LEAD.sub("", setting)
    return bool(re.search(r"(?:\b(?:for|in|during|at|within)\s+(?:(?:a|an|the)\s+)?|[在为于])"
                          + re.escape(place) + r"(?![a-z0-9_])", original_normal))


def _appended_relevance(proposed, original):
    original_normal = normalized(original)
    original_words = set(re.findall(r"[a-z0-9]+|[一-鿿]", original_normal))
    for match in APPENDED_RELEVANCE.finditer(proposed):
        word = normalized(next(value for value in match.groupdict().values() if value))
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", original_normal):
            continue
        appended = not re.search(r"[.。!?！？;；]\s*\S", proposed[match.end():])
        carried = original_words <= set(re.findall(r"[a-z0-9]+|[一-鿿]", normalized(proposed[:match.start()])))
        if appended and carried:
            return True
    return False


def claim_upgrade_findings(proposed, original):
    """Split the single-bullet claim locks into (hard, soft) findings.

    Hard findings change who did what, add an action, status, leadership,
    setting, quality or relevance clause, move a number or name a different
    object, or drop a team/help/negation/publication qualifier entirely; no
    reviewer may overrule them. Soft findings are the paraphrase-level
    failures of this finite checker (a locked clause reworded while its
    qualifier words survive, an object reworded or a setting moved), which a
    faithfulness review may accept. ``claim_upgrade_detected`` is unchanged:
    whenever it rejects, at least one finding is returned here.
    """
    if normalized(proposed) == normalized(original):
        return [], []
    hard = []
    if _team_marked(original) and not _team_marked(proposed):
        hard.append("team_qualifier_dropped")
    # "As part of a team" may stand in for "helped" only when the original
    # already said the work was shared.
    if HELP.search(original) and not HELP.search(proposed) and not (
            _team_marked(original) and _team_marked(proposed)):
        hard.append("help_qualifier_dropped")
    if NEGATION.search(original) and not NEGATION.search(proposed):
        hard.append("negation_dropped")
    if PUBLICATION.search(original) and not PUBLICATION.search(proposed):
        hard.append("publication_qualifier_dropped")
    if personal_actions(proposed) - personal_actions(original):
        hard.append("personal_action_added")
    if publication_stages(proposed) - publication_stages(original):
        hard.append("publication_stage_added")
    original_normal = normalized(original)
    if any(normalized(match.group(0)).strip(",，;； ") not in original_normal
           for match in RELEVANCE_PADDING.finditer(proposed)) or _appended_relevance(proposed, original):
        hard.append("relevance_clause_added")
    # Inside a team clause too: personal_actions skips those, and "helped design"
    # as part of a team must not become "led the design".
    if any(re.search(ACTIONS[name], proposed, re.I) and not re.search(ACTIONS[name], original, re.I)
           for name in LEADERSHIP):
        hard.append("leadership_claim_added")
    # A Chinese rewrite of an English original (locale zh) is a translation this
    # word comparison cannot judge; Chinese words are compared with Chinese only.
    comparable = [match for pattern in (SETTING, QUALITY) for match in pattern.finditer(proposed)
                  if not _CJK.search(match.group(0)) or _CJK.search(original)]
    if any(match.re is SETTING and not _setting_in(normalized(match.group(0)), original_normal)
           for match in comparable):
        hard.append("setting_added")
    if any(match.re is QUALITY and normalized(match.group(0)) not in original_normal for match in comparable):
        hard.append("quality_claim_added")
    hard.extend(dict.fromkeys(_moved_claims(proposed, original) + _parsed_claim_findings(proposed, original)))
    soft = []
    proposed_normal = normalized(proposed)
    if any((NEGATION.search(clause) or TEAM.search(clause) or PUBLICATION.search(clause))
           and normalized(clause) not in proposed_normal for clause in clauses(original)):
        soft.append("locked_clause_reworded")
    if experience_attribution_violations(proposed, [original], allow_subjectless_claims=True):
        soft.append("attribution_unverified")
    return hard, soft


def supported_claim_upgrade_detected(proposed, originals):
    """Finite checks over explicit source entries; never collapse their attribution.

    Shared activity membership permits consulting selected entries, not moving a
    number, action, actor or qualifier between their clauses. Ambiguous syntax
    remains outside this finite EN/ZH checker and is not a semantic guarantee.
    """
    if len(originals) == 1:
        return claim_upgrade_detected(proposed, originals[0])
    proposed_normal = normalized(proposed)
    for original in originals:
        for clause in clauses(original):
            if (NEGATION.search(clause) or TEAM.search(clause) or PUBLICATION.search(clause)) and normalized(clause) not in proposed_normal:
                return True
    if personal_actions(proposed) - set().union(*(personal_actions(original) for original in originals)):
        return True
    if publication_stages(proposed) - set().union(*(publication_stages(original) for original in originals)):
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
                for tool in tools:
                    if objects.endswith(' with ' + tool):
                        objects = objects[:-len(' with ' + tool)] + ' using ' + tool
                values.append((action, actor, objects))
        return values

    permitted = set()
    for source in originals:
        for action, actor, objects in forms(source):
            permitted.add((action, actor, objects))
            for tool in tools:
                if action != 'exact' and objects.endswith(' using ' + tool):
                    permitted.add((action, actor, objects[:-len(' using ' + tool)]))
    proposed_forms = forms(proposed)
    return bool(proposed_forms) and all(item in permitted for item in proposed_forms)
