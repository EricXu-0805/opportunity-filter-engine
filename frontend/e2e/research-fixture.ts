import { createHash } from 'node:crypto';
import type { ResearchContext } from '../src/lib/research-context';

// Synthetic source metadata. This does not verify any real researcher or work.
export const RESEARCH_TITLE = 'Synthetic instrument research 王🧪';
export const RESEARCH_ABSTRACT = 'The research team used laser interferometry to compare instrument readings. This is professor research, not a student accomplishment.';
const canonical = (value: unknown): string => Array.isArray(value) ? `[${value.map(canonical).join(',')}]`
  : value !== null && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(',')}}`
  : JSON.stringify(value);
export function researchFixture(status: 'available' | 'stale' = 'available'): ResearchContext {
  const snapshot = { version: 1 as const, source: 'openalex' as const, record_source_url: 'https://example.edu/synthetic-researcher',
    identity_name: 'Synthetic Researcher', institution_id: 'https://openalex.org/I157725225', author_id: 'https://openalex.org/A5000000123', gate_version: 3,
    checked_at: new Date(Date.now() - (status === 'stale' ? 40 * 86400000 : 60000)).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    works: [{ work_id: 'https://openalex.org/W4000000123', title: RESEARCH_TITLE, year: 2025, publication_date: '2025-01-01',
      source_url: 'https://doi.org/10.1234/synthetic-instrument-study', doi: 'https://doi.org/10.1234/synthetic-instrument-study',
      abstract: RESEARCH_ABSTRACT, abstract_status: 'present' as const, updated_date: '2026-09-01T00:00:00Z' }],
  };
  return { version: 1, status, snapshot: { ...snapshot, snapshot_version: 'rs1:' + createHash('sha256').update(canonical(snapshot)).digest('hex') } };
}
