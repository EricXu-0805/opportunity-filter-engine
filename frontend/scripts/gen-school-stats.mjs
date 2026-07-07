// Derives the per-school coverage counts shown on the university switcher
// cards from the shipped corpus. Runs via the `prebuild` npm hook, so
// `next build` always ships fresh counts; the output JSON is committed so
// dev/test work without re-running it. The 80MB corpus is only ever read
// here at build time — never import it into runtime code.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const corpusPath = join(frontendRoot, '..', 'data', 'processed', 'opportunities.json');
const outPath = join(frontendRoot, 'src', 'lib', 'school-stats.json');

const raw = readFileSync(corpusPath, 'utf8');
// The corpus is Git LFS-tracked. Vercel's build checkout does NOT pull LFS
// objects, so here the file is a small pointer ("version https://git-lfs...")
// rather than JSON — JSON.parse would crash and fail the whole deploy. We also
// don't WANT Vercel to fetch it (that would burn the free-tier LFS bandwidth on
// every preview/prod build to read a file we only need aggregate counts from).
// Keep the committed school-stats.json instead; CI and the weekly refresh (both
// check out with lfs:true) regenerate it against the real corpus.
if (raw.startsWith('version https://git-lfs')) {
  console.log(
    'school-stats: corpus is an unresolved Git LFS pointer (no LFS in this ' +
    'checkout) — keeping committed school-stats.json.',
  );
  process.exit(0);
}
const records = JSON.parse(raw);
const campusBySlug = new Map();
let national = 0;
for (const record of records) {
  if (record.school == null) national += 1;
  else campusBySlug.set(record.school, (campusBySlug.get(record.school) ?? 0) + 1);
}

const stats = Object.fromEntries(
  [...campusBySlug.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([slug, campus]) => [slug, { campus, national }]),
);
writeFileSync(outPath, `${JSON.stringify(stats, null, 2)}\n`);
console.log(
  `school-stats: ${records.length} records → ${campusBySlug.size} schools, national=${national}`,
);
