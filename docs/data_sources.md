# V1 Data Sources — Executable List

## Priority Tier 1: UIUC On-Campus (Scrape or Semi-Auto)

| # | Source | URL | Type | Int'l Friendly | Method | Notes |
|---|--------|-----|------|----------------|--------|-------|
| 1 | UIUC OUR Blog (RSS) | https://blogs.illinois.edu/xml/6204/rss.xml | RSS feed | Yes (on-campus) | Auto (feedparser) | Lowest friction; already implemented |
| 2 | UIUC Summer Research Opps Database | https://researchops.web.illinois.edu/ | HTML scrape | Mixed | Semi-auto | ~279 listings, paginated Drupal |
| 3 | ECE Undergrad Research Openings | https://ece.illinois.edu/academics/ugrad/undergrad-research/opportunities | HTML scrape | Yes (on-campus) | Semi-auto | Faculty-posted lab openings |
| 4 | Siebel School Undergrad Research | https://siebelschool.illinois.edu/research/undergraduate-research | HTML scrape | Yes (on-campus) | Semi-auto | CS/DS research positions |
| 5 | Grainger College Research Opps | https://students.grainger.illinois.edu/research/research-opportunities/ | HTML scrape | Yes (on-campus) | Semi-auto | Engineering-wide listings |
| 6 | UIUC Career Center — UG Research | https://www.careercenter.illinois.edu/undergraduateresearch | Link page | Mixed | Manual | Curated link page |

## Priority Tier 2: UIUC Summer Programs (Manual + URL Parser)

| # | Source | URL | Paid | Int'l Friendly | Notes |
|---|--------|-----|------|----------------|-------|
| 7 | Illinois Space Grant UROP | https://isgc.aerospace.illinois.edu/students/undergraduate-research-opportunities-program/ | $7,000 | UIUC only | 10 weeks STEM |
| 8 | Siebel SRP | https://siebelschool.illinois.edu/research/undergraduate-research/srp | Yes | Check yearly | Hybrid; May-Jul |
| 9 | Physics REU | https://physics.illinois.edu/research/reu | Yes | US only | 10 weeks summer |
| 10 | ISRP (Grad College) | https://grad.illinois.edu/diversity/isrp | Yes | US only | Since 1986 |

## Priority Tier 3: External REU & National (Manual Entry)

| # | Source | URL | Paid | Int'l Friendly | Notes |
|---|--------|-----|------|----------------|-------|
| 11 | NSF REU Site Search | https://www.nsf.gov/crssprgm/reu/reu_search.jsp | Yes | Usually No | Filter by CS/Eng |
| 12 | REU Finder | https://reufinder.com/ | Yes | Varies | Community-curated |
| 13 | Caltech SURF | https://sfp.caltech.edu/undergraduate-research/programs/surf | Yes | Yes | Prestigious |
| 14 | CMU RISS | https://riss.ri.cmu.edu/ | Yes | Yes | Robotics |
| 15 | PathwaysToScience | https://www.pathwaystoscience.org/programs.aspx | Yes | Varies | 1,070+ STEM programs |

## V1 Collection Strategy

### Phase A — Manual Seed (Week 1)
Hand-enter 20-30 opportunities using `manual_importer.py`. Focus on ECE/CS/STAT positions with clear eligibility info.

### Phase B — RSS Auto-Collect (Week 1-2)
Run `uiuc_our_rss.py` → normalize → store in `data/processed/`.

### Phase C — HTML Scrape (Week 2-3)
Validate CSS selectors for `uiuc_sro.py` against live DOM. Scrape SRO database.

### Phase D — URL Parser Semi-Auto (Ongoing)
Paste-and-parse new URLs as they surface. Manual review before insertion.

## Data Quality Rules
- Every record must have: title, url, source, opportunity_type
- `international_friendly` must be tagged (yes/no/unknown)
- `confidence_score`: 0.6 auto-collected, 0.9 manually entered
- Manually reviewed records get `manually_reviewed: true`
