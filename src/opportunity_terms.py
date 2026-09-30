"""Conservative lexical opportunity labels, never source-verification evidence.

The diagnostic mention API finds technical terms. The classifier additionally
requires local qualification wording for required/preferred; negative or
conflicting occurrences are excluded from all positive arrays. Original source
text must be retained by callers. These finite English rules are not semantic
qualification extraction and must be stamped as inferred by producers.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from html import unescape

# Union of the existing normalizer/enricher vocabulary, with bounded aliases.
_PATTERNS = {
    'Python': r'python', 'Java': r'java(?!script)', 'C++': r'c\+\+',
    'C#': r'c\#', 'C': r'c(?![+#])', 'JavaScript': r'javascript',
    'TypeScript': r'typescript', 'R': r'r', 'MATLAB': r'matlab', 'SQL': r'sql',
    'Rust': r'rust', 'Go': r'go|golang', 'PyTorch': r'pytorch',
    'TensorFlow': r'tensor\s*flow', 'scikit-learn': r'scikit[- ]learn|sklearn',
    'pandas': r'pandas', 'NumPy': r'numpy', 'OpenCV': r'opencv',
    'HuggingFace': r'hugging\s*face', 'transformers': r'transformers',
    'machine learning': r'machine\s+learning',
    'deep learning': r'deep\s+learning|neural\s+networks?', 'NLP': r'nlp',
    'data analysis': r'data\s+analysis|data\s+analytics',
    'data visualization': r'data\s+visualization',
    'statistical analysis': r'statistical\s+analysis|regression\s+analysis',
    'Linux': r'linux|unix|bash\s+scripting', 'Git': r'git|github|gitlab',
    'Docker': r'docker', 'React': r'react(?:\.js|js)?', 'Flask': r'flask',
    'FastAPI': r'fastapi', 'Django': r'django',
    'AWS': r'aws|amazon\s+web\s+services', 'GCP': r'gcp|google\s+cloud',
    'Azure': r'(?:microsoft\s+)?azure', 'SAS': r'sas', 'Stata': r'stata',
    'SPSS': r'spss', 'HTML/CSS': r'html(?:\s*/\s*css)?|css', 'LaTeX': r'latex',
    'LabVIEW': r'labview', 'Verilog': r'(?:system)?verilog', 'VHDL': r'vhdl',
    'FPGA': r'fpga', 'PCB design': r'pcb\s+design',
    'CAD': r'cad|autocad|solidworks|fusion\s*360',
    'FEA': r'fea|finite\s+element(?:\s+analysis)?|ansys|abaqus',
    '3D printing': r'3d\s+printing|additive\s+manufacturing', 'PCR': r'q?pcr',
    'microscopy': r'(?:(?:confocal|fluorescence|electron)\s+)?microscopy',
    'HPLC': r'hplc|lc[- ]ms|gc[- ]ms', 'cell culture': r'(?:cell|tissue)\s+culture',
    'spectroscopy': r'(?:(?:nmr|ir|uv[- ]vis|raman)\s+)?spectroscopy|mass\s+spectrometry',
}
_REGEXES = [(label, re.compile(r'(?<![\w+#])(?:' + pattern + r')(?![\w+#])', re.I))
            for label, pattern in _PATTERNS.items()]
_AMBIGUOUS = {'R', 'C', 'Go', 'React', 'SAS', 'Rust'}
_TECH_AFTER = re.compile(
    r'^\s*(?:[-/]\s*)?(?:programming|language|scripts?|packages?|librar(?:y|ies)|'
    r'code|coding|software|framework|development|developer|analytics|statistical)\b', re.I)
_TECH_BEFORE = re.compile(
    r'\b(?:programming|coding|programmed|written|implemented|developed|'
    r'proficien(?:cy|t)|experience|knowledge|familiarity|skills?|expertise|'
    r'fluency|fluent|use|uses|using|utilize|utilizes)\s+'
    r'(?:(?:in|with|of)\s+)?$', re.I)
_TECH_HEADING = re.compile(r'\b(?:programming languages?|technical skills?|technologies|tech stack)\s*:', re.I)
_REQUIRED = re.compile(
    r'\b(?:required|mandatory|essential|prerequisites?|require[sd]?|'
    r'must\s+(?:know|have|be|use|possess|demonstrate)|need\s+to\s+(?:know|have|use))\b', re.I)
_PREFERRED = re.compile(r'\b(?:preferred|desir(?:ed|able)|recommended|helpful|beneficial|a\s+plus|an?\s+advantage)\b', re.I)
_NEGATIVE = re.compile(
    r'\b(?:no|never|neither|nor|without|unnecessary|optional|'
    r'not(?!\s+only\b)|(?:is|are|was|were|do|does|did|can|will)n[’\']t)\b', re.I)
_HEADING = re.compile(
    r'^\s*(?:[-*#•]\s*)?(?:(required|mandatory|essential|preferred|desired|desirable)'
    r'(?:\s+(?:skills?|qualifications?|experience|knowledge))?|'
    r'(skills?|qualifications?|experience|knowledge)\s+(required|preferred|desired))\s*:\s*', re.I)


@dataclass(frozen=True)
class _Mention:
    label: str
    start: int
    end: int


def _source_text(text: str) -> str:
    if not isinstance(text, str):
        return ''
    text = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', ' ', text, flags=re.I | re.S)
    text = re.sub(r'<li\b[^>]*>', '\n- ', text, flags=re.I)
    text = re.sub(r'</li\s*>', '', text, flags=re.I)
    text = re.sub(r'<(?:br\s*/?|/?(?:p|div|h[1-6]))\b[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]*>', ' ', text)
    text = unescape(text)
    text = re.sub(r'(?:https?://|www\.)[^\s<>]+|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b', ' ', text, flags=re.I)
    return re.sub(r'\n[ \t]*\n', '\n', text)


def _technical_context(text: str, mention: _Mention, unambiguous: list[_Mention]) -> bool:
    before, after = text[max(0, mention.start - 100):mention.start], text[mention.end:mention.end + 80]
    token = text[mention.start:mention.end]
    # Initials/grades and ordinary verbs are not technologies, even in a
    # sentence which happens to mention programming elsewhere.
    if mention.label in {'R', 'C'} and (
        re.search(r'\b(?:Dr|Prof|Professor|Mr|Ms)\.?\s*$', before, re.I)
        or re.match(r'\.\s*[A-Z][a-z]', after)
        or re.search(r'\b(?:grade|vitamin|section|appendix|panel|figure)\s*$', before, re.I)
        or re.match(r'\s*&\s*D\b', after, re.I)
    ):
        return False
    if mention.label == 'Go' and re.match(r'\s+(?:to|through|ahead|home|abroad|beyond|back)\b', after, re.I):
        return False
    if mention.label == 'React' and re.match(r'\s+(?:to(?!\s+(?:build|develop|create|implement)\b)|with|against)\b', after, re.I):
        return False
    if mention.label == 'Rust' and token.islower() and not _TECH_AFTER.search(after):
        return False
    if mention.label == 'Go' and token.lower() == 'golang':
        return True
    if mention.label == 'React' and token.lower() in {'react.js', 'reactjs'}:
        return True
    if mention.label in {'Go', 'React', 'Rust'} and token[0].isupper() and re.match(r'\s+(?:(?:is|experience\s+is)\s+)?(?:required|preferred)\b', after, re.I):
        return True
    if _TECH_AFTER.search(after) or _TECH_BEFORE.search(before):
        return True
    line_prefix = before.rsplit('\n', 1)[-1]
    if _TECH_HEADING.search(line_prefix):
        return True
    # A genuinely technical list supports short names; arbitrary nearby
    # skills in the same paragraph do not (e.g. "Python users must go home").
    for other in unambiguous:
        gap = (text[other.end:mention.start] if other.end <= mention.start
               else text[mention.end:other.start] if mention.end <= other.start else None)
        if gap is not None and re.fullmatch(r'[\s,/&]*(?:(?:and|or)[\s,/&]*)?', gap, re.I):
            return True
    return False


def _mentions(text: str) -> list[_Mention]:
    candidates = [_Mention(label, match.start(), match.end())
                  for label, regex in _REGEXES for match in regex.finditer(text)]
    found = []
    for mention in candidates:
        before, after = text[max(0, mention.start - 50):mention.start], text[mention.end:mention.end + 40]
        # Honor a local proper-name/physical-object reading. No paragraph-wide
        # blocklist: "Research using R programming" remains a positive.
        if re.search(r'\b(?:Dr|Prof|Professor|Mr|Ms)\.?\s*(?:[A-Z][a-z]+\s+)?$', before):
            continue
        if mention.label == 'Java' and (re.search(r'\b(?:island|province)\s+(?:of\s+)?$', before, re.I)
                                        or re.match(r'\s+(?:island|coffee)\b', after, re.I)):
            continue
        if mention.label == 'Rust' and re.match(r'\s+(?:corrosion|formation|removal)\b', after, re.I):
            continue
        if mention.label == 'transformers' and re.search(r'\b(?:power|electrical|voltage)\s*$', before, re.I):
            continue
        if mention.label == 'Flask' and re.search(r'\b(?:glass|conical|volumetric)\s*$', before, re.I):
            continue
        found.append(mention)
    accepted = [m for m in found if m.label not in _AMBIGUOUS]
    pending = [m for m in found if m.label in _AMBIGUOUS]
    while pending:
        newly_valid = [m for m in pending if _technical_context(text, m, accepted)]
        if not newly_valid:
            break
        accepted.extend(newly_valid)
        pending = [m for m in pending if m not in newly_valid]
    return sorted(accepted, key=lambda m: (m.start, m.end, m.label))


def extract_skill_mentions(text: str) -> list[str]:
    """Technical lexical mentions, including negated ones; diagnostic only."""
    return list(dict.fromkeys(m.label for m in _mentions(_source_text(text))))


def _category(piece: str) -> str | None:
    negative = _NEGATIVE.search(piece)
    required, preferred = bool(_REQUIRED.search(piece)), bool(_PREFERRED.search(piece))
    if negative:
        # "not required" is compatible with an explicit preference, but is
        # not itself a positive signal. Other negatives remain excluded.
        not_required = bool(re.search(
            r"\b(?:not|isn['’]t|aren['’]t)\s+(?:strictly\s+)?required\b|"
            r"\bno\b[^.;]*\brequired\b|\b(?:do|does)\s+not\s+require\b", piece, re.I))
        if not_required and len(_NEGATIVE.findall(piece)) == 1:
            return 'preferred' if preferred else 'not_required'
        return 'excluded'
    if required and preferred:
        return 'excluded'
    return 'required' if required else 'preferred' if preferred else None


def _qualification_applies(piece: str, mention: _Mention, mentions: list[_Mention], category: str) -> bool:
    """A nearby cue must modify the skill phrase, not an unrelated CV/course.

    Permit a small grammar of skill lists and proficiency modifiers. Unknown
    intervening prose remains a mention rather than inheriting a requirement.
    """
    pattern = _REQUIRED if category == 'required' else _PREFERRED
    for cue in pattern.finditer(piece):
        if cue.end() <= mention.start:
            start, end = cue.end(), mention.start
        elif mention.end <= cue.start():
            if category == 'required' and re.fullmatch(r'requires?', cue.group(), re.I):
                continue  # active require(s) takes an object after it
            start, end = mention.end, cue.start()
        else:
            continue
        gap = piece[start:end]
        for other in reversed(mentions):
            if start <= other.start < other.end <= end:
                a, b = other.start - start, other.end - start
                gap = gap[:a] + ' ' * (b - a) + gap[b:]
        if category == 'preferred':
            gap = re.sub(r"\b(?:not|isn['’]t|aren['’]t)\s+required\s+but\b", ' ', gap, flags=re.I)
        gap = re.sub(r"\b(?:and|or|either|in|of|with|is|are|be|a|an|the|"
                     r"experience|knowledge|expertise|proficiency|proficient|familiarity|familiar|"
                     r"skills?|programming|languages?|fluency|fluent|ability|"
                     r"basic|strong|prior|advanced|demonstrated|working|some)\b", ' ', gap, flags=re.I)
        if not re.sub(r'[\s:/*&()\-•]', '', gap):
            return True
    return False


def _list_fragment(piece: str, mentions: list[_Mention]) -> bool:
    remaining = piece
    for mention in reversed(mentions):
        remaining = remaining[:mention.start] + ' ' + remaining[mention.end:]
    remaining = re.sub(r'\b(?:and|or|with|in|of|experience|knowledge|proficiency|familiarity|'
                       r'programming|language|languages|skills|skill|basic|strong|prior|advanced|either|also)\b', ' ', remaining, flags=re.I)
    return not re.sub(r'[\s:/*&()\-•]', '', remaining)


def _pieces(sentence: str) -> list[tuple[str, int, int]]:
    # Keep offsets into source text so a short technical name in a comma list
    # retains its validated context when clauses are classified independently.
    cuts = [(m.start(), m.end()) for m in re.finditer(r",|\b(?:but|whereas|however|while)\b", sentence, re.I)
            if not (m.group().lower() == 'but' and re.search(r'\b(?:not|isn[’\']t|aren[’\']t)\s+required\s*$', sentence[:m.start()], re.I)
                    and _PREFERRED.match(sentence[m.end():].lstrip()))]
    bounds = [(0, 0), *cuts, (len(sentence), len(sentence))]
    result = []
    for left, right in zip(bounds, bounds[1:], strict=False):
        start, end = left[1], right[0]
        part = sentence[start:end]
        joins = list(re.finditer(r"\b(?:and|or)\b", part, re.I))
        chunks = re.split(r"\b(?:and|or)\b", part, flags=re.I)
        separate_claim = any(re.match(r'\s*(?:(?:we|they|applicants?)\s+)?(?:do\s+not|does\s+not|don[’\']t|use|uses)\b', chunk, re.I) for chunk in chunks[1:])
        if joins and (sum(_category(chunk) is not None for chunk in chunks) > 1 or separate_claim):
            subbounds = [(0, 0), *((m.start(), m.end()) for m in joins), (len(part), len(part))]
            result.extend((part[a[1]:b[0]], start + a[1], start + b[0]) for a, b in zip(subbounds, subbounds[1:], strict=False))
        else:
            result.append((part, start, end))
    return result


def extract_skill_requirements(text: str) -> dict[str, list[str]]:
    """Separate local requirements, preferences and affirmative bare mentions.

    Negative/contradictory evidence is omitted from every positive list. A bare
    domain, title or technology cannot become an applicant requirement merely
    because another sentence requires a CV. Returned labels are rule inferences.
    """
    source = _source_text(text)
    all_mentions = _mentions(source)
    mention_starts = [m.start for m in all_mentions]
    ordered = list(dict.fromkeys(m.label for m in all_mentions))
    events: dict[str, set[str]] = {label: set() for label in ordered}
    heading_category = None
    # Delimiters retain offsets (rather than re-extracting from isolated pieces).
    for line_match in re.finditer(r"[^\n]*\n|[^\n]+$", source):
        line, line_start = line_match.group().rstrip("\n"), line_match.start()
        if not line.strip():
            heading_category = None
            continue
        heading = _HEADING.match(line)
        if heading:
            heading_category = _category(heading.group())
            line_start += heading.end()
            line = line[heading.end():]
        elif re.match(r"^\s*[A-Za-z][A-Za-z ]{2,45}:\s*$", line):
            heading_category = None
        elif not re.match(r"^\s*[-*•]", line):
            heading_category = None
        for sentence_match in re.finditer(r"[^;!?\n]+", line):
            # A full stop followed by whitespace ends a sentence. Decimal
            # values and React.js remain intact; lexical initials were already
            # excluded against the complete source before this split.
            chunk = sentence_match.group()
            sentence_bounds = [(0, 0), *((m.start(), m.end()) for m in re.finditer(r"\.(?=\s|$)", chunk)), (len(chunk), len(chunk))]
            for left, right in zip(sentence_bounds, sentence_bounds[1:], strict=False):
                sentence = chunk[left[1]:right[0]]
                offset = line_start + sentence_match.start() + left[1]
                pieces = _pieces(sentence)
                parts = [part for part, _, _ in pieces]
                part_mentions = [
                    [_Mention(m.label, m.start - offset - start, m.end - offset - start)
                     for m in all_mentions[bisect_left(mention_starts, offset + start):bisect_left(mention_starts, offset + end)]
                     if m.end <= offset + end]
                    for _, start, end in pieces
                ]
                categories = [_category(part) for part in parts]
                for i, category in enumerate(categories):
                    if category in {'required', 'preferred'} and not any(
                        _qualification_applies(parts[i], mention, part_mentions[i], category)
                        for mention in part_mentions[i]
                    ):
                        categories[i] = None
                is_list = [_list_fragment(part, mentions) and bool(mentions)
                           for part, mentions in zip(parts, part_mentions, strict=True)]
                for i, (part, mentions) in enumerate(zip(parts, part_mentions, strict=True)):
                    category = categories[i]
                    if category is None and is_list[i]:
                        for j in range(i + 1, len(parts)):
                            if categories[j] is not None and part_mentions[j]:
                                category = categories[j]
                                break
                            if not is_list[j]:
                                break
                        if category is None:
                            for j in range(i - 1, -1, -1):
                                if categories[j] is not None and part_mentions[j]:
                                    category = categories[j]
                                    break
                                if not is_list[j]:
                                    break
                        category = category or heading_category
                    for mention in mentions:
                        value = category or 'mentioned'
                        if value in {'required', 'preferred'} and categories[i] is not None and not _qualification_applies(part, mention, mentions, value):
                            value = 'mentioned'
                        if value == 'required' and re.search(r'\b(?:or|unless|if|when)\b', part, re.I):
                            value = 'mentioned'  # conditional/alternative, not individually unconditional
                        if value in {'required', 'preferred'} and re.search(r'\b(?:for|to perform|to conduct)\s+[^,;]*$', part[:mention.start], re.I):
                            value = 'mentioned'
                        events[mention.label].add(value)
    result = {'required': [], 'preferred': [], 'mentioned': []}
    for label in ordered:
        categories = events[label]
        if ('excluded' in categories or {'required', 'preferred'} <= categories
                or {'required', 'not_required'} <= categories):
            continue
        for category in ('required', 'preferred', 'mentioned'):
            if category in categories:
                result[category].append(label)
                break
    return result
