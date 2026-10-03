import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: 'en' }) }));
vi.mock('@/lib/private-import-target-api', async original => {
  const importedModule = await original<typeof import('@/lib/private-import-target-api')>();
  return { ...importedModule, getPrivateImportTarget: vi.fn(), getResolvedPrivateImportTarget: vi.fn() };
});
vi.mock('@/components/PrivateEmailLauncher', () => ({ default: ({ available }: { available: boolean }) => available ? <button>Prepare private email</button> : null }));
vi.mock('@/components/ApplicationRecordForm', async () => {
  const { useState } = await import('react'); const { captureOwnerToken } = await import('@/lib/identity-owner');
  return { default: function Form({ opportunityId, ownerReady, verifyTarget }: { opportunityId: string; ownerReady: boolean; verifyTarget?: (owner: ReturnType<typeof captureOwnerToken>) => Promise<boolean> }) {
    const [checked, setChecked] = useState<string | null>(null);
    return <><p>{ownerReady && 'Personal application record ' + opportunityId}</p>
      <button type="button" onClick={() => { void (verifyTarget ? verifyTarget(captureOwnerToken()) : Promise.resolve(true)).then(ok => setChecked(String(ok))); }}>Check target</button>
      {checked && <p>Target check {checked}</p>}</>;
  } };
});
vi.mock('@/components/ContactHistory', () => ({ default: ({ opportunityId }: { opportunityId: string }) => <p>Contact history {opportunityId}</p> }));
vi.mock('@/components/ApplicationHistory', () => ({ default: ({ opportunityId }: { opportunityId: string }) => <p>Application history {opportunityId}</p> }));
import { getPrivateImportTarget, getResolvedPrivateImportTarget, type PrivateResolvedTarget, PrivateTargetError } from '@/lib/private-import-target-api';
import { setupOwner, owner as setOwner, OTHER, deferred } from '@/lib/application-material.test-utils';
import PrivateImportDetail from './PrivateImportDetail';
import PrivateImportPage from './page';
const id = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const raw = vi.mocked(getPrivateImportTarget); const resolved = vi.mocked(getResolvedPrivateImportTarget);
const source = { target_version: 'pit1:' + '1'.repeat(64), detail: { title: 'Private test title', organization: 'Private Lab', description_raw: 'GPA < 3.0 and score > 80. END',
  source_url: null, url: null } } as PrivateResolvedTarget;
beforeEach(async () => { await setupOwner(); raw.mockReset(); resolved.mockReset();
  raw.mockResolvedValue({ target: { deleted_at: null, target_version: 'pit1:' + '1'.repeat(64) } } as Awaited<ReturnType<typeof getPrivateImportTarget>>);
  resolved.mockResolvedValue(source);
});
afterEach(() => vi.restoreAllMocks());
it('opens full private source and both owner-scoped histories with private email preparation and no send action', async () => {
  render(<PrivateImportDetail id={id} />);
  await screen.findByText('Private test title');
  expect(screen.getByText('GPA < 3.0 and score > 80. END')).toBeInTheDocument();
  expect(screen.getByText('Contact history ' + id)).toBeInTheDocument();
  expect(screen.getByText('Application history ' + id)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /generate|send|apply/i })).toBeNull();
  expect(screen.getByRole('button', { name: 'Prepare private email' })).toBeInTheDocument();
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

it('re-resolves the exact shown version before an application write and withdraws the form after a deletion', async () => {
  render(<PrivateImportDetail id={id} />); await screen.findByText('Personal application record ' + id);
  resolved.mockClear(); resolved.mockRejectedValueOnce(new PrivateTargetError('deleted'));
  fireEvent.click(screen.getByRole('button', { name: 'Check target' }));
  await screen.findByText(/This account copy was deleted/);
  expect(resolved).toHaveBeenCalledOnce(); expect(resolved.mock.calls[0][0]).toBe(id);
  expect(resolved.mock.calls[0][1]).toMatchObject({ expectedVersion: 'pit1:' + '1'.repeat(64), owner: expect.objectContaining({ uid: expect.any(String) }) });
  expect(screen.queryByText('Personal application record ' + id)).toBeNull(); expect(screen.queryByRole('button', { name: 'Prepare private email' })).toBeNull();
  expect(screen.getByText('Application history ' + id)).toBeInTheDocument();
});
it('refuses an application write when the target changed or cannot be read, keeping the page', async () => {
  render(<PrivateImportDetail id={id} />); await screen.findByText('Personal application record ' + id);
  resolved.mockRejectedValueOnce(new PrivateTargetError('changed'));
  fireEvent.click(screen.getByRole('button', { name: 'Check target' })); await screen.findByText('Target check false');
  expect(screen.getByText('Private test title')).toBeInTheDocument();
});

it('opens the import named by the route segment, which Next hands the page percent-encoded', async () => {
  // Every import id has a ':'. The page passed '%3A' on, the id check refused it before any
  // request, and every import page said it could not be loaded.
  render(await PrivateImportPage({ params: Promise.resolve({ id: encodeURIComponent(id) }) }));
  await screen.findByText('Private test title');
  expect(raw).toHaveBeenCalledOnce(); expect(raw.mock.calls[0][0]).toBe(id); expect(resolved.mock.calls[0][0]).toBe(id);
  expect(screen.getByText('Contact history ' + id)).toBeInTheDocument();
});
