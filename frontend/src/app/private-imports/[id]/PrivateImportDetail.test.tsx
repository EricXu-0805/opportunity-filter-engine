import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: 'en' }) }));
vi.mock('@/lib/private-import-target-api', async original => {
  const importedModule = await original<typeof import('@/lib/private-import-target-api')>();
  return { ...importedModule, getPrivateImportTarget: vi.fn(), getResolvedPrivateImportTarget: vi.fn() };
});
vi.mock('@/components/ApplicationRecordForm', () => ({ default: ({ opportunityId, ownerReady }: { opportunityId: string; ownerReady: boolean }) => <p>{ownerReady && 'Personal application record ' + opportunityId}</p> }));
vi.mock('@/components/ContactHistory', () => ({ default: ({ opportunityId }: { opportunityId: string }) => <p>Contact history {opportunityId}</p> }));
vi.mock('@/components/ApplicationHistory', () => ({ default: ({ opportunityId }: { opportunityId: string }) => <p>Application history {opportunityId}</p> }));
import { getPrivateImportTarget, getResolvedPrivateImportTarget, type PrivateResolvedTarget, PrivateTargetError } from '@/lib/private-import-target-api';
import { setupOwner, owner as setOwner, OTHER, deferred } from '@/lib/application-material.test-utils';
import PrivateImportDetail from './PrivateImportDetail';
const id = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const raw = vi.mocked(getPrivateImportTarget); const resolved = vi.mocked(getResolvedPrivateImportTarget);
const source = { detail: { title: 'Private test title', organization: 'Private Lab', description_raw: 'GPA < 3.0 and score > 80. END',
  source_url: null, url: null } } as PrivateResolvedTarget;
beforeEach(async () => { await setupOwner(); raw.mockReset(); resolved.mockReset();
  raw.mockResolvedValue({ target: { deleted_at: null, target_version: 'pit1:' + '1'.repeat(64) } } as Awaited<ReturnType<typeof getPrivateImportTarget>>);
  resolved.mockResolvedValue(source);
});
afterEach(() => vi.restoreAllMocks());
it('opens full private source and both owner-scoped histories without writing controls', async () => {
  render(<PrivateImportDetail id={id} />);
  await screen.findByText('Private test title');
  expect(screen.getByText('GPA < 3.0 and score > 80. END')).toBeInTheDocument();
  expect(screen.getByText('Contact history ' + id)).toBeInTheDocument();
  expect(screen.getByText('Application history ' + id)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /generate|send|apply/i })).toBeNull();
  expect(screen.getByText('Personal application record ' + id)).toBeInTheDocument();
  expect(resolved.mock.calls[0][1].expectedVersion).toBe('pit1:' + '1'.repeat(64));
});
it('retains histories for an owned tombstone without resolving old content', async () => {
  raw.mockResolvedValue({ target: { deleted_at: '2026-09-28T00:00:00Z' } } as Awaited<ReturnType<typeof getPrivateImportTarget>>);
  render(<PrivateImportDetail id={id} />);
  await screen.findByText(/This account copy was deleted/);
  expect(screen.getByText('Contact history ' + id)).toBeInTheDocument(); expect(resolved).not.toHaveBeenCalled();
  expect(screen.queryByText('Personal application record ' + id)).toBeNull();
});
it('never mounts history for a missing or foreign target', async () => {
  raw.mockResolvedValue(null); render(<PrivateImportDetail id={id} />);
  await screen.findByText('This import is not available in this account.');
  expect(screen.queryByText('Contact history ' + id)).toBeNull();
});
it('withdraws old owner content immediately and ignores late old-owner reads', async () => {
  const gate = deferred<Awaited<ReturnType<typeof getPrivateImportTarget>>>(); raw.mockReturnValueOnce(gate.promise);
  render(<PrivateImportDetail id={id} />); await waitFor(() => expect(raw).toHaveBeenCalledTimes(1));
  raw.mockResolvedValue(null); await act(async () => { await setOwner(OTHER); });
  await screen.findByText('This import is not available in this account.');
  await act(async () => { gate.resolve({ target: { deleted_at: null, target_version: 'pit1:' + '1'.repeat(64) } } as Awaited<ReturnType<typeof getPrivateImportTarget>>); });
  expect(resolved).not.toHaveBeenCalled(); expect(screen.queryByText('Private test title')).toBeNull();
});

it('keeps history reachable when the target is deleted between its two reads', async () => {
  resolved.mockRejectedValue(new PrivateTargetError('deleted'));
  render(<PrivateImportDetail id={id} />);
  await screen.findByText(/This account copy was deleted/);
  expect(screen.getByText('Application history ' + id)).toBeInTheDocument();
  expect(screen.queryByText('Private test title')).toBeNull();
  expect(screen.queryByText('Personal application record ' + id)).toBeNull();
});
