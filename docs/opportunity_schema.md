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

Primary dedup key: `url` (UNIQUE constraint)

Secondary dedup: fuzzy match on `title + organization` for cross-source duplicates (e.g., same position posted on OUR blog and department page).
