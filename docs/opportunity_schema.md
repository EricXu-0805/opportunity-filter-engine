# Opportunity Schema

## Core Fields

Every opportunity is normalized into this structure regardless of source.

```json
{
  "id": "uuid-v4",
  "source": "uiuc_our_rss",
  "source_url": "https://blogs.illinois.edu/view/6204/...",
  "source_type": "uiuc_research | summer_program | external_reu | federal | linkedin_manual",

  "title": "Undergraduate Research Assistant – Data Systems Lab",
  "organization": "University of Illinois at Urbana-Champaign",
  "department": "Computer Science",
  "lab_or_program": "Data Systems Lab",
  "pi_name": "Prof. Jane Smith",
  "url": "https://...",

  "location": "Champaign, IL",
  "on_campus": true,
  "remote_option": "no | yes | hybrid | unknown",

  "opportunity_type": "research | summer_program | internship | fellowship | project",
  "paid": "yes | no | stipend | unknown",
  "compensation_details": "$15/hr or 3 credit hours",

  "deadline": "2026-04-15",
  "posted_date": "2026-03-01",
  "start_date": "2026-06-01",
  "duration": "10 weeks",

  "eligibility": {
    "preferred_year": ["freshman", "sophomore"],
    "min_gpa": null,
    "majors": ["CS", "ECE", "STAT"],
    "skills_required": ["Python", "data analysis"],
    "skills_preferred": ["SQL", "machine learning"],
    "citizenship_required": false,
    "international_friendly": "yes | no | unknown",
    "work_auth_notes": "",
    "eligibility_text_raw": "Open to all UIUC undergraduates..."
  },

  "application": {
    "contact_method": "application_form | email | portal | unknown",
    "requires_resume": "yes | no | unknown",
    "requires_cover_letter": "no",
    "requires_transcript": "no",
    "requires_recommendation": "no",
    "application_effort": "low | medium | high | unknown",
    "application_url": "https://..."
  },

  "description_raw": "Full original text...",
  "description_clean": "Cleaned/summarized text...",
  "keywords": ["machine learning", "undergraduate", "research assistant"],

  "metadata": {
    "confidence_score": 0.85,
    "last_verified": "2026-03-15",
    "first_seen_at": "2026-03-01",
    "last_seen_at": "2026-03-15",
    "is_active": true,
    "manually_reviewed": false,
    "notes": ""
  }
}
```

## Field Extraction Strategy

| Field | Auto-extractable? | Method |
|-------|-------------------|--------|
| title | Yes | HTML/RSS parsing |
| organization | Yes | Domain + metadata |
| deadline | Partial | Regex + LLM fallback |
| preferred_year | Partial | Keyword matching + LLM |
| majors | Partial | Keyword matching |
| skills_required | Partial | LLM extraction from description |
| international_friendly | Rarely | LLM inference + manual review |
| application_effort | No | Manual or LLM estimate |
| paid | Partial | Keyword matching |

**Rule:** If confidence < 0.6 on any critical field (international_friendly, eligibility), flag for manual review.

## International-Friendly Tagging Logic

This is a first-order concern for our target users. The `international_friendly` field uses this decision tree:

```
1. Does the posting explicitly say "US citizens only" or "must be authorized"?
   → international_friendly = "no"

2. Does it say "open to all students" or make no mention of citizenship?
   → international_friendly = "yes" (if on-campus UIUC)
   → international_friendly = "unknown" (if external)

3. Is it a federal program (NSF REU, DOE SULI, NASA)?
   → Check individual program — many NSF REUs require US citizenship/permanent residency
   → international_friendly = "no" (default for federal, unless explicitly stated otherwise)

4. Is it an on-campus UIUC research position?
   → international_friendly = "yes" (generally, campus RA positions don't require work auth)
```

## Deduplication

Canonical identity is the record's `id` string.

- **Serving layer (enforced):** `backend/data_loader._canonicalize_corpus`
  deduplicates by `id` at corpus load — first occurrence wins, a warning is
  logged — so the ranked list and the by-id lookup are always the same
  records even if a shard upsert ever leaves the same id in two shards.
- **Pipeline (enforced per collector):** `src/collectors/refresh_all.py`
  merges by id and runs the joint-appointment / same-person collapse passes.
- The url-UNIQUE constraint and fuzzy `title + organization` matching that an
  earlier revision of this document described were never implemented; they
  remain future work, not a property of the current system.

## Source-backed contact instructions (local candidate)

`application.contact_method` is a legacy normalized field and can be inferred. It is not proof that a professor accepts email. Current detail projection recomputes `contact_instructions` from retained website evidence; client-supplied or cached top-level rules are not authoritative.

- Internal evidence: `metadata.contact_instruction_sources[]`, containing `source_url`, `record_source_url`, timezone-aware `checked_at`, and `sections: [{heading, text}]`. Faculty evidence also binds `identity_name` to the current professor. Raw evidence is removed from public output.
- Public result: `version: 1`, `status: unknown | known | conflicting`, `email_policy: unknown | allowed | not_accepted | form_only | conflicting`, and `rules[]`. Each rule has a kind, exact quote, source URL and original check time. Public email redaction still applies.
- Rule kinds: `no_email`, `form_only`, `email_allowed`, `subject`, `materials`, and reserved `contact_person`. This candidate does not extract or select a designated contact automatically.
- A subject rule contains either an exact `subject`, a `subject_template` with placeholders, or only its unparsed format quote. Exact subjects survive initial generation and refinement. Formats require the user to complete and confirm the subject before opening an email app; the model must not invent names.
- Material values: `resume_cv`, `unofficial_transcript`, `transcript`, `cover_letter`, `statement_of_interest`, `application_form`, `single_pdf`. Listing a requirement does not attach, combine, or submit a file.
- More than 40 distinct rules adds `review_required: true` and `reason: too_many_requirements`. Output stays bounded to 40 rules while policy/conflict detection considers all retained sections. Generation and new composition stop until review; overflow is not described as a source conflict.

The first extractor accepts only clearly undergraduate or all-applicant sections. Conditional/optional rules and mixed audiences are conservatively omitted. A ban on application-status inquiries is not a ban on first contact; an application portal alone is not evidence that inquiry emails are forbidden. Unknown means no applicable rule was confirmed, not permission or a vacancy.

Source collection is connected to successful SRO detail, URL fetch, and identity-matched faculty profile reads. Parsing caller-supplied HTML, an OG summary, a generated description, an address, or a publication cannot create official contact evidence. Existing records are not backfilled by this change.

The complete public result participates in `writing_target_version`. Initial generation, variants, streaming, and refinement recheck current policy before provider work. New composition refreshes the current stored target and profile; a server-provided recipient is checked separately because addresses are intentionally excluded from the writing version. This does not fetch the official webpage at click time. Copying a draft and confirming a historical send retain their existing meanings.
