/**
 * The history preview of a saved renovation (round-2 review, criteria 1 and 3).
 *
 * Restore, adopt and open pass a saved doc through reviewedRenovation, so a bullet whose
 * current variant no w14 review accepted opens at its own text. The history preview read
 * each bullet's current variant directly: a version saved under main (w13.x: unreviewed,
 * in the UI locale) was previewed with that variant as the bullet. A legacy_doc version can
 * only be read, so the preview is all the student sees. It now shows the bullet's own text.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ listRenovationVersions: api.list, readRenovationVersion: api.read }));
vi.mock('@/lib/identity-owner', () => ({ isOwnerTokenValid: () => true }));
import RenovationHistory from './RenovationHistory';

const ID = '00000000-0000-4000-8000-000000000001';
const BASE = 'Helped build a data pipeline for the lab';
const UNREVIEWED = '主导搭建了实验室的容错数据管道';   // main's zh-locale rewrite: drops "Helped", other language
const REVIEWED = 'Helped build a data pipeline in Python for the lab';

afterEach(() => { cleanup(); vi.resetAllMocks(); });

async function preview(kind: 'complete' | 'legacy_doc', variant: Record<string, unknown>, resumeText?: string) {
  const summary = { id: ID, created_at: '2026-09-01T00:00:00Z', revision: kind === 'complete' ? 3 : null,
    snapshot_kind: kind, source_revision: null, source_updated_at: null };
  api.list.mockResolvedValue({ items: [summary], next_cursor: null });
  api.read.mockResolvedValue({ ...summary, owner_id: 'o', opportunity_id: 'opp',
    payload: { doc: { sections: [{ id: 's1', heading: 'Research', kind: 'research', bullets: [
      { id: 'b1', base_text: BASE, variants: [variant], current: 0, action: 'foreground' }] }] },
    base_snapshot: kind === 'complete' ? { sections: [] } : null, method: 'ai', warnings: kind === 'complete' ? [] : null } });
  render(<RenovationHistory opportunityId="opp" owner={{ uid: 'o' } as never} locale="en" disabled={false} resumeText={resumeText}
    onRestore={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: /Version 3|Imported version/ }));
  return screen.findByTestId('renovation-history-preview');
}

describe.each(['complete', 'legacy_doc'] as const)('a %s history version', (kind) => {
  it('saved under main previews the bullet at its own text, not the unreviewed variant', async () => {
    const shown = await preview(kind, { source: 'macro', text: UNREVIEWED, source_evidence: BASE });
    await waitFor(() => expect(shown.textContent).toContain(BASE));
    expect(shown.textContent).not.toContain(UNREVIEWED);
  });

  it('previews a variant a w14 review accepted', async () => {
    const shown = await preview(kind, { source: 'macro', text: REVIEWED, source_evidence: BASE, ops: ['lead_with'],
      reviewed: 'w14.1' });
    await waitFor(() => expect(shown.textContent).toContain(REVIEWED));
  });
});

describe('a history version\'s section heading (round-3 re-measure, criterion 1)', () => {
  it('previews a heading the model wrote as the standard name of its kind', async () => {
    const shown = await preview('complete', { source: 'user', text: BASE, source_evidence: BASE }, `• ${BASE}`);
    await waitFor(() => expect(shown.textContent).toContain(BASE));
    expect(shown.textContent!.split('\n')[0]).toBe('Experience');
  });

  it('previews the student\'s own heading row as they wrote it', async () => {
    const shown = await preview('complete', { source: 'user', text: BASE, source_evidence: BASE }, `RESEARCH\n• ${BASE}`);
    await waitFor(() => expect(shown.textContent).toContain(BASE));
    expect(shown.textContent!.split('\n')[0]).toBe('RESEARCH');
  });
});
