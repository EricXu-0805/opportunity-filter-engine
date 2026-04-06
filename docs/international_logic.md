# International Student Logic

## Why This Is a First-Order Concern

International students on F-1 visas face constraints that domestic students don't:

1. **CPT** (Curricular Practical Training): requires 1 full academic year enrollment before eligibility for off-campus work
2. **On-campus employment**: allowed from day one, no special authorization needed — this is why campus research is the best V1 focus
3. **NSF REUs**: most require US citizenship or permanent residency
4. **Federal programs**: NASA, DOE SULI, NIH — almost always require citizenship
5. **Private sector internships**: require CPT authorization, which freshmen typically can't get

## Decision Matrix

```
Is the student international?
├─ No → No additional filtering needed
└─ Yes →
    ├─ Is the opportunity on-campus at UIUC?
    │   └─ Yes → ✅ Generally accessible (no work auth needed)
    ├─ Is it an off-campus internship?
    │   ├─ Student has 1+ year enrollment?
    │   │   └─ Yes → ✅ CPT eligible, but flag as "requires CPT"
    │   └─ No → ⚠️ Flag: "May not be eligible — check with ISSS"
    ├─ Is it a federal program (NSF, DOE, NASA, NIH)?
    │   └─ Default → ❌ Likely requires US citizenship (check individually)
    └─ Is it an external university program?
        └─ Check program page → Tag accordingly
```

## Tagging Fields

```json
{
  "international_friendly": "yes | no | unknown",
  "work_auth_notes": "On-campus position, no work authorization required",
  "work_auth_risk": "low | medium | high | unknown"
}
```

**Risk levels:**
- **low**: on-campus UIUC, or program explicitly states international-friendly
- **medium**: off-campus but CPT-eligible, or program doesn't specify
- **high**: federal funding, citizenship mentioned, or known restrictions

## Impact on Scoring

When `student.international = true`:

- Opportunities with `international_friendly = "no"` → **hard filter out**
- Opportunities with `work_auth_risk = "high"` → eligibility score penalty of -40
- Opportunities with `work_auth_risk = "medium"` → eligibility score penalty of -15, add note
- On-campus UIUC opportunities → eligibility boost of +10

## ISSS Reference

UIUC's International Student & Scholar Services (ISSS) is the authoritative source. The system should never give legal advice — instead, flag and say:

> "This opportunity may have work authorization requirements. Check with ISSS (isss.illinois.edu) or your international advisor before applying."

## Common Patterns

| Opportunity type | Typical international eligibility |
|-----------------|----------------------------------|
| UIUC campus RA | ✅ Yes |
| UIUC Research Park intern | ⚠️ CPT required (1yr enrollment) |
| NSF REU | ❌ Usually US citizens only |
| DOE SULI | ❌ US citizens only |
| NASA internships | ❌ US citizens only |
| Private company internship | ⚠️ CPT required |
| External university summer program | Varies — check individually |
| Volunteer research (unpaid) | ✅ Generally yes |
