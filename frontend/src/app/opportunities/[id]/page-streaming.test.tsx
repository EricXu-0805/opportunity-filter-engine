import { PassThrough } from 'node:stream';
import type { ReactNode } from 'react';
import { renderToPipeableStream } from 'react-dom/server.node';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SimilarOpportunity } from '@/lib/api-server';

const api = vi.hoisted(() => ({ detail: vi.fn(), similar: vi.fn() }));
vi.mock('@/lib/api-server', () => ({ fetchOpportunityDetail: api.detail, fetchSimilarServer: api.similar }));
vi.mock('next/navigation', () => ({ notFound: () => { throw new Error('REAL_NOT_FOUND'); } }));
vi.mock('./OpportunityDetail', () => ({ default: ({ opp, similarContent }: { opp: { title: string }; similarContent?: ReactNode }) =>
  <main><a href="/results">Back to matches</a><h1>{opp.title}</h1><p>Primary content</p>{similarContent}<footer>Source footer</footer></main> }));
vi.mock('./OpportunityUnavailable', () => ({ default: () => <p>Opportunity temporarily unavailable</p> }));
vi.mock('./json-ld', () => ({ buildOpportunityJsonLd: () => null }));
vi.mock('next/link', () => ({ default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));

import OpportunityPage from './page';

const aborts: Array<() => void> = [];
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function stream(element: ReactNode) {
  const body = new PassThrough();
  const first = deferred<string>();
  const end = deferred<string>();
  let html = '';
  body.on('data', chunk => { html += String(chunk); first.resolve(html); });
  body.on('end', () => end.resolve(html));
  const rendering = renderToPipeableStream(element, { onShellReady() { rendering.pipe(body); } });
  aborts.push(() => rendering.abort());
  return { first: first.promise, end: end.promise };
}
const row = { id: 'related', title: 'Related study', source_type: 'campus_program', opportunity_type: 'research',
  target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting',
    reason_code: null, verified_at: null, expires_at: null }, _similarity: 3 } as SimilarOpportunity;

beforeEach(() => { api.detail.mockReset(); api.similar.mockReset(); });
afterEach(() => { aborts.splice(0).forEach(abort => abort()); });

describe('the primary detail does not await optional recommendations', () => {
  it('streams title, return link and source before recommendations complete, then fills only the rail', async () => {
    const related = deferred<SimilarOpportunity[]>();
    api.detail.mockResolvedValue({ status: 'ok', opportunity: { id: 'A', title: 'Primary A' } });
    api.similar.mockReturnValue(related.promise);
    const element = await OpportunityPage({ params: Promise.resolve({ id: 'A' }) });
    const output = stream(element);
    const first = await output.first;
    expect(first).toContain('<h1>Primary A</h1>');
    expect(first).toContain('Back to matches');
    expect(first).toContain('Source footer');
    expect(first).not.toContain('Related study');
    expect(api.similar).toHaveBeenCalledWith('A', 5);
    related.resolve([row]);
    const completed = await output.end;
    expect(completed).toContain('Related study');
    expect(completed.match(/<h1>Primary A<\/h1>/g)).toHaveLength(1);
  });

  it('keeps the primary page when the optional request falls back to no results', async () => {
    const related = deferred<SimilarOpportunity[]>();
    api.detail.mockResolvedValue({ status: 'ok', opportunity: { id: 'A', title: 'Primary A' } });
    api.similar.mockReturnValue(related.promise);
    const output = stream(await OpportunityPage({ params: Promise.resolve({ id: 'A' }) }));
    expect(await output.first).toContain('Primary content');
    related.resolve([]);
    expect(await output.end).toContain('Source footer');
  });

  it('does not fetch recommendations for a real missing target', async () => {
    api.detail.mockResolvedValue({ status: 'not-found' });
    api.similar.mockResolvedValue([]);
    await expect(OpportunityPage({ params: Promise.resolve({ id: 'missing' }) })).rejects.toThrow('REAL_NOT_FOUND');
    expect(api.similar).not.toHaveBeenCalled();
  });

  it('keeps transport failure distinct from missing data without fetching recommendations', async () => {
    api.detail.mockResolvedValue({ status: 'unavailable' });
    api.similar.mockResolvedValue([]);
    const output = stream(await OpportunityPage({ params: Promise.resolve({ id: 'A' }) }));
    expect(await output.end).toContain('Opportunity temporarily unavailable');
    expect(api.similar).not.toHaveBeenCalled();
  });
});
