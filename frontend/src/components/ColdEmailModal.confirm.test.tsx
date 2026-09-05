/**
 * CE0 — Cold Email: the atomic sent-confirmation contract.
 *
 * The frozen product rule is "Copy/Open never counts; only an explicit
 * `I sent it` that PERSISTED enters the Tracker." Every fixture here exists
 * because some way of breaking that rule produces a tracker row (or a
 * confirmed-looking modal) the student never earned:
 *
 *   - a read + conditional upsert + metadata update is three round trips
 *     where the contract needs one, so a concurrent status change can be
 *     interleaved and downgraded;
 *   - painting `sent` before the write resolves shows a contact that may
 *     never have landed;
 *   - a swallowed rejection shows the same thing on a write that provably
 *     did not land;
 *   - an owner move or a target switch mid-flight lets one session's
 *     completion paint another session's UI;
 *   - re-running the contact recorder to save a reminder moves
 *     last_contacted_at, recording an outreach that never happened.
 *
 * The mocked boundary is the atomic helper itself (confirmInteractionContact)
 * — not an internal state the UI could never reach on its own — and the owner
 * capability is the REAL identity-owner primitive, so "the identity moved"
 * means here exactly what it means in the browser.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useLayoutEffect, type ComponentProps } from 'react';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  const stableT = (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    const parts = Object.entries(vars).map(([, v]) => String(v));
    return parts.length > 0 ? `${key}:${parts.join('|')}` : key;
  };
  return {
    useT: () => ({ t: stableT, locale: 'en' as const, setLocale: () => {} }),
  };
});

const mockGetVariants = vi.fn();
vi.mock('@/lib/api', () => ({
  getEmailVariants: (...args: unknown[]) => mockGetVariants(...args),
  generateColdEmail: vi.fn().mockRejectedValue(new Error('no ai in tests')),
  generateColdEmailStream: vi.fn().mockRejectedValue(new Error('no stream in tests')),
  refineEmail: vi.fn(),
  extractResumeBullets: async () => ({ bullets: [], method: 'heuristic' }),
  getVapidPublicKey: async () => 'test-vapid-key',
}));

// The notification offer only appears for a device that could actually
// receive one, so these tests drive the browser's push state directly.
let pushStatus: 'default' | 'subscribed' | 'denied' | 'unsupported' = 'default';
vi.mock('@/lib/push', () => ({
  isPushSupported: () => pushStatus !== 'unsupported',
  getPushStatus: async () => pushStatus,
  subscribeToPush: async () => true,
  unsubscribeFromPush: async () => true,
}));

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({
    open: false,
    phase: 'auto',
    reason: null,
    openModal: vi.fn(),
    closeModal: () => {},
    setPhase: () => {},
  }),
}));

const confirmContactMock = vi.fn();
const trackInteractionMock = vi.fn();
const getInteractionDetailMock = vi.fn();
const updateInteractionDetailsMock = vi.fn();
vi.mock('@/lib/supabase', () => ({
  confirmInteractionContact: (...args: unknown[]) => confirmContactMock(...args),
  trackInteraction: (...args: unknown[]) => trackInteractionMock(...args),
  getInteractionDetail: (...args: unknown[]) => getInteractionDetailMock(...args),
  updateInteractionDetails: (...args: unknown[]) => updateInteractionDetailsMock(...args),
  onAuthChange: () => () => {},
}));

import ColdEmailModal from './ColdEmailModal';
import {
  advanceOwnerEpoch,
  captureOwnerToken,
  syncLocalIdentityOwner,
  type OwnerToken,
} from '@/lib/identity-owner';
import type { ProfileData, EmailVariant } from '@/lib/types';

// ---------------------------------------------------------------------
// Deferred per-call queues. Each call parks its own resolver, so a fixture
// that releases "the second confirmation" cannot accidentally release the
// first — the failure mode a single shared `let resolve` has.
// ---------------------------------------------------------------------
interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (err: unknown) => void;
}

function defer<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  // Nothing here is allowed to become an unhandled rejection just because a
  // fixture asserts the component swallowed it correctly.
  promise.catch(() => {});
  return { promise, resolve, reject };
}

const confirmCalls: Deferred<unknown>[] = [];
const updateCalls: Deferred<void>[] = [];

const APPLIED = { type: 'applied' as const, last_contacted_at: '2026-08-06T12:00:00.000Z' };

async function settle<T>(d: Deferred<T>, run: () => void): Promise<void> {
  await act(async () => {
    run();
    await d.promise.catch(() => {});
  });
}

const resolveConfirm = (i: number, value: unknown = APPLIED) =>
  settle(confirmCalls[i], () => confirmCalls[i].resolve(value));
const rejectConfirm = (i: number, err: unknown = new Error('network down')) =>
  settle(confirmCalls[i], () => confirmCalls[i].reject(err));

const profile: ProfileData = {
  name: 'Alex Chen',
  institution: 'UIUC',
  college: 'Grainger',
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: [],
  coursework: ['CS 225'],
};

function variantFor(oppId: string): EmailVariant {
  return {
    id: `v-${oppId}`,
    label: `Template ${oppId}`,
    subject: `Interested in ${oppId}`,
    body: `Dear Professor,\n\nAbout ${oppId}.\n\nBest,\nAlex`,
    recipient_email: 'prof@illinois.edu',
    mailto_link: 'mailto:prof@illinois.edu',
  };
}

// A fresh uid per call: advanceOwnerEpoch deliberately no-ops on a same-uid
// re-observation, so reusing one string across fixtures would silently share
// an epoch between tests.
let uidSeq = 0;
async function becomeOwner(label: string): Promise<string> {
  const uid = `${label}-${++uidSeq}`;
  advanceOwnerEpoch(uid);
  const ready = await syncLocalIdentityOwner(uid);
  expect(ready, `${uid} owns this browser's private storage`).toBe(true);
  return uid;
}

/** Observable barrier: waits for a condition instead of a fixed sleep. */
function until(predicate: () => boolean, label: string): Promise<void> {
  return waitFor(() => { expect(predicate(), label).toBe(true); });
}

const confirmedUiShown = (): boolean =>
  screen.queryByText('coldEmail.remindPrompt') !== null
  || screen.queryByText(/^coldEmail\.reminderSet/) !== null;

function expectNoConfirmedUi(when: string): void {
  expect(screen.queryByText('coldEmail.remindPrompt'), `no reminder prompt ${when}`).toBeNull();
  expect(screen.queryByText(/^coldEmail\.reminderSet/), `no reminder chip ${when}`).toBeNull();
  expect(screen.queryByText('coldEmail.remind3'), `no reminder options ${when}`).toBeNull();
  // The unanswered question must still be on screen: the session is not done.
  // Asserted on the question, not the button's label — the label legitimately
  // changes to "Recording…"/"Try again" while the answer is still outstanding.
  expect(screen.queryByText('coldEmail.sentQuestion'), `still asking ${when}`).not.toBeNull();
}

/** The confirm control, whatever its label currently says. */
const confirmButton = () => screen.getByTestId('cold-email-confirm-sent');

beforeEach(() => {
  pushStatus = 'default';
  confirmCalls.length = 0;
  updateCalls.length = 0;
  confirmContactMock.mockReset().mockImplementation(() => {
    const d = defer<unknown>();
    confirmCalls.push(d);
    return d.promise;
  });
  updateInteractionDetailsMock.mockReset().mockImplementation(() => {
    const d = defer<void>();
    updateCalls.push(d);
    return d.promise;
  });
  trackInteractionMock.mockReset().mockResolvedValue(undefined);
  getInteractionDetailMock.mockReset().mockResolvedValue(null);
  mockGetVariants.mockReset().mockImplementation(async (_p: unknown, oppId: string) => ({
    variants: [variantFor(oppId)],
  }));
  Element.prototype.scrollIntoView = vi.fn();
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
    writable: true,
  });
  vi.stubGlobal('open', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// This whole file is the confirm-flow harness, and it reads the reminder
// prompt as its "confirmed" signal — so its target has to be one the
// reminders cron would actually send for. Supplied here and nowhere else:
// a ColdEmail test that does not care about reminders omits the prop and
// correctly gets no follow-up controls at all.
// NonNullable, so the builder returns a value that can be spread and mutated
// without casts; call sites that need "no provable target" pass undefined
// explicitly through the `| undefined` parameter types below.
type ReminderTarget = NonNullable<ComponentProps<typeof ColdEmailModal>['reminderTarget']>;

function liveListingTarget(id = 'opp-A'): ReminderTarget {
  return {
    id,
    source_type: 'campus_program',
    record_kind: 'listing',
    target_truth: {
      listing_state: 'open', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    },
  };
}

function renderModal(
  oppId = 'opp-A',
  target: ReminderTarget | undefined = liveListingTarget(oppId),
  onContactConfirmed?: (record: unknown) => void,
  onReminderSet?: (date: string) => void,
) {
  const onClose = vi.fn();
  const utils = render(
    <ColdEmailModal
      isOpen
      onClose={onClose}
      opportunityId={oppId}
      opportunityTitle="REU"
      profile={profile}
      reminderTarget={target}
      onContactConfirmed={onContactConfirmed}
      onReminderSet={onReminderSet}
    />,
  );
  const show = (open: boolean, id: string, next: ReminderTarget | undefined = liveListingTarget(id)) =>
    utils.rerender(
      <ColdEmailModal
        isOpen={open}
        onClose={onClose}
        opportunityId={id}
        opportunityTitle="REU"
        profile={profile}
        reminderTarget={next}
      />,
    );
  return { ...utils, onClose, show };
}

async function openedOn(oppId: string): Promise<void> {
  await screen.findByDisplayValue(`Interested in ${oppId}`);
}

/** Copy the draft so the confirm strip is on screen, then click "I sent it". */
async function reachConfirmStrip(): Promise<void> {
  fireEvent.click(screen.getByText('coldEmail.copy'));
  await screen.findByText('coldEmail.sentQuestion');
}

// =====================================================================
describe('CE0-1 — copying or opening a draft is not a contact', () => {
  it.each([
    ['coldEmail.copy'],
    ['coldEmail.openInEmail'],
    ['coldEmail.gmail'],
    ['coldEmail.outlook'],
  ])('%s writes nothing to the tracker', async (label) => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');

    fireEvent.click(screen.getByText(label));

    // The strip may appear — that is an invitation to attest, not a record.
    expect(await screen.findByText('coldEmail.sentQuestion')).toBeInTheDocument();
    expect(confirmContactMock, 'atomic confirm').not.toHaveBeenCalled();
    expect(trackInteractionMock, 'legacy status write').not.toHaveBeenCalled();
    expect(updateInteractionDetailsMock, 'reminder/metadata write').not.toHaveBeenCalled();
    expectNoConfirmedUi('after a non-contact action');
  });

  it('a clipboard that refuses reports the failure and claims nothing', async () => {
    // Found by running this flow in a real browser: `writeText` rejects on a
    // denied permission, an unfocused document or an insecure context, and the
    // handler used to abort on that rejection — no "Copied", no strip, and an
    // unhandled promise rejection. A copy that did not happen must not read as
    // one, and must not open an attestation for a draft nobody holds.
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('NotAllowedError')) },
      configurable: true,
      writable: true,
    });
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');

    fireEvent.click(screen.getByText('coldEmail.copy'));

    expect(await screen.findByText('coldEmail.copyFailed')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.copied'), 'nothing was copied').toBeNull();
    expect(screen.queryByText('coldEmail.sentQuestion'), 'no draft in hand to attest to').toBeNull();
    expect(confirmContactMock).not.toHaveBeenCalled();
  });
});

// =====================================================================
describe('CE0-2 — the confirmation is one atomic call, and the UI follows it', () => {
  it('holds the confirmed UI until the atomic call resolves', async () => {
    await becomeOwner('u1');
    const expected: OwnerToken = captureOwnerToken();
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'exactly one atomic call started');

    expect(confirmContactMock).toHaveBeenCalledTimes(1);
    expect(confirmContactMock.mock.calls[0][0], 'the opportunity being confirmed').toBe('opp-A');
    expect(confirmContactMock.mock.calls[0][1], 'the click-time owner capability').toEqual(expected);
    // The old two-step path must be gone entirely, not merely also-called.
    expect(getInteractionDetailMock, 'no TOCTOU read').not.toHaveBeenCalled();
    expect(trackInteractionMock, 'no separate status write').not.toHaveBeenCalled();
    expect(updateInteractionDetailsMock, 'no separate metadata write').not.toHaveBeenCalled();

    expectNoConfirmedUi('while the write is still in flight');

    await resolveConfirm(0);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
  });

  it('a rapid double click still produces exactly one atomic call', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    const button = confirmButton();
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    await until(() => confirmCalls.length >= 1, 'a confirmation started');

    expect(confirmContactMock, 'one attestation, one write').toHaveBeenCalledTimes(1);
    await resolveConfirm(0);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
    expect(confirmContactMock).toHaveBeenCalledTimes(1);
  });
});

// =====================================================================
describe('CE0-3 — a failed confirmation is visible, retryable and unconfirmed', () => {
  it('shows the failure, leaves the session unconfirmed, and lets a retry start exactly one new call', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'first attempt started');
    await rejectConfirm(0);

    expect(await screen.findByText('coldEmail.confirmFailed')).toBeInTheDocument();
    expectNoConfirmedUi('after a rejected write');

    // The latch must have been released — a stuck one strands the student on
    // a failure they can see but never clear.
    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 2, 'retry started exactly one new call');
    expect(confirmContactMock).toHaveBeenCalledTimes(2);

    await resolveConfirm(1);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.confirmFailed'), 'error cleared by the successful retry').toBeNull();
  });

  it('repeats cleanly — three consecutive failures each surface and each stay unconfirmed', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    for (let attempt = 0; attempt < 3; attempt += 1) {
      fireEvent.click(confirmButton());
      await until(() => confirmCalls.length === attempt + 1, `attempt ${attempt + 1} started`);
      await rejectConfirm(attempt);
      expect(await screen.findByText('coldEmail.confirmFailed')).toBeInTheDocument();
      expectNoConfirmedUi(`after failure ${attempt + 1}`);
    }
    expect(confirmContactMock).toHaveBeenCalledTimes(3);
  });
});

// =====================================================================
describe('CE0-5 — the host page is told what was recorded', () => {
  it('hands the confirmed row to the caller', async () => {
    // Without this the detail page keeps showing "Pick a status above first"
    // and a disabled notes box for a contact it just recorded: its interaction
    // read re-runs only on mount or a real identity change, and closing the
    // modal triggers neither.
    await becomeOwner('u1');
    const onConfirmed = vi.fn();
    renderModal('opp-A', liveListingTarget('opp-A'), onConfirmed);
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'confirmation started');
    await resolveConfirm(0);

    await screen.findByText('coldEmail.remindPrompt');
    expect(onConfirmed).toHaveBeenCalledTimes(1);
    // The row the RPC returned, verbatim — the caller decides what to do with
    // it, and a status the server resolved to something other than 'contacted'
    // (an existing 'applied' row it left alone) must reach the page as-is.
    expect(onConfirmed).toHaveBeenCalledWith(APPLIED);
  });

  it('tells nobody when the confirmation resolved for an owner who has moved on', async () => {
    await becomeOwner('u1');
    const onConfirmed = vi.fn();
    renderModal('opp-A', liveListingTarget('opp-A'), onConfirmed);
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'U1 confirmation started');
    await becomeOwner('u2');
    await resolveConfirm(0);

    expect(onConfirmed).not.toHaveBeenCalled();
  });
});

describe('CE0-6 — a send onto a terminal status says what the row kept', () => {
  it('names the status a dismissed row kept, and that it stays off the tracker', async () => {
    // confirm_interaction_contact deliberately never downgrades a status, so a
    // row the student had marked "Not interested" comes back unchanged. The
    // tracker omits 'dismissed' from every column, so the outreach lands
    // nowhere the student can see and the strip said only that a reminder was
    // unavailable — no error, no explanation, and a real send believed to be
    // on their board.
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'confirmation started');
    await resolveConfirm(0, { type: 'dismissed', last_contacted_at: '2026-09-03T12:00:00.000Z' });

    expect(await screen.findByText('coldEmail.confirmedKeptDismissed')).toBeInTheDocument();
  });

  it('names the status a rejected row kept', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'confirmation started');
    await resolveConfirm(0, { type: 'rejected', last_contacted_at: '2026-09-03T12:00:00.000Z' });

    expect(await screen.findByText('coldEmail.confirmedKeptStatus')).toBeInTheDocument();
  });
});

describe('CE0-4 — an owner move invalidates the confirmation in flight', () => {
  it('control: no move, so the U1 confirmation paints normally', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'confirmation started');
    await resolveConfirm(0);

    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
  });

  it('a success released after the owner moved to U2 paints nothing', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'U1 confirmation started');

    // Owner-only movement: the global owner really changes and U2's realm is
    // really ready, but no auth callback is delivered to any component — the
    // modal has no such subscription, which is exactly why a component-level
    // generation counter cannot be the thing that saves us here.
    await act(async () => { await becomeOwner('u2'); });

    await resolveConfirm(0);

    expectNoConfirmedUi("after U1's success landed under U2");
    expect(confirmContactMock, 'no write attributed to U2').toHaveBeenCalledTimes(1);
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
    // Not silence: the click is answered, but with the one thing that is true
    // for whoever is signed in NOW — nothing was marked for them. U1's outcome
    // itself is never shown.
    expect(await screen.findByText('coldEmail.confirmOwnerChanged')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.confirmFailed'), "not U1's failure").toBeNull();
    expect(confirmButton(), 'the current account can still attest for itself')
      .toHaveTextContent('coldEmail.confirmSent');
  });

  it('a failure released after the owner moved to U2 paints nothing either', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'U1 confirmation started');
    await act(async () => { await becomeOwner('u2'); });
    await rejectConfirm(0);

    expect(screen.queryByText('coldEmail.confirmFailed'), "U1's failure is not U2's error").toBeNull();
    expectNoConfirmedUi("after U1's failure landed under U2");
    expect(await screen.findByText('coldEmail.confirmOwnerChanged')).toBeInTheDocument();
  });

  it('same uid, new epoch (sign out and back in) is a different capability', async () => {
    const uid = await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'confirmation started');

    await act(async () => {
      advanceOwnerEpoch(null);          // sign out
      advanceOwnerEpoch(uid);           // the same person signs back in
      await syncLocalIdentityOwner(uid);
    });

    await resolveConfirm(0);
    expectNoConfirmedUi('after a sign-out/sign-in cycle under the same uid');
  });
});

// =====================================================================
describe('CE0-5 — a target switch supersedes the confirmation in flight', () => {
  it('switching the mounted modal from A to B leaves B unconfirmed when A resolves', async () => {
    await becomeOwner('u1');
    const { show } = renderModal('opp-A');
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, "A's confirmation started");
    expect(confirmContactMock.mock.calls[0][0]).toBe('opp-A');

    await act(async () => { show(true, 'opp-B'); });
    await openedOn('opp-B');

    await resolveConfirm(0);

    expect(screen.queryByText('coldEmail.sentQuestion'), 'B starts from a clean strip').toBeNull();
    expect(confirmedUiShown(), "A's success did not confirm B").toBe(false);
    expect(screen.queryByText('coldEmail.confirmFailed')).toBeNull();

    // And B confirms normally on its own.
    await reachConfirmStrip();
    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 2, "B's own confirmation started");
    expect(confirmContactMock.mock.calls[1][0]).toBe('opp-B');
    await resolveConfirm(1);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
  });

  it('closing and reopening on B leaves B unconfirmed when A resolves', async () => {
    await becomeOwner('u1');
    const { show } = renderModal('opp-A');
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, "A's confirmation started");

    await act(async () => { show(false, 'opp-A'); });
    await act(async () => { show(true, 'opp-B'); });
    await openedOn('opp-B');

    await resolveConfirm(0);

    expect(screen.queryByText('coldEmail.sentQuestion')).toBeNull();
    expect(confirmedUiShown(), "A's success did not confirm B").toBe(false);
  });
});

// =====================================================================
describe('CE0-6 — a reminder is not a second contact', () => {
  it('choosing and changing a follow-up date never re-runs the contact recorder', async () => {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'confirmation started');
    await resolveConfirm(0);
    await screen.findByText('coldEmail.remindPrompt');

    fireEvent.click(screen.getByText('coldEmail.remind3'));
    await until(() => updateCalls.length === 1, 'the reminder write started');
    await settle(updateCalls[0], () => updateCalls[0].resolve());
    expect(await screen.findByText(/^coldEmail\.reminderSet/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('coldEmail.remind14'));
    await until(() => updateCalls.length === 2, 'the changed reminder write started');
    await settle(updateCalls[1], () => updateCalls[1].resolve());

    expect(confirmContactMock, 'the contact was attested once and recorded once').toHaveBeenCalledTimes(1);
    for (const call of updateInteractionDetailsMock.mock.calls) {
      expect(Object.keys(call[1]), 'the reminder path writes remind_at and nothing else').toEqual(['remind_at']);
      expect(call[1].last_contacted_at, 'a reminder never restamps the contact time').toBeUndefined();
    }
    expect(trackInteractionMock, 'a reminder never rewrites the status').not.toHaveBeenCalled();
  });
});

// =====================================================================
describe('CE0-7 — closing or switching resets every session-specific state', () => {
  it('a confirmed, reminded, then failed session on A leaves nothing behind on B', async () => {
    await becomeOwner('u1');
    const { show } = renderModal('opp-A');
    await openedOn('opp-A');
    await reachConfirmStrip();

    // Confirmed…
    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'A confirmation started');
    await resolveConfirm(0);
    await screen.findByText('coldEmail.remindPrompt');

    // …reminded…
    fireEvent.click(screen.getByText('coldEmail.remind7'));
    await until(() => updateCalls.length === 1, 'A reminder started');
    await settle(updateCalls[0], () => updateCalls[0].resolve());
    await screen.findByText(/^coldEmail\.reminderSet/);

    await act(async () => { show(false, 'opp-A'); });
    await act(async () => { show(true, 'opp-B'); });
    await openedOn('opp-B');

    expect(screen.queryByText('coldEmail.sentQuestion'), 'contacted reset').toBeNull();
    expect(screen.queryByText('coldEmail.remindPrompt'), 'sendConfirmed reset').toBeNull();
    expect(screen.queryByText(/^coldEmail\.reminderSet/), 'followUpDate reset').toBeNull();
    expect(screen.queryByText('coldEmail.confirmFailed'), 'error reset').toBeNull();

    // Absence while `contacted` is false proves only that the strip is hidden.
    // Re-open it on B and look inside: a state that survived the switch would
    // paint the moment the student copies B's draft, telling them they have
    // already contacted an opportunity they have never written to.
    await reachConfirmStrip();
    expectNoConfirmedUi('inside B\'s freshly opened strip');
    expect(confirmButton(), 'B offers a first confirmation, not a retry')
      .toHaveTextContent('coldEmail.confirmSent');

    // followUpDate is only ever READ in the confirmed branch, so a stale one
    // stays invisible until B is confirmed — and then presents A's date as
    // B's reminder. Confirm B and look.
    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 2, "B's confirmation started");
    await resolveConfirm(1);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
    expect(screen.queryByText(/^coldEmail\.reminderSet/), "A's reminder date is not B's")
      .toBeNull();
  });

  it('an error raised on A does not survive into B', async () => {
    await becomeOwner('u1');
    const { show } = renderModal('opp-A');
    await openedOn('opp-A');
    await reachConfirmStrip();

    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'A confirmation started');
    await rejectConfirm(0);
    await screen.findByText('coldEmail.confirmFailed');

    await act(async () => { show(false, 'opp-A'); });
    await act(async () => { show(true, 'opp-B'); });
    await openedOn('opp-B');

    expect(screen.queryByText('coldEmail.confirmFailed'), "A's error is not B's").toBeNull();
    expect(screen.queryByText('coldEmail.sentQuestion')).toBeNull();

    await reachConfirmStrip();
    expect(screen.queryByText('coldEmail.confirmFailed'), "A's error is not B's, strip open").toBeNull();
    expect(confirmButton(), 'B is asked the question, not offered a retry')
      .toHaveTextContent('coldEmail.confirmSent');
  });
});

describe('ColdEmailModal — evidence honesty (grounding)', () => {
  /** The backend answers one `grounding` value per opportunity. When it says
   *  the record carries NO research signal, the modal must say the draft is a
   *  general inquiry — not let it pass as tailored homework. */
  it('shows the no-target-data notice when the backend says so', async () => {
    mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
      variants: [variantFor(oppId)],
      grounding: 'no_target_data',
    }));
    renderModal();
    await openedOn('opp-A');
    expect(screen.getByTestId('grounding-notice')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.noTargetDataTitle')).toBeInTheDocument();
  });

  it('shows nothing for a specific record, and for older responses without the field', async () => {
    mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
      variants: [variantFor(oppId)],
      grounding: 'specific',
    }));
    const { show } = renderModal();
    await openedOn('opp-A');
    expect(screen.queryByTestId('grounding-notice')).toBeNull();

    // Absent field (an older cached response): same silence.
    mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
      variants: [variantFor(oppId)],
    }));
    await act(async () => { show(false, 'opp-A'); });
    await act(async () => { show(true, 'opp-B'); });
    await openedOn('opp-B');
    expect(screen.queryByTestId('grounding-notice')).toBeNull();
  });
});

describe('ColdEmailModal — source freshness', () => {
  /** The backend has always computed `source_freshness` ("the UI must not
   *  present the draft as current outreach") and nothing read it, so a draft
   *  to a professor whose record was retired looked exactly like a draft to a
   *  currently-listed one. 311 faculty records in the corpus are inactive and
   *  still carry a contact_email. */
  it('warns when the source record was retired', async () => {
    mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
      variants: [variantFor(oppId)],
      source_freshness: 'inactive',
    }));
    renderModal();
    await openedOn('opp-A');
    expect(screen.getByTestId('freshness-notice')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.sourceInactiveTitle')).toBeInTheDocument();
  });

  it('nudges re-verification when the record is past the TTL', async () => {
    mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
      variants: [variantFor(oppId)],
      source_freshness: 'stale',
    }));
    renderModal();
    await openedOn('opp-A');
    expect(screen.getByTestId('freshness-notice')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.sourceStaleTitle')).toBeInTheDocument();
  });

  it('stays silent for a fresh record, an unknown one, and older responses', async () => {
    for (const value of ['fresh', 'unknown', undefined]) {
      mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
        variants: [variantFor(oppId)],
        ...(value === undefined ? {} : { source_freshness: value }),
      }));
      const { show } = renderModal();
      await openedOn('opp-A');
      expect(
        screen.queryByTestId('freshness-notice'),
        `source_freshness=${String(value)} must not warn`,
      ).toBeNull();
      await act(async () => { show(false, 'opp-A'); });
      cleanup();
    }
  });

  it('does not carry one opportunity’s warning onto the next', async () => {
    mockGetVariants.mockImplementation(async (_p: unknown, oppId: string) => ({
      variants: [variantFor(oppId)],
      source_freshness: oppId === 'opp-A' ? 'inactive' : 'fresh',
    }));
    const { show } = renderModal();
    await openedOn('opp-A');
    expect(screen.getByTestId('freshness-notice')).toBeInTheDocument();

    await act(async () => { show(false, 'opp-A'); });
    await act(async () => { show(true, 'opp-B'); });
    await openedOn('opp-B');
    expect(
      screen.queryByTestId('freshness-notice'),
      'a retired A must not make a live B look retired',
    ).toBeNull();
  });
});

describe('ColdEmailModal — a follow-up reminder is only offered where one would be delivered', () => {
  const LIVE_LISTING_TARGET = liveListingTarget();
  const LIVE_FACULTY_TARGET: ReminderTarget = {
    id: 'opp-A',
    source_type: 'faculty_research',
    record_kind: 'faculty_contact',
    target_truth: {
      listing_state: 'unknown', reference_only: false, actionable: true,
      accepting_state: 'unknown', reason_code: null,
      verified_at: null, expires_at: null,
    },
  };
  const CLOSED_TARGET: ReminderTarget = {
    ...liveListingTarget(),
    target_truth: {
      listing_state: 'closed', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    },
  };

  function renderWith(target: ReminderTarget | undefined) {
    return render(
      <ColdEmailModal
        isOpen
        onClose={vi.fn()}
        opportunityId="opp-A"
        opportunityTitle="REU"
        profile={profile}
        reminderTarget={target}
      />,
    );
  }

  async function confirmWith(target: ReminderTarget | undefined, status: string) {
    renderWith(target);
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(0, { type: status, last_contacted_at: '2026-08-06T12:00:00.000Z' });
  }

  // The migration creates 'contacted'; the RPC is an upsert that PRESERVES
  // whatever status the row already had, so all three of these can come back
  // from a perfectly real send.
  it.each(['contacted', 'applied', 'replied', 'interviewing'])(
    'a %s row on a live listing gets the prompt, and a chip writes the reminder',
    async (status) => {
      await confirmWith(LIVE_LISTING_TARGET, status);

      expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
      expect(screen.queryByText('coldEmail.reminderUnavailable')).toBeNull();

      fireEvent.click(screen.getByText('coldEmail.remind7'));
      await settle(updateCalls[0], () => updateCalls[0].resolve());
      expect(updateInteractionDetailsMock).toHaveBeenCalledTimes(1);
      expect(updateInteractionDetailsMock.mock.calls[0][1])
        .toEqual({ remind_at: expect.any(String) });
    },
  );

  it('a live faculty contact gets it too — that is what most reminders are set on', async () => {
    await confirmWith(LIVE_FACULTY_TARGET, 'contacted');
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
  });

  it.each([
    // A row the confirm RPC left on a terminal status says which one it kept —
    // "a reminder is unavailable" was true but told the student nothing about
    // where their outreach went, and for 'dismissed' the answer is nowhere.
    ['a rejected row', LIVE_LISTING_TARGET, 'rejected', 'coldEmail.confirmedKeptStatus'],
    ['a dismissed row', LIVE_LISTING_TARGET, 'dismissed', 'coldEmail.confirmedKeptDismissed'],
    ['a closed target', CLOSED_TARGET, 'contacted', 'coldEmail.reminderUnavailable'],
    ['no provable target', undefined, 'contacted', 'coldEmail.reminderUnavailable'],
  ])('%s gets no reminder UI at all and writes nothing', async (_label, target, status, message) => {
    await confirmWith(target, status);

    // The whole block, not just the chips: offering "want a reminder?" and
    // then having nothing to offer is the same false capability, earlier.
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.remindPrompt')).toBeNull();
    expect(screen.queryByText(/^coldEmail\.reminderSet/)).toBeNull();
    expect(screen.queryByText('coldEmail.remind3')).toBeNull();
    expect(screen.queryByText('coldEmail.remind7')).toBeNull();
    expect(screen.queryByText('coldEmail.remind14')).toBeNull();
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
  });

  it('a live target for a DIFFERENT id proves nothing about this one', async () => {
    // A results list mid-swap, or a favorites modal whose id moved on, hands
    // over a perfectly live record that describes something else entirely.
    renderWith(liveListingTarget('opp-OTHER'));
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(0);

    expect(await screen.findByText('coldEmail.reminderUnavailable')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.remindPrompt')).toBeNull();
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
  });

  it('the write refuses even when the rendered chip is stale — the sink is not the DOM', async () => {
    // The tripwire for the handler gate specifically. One mutable target
    // object: confirm while it is live, keep the rendered chip, then mutate
    // that same object to closed WITHOUT a rerender. React never repaints,
    // so the chip is still on screen and still clickable — exactly the state
    // a DOM-only gate cannot see. Deleting the check inside setFollowUp
    // leaves every other assertion in this file green.
    const target = liveListingTarget();
    renderWith(target);
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(0);
    const chip = await screen.findByText('coldEmail.remind7');

    target.target_truth = {
      listing_state: 'closed', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    };

    fireEvent.click(chip);

    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
    expect(screen.queryByText(/^coldEmail\.reminderSet/)).toBeNull();
  });

  it('the write refuses a stale chip whose target IDENTITY moved, not just its truth', async () => {
    // The parallel tripwire. The mismatched-id case above only exercises the
    // render gate; with the DOM gate intact, deleting the id check inside
    // setFollowUp would survive it. Mutating the same object's id without a
    // rerender leaves a chip on screen that was drawn for opp-A while the
    // record now describes something else.
    const target = liveListingTarget();
    renderWith(target);
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(0);
    const chip = await screen.findByText('coldEmail.remind7');

    target.id = 'opp-OTHER';
    fireEvent.click(chip);

    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
    expect(screen.queryByText(/^coldEmail\.reminderSet/)).toBeNull();
  });

  it('A confirmed, then rerendered onto live B: B shows nothing of A and writes nothing', async () => {
    // WHAT THIS PROVES, precisely: after a target switch, B carries none of
    // A's session and no reminder is written for it.
    //
    // WHAT IT DOES NOT PROVE: that the id stamps (`contactedForId` /
    // `confirmedForId`) are what achieve it. Removing both leaves this test
    // green, and so does the commit probe below. Under act() — which RTL
    // wraps `rerender` in — React flushes the previous commit's passive
    // cleanup BEFORE the next render begins, so the one-commit window the
    // stamps exist to close cannot be reached from here at all. The probe is
    // kept because it is the strongest observation available (a layout effect
    // sees each commit before that commit's passive effects), and it
    // documents the limit rather than hiding it.
    //
    // The stamps stay: they make the state unusable by construction instead
    // of by scheduling, which is the right shape whether or not a test in
    // this harness can see the difference. Their evidence level is
    // "reasoned, not test-killed" — recorded as such in the ledger.
    const commits: string[] = [];
    function CommitProbe() {
      useLayoutEffect(() => { commits.push(document.body.textContent ?? ''); });
      return null;
    }

    const onClose = vi.fn();
    const view = render(
      <>
        <ColdEmailModal
          isOpen onClose={onClose} opportunityId="opp-A" opportunityTitle="REU"
          profile={profile} reminderTarget={liveListingTarget('opp-A')}
        />
        <CommitProbe />
      </>,
    );
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(0);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();

    commits.length = 0;
    view.rerender(
      <>
        <ColdEmailModal
          isOpen onClose={onClose} opportunityId="opp-B" opportunityTitle="REU"
          profile={profile} reminderTarget={liveListingTarget('opp-B')}
        />
        <CommitProbe />
      </>,
    );

    // The very first commit after the id changed — before any cleanup ran.
    expect(commits.length).toBeGreaterThan(0);
    expect(commits[0]).not.toContain('coldEmail.remindPrompt');
    expect(commits[0]).not.toContain('coldEmail.reminderUnavailable');
    expect(commits[0]).not.toContain('coldEmail.remind7');
    expect(commits[0]).not.toContain('coldEmail.sentQuestion');
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();

    // And B still earns its own strip and its own confirmation afterwards.
    await openedOn('opp-B');
    await reachConfirmStrip();
    expect(screen.getByText('coldEmail.sentQuestion')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(1);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();
    expect(confirmCalls).toHaveLength(2);
  });

  it('a confirmed status never carries across a target change', async () => {
    // The confirmed status is per-target state. Left behind, A's 'contacted'
    // would decide whether B may take a reminder before B has been confirmed
    // at all.
    const onClose = vi.fn();
    const utils = render(
      <ColdEmailModal
        isOpen onClose={onClose} opportunityId="opp-A" opportunityTitle="REU"
        profile={profile} reminderTarget={LIVE_LISTING_TARGET}
      />,
    );
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(screen.getByTestId('cold-email-confirm-sent'));
    await resolveConfirm(0);
    expect(await screen.findByText('coldEmail.remindPrompt')).toBeInTheDocument();

    utils.rerender(
      <ColdEmailModal
        isOpen onClose={onClose} opportunityId="opp-B" opportunityTitle="REU"
        profile={profile}
        reminderTarget={liveListingTarget('opp-B')}
      />,
    );
    await openedOn('opp-B');

    // B is unconfirmed, so there is no reminder surface of any kind yet.
    expect(screen.queryByText('coldEmail.remindPrompt')).toBeNull();
    expect(screen.queryByText('coldEmail.remind7')).toBeNull();
    expect(updateInteractionDetailsMock).not.toHaveBeenCalled();
  });
});

describe('a follow-up reminder the page can see', () => {
  it('tells the parent the same date it wrote', async () => {
    // The chips write remind_at straight to the row and the modal told nobody.
    // The tracker panel on the same page seeds its date field from
    // interactionDetail.remind_at, so it rendered empty for a reminder just
    // set — and the status-change suggestion, which fires only when remind_at
    // is unset, then offered to set one and overwrote it on a single click.
    const seen: string[] = [];
    await becomeOwner('u1');
    renderModal('opp-A', liveListingTarget('opp-A'), undefined, (d) => seen.push(d));
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'the confirm started');
    await resolveConfirm(0);
    await screen.findByText('coldEmail.remindPrompt');

    fireEvent.click(screen.getByText('coldEmail.remind3'));
    await until(() => updateCalls.length === 1, 'the reminder write started');
    await settle(updateCalls[0], () => updateCalls[0].resolve());
    await until(() => seen.length === 1, 'the parent was told');

    const written = updateInteractionDetailsMock.mock.calls.at(-1)?.[1] as { remind_at: string };
    expect(seen[0]).toBe(written.remind_at);

    // Three days on the student's own calendar. Counting in UTC put it on the
    // fourth for anyone west of Greenwich after their evening rolled over —
    // the same arithmetic the tracker's presets had.
    const expected = new Date();
    expected.setDate(expected.getDate() + 3);
    const pad = (n: number) => String(n).padStart(2, '0');
    expect(written.remind_at).toBe(
      `${expected.getFullYear()}-${pad(expected.getMonth() + 1)}-${pad(expected.getDate())}`,
    );
  });
});


describe('offering notifications once a reminder exists', () => {
  // The reminders cron has a third filter the controls never checked: a
  // channel to reach this student. push.py counts no_channel when the device
  // has no push_subscriptions row and _account_email returns None, which is
  // always true for an anonymous one. The reminder still works in the app —
  // it renders on the Tracker card and flips to "Follow-up due" — but nothing
  // arrived outside it, and nothing offered to change that.
  async function reachReminderStrip() {
    await becomeOwner('u1');
    renderModal();
    await openedOn('opp-A');
    await reachConfirmStrip();
    fireEvent.click(confirmButton());
    await until(() => confirmCalls.length === 1, 'the confirm started');
    await resolveConfirm(0);
    await screen.findByText('coldEmail.remindPrompt');
  }

  it('says nothing until a reminder actually exists', async () => {
    await reachReminderStrip();
    expect(screen.queryByText('coldEmail.reminderEnablePush')).toBeNull();
  });

  it('offers notifications after one is set, when the device could receive them', async () => {
    await reachReminderStrip();

    fireEvent.click(screen.getByText('coldEmail.remind3'));
    await until(() => updateCalls.length === 1, 'the reminder write started');
    await settle(updateCalls[0], () => updateCalls[0].resolve());

    expect(await screen.findByText('coldEmail.reminderEnablePush')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.reminderInAppOnly')).toBeInTheDocument();
  });

  it('stays quiet when the device is already subscribed', async () => {
    pushStatus = 'subscribed';
    await reachReminderStrip();

    fireEvent.click(screen.getByText('coldEmail.remind3'));
    await until(() => updateCalls.length === 1, 'the reminder write started');
    await settle(updateCalls[0], () => updateCalls[0].resolve());
    await screen.findByText(/^coldEmail\.reminderSet/);

    expect(screen.queryByText('coldEmail.reminderEnablePush')).toBeNull();
  });
});
