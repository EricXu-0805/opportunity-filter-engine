import type { ResearchContext } from './research-context';
export function researchFixture(): ResearchContext {
  return { version: 1, status: 'available', snapshot: {
    version: 1, source: 'openalex', record_source_url: 'https://example.edu/people/pat',
    identity_name: 'Pat Lee', institution_id: 'https://openalex.org/I1', author_id: 'https://openalex.org/A1',
    gate_version: 3, checked_at: '2026-09-25T12:00:00Z', snapshot_version: 'rs1:' + 'a'.repeat(64),
    works: [{ work_id: 'https://openalex.org/W1', title: 'Grounded Models 研究 🧪', year: 2025,
      publication_date: '2025-05-01', source_url: 'https://doi.org/10.1234/models', doi: 'https://doi.org/10.1234/models',
      abstract: 'We measure errors in source extraction.', abstract_status: 'present', updated_date: '2026-09-01T10:11:12.123456' }],
  } };
}
