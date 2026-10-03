"""Conservative EN/ZH claim locks, in addition to token/quantity grounding.

This is not semantic entailment. Sensitive source clauses must remain verbatim
apart from whitespace/case and may move; ambiguous paraphrases are refused for
manual review rather than silently upgrading attribution or publication status.
"""
from __future__ import annotations

import bisect
import re

from backend.lib.email_experience_attribution import _TEAM_CONTEXT, experience_attribution_violations

# Bump independently of the wire/pipeline version when source checks change.
SOURCE_CHECK_VERSION = "target-resume-source-checks-v4"

NEGATION = re.compile(r"\b(?:not|never|no|without|only)\b|\b\w+n['’]t\b|没有|并非|尚未|从未|未经|仅|只|未|不(?:曾|会|能|是|负责|主导|带领|独立|领导|参与|承担|完成|接受|录用|发表)", re.I)
TEAM = re.compile(r"\b(?:team|teammates?|we|our|collaborat\w*)\b|团队|小组|我们|共同|协作|合作", re.I)
PUBLICATION = re.compile(r"\b(?:submitted|submission|under review|accepted|acceptance|published|publication|preprint|rejected|withdrawn)\b|投稿|提交|审稿|评审|录用|发表|出版|预印本|拒稿|撤稿", re.I)
PERSONAL = re.compile(r"\b(?:i|my|personally|independently)\b|本人|我(?!们)|独立|个人", re.I)
ACTIONS = {
    "lead": r"\b(?:lead|led|leading|leader|leadership|managed|headed)\b|主导|带领|领导|牵头",
    "own": r"\b(?:owned|ownership|responsible)\b|负责|承担",
    "build": r"\b(?:built|build|developed|implemented|created)\b|开发|构建|实现|搭建|完成",
    # "design team", "design project": the noun, not something the student designed.
    "design": r"\b(?:designed|design(?!\s+(?:teams?|groups?|projects?|courses?|class(?:es)?|competitions?|challenges?|studios?)\b))\b|设计",
    "review": r"\b(?:reviewed|review)\b|审阅|检查",
    "independent": r"\b(?:independently|solely|alone|sole)\b|独立|独自|单独",
}
STAGES = {
    "accepted": r"\b(?:accepted|acceptance)\b|录用",
    "published": r"\b(?:published|publication)\b|发表|出版",
}
# "Responsible for building" states build. A gerund counts only where it is the
# clause's own action: first in the clause, after a comma, or after one of these
# openers. "Interested in building", "participated in building" and "the Beckman
# building" state no build.
ACTION_GERUNDS = {
    "lead": r"leading|managing|heading",
    "build": r"building|developing|implementing|creating",
    "design": r"designing",
    "review": r"reviewing",
}
_GERUND_POSITION = re.compile(
    r"(?:^|[,，]\s*|\b(?:responsible\s+for|in\s+charge\s+of|helped(?:\s+with)?|assisted\s+(?:with|in)"
    r"|my\s+(?:part|role|job|task)s?\s+(?:was|were|is|are|included))\s+)"
    r"(?:(?:also|currently|still|personally|independently|jointly|actively)\s+)?(?P<word>[a-z]+ing)\b"
    # "building on prior protocols" draws on earlier work; it builds nothing.
    r"(?!(?<=building)\s+(?:on|upon)\b)", re.I)
# "wiring the logger and designing the battery": a gerund joined to a guarded one is guarded too.
_GERUND_AND = re.compile(r"^[^,，;；]*?\b(?:and|or)\s+(?P<word>[a-z]+ing)\b", re.I)
# Hoped-for, planned or tried work. Dropping the word turns it into work done.
# 拟 plans (拟于, 拟招募), but 模拟 simulates, 拟合 fits, 拟定 draws up a plan and 拟南芥
# is Arabidopsis.
_ZH_PLAN = r"(?<![模虚草比])拟(?!合|人|稿|南芥|定(?!于|在))"
INTENT = re.compile(
    r"\b(?:aim(?:s|ed|ing)?|hop(?:e|es|ed|ing)|plan(?:s|ned|ning)?|tr(?:y|ies|ied|ying)|attempt(?:s|ed|ing)?"
    r"|intend(?:s|ed|ing)?|want(?:s|ed|ing)?|seek(?:s|ing)?|sought|looking|eager|applying|would\s+like)\s+to\b"
    r"|\binterest(?:ed)?\s+in\b|\bgoal\s+(?:is|was)\s+to\b"
    r"|希望|计划|打算|" + _ZH_PLAN + r"|想要|有意|期望|期待|感兴趣|志在", re.I)
# A planned or scheduled thing, where INTENT needs "to": "a planned EEG study",
# "a proposed NSF grant", "a study scheduled for May", 预定于 5 月. "Planned the
# outreach event" and "the proposed model" state no status, nor does "the
# scheduled maintenance", routine work done to a schedule.
PLANNED = re.compile(
    r"\b(?:a|an|the|this|that|these|those|my|our|their|its|his|her|one|two|three|four|five|several|\d+)\s+"
    r"(?:planned|proposed(?=\s+(?:[\w-]+\s+){0,2}?(?:grants?|stud(?:y|ies)|projects?"
    r"|experiments?|research|trials?|surveys?|fieldwork)\b))\b"
    r"|\b(?:planned|scheduled)\s+(?:for|to)\b|\btentative(?:ly)?\b|预定(?!了)|暂定", re.I)
# Work the original says is unfinished. A past-tense verb for it, or a Chinese
# rewrite without any such word, states it finished.
UNFINISHED = re.compile(
    r"\b(?:in\s+preparation|in[\s-]+progress|wip|ongoing|on-going|currently|not\s+yet|pending|forthcoming|upcoming"
    r"|to\s+appear|in\s+press|underway|will|unpublished|unfinished|expected|anticipated"
    r"|under\s+(?:review|revision|development|construction)|in\s+development(?!\s+of)|drafting)\b", re.I)
# A Chinese action verb + 中 is work under way when it ends its clause or describes
# a thing (系统开发中, 开发中的系统); within four characters after 在, 到 or 入 it is a
# place (在研究中发现, 在项目开发中). 在王老师指导下智能温室系统开发中 is still under way.
_ZH_UNDERWAY_VERBS = (
    "开发|测试|分析|研究|整理|采集|申请|审核|审稿|评审|撰写|准备|进行|筹备|设计|调试|搭建|建设|修改|修订|编写|实施|推进"
    "|招募|收集|处理|训练|优化|验证|调研|构建|部署|迭代|改进|完善|制作|编辑|翻译|录入|标注|统计|计算|筹建|筹划|策划|起草"
    "|实验|试验|研发|研制|孵化|运营|维护|升级|评估|审查|审批|投稿|提交|拍摄|剪辑|录制|复现|重构")
_ZH_PROGRESSIVE = ("".join(rf"(?<![在到入][^，,。；;：:、！？!?]{{{n}}})" for n in range(5))
                   + rf"(?:{_ZH_UNDERWAY_VERBS})中(?=$|[，,。；;：:、！？!?)）\s]|的)")
# Chinese for work still to come: 将在, 将会 and 将要 say "will"; in 将在线问卷, 将会议记录,
# 将会员信息, 将要点, 将要求 and 将要素, 将 marks the object.
FUTURE_ZH = re.compile(r"预计|即将|将于|将在(?!线)|将会(?!议|员)|将要(?!点|求|素)")
# Chinese for work under way or still to come; with the intent words below it is
# what status_upgraded reads.
UNDERWAY_ZH = re.compile(r"正在|撰写中|准备中|进行中|筹备中|在投|待发表|目前|尚未|未完成|未发表|" + FUTURE_ZH.pattern + "|"
                         + _ZH_PROGRESSIVE)
UNFINISHED_ZH = re.compile(UNDERWAY_ZH.pattern + r"|计划|打算|希望|" + _ZH_PLAN + r"|想要")

# Résumé verbs and their forms. Inflection only, not synonyms: every form maps
# back to one base, so "writing", "wrote" and "writes" are the same verb.
_REGULAR_VERBS = """
accelerate accept achieve acquire adapt add address adjust administer advise advocate aid align allocate analyse
analyze annotate answer apply appraise arrange assemble assess assign assist attend audit author automate balance
benchmark brainstorm budget calculate calibrate capture catalog categorize chair characterize chart check clarify
classify clean code collaborate collect communicate compare compile complete compose compute conceive conduct
configure consolidate construct consult contribute convert coordinate correct count create culture curate
customize cycle decrease define delegate deliver demonstrate deploy design detect determine develop devise
diagnose digitize direct discover dissect distribute document draft educate edit eliminate enable encourage
engineer enhance enroll ensure establish estimate evaluate examine execute expand experiment explain explore
extract fabricate facilitate file filter fix forecast format formulate gather generate genotype grade graph
guide handle help host identify illustrate image implement improve increase influence inform initiate inspect
install instruct integrate interpret interview introduce investigate isolate launch learn lecture maintain manage
manufacture market measure mentor merge migrate moderate modify monitor motivate negotiate observe obtain operate
optimize organize outline participate perform pilot position prepare present prioritize process produce promote
propose prototype provide publish purify quantify query raise rank reach recommend reconcile record recruit
redesign reduce refactor refine register reorganize repair report represent research resolve respond restructure
review revise sample scale schedule score screen sequence serve shadow simulate sketch solder solve sort source
spearhead standardize stain streamline strengthen study summarize supervise support survey synthesize tabulate
teach test titrate track train transcribe transform translate troubleshoot tutor update upgrade use validate verify
visualize volunteer walk work
"""
# Doubled final consonant before -ed/-ing ("planned", "debugging").
_DOUBLING_VERBS = """
admit ban chat clip commit compel control debug drop equip fit flip grab jog log map occur omit pat patrol permit
pin plan plot prefer prep program refer regret scan ship skim slip spot step stop strip submit sum tag tap tip
transfer transmit trim wrap zip
"""
# Both spellings of a doubled -l ("modeled", "modelled").
_L_VERBS = "cancel channel counsel fuel label level model signal travel total"
_IRREGULAR_VERBS = {
    "begin": ("began", "begun"), "bring": ("brought",), "build": ("built",), "buy": ("bought",), "catch": ("caught",),
    "choose": ("chose", "chosen"), "co-write": ("co-wrote", "co-written"), "cut": ("cut",), "deal": ("dealt",),
    "do": ("did", "done"), "draw": ("drew", "drawn"), "drive": ("drove", "driven"), "feed": ("fed",),
    "find": ("found",), "fly": ("flew", "flown"), "forget": ("forgot", "forgotten"), "get": ("got", "gotten"),
    "give": ("gave", "given"), "go": ("went", "gone"), "grow": ("grew", "grown"), "hold": ("held",),
    "keep": ("kept",), "know": ("knew", "known"), "lead": ("led",), "lend": ("lent",), "lose": ("lost",),
    "make": ("made",), "meet": ("met",), "oversee": ("oversaw", "overseen"), "pay": ("paid",), "put": ("put",),
    "read": ("read",), "rebuild": ("rebuilt",), "rewrite": ("rewrote", "rewritten"), "run": ("ran",),
    "say": ("said",), "seek": ("sought",), "sell": ("sold",), "send": ("sent",), "set": ("set",),
    "show": ("showed", "shown"), "speak": ("spoke", "spoken"), "spend": ("spent",), "stand": ("stood",),
    "take": ("took", "taken"), "teach": ("taught",), "tell": ("told",), "think": ("thought",),
    "undergo": ("underwent", "undergone"), "understand": ("understood",), "undertake": ("undertook", "undertaken"),
    "win": ("won",), "write": ("wrote", "written"),
}
_DOUBLED_IRREGULAR = {"begin", "cut", "forget", "get", "put", "run", "set", "win"}
# Verbs whose past is spelled like the base (cut, put, read, set); the forms table reads that spelling as the base.
_PAST_AS_BASE = frozenset(base for base, past in _IRREGULAR_VERBS.items() if base in past)


def _third_person(base):
    if re.search(r"[^aeiou]y$", base):
        return base[:-1] + "ies"
    return base + ("es" if re.search(r"(?:s|x|z|ch|sh|o)$", base) else "s")


def _ing(base, doubled):
    if doubled:
        return base + base[-1] + "ing"
    if base.endswith("ie"):
        return base[:-2] + "ying"
    if base.endswith("e") and not base.endswith(("ee", "ye", "oe")):
        return base[:-1] + "ing"
    return base + "ing"


def _past(base, doubled):
    if doubled:
        return base + base[-1] + "ed"
    if base.endswith("e"):
        return base + "d"
    if re.search(r"[^aeiou]y$", base):
        return base[:-1] + "ied"
    return base + "ed"


def _verb_forms():
    forms: dict[str, tuple[str, str]] = {}
    for base, past in _IRREGULAR_VERBS.items():
        for form in past:
            forms[form] = (base, "past")
        forms[_ing(base, base in _DOUBLED_IRREGULAR)] = (base, "ing")
        forms[_third_person(base)] = (base, "s")
    doubling = set(_DOUBLING_VERBS.split())
    for base in _REGULAR_VERBS.split() + sorted(doubling) + _L_VERBS.split():
        variants = [base in doubling] + ([True] if base in _L_VERBS.split() else [])
        for doubled in variants:
            forms.setdefault(_past(base, doubled), (base, "past"))
            forms.setdefault(_ing(base, doubled), (base, "ing"))
        forms.setdefault(_third_person(base), (base, "s"))
    for base in list(_IRREGULAR_VERBS) + _REGULAR_VERBS.split() + sorted(doubling) + _L_VERBS.split():
        # A form spelled like its base ("read", "set") is read as the base.
        forms[base] = (base, "base")
    return forms


RESUME_VERB_FORMS = _verb_forms()
_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")


def verb_use(word):
    """(base, kind) for a résumé verb form, kind one of base/past/ing/s; else None.

    A hyphenated compound is read by its last part ("co-authored" -> author).
    """
    word = word.casefold()
    return RESUME_VERB_FORMS.get(word) or RESUME_VERB_FORMS.get(word.rsplit("-", 1)[-1])


def _verb_uses(text):
    return [use for word in _WORD.findall(text) if (use := verb_use(word))]


def _lead_word(clause):
    """The clause's first word after "also", "still", "now", "currently" or an -ly adverb."""
    words = [word.casefold() for word in _WORD.findall(clause)]
    while words and (words[0] in {"also", "still", "now", "currently"} or words[0].endswith("ly")):
        words.pop(0)
    return words[0] if words else ""


def _progressive_clause(clause):
    return (verb_use(_lead_word(clause)) or ("", ""))[1] == "ing"


def _unknown_lead_finished(proposed, original):
    """A clause of the original led by an -ing word whose -ed form the rewrite adds.

    This reads the verbs the résumé list does not know: in "Wiring 3 soil
    sensors" -> "...: wired 3 soil sensors" the rewrite's own past form shows
    the word is a verb. Read by its suffix alone, "Visiting student",
    "Fundraising chair" and "Peking University" would lead work under way too.
    """
    leads = {lead[:-3] for clause in clauses(original) if (lead := _lead_word(clause)).endswith("ing")}
    stated = {word.casefold()[:-2] for word in _WORD.findall(original) if word.casefold().endswith("ed")}
    return any(word.casefold()[:-2] in leads - stated for word in _WORD.findall(proposed) if word.casefold().endswith("ed"))


def status_upgraded(proposed, original):
    """Planned, hoped-for or unfinished work now stated as done.

    English: the original marks the work as unfinished or intended (a status
    word, an intent phrase, or a clause led by a résumé verb's -ing form) and
    the rewrite uses the past tense of a verb the original only has in another
    form ("Co-authoring ... (in preparation)" -> "Co-authored ..."), or a clause
    led by an -ing word the list does not know has its -ed form in the rewrite
    ("Wiring ..." -> "wired"). Chinese: one
    of the original's unfinished or intent words is gone from a Chinese
    rewrite ("正在开发" -> "开发了"), even beside another one. A kept "(in
    preparation)" does not make a finished verb faithful.
    """
    # As many such words stay, of each kind: 论文将于 5 月发表，目前正在准备答辩 keeps its 将于
    # beside 目前, while 目前在做 may say 正在制作.
    if _CJK.search(proposed) and any(len(pattern.findall(proposed)) < len(pattern.findall(original))
                                     for pattern in (FUTURE_ZH, UNDERWAY_ZH, UNFINISHED_ZH)):
        return True
    if _unknown_lead_finished(proposed, original):
        return True
    if not (UNFINISHED.search(original) or INTENT.search(original)
            or any(_progressive_clause(clause) for clause in clauses(original))):
        return False
    uses = _verb_uses(original)
    past = {base for base, kind in uses if kind == "past"}
    other = {base for base, kind in uses if kind != "past"}
    # "Setting up a server" -> "set up a server": a verb that is its own past, which the
    # original has only under way, states the work done.
    under_way = _PAST_AS_BASE & ({base for base, kind in uses if kind == "ing"} - {base for base, kind in uses if kind != "ing"})
    return any(base in other - past if kind == "past" else kind == "base" and base in under_way
               for base, kind in _verb_uses(proposed))


def normalized(text):
    return " ".join(text.lower().split()).strip()


def clauses(text):
    # A negated first clause must not exempt an affirmative claim after an
    # explicit contrast: "not accepted, but later accepted" is two claims.
    # Keep this a bounded EN/ZH rule, not a general semantic parser. Splitting
    # also permits truthful "did not lead, but reviewed" clauses to reorder.
    # A boundary's leading space starts where a run of spaces starts, so a long run
    # is read once, not once from each of its characters.
    boundaries = (
        r"(?<!\d)\.(?!\d)|[!?;。！？；\n]+"
        r"|(?:[，,]|(?<!\s)|(?!\s))\s*\b(?:but|however|nevertheless)\b\s*[,，]?\s*"
        # A bare 'yet' can be temporal ('not yet accepted'), not a contrast.
        r"|[，,]\s*\byet\b\s*[,，]?\s*"
        r"|(?:[，,]|(?<!\s)|(?!\s))\s*(?:但是|但|然而|不过|卻|却)\s*[,，]?\s*"
    )
    return [part.strip() for part in re.split(boundaries, text, flags=re.I) if part.strip()]


def _guarded_gerunds(clause):
    """Action families of the gerunds that are this clause's own action."""
    found, text = set(), clause.strip()
    for match in _GERUND_POSITION.finditer(text):
        words, rest = [match["word"]], text[match.end():]
        while more := _GERUND_AND.match(rest):
            words.append(more["word"])
            rest = rest[more.end():]
        for word in words:
            for name, pattern in ACTION_GERUNDS.items():
                if re.fullmatch(pattern, word, re.I):
                    found.add(name)
    return found


def personal_actions(text, gerunds=False):
    found = set()
    for clause in clauses(text):
        # "My team built" names the team as the actor; "my" there is not the student.
        if NEGATION.search(clause) or _team_attributed(clause):
            continue
        # Résumé fragments with no subject are personal claims too.
        for name, pattern in ACTIONS.items():
            if any(not _team_relative(clause, match.start()) for match in re.finditer(pattern, clause, re.I)):
                found.add(name)
        if gerunds:
            found |= _guarded_gerunds(clause)
    return found


# The gates with no review behind them (the selection plan's compress rewrites,
# a multi-source merge) read actions as source-checks-v3 did. "Jointly", "with
# two classmates", "a team that built" and a "design team" noun never hide an
# action there; personal_actions reads that wider team context only because
# every rewrite claim_upgrade_findings passes still goes to the review.
_STATED_ACTIONS = {**ACTIONS, "design": r"\b(?:designed|design)\b|设计"}


def _stated_personal_actions(text):
    found = set()
    for clause in clauses(text):
        if NEGATION.search(clause) or (TEAM.search(clause) and not PERSONAL.search(clause)):
            continue
        for name, pattern in _STATED_ACTIONS.items():
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
    if _stated_personal_actions(proposed) - _stated_personal_actions(original):
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
    r"|(?:building|gaining|developing|strengthening)\b[^,;.，；]*\b(?:experience|skills?|expertise)\b)"
    r"|[，,]\s*(?:体现|展现|展示)了?|[，,]\s*(?:积累|锻炼|提升)了?[^，,。；;]*(?:经验|能力|技能)|为[^，,。；;为]*奠定",
    re.I)


# The same padding, phrased as a trailing clause after the complete original
# ("..., supporting the lab's aims", "..., enabling future work", "，培养了科研能力").
# These words also start real actions, so they count only when appended to an
# original that is otherwise carried whole.
APPENDED_RELEVANCE = re.compile(
    r"[,，;；]\s*(?:thereby\s+|while\s+)?(?P<word>supporting|enabling|strengthening|building|developing|gaining"
    r"|highlighting|reflecting|(?:directly\s+)?relevant\s+to|applicable\s+to|useful\s+for)\b"
    r"|(?:[,，;；]\s*|(?<!\s)\s+)(?P<focus>with\s+a\s+focus\s+on)\b"
    r"|[，,；;]\s*(?P<zh>培养|提升|锻炼)"
    r"|(?:[，,；;]|(?<![\s，,；;]))\s*(?P<base>为(?:(?!打下)[^，,。；;为])*打下[^，,。；;为]*基础)"
    r"|[，,；;]\s*(?P<related>与[^，,。；;]*相关)",
    re.I)
# Self-assessed quality is not something the original says the student did.
QUALITY = re.compile(
    r"\b(?:clear(?:ly)?|robust(?:ly)?|efficient(?:ly)?|effective(?:ly)?|comprehensive(?:ly)?|successful(?:ly)?"
    r"|significant(?:ly)?|substantial(?:ly)?|novel|innovative|rigorous(?:ly)?|thorough(?:ly)?|high-quality"
    r"|scalable|reliable|sophisticated|state-of-the-art|cutting-edge|extensive(?:ly)?|impactful"
    # A proficiency is a skill level the original never states.
    r"|proficient(?:ly)?|proficiency|expert|expertise|advanced|fluent(?:ly)?|skilled|skillful(?:ly)?|adept)\b"
    r"|高质量|高效|清晰|全面|深入|创新|显著|成功|出色|优秀|严谨|熟练|精通|擅长", re.I)
_NOT_PREPOSITION = r"(?!(?:for|in|during|at|within|on|with|to)\b)"
# A named setting the student worked in ("for a research project", "during CS
# 225 coursework", "为课题组的项目"). A new one is a new fact about the work.
SETTING = re.compile(
    r"\b(?:for|in|during|at|within)\s+(?:(?:a|an|the|my|our)\s+)?(?:" + _NOT_PREPOSITION + r"[\w'’-]+\s+){0,4}?"
    r"(?:projects?|study|studies|lab|laboratory|coursework|course|class|internship|competition|hackathon|program|company"
    # "research" as a setting ("for aging research"), not a role or skill word.
    r"|research(?!\s+(?:assistants?|associates?|aides?|interns?|technicians?|fellows?|fellowships?|scholars?"
    r"|volunteers?|coordinators?|experiences?|methods?|skills?|interests?|papers?|articles?)\b))\b"
    # A Chinese setting phrase stops at a bracket and at 并/和/及/、: "为认知测验评分并
    # 安排被试（认知老化实验室" is two actions and an aside, not a setting.
    r"|(?:在|为|于)[^，,。；;在为于（）()并和及、]{0,20}?(?:项目|课题|实验室|课程|课堂|公司|实习|比赛|竞赛"
    r"|研究(?!助理|生|员|方法|兴趣|经历|经验|能力))", re.I)
_CJK = re.compile(r"[\u4e00-\u9fff]")
# "did not build", "never led", "没有主导": a denial of the action that follows.
# A bare 不/未 is not one: 不断 (keep on), 不同 (different), 不少 (many), 未来.
# 不 denies only an action verb it directly precedes (不牵头, 不负责), or one after
# a closed set of adverbs (不再负责, 不亲自设计, 不再直接负责, 不太参与). Anything else
# between them is not a denial: 不到一周开发 (in under a week), 毫不犹豫地设计,
# 针对不足搭建, 不定期检查. 不得不 (had to) asserts.
_ZH_ACTIONS = "|".join(re.findall(r"[一-鿿]+", "|".join(ACTIONS.values())))
_ZH_DENIAL_ADVERB = r"(?:再|直接|亲自|太|常|曾|单独|独立)"
DENIAL = re.compile(
    r"\b(?:not|never|no)\b|\b\w+n['’]t\b|没有|并非|尚未|从未|未(?!来|知)"
    r"|(?<!得)不(?:曾|会|能|是|" + _ZH_DENIAL_ADVERB + r"{0,3}(?:参与|接受|录用|发表|" + _ZH_ACTIONS + r"))", re.I)
_TEAM_OWNER = re.compile(r"\b(?:my|our)\s+(?:team|teammates?|group|colleagues?)\b", re.I)
_OBJECT_END = re.compile(
    r"(?<!\s)\s+(?:and|then|while|as|in|for|with|using|on|at|during|to)\b|[,，、;；。.!?！？:：]|并|和|及|以及", re.I)
_SETTING_LEAD = re.compile(r"^(?:(?:for|in|during|at|within)\s+(?:(?:a|an|the)\s+)?|[在为于])")
LEADERSHIP = ("lead", "own", "independent")
# Credit shared through a co- word: "co-authored", "co-developed", "coauthored", 合著,
# 合写, 联合. Bench words name a method, not a co-author: co-culture, co-expression,
# co-IP, co-located; 联合国, 联合会 and 联合实验室 are bodies, 联合利华 and 联合航空
# companies, 北京联合大学 a school and 联合培养 a joint degree programme.
CO_CREDIT = re.compile(
    r"\bco-(?!(?:op|ops|cultur\w*|express\w*|occur\w*|locali[sz]\w*|locat\w*|immunoprecipitat\w*|ip|transfect\w*"
    r"|factors?|polymer\w*|crystal\w*|infect\w*|morbid\w*|evol\w*|receptors?|requisites?|ordinat\w*|operat\w*"
    r"|varian\w*|registr\w*|efficien\w*|linear\w*|enzymes?|solvents?|treat\w*|incubat\w*|inject\w*|hous\w*"
    r"|precipitat\w*|stimulat\w*|administ\w*|integrat\w*|planar|axial|valen\w*|dominan\w*|activat\w*)\b)[a-z]"
    r"|\bco(?:author|found|wr[io]t|writ)\w*|合著|合写|联合(?![国会]|利华|大学|培养|实验室|航空)", re.I)
# Shared credit said with an adverb ("wrote a report jointly") or a co- word. Only
# the claim locks read it; TEAM itself, and so claim_upgrade_detected, is unchanged.
_SHARED_CREDIT = re.compile(r"\b(?:jointly|collectively|cooperatively)\b|" + CO_CREDIT.pattern, re.I)


def _team_marked(text):
    return bool(TEAM.search(text) or _TEAM_CONTEXT.search(text) or _SHARED_CREDIT.search(text))


def _team_attributed(clause):
    # "My team built" names the team as the actor; "my" there is not the student.
    return _team_marked(clause) and not PERSONAL.search(_TEAM_OWNER.sub(" ", clause))


# "... on a team that built X": the relative clause's doer is the team, whatever
# the sentence's own subject.
_TEAM_RELATIVE = re.compile(
    r"\b(?:teams?|teammates|groups?|labmates|classmates)\s+(?:that|which|who)\s+(?:also\s+|then\s+)?$", re.I)


def _team_relative(clause, start):
    return bool(_TEAM_RELATIVE.search(clause[max(0, start - 60):start]))


_OBJECT_WINDOW = 300


def _action_objects(clause, after=0, before=None, team_relative=False):
    """(action family, object words) for each ACTIONS verb in ``clause``, EN or ZH.

    Verbs whose doer is a team relative clause count only with team_relative=True.
    """
    pairs = set()
    for name, pattern in ACTIONS.items():
        for match in re.finditer(pattern, clause, re.I):
            if (match.start() < after or (before is not None and match.start() >= before)
                    or _team_relative(clause, match.start()) != team_relative):
                continue
            # An object ends long before this; reading the clause's whole rest per verb was quadratic.
            rest = re.sub(r"^\s*(?:了|过)?", "", clause[match.end():match.end() + _OBJECT_WINDOW])
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
        team |= _action_objects(clause, team_relative=True)
    found = []
    for clause in clauses(proposed):
        denial = DENIAL.search(clause)
        pairs = _action_objects(clause, before=denial.start() if denial else None)
        if not _team_attributed(clause) and pairs & (team - affirmed):
            found.append("team_result_claimed")
        if pairs & (denied - affirmed):
            found.append("denied_action_asserted")
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


_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_WORD = re.compile(r"[A-Za-z]+")


def language(text):
    """"zh" when Chinese carries the sentence, else "en".

    A Chinese line keeps English tool and course names ("用 PyTorch 训练 CNN
    模型"); an English line may name a Chinese place once ("at 北京大学").
    """
    cjk = len(_CJK.findall(text))
    if not cjk:
        return "en"
    runs = len(_CJK_RUN.findall(text))
    leading = re.sub(r"^[^A-Za-z\u4e00-\u9fff]+", "", text)[:1]
    chinese_frame = runs >= 2 or bool(_CJK.match(leading))
    return "zh" if chinese_frame and cjk >= len(_LATIN_WORD.findall(text)) else "en"


# Who did each action. A résumé verb with no subject is the student's; a
# subject at the start of a clause ("our team", "I", "my advisor", 团队, 本人,
# 导师) holds for the rest of its sentence, and a subjectless sentence keeps the
# previous sentence's doer. The actor of every verb the rewrite keeps must not
# change: "Our team built a robot; I wrote the controller" -> "As part of a
# team, built a robot and wrote the controller" gives the team's build to the
# student.
_ABBREVIATION = r"(?<!\bdr)(?<!\bprof)(?<!\bmr)(?<!\bms)(?<!\bmrs)(?<!\bst)(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)(?<!\bno)"
_SENTENCE_BREAK = re.compile(_ABBREVIATION + r"(?<!\d)\.(?!\d)|[;!?。；！？\n]", re.I)
_CLAUSE_BREAK = re.compile(r"[,，:：]|(?<!\s)\s+(?=(?:and|but|then|that|which|who|whom|where|while|whereas)\b)|(?=并且|并|而且|而)",
                           re.I)
_CLAUSE_LEAD = re.compile(r"^(?:\s|[(（]|(?:and|but|then|that|which|who|whom|where|while|whereas)\b|并|而|且)+", re.I)
_PERSONAL_SUBJECT = re.compile(r"I\b|(?i:my\s+(?:part|role|contribution|job|task|work)s?\b|personally\b)|本人|我(?!们)")
# A subject or an agent is read only where it stands, at the start of its text.
_OTHER_SUBJECT = re.compile(
    r"\A(?:(?P<determiner>(?:my|the|a|an|our|his|her|their|two|three|four|several|\d+)\s+)?(?:(?:graduate|grad|phd|doctoral|senior"
    r"|lab|research|attending|head)\s+)?(?:advisors?|advisers?|supervisors?|mentors?|pis?|professors?|prof\b\.?"
    r"|dr\b\.?|postdocs?|tas?|nurses?|doctors?|physicians?|surgeons?|veterinarians?|therapists?|pharmacists?"
    r"|operators?|staff|clinicians?|technicians?|instructors?|teachers?|he|she|they)\b"
    r"|导师|博士生|研究生|老师|医生|护士|药师|技术员|他们|他|她|对方|合作者|师兄|师姐|主治医生)", re.I)
_TEAM_SUBJECT = re.compile(
    r"(?:we|our|us|together\s+with|my\s+(?:team|group|lab|club|teammates?|classmates?|lab\s*mates?))\b"
    r"|the\s+(?:team|group|club)\b|团队|小组|我们|组员|课题组|项目组|研究组|大家", re.I)
_ZH_VERBS = re.compile(
    "采集|检测|监测|负责|整理|设计|安装|担任|协助|参与|开发|搭建|分析|完成|实现|编写|撰写|测定|测量|培养|维护|运行"
    "|组织|主持|带领|主导|制作|处理|研究|学习|检查|审阅|评分|安排|记录|采购|构建|建立|绘制|测试|调试|训练|清洗|收集"
    "|录入|发表|投稿|讲解|辅导|观察|观摩|调配|实施|操作|部署|优化|复现|爬取|统计|标注|访谈|招募|筛选|提取|纯化|合成"
    "|焊接|组装|编辑|翻译|汇报|展示|领导|牵头|评估|验证|规划|做")
_BASE_VERB_CUE = frozenset({"to", "help", "helped", "helping", "helps", "not", "never", "will", "did", "didn't"})


def _pieces(text, pattern):
    """Spans of ``text`` between matches of ``pattern``, never splitting inside brackets."""
    depth, spans, start = 0, [], 0
    breaks = {match.start(): match.end() for match in pattern.finditer(text)}
    i = 0
    while i < len(text):
        character = text[i]
        if character in "(（[":
            depth += 1
        elif character in ")）]":
            depth = max(0, depth - 1)
        if depth == 0 and i in breaks:
            spans.append((start, i))
            start = max(breaks[i], i + 1) if breaks[i] > i else i
            if breaks[i] > i:
                i = breaks[i]
                continue
        i += 1
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _verbs(clause):
    """(position, lemma) of each action verb in a clause, English and Chinese."""
    found = [(match.start(), match.group(0)) for match in _ZH_VERBS.finditer(clause)]
    words = list(_WORD.finditer(clause))
    for index, match in enumerate(words):
        use = verb_use(match.group(0))
        if not use:
            continue
        previous = words[index - 1].group(0).casefold() if index else ""
        # "helped a nurse record": help's object stands between it and the verb.
        helped = any(HELP.fullmatch(word.group(0)) for word in words[max(0, index - 4):index])
        if use[1] != "base" or index == 0 or previous in _BASE_VERB_CUE or helped:
            found.append((match.start(), use[0]))
    return sorted(found)


# "supervised by a postdoc", "trained by graduate students": the agent did it.
_STUDENT_AGENT = re.compile(
    r"\A(?:(?:a|an|the|my|our|two|three|several|\d+)\s+)?(?:graduate|grad|phd|doctoral|senior|older)\s+students?\b", re.I)
_BY = re.compile(r"(?<!\s)\s+by\s+", re.I)


def _passive_agent(clause, position):
    """The doer of a past participle followed by "by <someone>", else None."""
    word = _WORD.match(clause, position)
    if not word or (verb_use(word.group(0)) or ("", ""))[1] != "past":
        return None
    by = _BY.match(clause, word.end())
    if not by:
        return None
    agent = clause[by.end():]
    if _OTHER_SUBJECT.match(agent) or _STUDENT_AGENT.match(agent):
        return "O"
    return "T" if _TEAM_SUBJECT.match(agent) else None


def _names_another_doer(lead, other):
    """Whether an _OTHER_SUBJECT match that opens ``lead`` is someone else doing the clause's work.

    A bare role noun opening a résumé line is the student's own title: "TA for CS 124,
    holding office hours", "Research technician in the Smith Lab", 研究生期间负责. It is
    another person with a determiner ("The nurse, with my help, recorded"), as an
    abbreviated title ("Dr. Lee"), or when its own verb follows it directly, past a name
    or an adverb ("Lab technician ran the assays", "Professor Lee designed", 导师负责).
    """
    rest = lead[other.end():]
    if other["determiner"] or rest.startswith("."):
        return True
    if _CJK.match(other.group(0)):
        return bool(_ZH_VERBS.match(rest.lstrip()))
    words = _WORD.findall(rest)
    while words and words[0][0].isupper():
        words.pop(0)
    return (verb_use(_lead_word(" ".join(words))) or ("", ""))[1] in ("past", "s")


def _subject(clause):
    lead = _CLAUSE_LEAD.sub("", clause)
    if _PERSONAL_SUBJECT.match(lead):
        return "P"
    other = _OTHER_SUBJECT.match(lead)
    if other and _names_another_doer(lead, other):
        return "O"
    if _TEAM_SUBJECT.match(lead):
        return "T"
    return None


def action_actors(text):
    """{verb: [actor, ...]} with actor P (the student), T (the team) or O (another person)."""
    actors: dict[str, list[str]] = {}
    running = "P"
    for sentence_start, sentence_end in _pieces(text, _SENTENCE_BREAK):
        sentence = text[sentence_start:sentence_end]
        for clause_start, clause_end in _pieces(sentence, _CLAUSE_BREAK):
            clause = sentence[clause_start:clause_end]
            running = _subject(clause) or running
            for position, verb in _verbs(clause):
                actors.setdefault(verb, []).append(_passive_agent(clause, position) or running)
    return actors


def actor_changed(proposed, original):
    before, after = action_actors(original), action_actors(proposed)
    for verb in before.keys() & after.keys():
        if len(before[verb]) == len(after[verb]):
            if sorted(before[verb]) != sorted(after[verb]):
                return True
        elif not set(after[verb]) <= set(before[verb]):
            return True
    return False


# Each qualifier stays on its action: "I helped design X and cleaned Y" ->
# "Designed X and helped clean Y" moves the help. A qualifier binds to the next
# verb in its clause (a span word to the next word or number); "alone" binds to
# the verb before it. Shared credit ("with two teammates", "jointly", 与组员一起)
# binds to its action, and a publication status to the work it describes.
_TEAM_WITH = re.compile(
    r"\b(?:together\s+)?(?:with|alongside)\s+(?:(?:my|our|the|other|a|an|another|fellow|several|one|two|three|four"
    r"|five|six|\d+)\s+)?(?:(?:research|lab|project|fellow|other)\s+)?(?:team(?:mates?)?|colleagues?|classmates?"
    r"|lab\s*mates?|lab\s+partners?|partners?|peers?|group\s*mates?|friends?|roommates?)\b"
    r"|\b(?:jointly|collectively|cooperatively|collaboratively)\b"
    r"|(?:与|和|同|跟)[^，,。；;、]{1,12}?(?:一起|共同|合作)", re.I)
# Each publication status is its own family, so a swap between two works shows.
# Pre-verbal ones ("currently", 正在, 计划) are status_upgraded's and intent's.
_STATUS_CLASSES = {
    "submitted": r"\b(?:submitted|submission)\b|投稿|提交|在投",
    "under_review": r"\bunder\s+review\b|审稿|评审",
    "accepted": r"\b(?:accepted|acceptance)\b|录用",
    "published": r"\b(?:published|publication)\b|发表|出版",
    "preprint": r"\bpreprints?\b|预印本",
    "rejected": r"\brejected\b|拒稿",
    "withdrawn": r"\bwithdrawn\b|撤稿",
    "unfinished": r"\b(?:in\s+preparation|in\s+progress|ongoing|on-going|not\s+yet|pending|forthcoming|upcoming"
                  r"|under\s+(?:revision|development))\b|撰写中|准备中|进行中|筹备中|待发表|未完成",
}
_QUALIFIERS = {
    "help": (HELP, "verb"),
    "negation": (re.compile(r"\b(?:not|never|didn['’]t|no\s+longer)\b|没有|并非|尚未|从未|未(?!来|知)"
                            r"|(?<!得)不(?=(?:再|直接|亲自|太|常|曾|单独|独立){0,3}(?:参与|负责|主导|带领|设计|开发|完成))", re.I), "verb"),
    "limit": (re.compile(r"\b(?:only|just|solely)\b|只|仅", re.I), "verb"),
    "solo": (re.compile(r"\b(?:alone|independently|single-handedly|by\s+myself|on\s+my\s+own)\b", re.I), "previous"),
    "solo_zh": (re.compile(r"独立|独自|单独"), "verb"),
    "span": (re.compile(r"\b(?:about|approximately|approx\.?|roughly|nearly|almost|around|over|more\s+than|less\s+than"
                        r"|at\s+least|at\s+most|up\s+to|since|until|per)\b|约|大约|将近|超过|至少", re.I), "next"),
    "intent": (INTENT, "verb"),
    "team": (_TEAM_WITH, "action"),
    **{f"status_{name}": (re.compile(pattern, re.I), "object") for name, pattern in _STATUS_CLASSES.items()},
}
_NEXT_TOKEN = re.compile(r"\d+(?:[.,]\d+)*%?|[A-Za-z]+(?:-[A-Za-z]+)*|[\u4e00-\u9fff]")
# "Collaborated with two teammates to build X": the team is on the build.
_CO_ACTIONS = frozenset({"collaborate", "work"})
_NOUN_END = re.compile(_OBJECT_END.pattern + r"|[(（]", re.I)
_NOT_HEAD = frozenset({"a", "an", "the", "its", "their", "his", "her", "my", "our", "this", "that", "these", "those",
                       "another", "one", "two", "three", "not", "yet", "also"})
_ZH_LEAD = re.compile(r"^(?:了|过|的|还有|有|另|已经|已|一(?:篇|个|份|项|部|本)|[篇个份项部本])+")
_ZH_TAIL = re.compile(r"(?:了|过|的|已经|已|正在|在|中)+$")
# Any status word of _STATUS_CLASSES, matched whole.
_STATUS_WORDS = re.compile("|".join(f"(?:{pattern})" for pattern in _STATUS_CLASSES.values()), re.I)
_CJK_RUN_AT = re.compile(r"[\u4e00-\u9fff]*")
_CJK_RUN_END = re.compile(r"(?<![\u4e00-\u9fff])[\u4e00-\u9fff]*$")
# The Chinese run a status reads is bounded, so a long run costs the same as a short one.
_ZH_WINDOW = 24


class _Verbs:
    """(position, verb) pairs in order, searchable by position.

    A qualifier reads the verb before or after it; with a few hundred
    qualifiers in a 6,000-character source, a scan per qualifier was
    quadratic.
    """

    def __init__(self, pairs):
        self.pairs = pairs
        self.positions = [position for position, _ in pairs]

    def before(self, position):
        """The last verb that starts before ``position``, or None."""
        index = bisect.bisect_left(self.positions, position)
        return self.pairs[index - 1][1] if index else None

    def at_or_after(self, position):
        """The first verb that starts at or after ``position``, or None."""
        index = bisect.bisect_left(self.positions, position)
        return self.pairs[index][1] if index < len(self.pairs) else None


def _action_target(verbs, match, sentence_verbs, offset, *, co_action=False):
    """The action a qualifier belongs to: the verb before it in its clause, else the next one in its sentence.

    With ``co_action``, "collaborated with" or "worked with" hands shared credit
    on to the verb that follows. ``verbs`` and ``sentence_verbs`` are _Verbs.
    """
    before = verbs.before(match.start())
    if before is not None and not (co_action and before in _CO_ACTIONS):
        return before
    after = sentence_verbs.at_or_after(offset + match.end())
    return after if after is not None else sentence_verbs.before(offset + match.start())


def _noun_head(text):
    words = [word.casefold() for word in _WORD.findall(_NOUN_END.split(text, maxsplit=1)[0])]
    words = [word for word in words if word not in _NOT_HEAD and not _STATUS_WORDS.fullmatch(word)]
    if not words:
        return None
    head = words[-1]
    return head[:-1] if len(head) > 3 and head.endswith("s") else head


def _status_target(clause, match, verbs, heads):
    """The work a publication status describes: the object of its clause's first verb, else its first noun.

    An English status reads one of two noun heads per clause, kept in ``heads``.
    """
    if _CJK.search(match.group(0)):
        after = _ZH_LEAD.sub("", _CJK_RUN_AT.match(clause, match.end(), match.end() + _ZH_WINDOW).group(0))
        if after:
            return after[:4]
        before = _CJK_RUN_END.search(clause[max(0, match.start() - _ZH_WINDOW):match.start()]).group(0)
        return _ZH_LEAD.sub("", _ZH_TAIL.sub("", before))[-4:] or None
    first = verbs.positions[0] if verbs.positions and verbs.positions[0] <= match.start() else None
    if first not in heads:
        if first is None:
            heads[first] = _noun_head(_CLAUSE_LEAD.sub("", clause))
        else:
            verb = _WORD.match(clause, first)
            # "Paper submitted to CHI 2026": nothing after the verb names the work.
            heads[first] = _noun_head(clause[verb.end() if verb else first:]) or _noun_head(clause[:first])
    return heads[first]


def _sentence_verbs(sentence, pieces):
    return _Verbs([(clause_start + position, verb) for clause_start, clause_end in pieces
                   for position, verb in _verbs(sentence[clause_start:clause_end])])


def _qualifier_bindings(text):
    found = []
    for sentence_start, sentence_end in _pieces(text, _SENTENCE_BREAK):
        sentence = text[sentence_start:sentence_end]
        pieces = _pieces(sentence, _CLAUSE_BREAK)
        sentence_verbs = _sentence_verbs(sentence, pieces)
        for clause_start, clause_end in pieces:
            clause = sentence[clause_start:clause_end]
            verbs, heads = _Verbs(_verbs(clause)), {}
            for family, (pattern, binds) in _QUALIFIERS.items():
                for match in pattern.finditer(clause):
                    if binds == "previous":
                        target = verbs.before(match.start())
                    elif binds == "next":
                        token = _NEXT_TOKEN.search(clause, match.end())
                        target = token.group(0).casefold() if token else None
                    elif binds == "action":
                        target = _action_target(verbs, match, sentence_verbs, clause_start, co_action=True)
                    elif binds == "object":
                        target = _status_target(clause, match, verbs, heads)
                    else:
                        target = verbs.at_or_after(match.end())
                    found.append((family, target))
    return sorted(found, key=str)


_DURATION = re.compile(r"\b(?:since|until|till)\b", re.I)


def _duration_bindings(text):
    """((word, time), verb) for each since/until: the verb before it in its clause, else the next one."""
    found = []
    for sentence_start, sentence_end in _pieces(text, _SENTENCE_BREAK):
        sentence = text[sentence_start:sentence_end]
        pieces = _pieces(sentence, _CLAUSE_BREAK)
        sentence_verbs = _sentence_verbs(sentence, pieces)
        for clause_start, clause_end in pieces:
            clause = sentence[clause_start:clause_end]
            verbs = None
            for match in _DURATION.finditer(clause):
                verbs = verbs or _Verbs(_verbs(clause))
                token = _NEXT_TOKEN.search(clause, match.end())
                key = (match.group(0).casefold(), token.group(0).casefold() if token else None)
                found.append((key, _action_target(verbs, match, sentence_verbs, clause_start)))
    return found


def _duration_moved(proposed, original):
    """"Tutored 30 students since 2024; graded exams in 2023" -> "Graded exams since 2024; ...".

    Only verbs both texts keep are compared: a verb-first rewrite that drops
    "Worked" may carry "since January 2026" to the line's end.
    """
    before, after = _duration_bindings(original), _duration_bindings(proposed)
    kept = set(action_actors(original)) & set(action_actors(proposed))
    for key in {key for key, _ in before} & {key for key, _ in after}:
        old = sorted(verb for item, verb in before if item == key and verb in kept)
        new = sorted(verb for item, verb in after if item == key and verb in kept)
        if old and new and old != new:
            return True
    return False


def qualifier_moved(proposed, original):
    before, after = _qualifier_bindings(original), _qualifier_bindings(proposed)
    families = {family for family, _ in before} & {family for family, _ in after}
    return ([pair for pair in before if pair[0] in families] != [pair for pair in after if pair[0] in families]
            or _duration_moved(proposed, original))


def _leadership(text, name):
    return bool(re.search(ACTIONS[name], text, re.I)) or any(name in _guarded_gerunds(clause) for clause in clauses(text))


# A count word is not a limit: "12 只小鼠" is twelve mice. NEGATION reads 只 as
# "only", so "Dissected 12 mice" would drop a negation and the clause's own
# actions would count as denied. NEGATION is also the selection plan's, so the
# claim locks below read both texts with the count word written as 个.
_COUNT_ZHI = re.compile(r"(?<=[\d一二三四五六七八九十两几数多每])(\s?)只")
_UNDERWAY_ACTION = re.compile(_ZH_PROGRESSIVE)
# "to appear" and "in press" say the work is being published, as 即将发表 does.
_IN_PRESS = re.compile(r"\b(?:to\s+appear|in\s+press)\b", re.I)


def claim_text(text):
    return _COUNT_ZHI.sub(r"\1个", text)


def _claimed_actions(text):
    """A rewrite's actions, with a Chinese verb + 中 read as work under way.

    "气象站搭建中" (a weather station under construction) and "开发中的仪表板" (an
    in-progress dashboard) say the student built nothing new. The original keeps
    its own actions.
    """
    return personal_actions(_UNDERWAY_ACTION.sub("进行中", text), gerunds=True)


def _stages(text):
    return publication_stages(text) | ({"published"} if _IN_PRESS.search(text) else set())


def claim_upgrade_findings(proposed, original):
    """Split the single-bullet claim locks into (hard, soft) findings.

    Hard findings change who did what, add an action, status, leadership,
    setting, quality or relevance clause, or drop a team/help/negation/
    publication qualifier entirely; no reviewer may overrule them, so each
    must stay silent on faithful rewrites. Soft findings go to a faithfulness
    review, which may accept them.
    Every changed rewrite gets at least one finding: when no rule names a
    problem, ``wording_changed`` still sends it to the review, because a regex
    that sees nothing (Chinese syntax, an unknown verb) proves nothing. Only
    text identical after whitespace/case normalization has none.
    ``claim_upgrade_detected`` is unchanged.
    """
    if normalized(proposed) == normalized(original):
        return [], []
    proposed, original = claim_text(proposed), claim_text(original)
    hard = []
    if _team_marked(original) and not _team_marked(proposed):
        hard.append("team_qualifier_dropped")
    # "As part of a team" may stand in for "helped" only when the original
    # already said the work was shared.
    if HELP.search(original) and not HELP.search(proposed) and not (
            _team_marked(original) and _team_marked(proposed)):
        hard.append("help_qualifier_dropped")
    # DENIAL also sees 不 + a closed adverb before its verb (不太参与, 不再负责); an open
    # gap would let 不到一周参与 stand in for a dropped 未参与.
    if (NEGATION.search(original) or DENIAL.search(original)) and not (
            NEGATION.search(proposed) or DENIAL.search(proposed)):
        hard.append("negation_dropped")
    if PUBLICATION.search(original) and not PUBLICATION.search(proposed):
        hard.append("publication_qualifier_dropped")
    if _claimed_actions(proposed) - personal_actions(original, gerunds=True):
        hard.append("personal_action_added")
    if _stages(proposed) - _stages(original):
        hard.append("publication_stage_added")
    if (INTENT.search(original) or PLANNED.search(original)) and not (
            INTENT.search(proposed) or PLANNED.search(proposed)):
        hard.append("intent_dropped")
    if status_upgraded(proposed, original):
        hard.append("status_upgraded")
    original_normal = normalized(original)
    if (any(normalized(match.group(0)).strip(",，;； ") not in original_normal
            for match in RELEVANCE_PADDING.finditer(proposed))
            or _appended_relevance(proposed, original)):
        hard.append("relevance_clause_added")
    # Inside a team clause too: personal_actions skips those, and "helped design"
    # as part of a team must not become "led the design".
    if any(_leadership(proposed, name) and not _leadership(original, name) for name in LEADERSHIP):
        hard.append("leadership_claim_added")
    # An English line may name a Chinese place ("at 北京大学"): a Chinese word
    # counts only against an original that has Chinese.
    comparable = [match for pattern in (SETTING, QUALITY) for match in pattern.finditer(proposed)
                  if not _CJK.search(match.group(0)) or _CJK.search(original)]
    if any(match.re is SETTING and not _setting_in(normalized(match.group(0)), original_normal)
           for match in comparable):
        hard.append("setting_added")
    if any(match.re is QUALITY and normalized(match.group(0)) not in original_normal for match in comparable):
        hard.append("quality_claim_added")
    if actor_changed(proposed, original):
        hard.append("actor_changed")
    if qualifier_moved(proposed, original):
        hard.append("qualifier_moved")
    hard.extend(dict.fromkeys(_moved_claims(proposed, original)))
    proposed_normal = normalized(proposed)
    reworded = any((NEGATION.search(clause) or TEAM.search(clause) or PUBLICATION.search(clause))
                   and normalized(clause) not in proposed_normal for clause in clauses(original))
    return hard, ["locked_clause_reworded" if reworded else "wording_changed"]


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
    if _stated_personal_actions(proposed) - set().union(*(_stated_personal_actions(original) for original in originals)):
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
            # A run of spaces starts one split, not one per space.
            for part in re.split(r'(?<!\s)\s+(?:and|then)\s+(?=(?:' + _SURFACE_ACTOR + r'\s+)?(?:' + _SURFACE_ACTION + r')\b)',
                                 sentence, flags=re.I):
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
