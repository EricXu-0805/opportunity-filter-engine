# User Profile Schema

## V1 Minimal Input Form

To keep onboarding under 3 minutes, the first user-facing form collects only these fields:

| Field | Type | Required | Example |
|-------|------|----------|---------|
| year | select | Yes | freshman |
| major | text | Yes | Computer Engineering |
| international_student | boolean | Yes | true |
| seeking_type | multi-select | Yes | [research, summer_program] |
| interested_fields | multi-select | Yes | [AI/ML, systems, data science] |
| hard_skills | tags | Yes | [Python, Java, C++, pandas] |
| relevant_coursework | tags | No | [CS 124, STAT 107, ECE 120] |
| resume_ready | boolean | Yes | false |
| can_cold_email | boolean | Yes | true |

## Full Internal Profile Schema

```json
{
  "id": "uuid-v4",
  "name": "Guoyi Xu",
  "school": "UIUC",
  "year": "freshman | sophomore | junior | senior",
  "major": "Computer Engineering",
  "secondary_interests": ["CS", "STAT", "Data Science"],

  "international_student": true,
  "citizenship": "China",
  "work_authorization_notes": "F-1, CPT eligible after 1 year",

  "seeking_type": ["research", "summer_program"],
  "desired_fields": ["AI", "ML", "computer vision", "systems", "data science"],
  "preferred_location": "on-campus | remote | either",
  "time_availability": "part-time | summer | flexible",

  "hard_skills": ["Python", "Java", "C++", "pandas", "PyTorch"],
  "coursework": ["CS 124", "STAT 107", "ECE 120", "PHYS 214"],
  "projects": [
    {
      "name": "OpenEd",
      "description": "Educational platform co-founder, Flask/FastAPI",
      "skills_demonstrated": ["Python", "Flask", "FastAPI", "full-stack"]
    }
  ],
  "publications": 2,
  "prior_research": true,
  "research_description": "VLM bias, Video Scene Graph Generation",

  "experience_level": "none | beginner | some | strong",
  "resume_ready": false,
  "linkedin_ready": false,
  "can_cold_email": true,

  "preferences": {
    "min_match_threshold": 60,
    "show_reach_opportunities": true,
    "prioritize_paid": true,
    "exclude_citizenship_restricted": true
  }
}
```

## Profile → Filter Mapping

The profile drives the matching engine through these mappings:

| Profile field | Filters... | Matching layer |
|--------------|-----------|----------------|
| year | Year eligibility requirements | Eligibility |
| international_student | Citizenship restrictions | Eligibility |
| major + interested_fields | Major/field requirements | Eligibility |
| hard_skills | Skill overlap | Eligibility + Readiness |
| coursework | Prerequisite coverage | Readiness |
| experience_level | Competitive readiness | Readiness |
| resume_ready | Application completeness | Readiness |
| can_cold_email | Outreach capability | Readiness |
| seeking_type | Opportunity type filter | Pre-filter |
| preferred_location | Location filter | Pre-filter |
| exclude_citizenship_restricted | Remove ineligible | Pre-filter |

## Example: Profile-Driven Decision Logic

**Profile:** Freshman, international, CS-adjacent, knows Python, no research experience, no resume

**System behavior:**
- Pre-filter: exclude `citizenship_required = true` opportunities
- Eligibility: prioritize positions accepting freshmen, matching CS/ECE/STAT
- Readiness: penalize opportunities requiring resume or prior research; boost low-barrier positions
- Upside: boost on-campus UIUC positions (easier for international freshmen), boost paid positions
- Output: "Best Matches Now" = campus RA positions with low barriers; "Worth Stretching For" = select REUs that accept internationals
