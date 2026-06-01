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
})


def hard_claims(text: str) -> set[str]:
    """Extract 5+ char lowercase ASCII tokens — candidate 'hard claims'."""
    return set(_HARD_CLAIM_RE.findall(text.lower()))


def validate_no_fabrication(
    text: str,
    evidence_corpus: str,
    *,
    extra_allow: frozenset[str] = frozenset(),
) -> tuple[bool, list[str]]:
    """Return ``(passed, fabricated_tokens)``.

    A token is fabricated when it is a 5+ char lowercase ASCII word in
    ``text`` that is NOT in the common-filler allowlist, NOT in the
    caller's ``extra_allow`` set (e.g. cold-email salutation/closing
    scaffolding), and does NOT appear anywhere in ``evidence_corpus``.

    Substring matching against the (already-lowercased) corpus is
    intentional: it lets "python" hit when the corpus has "python3" and
    avoids false flags on stem variations.
    """
    claims = hard_claims(text)
    fabricated = [
        c for c in claims
        if c not in _COMMON_FILLER
        and c not in extra_allow
        and c not in evidence_corpus
    ]
    return (len(fabricated) == 0, sorted(fabricated))
