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
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

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

function renderModal(oppId = 'opp-A') {
  const onClose = vi.fn();
  const utils = render(
    <ColdEmailModal
      isOpen
      onClose={onClose}
      opportunityId={oppId}
      opportunityTitle="REU"
      profile={profile}
    />,
  );
  const show = (open: boolean, id: string) => utils.rerender(
    <ColdEmailModal
      isOpen={open}
      onClose={onClose}
      opportunityId={id}
      opportunityTitle="REU"
      profile={profile}
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
