"""Readiness evidence from a student's confirmed work, bound to a listing's stated method."""
from __future__ import annotations

import re

# Keep this narrow: a matching tool name describes work the student did, without
# promoting that tool to a confirmed skill or claiming they meet a requirement.
_METHODS = (
    'Python', 'MATLAB', 'Stata', 'SPSS', 'SQL', 'PyTorch', 'TensorFlow', 'JavaScript',
    'TypeScript', 'C++', 'C#', 'SolidWorks', 'AutoCAD', 'ArcGIS', 'QGIS', 'GIS',
    'ROS', 'ROS 2', 'OpenCV', 'NumPy', 'pandas', 'scikit-learn', 'Qualtrics',
    'ImageJ', 'LaTeX', 'qPCR', 'PCR', 'Western blot', 'flow cytometry', 'RNA sequencing',
)
_BY_NAME = {label.casefold(): label for label in _METHODS}
# Methods may touch Chinese text, which does not use spaces as word boundaries.
_METHOD = re.compile(r"(?<![a-z0-9_+#])(?:"
                     + "|".join(re.escape(label) for label in sorted(_METHODS, key=len, reverse=True))
                     + r")(?![a-z0-9_+#])", re.I | re.ASCII)
_ENGLISH_ACTION = (r"(?:built|developed|implemented|analy[sz]ed|tested|used|wrote|designed|applied|trained|ran|mapped|"
                   r"processed|measured|coded|automated|validated|calibrated)")
_CHINESE_ACTION = r"(?:使用|实现|實現|分析|开发|開發|编写|編寫|测量|測量|处理|處理|训练|訓練)"
# A first-person statement or a résumé bullet can establish whose action it
# was. The existence of a past-tense verb somewhere in a quotation cannot.
_OWN_ACTION = re.compile(r"(?:^\s*[-•*]?\s*|\bI\s+(?:have\s+)?(?:personally\s+)?)" + _ENGLISH_ACTION + r"\b|"
                         r"^\s*[-•*]?\s*(?:我|本人)?(?:曾经|曾經|曾|独立|獨立|亲自|親自)?" + _CHINESE_ACTION, re.I)
_NOT_PERFORMED = re.compile(r"\b(?:not|never|no|without|haven['’]t|didn['’]t|learning to|intend to|plan to|would|may|might|could|interested in)\b|(?:没有|沒有|未使用|未曾|计划|計畫|想学|想學)", re.I)
_OTHER_ACTOR = re.compile(r"\b(?:she|he|they|colleagues?|collaborators?|teammates?|supervisors?|my mentor|our team)\b|(?:同事|合作者|导师|導師|队友|隊友)", re.I)
_CLAUSE = re.compile(r"[.!?;\n。！？；]+")
# Do not attribute a second actor's method to a student's earlier verb.
_OWN_CLAUSE = re.compile(_CLAUSE.pattern + r"|[,，]|\b(?:but|whereas|while|who|which|that|where|how)\b|"
                        r"\band\b(?=\s+(?:[\w'-]+\s+){1,3}" + _ENGLISH_ACTION + r"\b)", re.I)


def confirmed_methods(entries):
    """Index once per ranking. Preserve the first matching full record's id and revision."""
    index = {}
    for entry in entries or ():
        if not isinstance(entry, dict) or entry.get("status") != "confirmed" or entry.get("source") not in ("manual", "github", "resume"):
            continue
        for clause in _OWN_CLAUSE.split(entry["text"]):
            if not _OWN_ACTION.search(clause) or _NOT_PERFORMED.search(clause) or _OTHER_ACTOR.search(clause):
                continue
            for term in _METHOD.finditer(clause):
                key = term.group().casefold()
                index.setdefault(key, {"entry_id": entry["id"], "revision": entry["revision"], "method": _BY_NAME[key]})
    return index


def target_methods(required, research):
    """Index the target's own stated requirements and research topics once per corpus."""
    terms = {}
    for label in required if isinstance(required, list) else ():
        if isinstance(label, str) and label.strip().casefold() in _BY_NAME:
            terms[label.strip().casefold()] = "stated_requirement"
    for text in research:
        if not isinstance(text, str):
            continue
        for clause in _CLAUSE.split(text):
            if _NOT_PERFORMED.search(clause):
                continue
            for term in _METHOD.finditer(clause):
                terms.setdefault(term.group().casefold(), "research_area")
    return tuple(terms.items())


def experience_for_target(index, target):
    for method, source in target:
        if method in index:
            return {**index[method], "target_source": source}
    return None
