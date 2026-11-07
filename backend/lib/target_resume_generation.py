"""Identify the configuration that writes full-target suggestions and plans.

It hashes the effective writer and reviewer routes (provider and model), the
three system prompts, the output budget policy and the declared pipeline and
source-check versions. Credentials and student material never enter it, and
it is not a signed receipt or a quality claim: a provider may change what a
model slug serves without changing this value.
"""
from __future__ import annotations

import hashlib
import json

from backend.lib import (
    evidence_map,
    target_resume_ai,
    target_resume_ai_grounding,
    target_resume_ai_schema,
    target_resume_output_budget,
    target_resume_plan,
    target_resume_plan_schema,
)
from backend.lib.llm import _resolve, model_for

VERSION_PATTERN = r"^target-resume-generation-v1:[0-9a-f]{64}$"


def _route(task):
    # chat_completion(**model_for(task)) uses the first configured provider when
    # model_for names none, and that provider's default model when it names none.
    options = model_for(task)
    provider = _resolve(options.get("provider_id"))
    return None if provider is None else [provider.pid, options.get("model") or provider.model]


def generation_version() -> str:
    # Not in the manifest: the call settings in code (temperature, reasoning effort, max_tokens and the
    # output-budget formulas). Changing one changes what is written but not this value, unless the
    # matching PIPELINE_VERSION is bumped with it.
    manifest = {
        "writer": _route("tailor"), "reviewer": _route("tailor_review"),
        "suggestions": target_resume_ai_schema.PIPELINE_VERSION, "plan": target_resume_plan_schema.PIPELINE_VERSION,
        "checks": target_resume_ai_grounding.SOURCE_CHECK_VERSION,
        "output_budget": target_resume_output_budget.OUTPUT_BUDGET_POLICY,
        "prompts": [target_resume_ai.SYSTEM_PROMPT, target_resume_plan.SYSTEM_PROMPT, evidence_map.REVIEW_SYSTEM_PROMPT],
    }
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"target-resume-generation-v1:{digest}"
