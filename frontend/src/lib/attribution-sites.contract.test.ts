import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Static contract, M96: a value our pipeline or our listing can supply (pay,
// the international answer, the citizenship rule, a location, a skill, major
// or class-year list, research topics) is shown with a marker wherever it is
// shown. Each fix so far found another copy of a render site that printed the
// value bare, so this test lists them: every source file that reads one of
// these values for display must also read the flag that says where it came
// from, or be named below with the reason it does not need to.
//
// A regex heuristic over the source, like user-scoped-storage.contract.test.ts.
// It cannot prove a file uses the flag on every branch (the per-site tests do
// that); it catches the next new file that renders the value with no flag in
// sight. docs/opportunity_schema.md "Where inferred values are shown" lists
// the sites.

const SRC = join(__dirname, '..');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) { out.push(...walk(full)); continue; }
    if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry) && !entry.includes('test-fixtures')) {
      out.push(full);
    }
  }
  return out;
}

const SOURCES = new Map(walk(SRC).map((f) => [f.slice(SRC.length + 1), readFileSync(f, 'utf8')]));

interface Rule { reads: RegExp; flag: RegExp }

const RULES: Record<string, Rule> = {
  paid: { reads: /\.paid\s*===\s*'(yes|stipend|no)'|getPaidBadge\(/, flag: /paid_attribution/ },
  international: {
    reads: /international_friendly\s*===\s*'yes'|getIntlBadge\(|facultySafeInternational\(/,
    flag: /international_attribution/,
  },
  citizenship: { reads: /citizenship_required\s*(===\s*true|&&|\))/, flag: /citizenship_attribution/ },
  compensation: { reads: /cleanCompensation\(\w+\.compensation_details\)/, flag: /compensation_attribution/ },
  location: { reads: /\b(opp|opportunity|o|s|m\.opportunity)\??\.location\b/, flag: /location_attribution/ },
  skills: { reads: /skills_required\??\.(map|join)\b|skills_required\)/, flag: /skills_attribution/ },
  keywords: { reads: /\bkeywords\??\.(map|slice|join)\b/, flag: /keywords_attribution/ },
  majors: { reads: /\.majors\??\.(map|join)\b|eligibility\??\.majors\)/, flag: /majors_attribution/ },
  preferredYear: { reads: /preferred_year\??\.(map|join|filter)\b/, flag: /preferred_year_attribution/ },
};

// Reviewed exceptions: file -> values it reads without the flag, and why.
const EXEMPT: Record<string, Record<string, string>> = {
  'app/api/og/opportunity/[id]/route.tsx': {
    paid: 'draws the pill only when og-facts.ts showPaid, which reads paid_attribution, says so',
  },
  'lib/badge-utils.ts': {
    paid: 'the helper itself: callers pass the flag as its attribution argument',
    international: 'the helper itself: callers pass the flag as its attribution argument',
  },
  'app/compare/scores.ts': {
    international: 'radar scores, not a value shown as the program\'s terms',
    majors: 'radar scores, not a value shown as the program\'s terms',
  },
  'lib/match-utils.ts': {
    citizenship: 'facultySafeInternational, a rule other sites call; the CSV it builds reads the flags',
  },
  'components/ResumeRenovationModal.tsx': {
    citizenship: 'shape validation of a payload, nothing rendered',
    skills: 'shape validation of a payload, nothing rendered',
    majors: 'shape validation of a payload, nothing rendered',
  },
  'lib/public-target-shape.ts': {
    citizenship: 'shape validation of a payload, nothing rendered',
  },
  'components/ImportOpportunityDetails.tsx': {
    location: 'a private import the student added; guessed fields carry its own inferred marker',
  },
  'components/OnboardingIntro.tsx': {
    location: 'a school\'s location in the school picker, not an opportunity value',
  },
};

describe('every site that shows an inferrable value reads its source flag', () => {
  for (const [value, rule] of Object.entries(RULES)) {
    it(`${value}: no file renders it without the flag`, () => {
      const missing = [...SOURCES]
        .filter(([file, src]) => rule.reads.test(src) && !rule.flag.test(src) && !EXEMPT[file]?.[value])
        .map(([file]) => file);
      expect(missing).toEqual([]);
    });
  }

  it('every exception still reads the value it is excused for', () => {
    const stale: string[] = [];
    for (const [file, values] of Object.entries(EXEMPT)) {
      for (const value of Object.keys(values)) {
        const src = SOURCES.get(file);
        if (src === undefined || !RULES[value].reads.test(src) || RULES[value].flag.test(src)) {
          stale.push(`${file}: ${value}`);
        }
      }
    }
    expect(stale).toEqual([]);
  });
});

// The *_attribution / *_basis keys Opportunity declares (lib/types.ts).
function declaredFlags(): string[] {
  const types = SOURCES.get('lib/types.ts')!;
  const body = types.slice(types.indexOf('export interface Opportunity {'));
  return [...new Set(
    [...body.slice(0, body.indexOf('\n}')).matchAll(/^\s*(\w+_(?:attribution|basis))\?:/gm)].map((m) => m[1]),
  )].filter((key) => key !== 'publication_attribution_status');
}

describe('the cached results page keeps every source flag the wire declares', () => {
  // A results page restored from local storage renders through the same card
  // and CSV as a fresh one; a flag missing from the cache projection prints
  // the value bare on every cache hit for seven days.
  it('lists each *_attribution / *_basis key of Opportunity', () => {
    const declared = declaredFlags();
    expect(declared.length).toBeGreaterThan(5);
    const cache = SOURCES.get('lib/match-cache.ts')!;
    expect(declared.filter((key) => !cache.includes(`'${key}'`))).toEqual([]);
  });
});

describe('the saved résumé target carries and labels every flag of a value it saves', () => {
  // The target snapshot is signed when the draft is saved and cannot be
  // recomputed, so a flag left out of it is lost for that draft; the saved
  // criteria page then prints the value bare.
  const NOT_SAVED: Record<string, string> = {
    keywords_attribution: 'research topics are not saved in the target',
    majors_basis: 'majors_attribution carries the same answer into the target',
    preferred_year_basis: 'preferred_year_attribution carries the same answer into the target',
  };
  const schema = SOURCES.get('lib/target-resume.ts')!;
  const saved = [...schema.slice(schema.indexOf('const CRITERIA_FIELDS'))
    .match(/attribution: \{([^}]*)\}/)![1].matchAll(/(\w+_attribution):/g)].map((m) => m[1]);
  it('saves each declared flag, or names why it does not', () => {
    expect(saved.length).toBeGreaterThan(5);
    expect(declaredFlags().filter((key) => !saved.includes(key) && !NOT_SAVED[key])).toEqual([]);
    expect(Object.keys(NOT_SAVED).filter((key) => saved.includes(key) || !declaredFlags().includes(key))).toEqual([]);
  });
  it('the server snapshot schema and the saved criteria page know each saved flag', () => {
    const server = readFileSync(join(SRC, '../../backend/lib/target_resume_context.py'), 'utf8');
    const page = SOURCES.get('components/TargetResumeCriteria.tsx')!;
    const labelled = page.slice(page.indexOf('const inferredFields'));
    expect(saved.filter((key) => !server.includes(`'${key}'`))).toEqual([]);
    expect(saved.filter((key) => !labelled.includes(`'${key}'`))).toEqual([]);
  });
});
