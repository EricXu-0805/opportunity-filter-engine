"""Shared anti-fabrication grounding check (R71 tailor, R72 cold-email).

Extracted from ``backend/routes/tailor.py`` so cold-email generation can
reuse the exact same guarantee: an LLM may only use vocabulary that is
present in an *evidence corpus* (the student's profile + the opportunity's
own text). Any 5-plus-character lowercase ASCII token that isn't generic
English filler, isn't in a caller-supplied allowlist, and doesn't appear in
the corpus is treated as a fabricated hard claim (PyTorch, Kubernetes,
NeurIPS, …).

The ASCII regex is intentionally locale-agnostic: it still catches the
high-priority risk (a model claiming a technology the student never listed)
even when the surrounding prose is Chinese, because technical proper nouns
stay in their ASCII form.
"""

from __future__ import annotations

import re

# 5+ char lowercase tokens with optional tech punctuation (c++, scikit-learn,
# node.js). Anything shorter is too generic to count as a hard claim.
_HARD_CLAIM_RE = re.compile(r"\b[a-z][a-z0-9+\-#./]{4,}\b")

# Generic English filler that shows up in any well-written sentence without
# representing a specific skill claim. Allow-listed so the validator doesn't
# flag "developed a research project" as fabrication.
#
# Design intent: be aggressive about adding common verbs / abstract nouns /
# academic vocabulary so the validator only fires on *concrete* technology /
# product / proper-noun terms. False-positive cost is high (we'd drop a
# legitimate draft to the template fallback); false-negative cost is bounded
# (filler-listing 'framework' can't smuggle in 'TensorFlow').
_COMMON_FILLER: frozenset[str] = frozenset({
    # Pronouns / connectives that slip through the >=5 cap
    "above", "across", "after", "against", "ahead", "alongside",
    "another", "below", "between", "during", "every", "other",
    "their", "there", "these", "those", "throughout", "through",
    "together", "under", "until", "where", "which", "while", "would",
    # Common verbs
    "achieved", "acquired", "added", "adapted", "addressed", "adjusted",
    "advised", "analyzed", "applied", "approved", "assembled",
    "assessed", "assisted", "attempted", "audited", "authored",
    "automated", "began", "build", "building", "built", "calculated",
    "captured", "categorized", "centralized", "checked", "chose",
    "claimed", "clarified", "classified", "coached", "coded",
    "collaborated", "collected", "combined", "communicated",
    "compared", "compiled", "completed", "composed", "computed",
    "conducted", "configured", "considered", "constructed",
    "consulted", "contributed", "controlled", "converted", "created",
    "curated", "customized", "debugged", "decided", "decreased",
    "defined", "delivered", "demonstrated", "designed", "detected",
    "determined", "developed", "developing", "diagnosed", "directed",
    "discovered", "discussed", "documented", "drafted", "edited",
    "enabled", "encountered", "enforced", "engaged", "enhanced",
    "ensured", "established", "estimated", "evaluated", "examined",
    "executed", "expanded", "experimented", "explained", "explored",
    "extended", "extracted", "facilitated", "filtered", "finalized",
    "focused", "followed", "forecasted", "formatted", "formulated",
    "founded", "gathered", "generated", "guided", "handled", "hosted",
    "identified", "implemented", "improved", "included", "increased",
    "indexed", "informed", "initiated", "inspected", "installed",
    "instructed", "integrated", "interpreted", "interviewed",
    "introduced", "investigated", "involved", "joined", "labeled",
    "launched", "learned", "leveraged", "linked", "listed", "loaded",
    "located", "maintained", "managed", "mapped", "measured",
    "mentored", "merged", "migrated", "mitigated", "modeled",
    "modified", "monitored", "negotiated", "noted", "obtained",
    "operated", "optimized", "ordered", "organized", "outlined",
    "overcame", "oversaw", "packaged", "parsed", "participated",
    "partnered", "performed", "piloted", "planned", "prepared",
    "presented", "processed", "produced", "programmed", "promoted",
    "proofread", "proposed", "provided", "published", "purchased",
    "ranked", "rated", "reached", "received", "recognized",
    "recommended", "reconciled", "recorded", "recovered",
    "redesigned", "reduced", "refactored", "refined", "regulated",
    "rejected", "released", "remained", "removed", "rendered",
    "reorganized", "repaired", "replaced", "reported", "represented",
    "researched", "reshaped", "resolved", "responded", "restored",
    "restructured", "returned", "reused", "reviewed", "revised",
    "rolled", "routed", "sampled", "saved", "scaled", "scanned",
    "scheduled", "scoped", "screened", "searched", "secured",
    "selected", "served", "shipped", "showcased", "simplified",
    "simulated", "solved", "spearheaded", "specified", "spoke",
    "sponsored", "staffed", "standardized", "started", "stored",
    "streamlined", "strengthened", "structured", "studied",
    "submitted", "succeeded", "suggested", "summarized", "supervised",
    "supported", "surveyed", "synchronized", "synthesized", "tagged",
    "tailored", "tested", "tracked", "trained", "transferred",
    "transformed", "translated", "treated", "tutored", "uncovered",
    "understood", "unified", "updated", "upgraded", "validated",
    "verified", "visualized", "volunteered", "wrote",
    # Abstract / academic nouns
    "ability", "abilities", "access", "accuracy", "achievement",
    "achievements", "activities", "activity", "advanced", "advance",
    "agenda", "agreement", "alternative", "alternatives", "amount",
    "amounts", "analysis", "analyses", "analytics", "approach",
    "approaches", "architecture", "architectures", "area", "areas",
    "argument", "arguments", "assessment", "assessments", "audience",
    "audiences", "background", "balance", "barriers", "baseline",
    "behavior", "benchmark", "benchmarks", "benefit", "benefits",
    "budget", "budgets", "campaign", "campaigns", "candidate",
    "candidates", "capability", "capabilities", "career", "careers",
    "case", "category", "categories", "challenge", "challenges",
    "changes", "channel", "channels", "client", "clients",
    "cluster", "clusters", "collection", "collections", "committee",
    "communication", "communications", "community", "communities",
    "company", "companies", "comparison", "comparisons", "complete",
    "complex", "complexity", "component", "components", "concept",
    "concepts", "conclusion", "conclusions", "condition", "conditions",
    "conference", "conferences", "configuration", "configurations",
    "connection", "connections", "consequence", "consequences",
    "consistent", "constraint", "constraints", "content", "context",
    "contexts", "control", "controls", "course", "courses",
    "coursework", "creative", "creativity", "criteria", "criterion",
    "critical", "current", "customer", "customers", "data", "dataset",
    "datasets", "decision", "decisions", "deployment", "deployments",
    "depth", "design", "detail", "details", "device", "devices",
    "diagram", "diagrams", "different", "difference", "differences",
    "discussion", "discussions", "document", "documents",
    "documentation", "domain", "domains", "draft", "drafts",
    "duration", "early", "education", "effort", "efforts", "element",
    "elements", "engineering", "engineer", "engineers", "environment",
    "environments", "error", "errors", "estimate", "estimates",
    "evaluation", "evaluations", "event", "events", "evidence",
    "example", "examples", "exception", "exceptions", "execution",
    "experience", "experienced", "experiences", "experiment",
    "experiments", "experimental", "expert", "experts", "expertise",
    "explanation", "explanations", "exploration", "extension",
    "extensions", "facility", "facilities", "factor", "factors",
    "feature", "features", "feedback", "field", "fields", "figure",
    "figures", "finance", "financial", "finding", "findings", "first",
    "focus", "form", "format", "formats", "foundation", "framework",
    "frameworks", "function", "functions", "functional", "general",
    "generic", "global", "graduate", "graduates", "grant", "grants",
    "group", "groups", "growing", "growth", "guidance", "guideline",
    "guidelines", "hardware", "history", "honors", "hours", "human",
    "idea", "ideas", "image", "images", "impact", "impacts",
    "implementation", "implementations", "improvement", "improvements",
    "independent", "individual", "industry", "information", "initial",
    "initiative", "initiatives", "input", "inputs", "insight",
    "insights", "institute", "institution", "institutions",
    "instruction", "instructions", "instrument", "instruments",
    "integration", "interface", "interfaces", "internal",
    "international", "intern", "interns", "internship", "internships",
    "issue", "issues", "item", "items", "iteration", "iterations",
    "journal", "journals", "junior", "knowledge", "laboratory",
    "language", "languages", "large", "larger", "largest", "later",
    "layer", "layers", "leader", "leaders", "leadership", "leading",
    "learning", "lecture", "lectures", "lesson", "lessons", "letter",
    "letters", "level", "levels", "library", "libraries", "lifecycle",
    "limit", "limits", "literature", "local", "logic", "machine",
    "machines", "majority", "manager", "managers", "material",
    "materials", "matter", "matters", "measurement", "measurements",
    "mechanism", "mechanisms", "meeting", "meetings", "member",
    "members", "membership", "memo", "memos", "memory", "mentor",
    "mentors", "message", "messages", "method", "methodology",
    "methodologies", "methods", "metric", "metrics", "milestone",
    "milestones", "minimum", "minutes", "model", "models", "modern",
    "module", "modules", "monthly", "multiple", "national", "needed",
    "network", "networks", "newer", "novel", "number", "numbers",
    "objective", "objectives", "observation", "observations",
    "operation", "operations", "opportunity", "opportunities",
    "option", "options", "order", "outcome", "outcomes", "output",
    "outputs", "outside", "overview", "owner", "package", "packages",
    "panel", "paper", "papers", "parallel", "parameter", "parameters",
    "partial", "participant", "participants", "partner", "partners",
    "patient", "patients", "pattern", "patterns", "peer", "people",
    "performance", "period", "personal", "personnel", "phase",
    "phases", "pipeline", "pipelines", "place", "places", "plan",
    "plans", "planning", "platform", "platforms", "point", "points",
    "policy", "policies", "popular", "population", "populations",
    "portfolio", "position", "positions", "possible", "potential",
    "practical", "practice", "practices", "prediction", "predictions",
    "preparation", "presentation", "presentations", "previous",
    "primary", "principle", "principles", "prior", "private",
    "problem", "problems", "procedure", "procedures", "process",
    "processes", "processing", "product", "products", "professional",
    "professor", "professors", "profile", "profiles", "program",
    "programs", "programming", "progress", "project", "projects",
    "property", "properties", "proposal", "proposals", "protocol",
    "protocols", "publication", "publications", "purpose", "quality",
    "quantitative", "qualitative", "quarter", "quarterly", "query",
    "queries", "range", "rate", "rates", "ratio", "reason", "reasons",
    "recent", "recently", "record", "records", "reference",
    "references", "regional", "regular", "related", "relation",
    "relationship", "relationships", "release", "releases", "relevant",
    "report", "reports", "request", "requests", "requirement",
    "requirements", "research", "researcher", "researchers",
    "resource", "resources", "respect", "response", "responses",
    "result", "results", "resulting", "review", "reviews", "revision",
    "revisions", "robust", "role", "roles", "round", "rounds",
    "routine", "routines", "runtime", "sample", "samples", "scale",
    "scaling", "scenario", "scenarios", "schedule", "scheduling",
    "schema", "scheme", "school", "scientific", "scientist",
    "scientists", "scope", "screen", "screens", "search", "searches",
    "secondary", "section", "sections", "security", "segment",
    "segments", "selection", "senior", "sequence", "sequences",
    "series", "server", "servers", "service", "services", "session",
    "sessions", "setting", "settings", "setup", "shared", "similar",
    "simulation", "simulations", "single", "site", "sites", "size",
    "sizes", "skill", "skills", "smaller", "software", "solution",
    "solutions", "source", "sources", "specific", "specifically",
    "specification", "specifications", "sponsor",
    "stable", "stage", "stages", "stakeholder", "stakeholders",
    "standard", "standards", "state", "states", "status", "step",
    "steps", "storage", "strategic", "strategy", "strategies",
    "strong", "structure", "structures", "student", "students",
    "studies", "study", "subject", "subjects", "successful",
    "successfully", "summary", "support", "survey", "surveys",
    "system", "systems", "table", "tables", "target", "targets",
    "task", "tasks", "team", "teams", "technical", "technique",
    "techniques", "technology", "technologies", "template",
    "templates", "test", "tests", "testing", "themes", "theory",
    "third", "throughput", "timeline", "timelines", "title", "today",
    "tomorrow", "tool", "tools", "topic", "topics", "total", "totals",
    "tracker", "training", "transfer", "transition", "treatment",
    "trend", "trends", "trial", "trials", "type", "types", "typical",
    "undergrad", "undergraduate", "underlying", "unique", "unit",
    "units", "university", "update", "updates", "upgrade", "upgrades",
    "usage", "useful", "user", "users", "using", "validation",
    "value", "values", "variable", "variables", "variation", "various",
    "vendor", "vendors", "version", "versions", "video", "videos",
    "virtual", "vision", "weekly", "wider", "within", "working",
    "world", "written", "year", "years", "young",
    # Adjectives
    "accurate", "active", "actual", "actually", "additional",
    "adequate", "agile", "annual",
    "applicable", "appropriate", "automatic", "available", "average",
    "basic", "broad", "central", "certain", "clear", "clinical",
    "closer", "common", "competitive", "comprehensive", "concrete",
    "conditional", "consecutive", "considerable", "continuous",
    "convenient", "correct", "cross", "deep", "deeper", "default", "detailed", "diverse",
    "dynamic", "easier", "easy", "efficient", "effective", "essential",
    "ethical", "evident", "exact", "excellent",
    "executive", "external", "extensive", "false", "familiar",
    "favorable", "feasible", "final", "fluid", "formal", "frequent",
    "front", "full", "fundamental", "future", "graphical",
    "great", "happy", "heavy", "helpful", "high", "higher", "highest",
    "historical", "ideal", "important", "incremental",
    "informal", "innovative", "intensive",
    "interactive", "interesting", "interpersonal",
    "introductory", "iterative", "joint", "keen", "kind", "known",
    "legal", "limited", "linear", "logical",
    "long-term", "longer", "longitudinal", "low", "lower", "mainly",
    "manual", "matched", "mathematical", "medical", "medium",
    "minimal", "minor", "moderate", "multidisciplinary",
    "narrow", "normal", "notable",
    "numerical", "obvious", "official",
    "ongoing", "open", "operational", "optimal", "optional", "oral",
    "original", "overall", "particular", "passive", "perfect",
    "physical", "positive", "post", "powerful",
    "preliminary", "production",
    "proper", "proven", "public", "quick", "quicker", "rapid", "rapidly", "rare",
    "reactive", "real", "relative", "reliable", "remote", "renewable",
    "required", "rigorous", "safer", "scalable", "selective", "shorter", "significant", "simple", "skilled", "slight", "small", "smart", "social", "static",
    "statistical", "steady", "straightforward", "stronger", "structural", "sufficient", "suitable",
    "supportive", "sustainable", "synthetic", "systematic",
    "systematically", "thematic", "theoretical",
    "thorough", "tight", "timely", "traditional",
    "true", "unable", "uncommon", "uniform",
    "universal", "unknown", "unlimited", "unusual", "upper",
    "valid", "verbal", "vertical", "viable",
    "vibrant", "visible", "visual", "vital", "weaker", "weighted", "wireless", "wrong", "yearly",
    # Connective phrases / adverbs
    "actively", "additionally", "almost", "already", "around",
    "before", "behind", "carefully", "clearly", "closely",
    "consistently", "currently", "directly", "earlier", "easily",
    "effectively", "efficiently", "especially", "eventually", "exactly",
    "explicitly", "extremely", "fairly", "finally", "frequently",
    "fully", "gradually", "heavily", "highly", "however", "ideally",
    "immediately", "implicitly", "indeed", "indirectly", "initially",
    "instead", "largely", "lately", "likely", "linearly",
    "manually", "meanwhile", "merely", "mostly", "namely",
    "naturally", "nearly", "necessarily", "normally", "obviously",
    "occasionally", "officially", "originally", "particularly",
    "partly", "perfectly", "perhaps", "personally", "physically",
    "potentially", "precisely", "previously", "primarily", "promptly",
    "proudly", "purely", "quickly", "rarely", "readily",
    "regularly", "relatively", "reliably", "remotely",
    "roughly", "scientifically", "seamlessly", "shortly", "significantly",
    "similarly", "simply", "slightly", "slowly", "smoothly", "softly",
    "steadily", "still", "strictly", "strongly",
    "substantially", "surely", "swiftly", "thoroughly",
    "thus", "tightly", "totally", "ultimately", "uniformly", "usually",
    "verbally", "visibly", "visually", "widely",
    # Warm cover-letter / cold-email prose. These tone, intensifier, connector
    # and abstract-noun words showed up as false positives on "make it warmer"
    # email edits (R72-A): ordinary register vocabulary that is never a skill
    # claim. Safe per the design intent above — a technology/credential is
    # never ordinary English, so listing "delighted" cannot smuggle "PyTorch".
    "about", "absolutely", "accordingly", "admire", "admired", "although",
    "amazing", "anything", "appreciate", "appreciated", "appreciation",
    "aspects", "aspiration", "aspirations", "because", "besides", "brilliant",
    "bring", "bringing", "brings", "certainly", "collaboration", "comfortable",
    "commitment", "completely", "confident", "consider", "consideration",
    "considering", "contribute", "contributing", "contributions",
    "conversations", "curiosity", "dedication", "deeply", "definitely",
    "delighted", "despite", "discover", "discovering", "discuss", "discussing",
    "dreams", "eagerness", "enjoy", "enjoyed", "enjoying", "enthusiasm",
    "enthusiastic", "entirely", "equally", "everyone", "everything",
    "exceptionally", "excited", "exciting", "explore", "exploring", "fantastic",
    "fascinated", "finds", "follow", "following", "fulfilling", "further",
    "furthermore", "genuine", "genuinely", "glad", "goals", "grateful",
    "gratitude", "greatly", "grow", "happen", "happening", "happens", "help",
    "helped", "helping", "honestly", "honored", "hoped", "hopeful", "hopes",
    "hoping", "humbled", "immensely", "impressive", "incredible", "incredibly",
    "inspired", "interest", "interests", "intrigued", "journey", "kindest",
    "learn", "likewise", "lovely", "loving", "maybe", "meaningful", "mentorship",
    "moreover", "motivation", "offer", "offering", "outstanding", "passion",
    "passionate", "passions", "perspective", "perspectives", "pleased", "proud",
    "qualities", "quite", "rather", "reaching", "really", "remarkable",
    "rewarding", "share", "sharing", "since", "someone",
    "something", "somewhat", "strengths", "supporting", "therefore", "things",
    "though", "thoughts", "thrilled", "tremendously", "truly", "unless",
    "valuable", "valued", "warmest", "welcome", "welcomed", "whenever",
    "wherever", "whether", "wholeheartedly", "willingness", "wished", "wishing",
    "wonder", "wonderful", "wonderfully", "wondering",
    "always", "attitude", "brief", "challenging", "chance", "collaborative",
    "committed", "cutting-edge", "dependable", "detail-oriented", "ethic",
    "excitement", "friendly", "groundbreaking", "hands-on", "hardworking",
    "heartfelt", "inspiring", "loves", "making", "persistent", "prospect",
    "relish", "sleeves", "solid", "spirit", "tackling",
})


# Validation policies. STRICT is the original deny-by-default behaviour
# (every unknown 5+ char token is a claim) — correct for terse resume bullets
# where unknown words are usually real claims. LENIENT_PROSE only treats tokens
# carrying a concreteness signal as claims — correct for warm cold-email prose
# where ordinary register words (delighted, genuinely, …) are not claims and
# the deny-by-default approach over-rejects benign edits.
STRICT = "strict"
LENIENT_PROSE = "lenient_prose"

# Concrete technology / tool / credential terms that are hard claims even in
# lowercase prose. The shape signal (internal caps, digits, +/#) misses two
# important classes: conventionally-lowercase names (numpy, pandas, kubernetes
# written lowercase) and short acronyms the 5-char regex never sees (aws, cuda,
# ros, k8s). This set backstops both. Seeded from the ranker skill taxonomy but
# PINNED here so the security gate cannot silently weaken when ranking changes
# (test_tech_terms_cover_security_critical guards the high-value members).
_TECH_TERMS: frozenset[str] = frozenset({
    "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn", "numpy",
    "pandas", "matplotlib", "seaborn", "scipy", "opencv", "huggingface",
    "transformers", "xgboost", "lightgbm", "spacy", "nltk", "jax",
    "python", "java", "javascript", "typescript", "kotlin", "swift", "rust",
    "golang", "scala", "haskell", "matlab", "verilog", "vhdl", "perl", "ruby",
    "kubernetes", "docker", "terraform", "ansible", "jenkins", "kafka",
    "spark", "hadoop", "airflow", "mongodb", "postgresql", "mysql", "redis",
    "elasticsearch", "graphql", "nginx", "django", "flask", "fastapi",
    "react", "angular", "node.js", "tailwind", "webpack",
    "aws", "gcp", "azure", "cuda", "ros", "ros2", "fpga", "asic",
    "labview", "solidworks", "ansys", "comsol", "autocad", "simulink",
    "nlp", "llm", "cnn", "rnn", "lstm", "bert", "hpc", "k8s", "cpp", "ci/cd",
    "pcr", "crispr", "elisa", "hplc", "fmri", "nmr",
    "chromatography", "spectroscopy", "microscopy",
    "patent", "patents", "dissertation", "fellowship", "valedictorian",
})

# Security gate: short tech acronyms (<5 chars) the hard-claim regex can't see,
# mapped to expansions. STRICT must flag a hallucinated "AWS"/"ROS", but a
# resume that abbreviates "natural language processing" to "NLP" must NOT be
# flagged (one flag drops the whole AI draft). Hence *bidirectional* grounding:
# grounded if the acronym OR its expansion is in the corpus. Empty value = no
# corpus-expressible expansion (bert, cuda) -> grounded by the token only.
_TECH_ACRONYMS: dict[str, str] = {
    "aws": "amazon web services",
    "gcp": "google cloud",
    "ros": "robot operating system",
    "ros2": "robot operating system",
    "k8s": "kubernetes",
    "fpga": "field programmable gate array",
    "asic": "application specific integrated circuit",
    "hpc": "high performance computing",
    "nlp": "natural language processing",
    "llm": "large language model",
    "cnn": "convolutional neural network",
    "rnn": "recurrent neural network",
    "lstm": "long short term memory",
    "bert": "",
    "cuda": "",
    "pcr": "polymerase chain reaction",
    "hplc": "high performance liquid chromatography",
    "fmri": "functional magnetic resonance",
    "nmr": "nuclear magnetic resonance",
}

# Collapse every non-alphanumeric run to a single space so an expansion like
# "high-performance liquid chromatography" matches a corpus that wrote it
# without the hyphen (or vice-versa).
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def _norm_phrase(s: str) -> str:
    return _NONALNUM_RE.sub(" ", s.lower()).strip()


def _expansion_grounded(token: str, corpus_norm: str) -> bool:
    """True if ``token`` is a known acronym whose expansion phrase appears in
    the (space-normalized) corpus — the acronym→expansion half of the
    bidirectional grounding. The acronym→token half is handled by the caller's
    word-boundary corpus check."""
    exp = _TECH_ACRONYMS.get(token)
    return bool(exp) and _norm_phrase(exp) in corpus_norm


# Case-preserving token scan (keeps tech punctuation so c++, node.js, ci/cd,
# scikit-learn survive as single tokens). Lower-cased + stripped before use.
_LENIENT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./\-]*")


def hard_claims(text: str) -> set[str]:
    """Extract 5+ char lowercase ASCII tokens — candidate 'hard claims'."""
    return set(_HARD_CLAIM_RE.findall(text.lower()))


def _corpus_tokens(corpus_lower: str) -> set[str]:
    return {t.strip("./-") for t in _LENIENT_TOKEN_RE.findall(corpus_lower)}


def _in_corpus(token: str, corpus_lower: str, corpus_tokens: set[str]) -> bool:
    """Word-boundary (exact-token) membership, with a substring fallback only
    for long (5+) tokens so "python" still matches a corpus "python3". Short
    tokens are word-boundary ONLY — otherwise "ros" would match "across".
    """
    if token in corpus_tokens:
        return True
    return len(token) >= 5 and token in corpus_lower


def _lenient_fabricated(
    text: str, corpus_lower: str, extra_allow: frozenset[str],
) -> list[str]:
    corpus_tokens = _corpus_tokens(corpus_lower)
    corpus_norm = _norm_phrase(corpus_lower)
    fabricated: list[str] = []
    for raw in _LENIENT_TOKEN_RE.findall(text):
        tok = raw.strip("./-")
        if not tok:
            continue
        low = tok.lower()
        # A claim candidate only if it carries a concreteness signal: an
        # internal capital (CamelCase: PyTorch — but NOT all-caps shouting or a
        # sentence-initial capital), a digit (GPT-4, ResNet50), '+'/'#' (c++,
        # c#), or membership in the pinned tech/credential taxonomy.
        internal_cap = any(c.isupper() for c in tok[1:]) and any(c.islower() for c in tok)
        has_digit = any(c.isdigit() for c in tok)
        has_techpunct = "+" in tok or "#" in tok
        if not (internal_cap or has_digit or has_techpunct or low in _TECH_TERMS):
            continue
        if low in extra_allow or _in_corpus(low, corpus_lower, corpus_tokens):
            continue
        if _expansion_grounded(low, corpus_norm):
            continue
        fabricated.append(low)
    return fabricated


def _acronym_fabricated(
    text: str, corpus_lower: str, extra_allow: frozenset[str],
) -> list[str]:
    """Short tech acronyms (aws, ros, cuda, k8s, nlp …) the 5-char hard-claim
    regex misses, flagged only when neither the acronym nor its expansion is
    grounded in the corpus. Closes a STRICT false-negative without the
    abbreviation false-positive (see ``_TECH_ACRONYMS``)."""
    corpus_tokens = _corpus_tokens(corpus_lower)
    corpus_norm = _norm_phrase(corpus_lower)
    fabricated: list[str] = []
    for raw in _LENIENT_TOKEN_RE.findall(text):
        low = raw.strip("./-").lower()
        if low not in _TECH_ACRONYMS or low in extra_allow:
            continue
        if low in corpus_tokens or _expansion_grounded(low, corpus_norm):
            continue
        fabricated.append(low)
    return fabricated


def validate_no_fabrication(
    text: str,
    evidence_corpus: str,
    *,
    extra_allow: frozenset[str] = frozenset(),
    policy: str = STRICT,
) -> tuple[bool, list[str]]:
    """Return ``(passed, fabricated_tokens)``.

    ``policy=STRICT`` (default, used by resume tailoring): a token is
    fabricated when it is a 5+ char lowercase ASCII word NOT in the
    common-filler allowlist, NOT in ``extra_allow``, and NOT a substring of
    ``evidence_corpus``. Aggressive — right for terse resume claims.

    ``policy=LENIENT_PROSE`` (cold-email): only tokens carrying a concreteness
    signal (internal caps, digit, '+'/'#', or pinned tech/credential taxonomy)
    can be fabricated, so warm register words pass without an allowlist arms
    race. Corpus matching is word-boundary for short/tech tokens (substring
    only for 5+ tokens), so short acronyms aren't swallowed by collisions.

    Both policies additionally flag ungrounded short tech acronyms via
    bidirectional acronym/expansion matching (``_TECH_ACRONYMS``).
    """
    corpus_lower = evidence_corpus.lower()
    if policy == LENIENT_PROSE:
        fabricated = sorted(set(_lenient_fabricated(
            text, corpus_lower, extra_allow,
        )))
        return (len(fabricated) == 0, fabricated)

    claims = hard_claims(text)
    fabricated = [
        c for c in claims
        if c not in _COMMON_FILLER
        and c not in extra_allow
        and c not in corpus_lower
    ]
    fabricated += _acronym_fabricated(text, corpus_lower, extra_allow)
    return (len(fabricated) == 0, sorted(set(fabricated)))


def policy_divergence(
    text: str,
    evidence_corpus: str,
    *,
    extra_allow: frozenset[str] = frozenset(),
) -> list[str]:
    """Tokens STRICT flags as fabricated but LENIENT_PROSE allows — the
    shadow delta between the two policies on one draft. Pure (no logging) so
    a caller can quantify, over real cold-email traffic, how much looser the
    lenient policy is than the strict resume baseline. Expected to be warm
    register words; a concrete tech term appearing here would signal a
    LENIENT false-negative worth review (it shouldn't, those are caught by
    both)."""
    _, strict_fab = validate_no_fabrication(
        text, evidence_corpus, extra_allow=extra_allow, policy=STRICT,
    )
    _, lenient_fab = validate_no_fabrication(
        text, evidence_corpus, extra_allow=extra_allow, policy=LENIENT_PROSE,
    )
    return sorted(set(strict_fab) - set(lenient_fab))
