// Derives the per-school coverage counts shown on the university switcher
// cards from the shipped corpus. Runs via the `prebuild` npm hook, so
// `next build` always ships fresh counts; the output JSON is committed so
// dev/test work without re-running it. The ~100MB corpus is only ever read
// here at build time — never import it into runtime code.
//
// The corpus is committed as per-school shards (data/processed/shards/*.json —
// GitHub's 100 MB blob limit; see scripts/shard_corpus.py). An assembled
// opportunities.json work file exists only in dev/pipeline checkouts, so read
// it when present and fall back to concatenating the shards otherwise.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const processedDir = join(frontendRoot, '..', 'data', 'processed');
const corpusPath = join(processedDir, 'opportunities.json');
const shardsDir = join(processedDir, 'shards');
const outPath = join(frontendRoot, 'src', 'lib', 'school-stats.json');

let records;
if (existsSync(corpusPath)) {
  const raw = readFileSync(corpusPath, 'utf8');
  // A Git-LFS-pointer work file means this checkout can't see the real corpus —
  // keep the committed school-stats.json rather than crash the deploy.
  if (raw.startsWith('version https://git-lfs')) {
    console.log(
      'school-stats: corpus is an unresolved Git LFS pointer — keeping committed school-stats.json.',
    );
    process.exit(0);
  }
  records = JSON.parse(raw);
} else if (existsSync(shardsDir)) {
  records = readdirSync(shardsDir)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .flatMap((f) => JSON.parse(readFileSync(join(shardsDir, f), 'utf8')));
} else {
  console.log('school-stats: no corpus in this checkout — keeping committed school-stats.json.');
  process.exit(0);
}

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
