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

const records = JSON.parse(readFileSync(corpusPath, 'utf8'));
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
