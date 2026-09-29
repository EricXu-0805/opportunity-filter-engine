import { emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ColdEmailResponse, EmailVariant, ProfileData } from '@/lib/types';

// Only the service boundary is replaced. Hydration, reconciliation, the journal,
// owner capability, action preflight and the email editor run their real code.
const services = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://foreground-refresh.test';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-only';
  return { session: vi.fn(), read: vi.fn(), from: vi.fn(), rpc: vi.fn(),
    variants: vi.fn(), stream: vi.fn(), generate: vi.fn(), refine: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: services.session, signInAnonymously: vi.fn(),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) },
  from: services.from, rpc: services.rpc,
}) }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt, getEmailVariants: (...args: unknown[]) => emailReceipt(services.variants(...args), args[1] as string, (args[3] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(services.stream(...args), args[1] as string, (args[2] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion), generateColdEmail: (...args: unknown[]) => emailReceipt(services.generate(...args), args[1] as string, (args[2] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion),
  refineEmail: (...args: unknown[]) => emailReceipt(services.refine(...args), args[3] as string, (args[4] as { expectedTargetVersion?: string } | undefined)?.expectedTargetVersion), getVapidPublicKey: vi.fn() }));
vi.mock('@/i18n/client', () => {
  const t = (key: string) => key;
  return { useT: () => ({ t, locale: 'en' }), useLocale: () => 'en' };
});
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import RawColdEmailModal from './ColdEmailModal';
import { emailTarget, emailReceipt, EMAIL_TARGET_VERSION } from './ColdEmailModal.test-fixtures';
function ColdEmailModal(props: Parameters<typeof RawColdEmailModal>[0]) {
  return <RawColdEmailModal target={emailTarget(props.opportunityId)} {...props} />;
}
import { PROFILE_REFRESH_INTERVAL_MS, useProfileRefresh } from '@/lib/use-profile-refresh';
import { useRetainedWritingProfile } from '@/lib/use-retained-writing-profile';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, readUserScopedRaw, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readProfileSyncEnvelope, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const BASE: ProfileData = { name: 'Alex', institution: 'UIUC', home_school: 'uiuc', college: 'Engineering',
  major: 'CS', grade: 'Junior', is_international: false, research_interests: 'robotics', skills: [], coursework: [] };
const variant: EmailVariant = { id: 'template', label: 'Template', subject: 'Template subject', body: 'Template body',
  recipient_email: 'lab@example.edu', mailto_link: '' };
const templates = { variants: [variant], pipeline_version: 'foreground-test' };
const row = (profile: ProfileData = BASE, revision = 1) => ({ data: { profile_data: profile, revision }, error: null });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
const mirror = () => JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE) ?? 'null');
// Native WebCrypto work is not a Promise microtask. Track the real operations
// so draining React work does not assert before receipt verification finishes.
// Profile deadlines remain frozen; there is no timeout increase or retry.
const pendingDigests = new Set<Promise<ArrayBuffer>>();
let digestGate: Promise<void> | null = null;
async function drain(waitForDigests = true) {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => {
      for (let n = 0; n < 40; n += 1) await Promise.resolve();
      if (waitForDigests) await Promise.all([...pendingDigests]);
    });
  }
}
function Harness() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const refresh = useProfileRefresh(true, (loaded) => setProfile(loaded.profile));
  const retained = useRetainedWritingProfile(profile, true, 'foreground-target');
  return <><output data-testid="refresh-state">{refresh.status}</output>
    {retained.profile && <ColdEmailModal isOpen onClose={() => {}} opportunityId="foreground-target"
      opportunityTitle="Robotics lab" profile={retained.profile} profileAvailable={retained.profileAvailable}
      profileRefresh={refresh} />}</>;
}
let ownerSequence = 0;
beforeEach(async () => {
  pendingDigests.clear(); digestGate = null;
  const nativeDigest = crypto.subtle.digest.bind(crypto.subtle);
  vi.spyOn(crypto.subtle, 'digest').mockImplementation((algorithm, data) => {
    const gate = digestGate;
    const pending = gate ? gate.then(() => nativeDigest(algorithm, data)) : nativeDigest(algorithm, data);
    pendingDigests.add(pending);
    void pending.then(() => pendingDigests.delete(pending), () => pendingDigests.delete(pending));
    return pending;
  });
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  const uid = `foreground-owner-${++ownerSequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
  services.session.mockReset().mockImplementation(async () => ({ data: { session: { user: { id: captureOwnerToken().uid } } } }));
  services.read.mockReset().mockResolvedValue(row()); services.rpc.mockReset();
  services.from.mockReset().mockImplementation((table: string) => {
    expect(table).toBe('profiles');
    return { select: (columns: string) => {
      expect(columns).toBe('profile_data, revision');
      return { eq: (key: string, owner: string) => {
        expect(key).toBe('id'); expect(owner).toBe(captureOwnerToken().uid);
        const query = { abortSignal: (_signal: AbortSignal) => query,
          // Deliberately ignore abort: the real consumer must reject late results.
          maybeSingle: () => Promise.resolve(services.read()) };
        return query;
      } };
    } };
  });
  services.variants.mockReset().mockResolvedValue(templates);
  services.stream.mockReset().mockResolvedValue({ ...variant, method: 'template' });
  services.generate.mockReset(); services.refine.mockReset();
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllTimers(); vi.useRealTimers(); });
async function openEditor() {
  render(<Harness />); await drain();
  expect(screen.getByDisplayValue('Template body')).toBeVisible();
  expect(screen.getByTestId('refresh-state')).toHaveTextContent('ready');
  expect(services.stream).toHaveBeenCalledOnce();
}
function editDraft() {
  fireEvent.change(screen.getByDisplayValue('Template subject'), { target: { value: 'My subject' } });
  fireEvent.change(screen.getByDisplayValue('Template body'), { target: { value: 'My manual body' } });
  fireEvent.change(screen.getByDisplayValue('lab@example.edu'), { target: { value: 'my@example.edu' } });
}
function expectManualDraft() {
  expect(screen.getByDisplayValue('My subject')).toBeVisible();
  expect(screen.getByDisplayValue('My manual body')).toBeVisible();
  expect(screen.getByDisplayValue('my@example.edu')).toBeVisible();
}
async function startRefine() {
  const response = deferred<{ body: string; method: 'llm' }>();
  services.refine.mockReturnValue(response.promise);
  fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.formal' }));
  await drain(); expect(services.refine).toHaveBeenCalledOnce();
  return response;
}
async function startPeriodicRead() {
  const response = deferred<{ data: { profile_data: ProfileData; revision: number } | null; error: { message: string } | null }>();
  services.read.mockReturnValueOnce(response.promise);
  const reads = services.read.mock.calls.length;
  act(() => { vi.advanceTimersByTime(PROFILE_REFRESH_INTERVAL_MS); }); await drain();
  expect(services.read).toHaveBeenCalledTimes(reads + 1);
  return response;
}

describe('foreground cloud refresh with the real cold-email editor', () => {
  it('accepts an in-flight AI draft while an unchanged periodic read is pending', async () => {
    const ai = deferred<ColdEmailResponse>(); services.stream.mockReturnValue(ai.promise);
    await openEditor(); const footer = screen.getByTestId('cold-email-footer');
    const query = await startPeriodicRead();
    expect(screen.getByTestId('refresh-state')).toHaveTextContent('ready');
    expect(screen.queryByText('Checking for profile updates…')).toBeNull();
    expect(screen.getByTestId('cold-email-footer')).toBe(footer);
    ai.resolve({ ...variant, subject: 'AI subject', body: 'Accepted AI body', method: 'ai', pipeline_version: 'foreground-test' });
    await drain();
    expect(screen.getByDisplayValue('Accepted AI body')).toBeVisible();
    query.resolve(row()); await drain();
    expect(screen.getByDisplayValue('Accepted AI body')).toBeVisible();
    expect(services.stream).toHaveBeenCalledOnce(); expect(services.generate).not.toHaveBeenCalled();
    expect(services.variants).toHaveBeenCalledOnce(); expect(services.rpc).not.toHaveBeenCalled();
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(1);
  });

  it('waits for the initial native receipt verification before asserting the template is ready', async () => {
    const ai = deferred<ColdEmailResponse>(); services.stream.mockReturnValue(ai.promise);
    const verified = deferred<void>(); digestGate = verified.promise;
    render(<Harness />);
    // The full-suite failure occurred inside openEditor, before its first
    // Template body assertion. This reproduces that synchronization gap:
    // queued microtasks drain while the initial native receipt is unfinished.
    await drain(false);
    expect(services.variants).toHaveBeenCalledOnce();
    expect(pendingDigests.size).toBe(1);
    expect(screen.getByTestId('refresh-state')).toHaveTextContent('ready');
    expect(screen.queryByDisplayValue('Template body')).toBeNull();
    expect(services.stream).not.toHaveBeenCalled();
    verified.resolve(); await drain();
    expect(pendingDigests.size).toBe(0);
    expect(screen.getByDisplayValue('Template body')).toBeVisible();
    expect(services.stream).toHaveBeenCalledOnce();
    expect(services.generate).not.toHaveBeenCalled();
  });

  it.each(['changed', 'deleted'] as const)('keeps manual edits and rejects a late refinement when periodic reading discovers profile %s', async (kind) => {
    await openEditor(); editDraft(); const editor = screen.getByDisplayValue('My manual body');
    const refinement = await startRefine(); const query = await startPeriodicRead();
    expect(screen.getByTestId('refresh-state')).toHaveTextContent('ready'); expectManualDraft();
    const changed = { ...BASE, research_interests: 'new cloud research' };
    query.resolve(kind === 'changed' ? row(changed, 2) : { data: null, error: null }); await drain();
    expectManualDraft(); expect(screen.getByDisplayValue('My manual body')).toBe(editor);
    if (kind === 'changed') {
      expect(screen.getByText('coldEmail.profileChanged')).toBeVisible();
      expect(mirror()).toEqual(changed); expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(2);
    } else {
      expect(screen.getByText('Your profile is no longer available. Your draft is kept; generation and outreach are paused.')).toBeVisible();
      expect(mirror()).toBeNull(); expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    }
    refinement.resolve({ body: 'STALE refinement must not replace my draft', method: 'llm' }); await drain();
    expectManualDraft(); expect(screen.queryByDisplayValue('STALE refinement must not replace my draft')).toBeNull();
    expect(services.stream).toHaveBeenCalledOnce(); expect(services.refine).toHaveBeenCalledOnce();
    expect(services.rpc).not.toHaveBeenCalled();
  });

  it('treats a periodic read failure as unknown freshness, retains the profile and manual draft, and rejects late refinement without writing', async () => {
    await openEditor(); editDraft(); const refinement = await startRefine();
    const confirmed = readProfileSyncEnvelope()?.confirmed; const query = await startPeriodicRead();
    query.resolve({ data: null, error: { message: 'Controlled read unavailable' } }); await drain();
    expect(screen.getByTestId('refresh-state')).toHaveTextContent('failed');
    expect(screen.getByText('Could not check for profile updates. Your draft is kept.')).toBeVisible();
    expect(screen.queryByText('Your profile is no longer available. Your draft is kept; generation and outreach are paused.')).toBeNull();
    expectManualDraft(); expect(mirror()).toEqual(BASE);
    expect(readProfileSyncEnvelope()?.confirmed).toEqual(confirmed);
    expect(readProfileSyncEnvelope()?.tombstone).toBeNull();
    refinement.resolve({ body: 'STALE after failed read', method: 'llm' }); await drain();
    expectManualDraft(); expect(screen.queryByDisplayValue('STALE after failed read')).toBeNull();
    expect(services.rpc).not.toHaveBeenCalled();
  });
});
