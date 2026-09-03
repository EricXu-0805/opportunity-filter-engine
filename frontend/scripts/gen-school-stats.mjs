// Build-time gate on the committed school-coverage fallback. Validates; never
// counts.
//
// This script used to derive the switcher's per-school numbers itself, by
// counting every corpus record with a `school` set. The API meanwhile served
// only the listings half of the corpus, and faculty contacts are ~97% of it, so
// the same chip rendered ~4,500 for JHU from this file and 28 once the live
// fetch landed. Two implementations of one number is what made that possible.
//
// The numbers now come from `scripts/gen_school_stats.py`, which calls the same
// function the API route calls. That has to be Python: which records count is
// decided by `target_truth` and the release scope, which are real business
// logic and cannot be mirrored here without recreating the drift. So this hook
// only checks that what is committed is a payload of the shape and schema the
// frontend can read — a fast, corpus-free structural check — and fails the
// build rather than letting a stale or pre-v2 file ship silently.
//
// `tests/test_school_coverage.py` is the other half: it regenerates from the
// shards in CI and fails if the committed numbers have gone stale.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Mirrors backend/lib/school_coverage.py — bump in both or in neither.
const EXPECTED_SCHEMA = 'school-coverage-v2';
const COUNT_FIELDS = [
  'listing_count',
  'faculty_contact_count',
  'unreviewed_count',
  'total_count',
];

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const statsPath = join(frontendRoot, 'src', 'lib', 'school-stats.json');

function fail(message) {
  console.error(`school-stats: ${message}`);
  console.error(
    'school-stats: regenerate with `python scripts/gen_school_stats.py` from the repo root.',
  );
  process.exit(1);
}

if (!existsSync(statsPath)) {
  fail('src/lib/school-stats.json is missing.');
}

let payload;
try {
  payload = JSON.parse(readFileSync(statsPath, 'utf8'));
} catch (error) {
  fail(`src/lib/school-stats.json is not valid JSON (${error.message}).`);
}

if (payload?.schema !== EXPECTED_SCHEMA) {
  // A pre-v2 file is the listings-only/unfiltered shape. Shipping it would put
  // the original understatement back on the first paint of every card.
  fail(
    `expected schema "${EXPECTED_SCHEMA}", found ${JSON.stringify(payload?.schema ?? null)}.`,
  );
}

if (!payload.schools || typeof payload.schools !== 'object') {
  fail('payload has no `schools` map.');
}

if (typeof payload.national_count !== 'number') {
  fail('payload has no numeric `national_count`.');
}

for (const [slug, counts] of Object.entries(payload.schools)) {
  for (const field of COUNT_FIELDS) {
    if (typeof counts?.[field] !== 'number' || !Number.isFinite(counts[field])) {
      fail(`school "${slug}" has no numeric ${field}.`);
    }
  }
  // The invariant this whole change exists to establish, checked on the artifact
  // that ships rather than trusted because the generator meant well.
  const expected = counts.listing_count + counts.faculty_contact_count;
  if (counts.total_count !== expected) {
    fail(
      `school "${slug}": total_count ${counts.total_count} != `
      + `listing_count ${counts.listing_count} + faculty_contact_count ${counts.faculty_contact_count}.`,
    );
  }
}

const schoolCount = Object.keys(payload.schools).length;
const coverage = Object.values(payload.schools).reduce((sum, s) => sum + s.total_count, 0);
console.log(
  `school-stats: ${schoolCount} schools, ${coverage} campus records `
  + `(listings + faculty contacts), national=${payload.national_count} — schema ok.`,
);
