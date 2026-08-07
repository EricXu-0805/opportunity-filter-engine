/*
 * The Results write path: what this page RENDERS and what a click WRITES
 * AGAINST come out of one accepted snapshot, and a flip only counts once it
 * actually took effect.
 *
 * The real coordinator runs here — only the service layer is faked — so these
 * are about the coordinator's own answers (conflict, stale view) rather than a
 * mock of the decision under test.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';

let serverRow: Record<string, unknown> | null = null;
let serverRevision = 0;
/** Set to hold the next commit open, so an in-flight attempt can be observed. */
let deferred: { resolve: (v: unknown) => void } | null = null;
let nextOutcome: 'saved' | 'conflict' | 'transport' = 'saved';
const commitMock = vi.fn(async (intent: { patch: Record<string, unknown> }) => {
  if (deferred) {
    const gate = deferred;
    deferred = null;
    await new Promise((r) => { gate.resolve = r; });
  }
  if (nextOutcome === 'conflict') {
    return { status: 'conflict' as const, revision: serverRevision, profile: serverRow ?? {} };
  }
  if (nextOutcome === 'transport') {
    return { status: 'transport-error' as const, message: 'offline' };
  }
  serverRow = { ...(serverRow ?? {}), ...intent.patch };
  serverRevision += 1;
  return { status: 'saved' as const, revision: serverRevision, profile: serverRow };
});

vi.mock('@/lib/supabase', () => ({
  loadProfile: async () => (serverRow
    ? { source: 'cloud' as const, profile: serverRow, revision: serverRevision, token: captureOwnerToken() }
    : { source: 'cloud-absent' as const, profile: null, revision: 0, token: captureOwnerToken() }),
  commitProfilePatch: (intent: { patch: Record<string, unknown> }) => commitMock(intent),
}));

import {
  advanceOwnerEpoch,
  captureOwnerToken,
  syncLocalIdentityOwner,
  writeUserScopedRaw,
} from '@/lib/identity-owner';
import { hydrateProfile, resetProfileDirtyLedger } from '@/lib/profile-sync';

/** Seed a PRIVATE key the way the app writes one. A raw `localStorage.setItem`
 *  targets an unprefixed name that belongs to whoever first claimed this
 *  browser — after an identity switch the live owner reads somewhere else
 *  entirely, and the seed is invisible. */
function seedPrivate(key: string, value: string): void {
  expect(writeUserScopedRaw(key, value, captureOwnerToken())).toBe(true);
}
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useAcceptedProfileView, useCrossSchoolToggle } from './use-results-profile-view';

/** A harness that exposes exactly what the page wires up. */
function Harness({ onApplied }: { onApplied: () => void }) {
  const { accepted, accept, clear } = useAcceptedProfileView();
  const toggle = useCrossSchoolToggle(accepted.view, onApplied);
  return (
    <div>
      <span data-testid="cross">{String(accepted.profile?.include_cross_school ?? 'none')}</span>
      <span data-testid="rev">{accepted.view ? accepted.view.revision : 'none'}</span>
      <span data-testid="uid">{accepted.view ? String(accepted.view.token.uid) : 'none'}</span>
      <span data-testid="busy">{String(toggle.busy)}</span>
      <span data-testid="failed">{String(toggle.failed)}</span>
      <button data-testid="accept" onClick={accept}>accept</button>
      <button data-testid="clear" onClick={() => { clear(); toggle.clear(); }}>clear</button>
      <button data-testid="on" onClick={() => toggle.toggle(true)}>on</button>
      <button data-testid="retry" onClick={toggle.retry}>retry</button>
    </div>
  );
}

beforeEach(async () => {
  let chain: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: (_n: string, _o: unknown, fn: () => Promise<unknown>) => {
        const run = chain.then(() => fn());
        chain = run.then(() => undefined, () => undefined);
        return run;
      },
    },
  });
  localStorage.clear();
  serverRow = { major: 'CS', include_cross_school: false };
  serverRevision = 4;
  deferred = null;
  nextOutcome = 'saved';
  commitMock.mockClear();
  resetProfileDirtyLedger();
  advanceOwnerEpoch('results-view-u1');
  await syncLocalIdentityOwner('results-view-u1');
});

async function seedAccepted() {
  await act(async () => { await hydrateProfile(); });
}

describe('the accepted tuple', () => {
  it('publishes the rendered document and the snapshot behind it from ONE read', async () => {
    await seedAccepted();
    const onApplied = vi.fn();
    render(<Harness onApplied={onApplied} />);
    act(() => { screen.getByTestId('accept').click(); });

    // Both halves describe the SAME row: the value on screen and the revision
    // a write from it would claim cannot have come from two different moments.
    expect(screen.getByTestId('cross').textContent).toBe('false');
    expect(screen.getByTestId('rev').textContent).toBe('4');

    // Another tab's write lands. Until this page accepts it, NEITHER half
    // moves — a document that changed under a revision that did not (or the
    // reverse) is exactly the disguise a paired snapshot exists to prevent.
    serverRow = { major: 'CS', include_cross_school: true };
    serverRevision = 9;
    await act(async () => { await hydrateProfile(); });
    expect(screen.getByTestId('cross').textContent).toBe('false');
    expect(screen.getByTestId('rev').textContent).toBe('4');

    // Accepting moves both, together.
    act(() => { screen.getByTestId('accept').click(); });
    expect(screen.getByTestId('cross').textContent).toBe('true');
    expect(screen.getByTestId('rev').textContent).toBe('9');

    // And the document must come out of the SAME parse as the revision. A
    // raw mirror left disagreeing with the envelope — a partial write, an
    // older build — must not be what the page renders, or the value on
    // screen belongs to one moment and the revision behind it to another.
    localStorage.setItem(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ major: 'CS', include_cross_school: false }),
    );
    act(() => { screen.getByTestId('accept').click(); });
    expect(screen.getByTestId('cross').textContent).toBe('true');
    expect(screen.getByTestId('rev').textContent).toBe('9');
  });

  it('clear() publishes nothing at all — no document, no snapshot', async () => {
    await seedAccepted();
    render(<Harness onApplied={vi.fn()} />);
    act(() => { screen.getByTestId('accept').click(); });
    expect(screen.getByTestId('rev').textContent).toBe('4');
    act(() => { screen.getByTestId('clear').click(); });
    expect(screen.getByTestId('rev').textContent).toBe('none');
    expect(screen.getByTestId('cross').textContent).toBe('none');
  });
});

describe('a flip counts only when it took effect', () => {
  it('a durably recorded operation that comes back CONFLICT keeps the data and offers a retry', async () => {
    await seedAccepted();
    const onApplied = vi.fn();
    render(<Harness onApplied={onApplied} />);
    act(() => { screen.getByTestId('accept').click(); });

    nextOutcome = 'conflict';
    await act(async () => { screen.getByTestId('on').click(); });

    // It WAS recorded — the journal keeps it, and the coordinator even tries
    // again on its own rebase — but the ROW never took it, so re-ranking the
    // match set under it would be a lie.
    expect(commitMock).toHaveBeenCalled();
    expect(serverRow!.include_cross_school).toBe(false);
    expect(onApplied).not.toHaveBeenCalled();
    expect(screen.getByTestId('failed').textContent).toBe('true');
  });

  it('two clicks in the same tick send ONE request', async () => {
    await seedAccepted();
    render(<Harness onApplied={vi.fn()} />);
    act(() => { screen.getByTestId('accept').click(); });

    await act(async () => {
      screen.getByTestId('on').click();
      screen.getByTestId('on').click();
    });
    expect(commitMock).toHaveBeenCalledTimes(1);
  });

  it("a retry after the identity moved on cannot write: the coordinator refuses U1's view", async () => {
    await seedAccepted();
    const onApplied = vi.fn();
    render(<Harness onApplied={onApplied} />);
    act(() => { screen.getByTestId('accept').click(); });
    expect(screen.getByTestId('uid').textContent).toBe('results-view-u1');

    // A TRANSPORT failure, not a conflict: a conflict locks the key, and a
    // locked key would stop the retry from sending for a reason that has
    // nothing to do with whose view it carries.
    nextOutcome = 'transport';
    await act(async () => { screen.getByTestId('on').click(); });
    expect(screen.getByTestId('failed').textContent).toBe('true');
    commitMock.mockClear();

    // U2 takes over AND this page accepts U2's own view. The failed flip is
    // still U1's, held with U1's view — so a retry that used whatever is
    // current would now be aimed at U2's row, with a token that passes every
    // preflight.
    await act(async () => {
      advanceOwnerEpoch('results-view-u2');
      await syncLocalIdentityOwner('results-view-u2');
    });
    seedPrivate(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 40, profile: { major: 'ME', include_cross_school: false } },
    }));
    act(() => { screen.getByTestId('accept').click(); });
    expect(screen.getByTestId('uid').textContent).toBe('results-view-u2');
    nextOutcome = 'saved';
    await act(async () => { screen.getByTestId('retry').click(); });

    // ZERO requests: retrying is the same click again, and its owner is gone.
    // Re-aiming it at whatever view is current would write U1's choice into
    // U2's row — which this same setup DOES reach when the retry is allowed
    // to pick up the current view instead.
    expect(commitMock).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();
    expect(serverRow!.include_cross_school, "U2's row never took U1's flip").toBe(false);
  });

  it('an attempt abandoned by an identity switch cannot fail, apply, or unlock the new owner', async () => {
    await seedAccepted();
    const onApplied = vi.fn();
    render(<Harness onApplied={onApplied} />);
    act(() => { screen.getByTestId('accept').click(); });

    // U1's flip is in flight and held open.
    const gate: { resolve: (v: unknown) => void } = { resolve: () => {} };
    deferred = gate;
    act(() => { screen.getByTestId('on').click(); });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('busy').textContent).toBe('true');

    // The identity switches. The control is released IMMEDIATELY — U2 must
    // not be locked out until U1's request happens to come back.
    await act(async () => {
      advanceOwnerEpoch('results-view-u2b');
      await syncLocalIdentityOwner('results-view-u2b');
      screen.getByTestId('clear').click();
    });
    expect(screen.getByTestId('busy').textContent).toBe('false');
    expect(screen.getByTestId('failed').textContent).toBe('false');

    // U2 accepts its own view and starts its own flip, also held open.
    seedPrivate(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 20, profile: { major: 'ME', include_cross_school: false } },
    }));
    act(() => { screen.getByTestId('accept').click(); });
    expect(screen.getByTestId('rev').textContent).toBe('20');
    const gate2: { resolve: (v: unknown) => void } = { resolve: () => {} };
    deferred = gate2;
    act(() => { screen.getByTestId('on').click(); });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('busy').textContent).toBe('true');

    // U1's request comes back FIRST.
    await act(async () => { gate.resolve(undefined); await Promise.resolve(); });

    // It changed nothing: no failure U2 never caused, no match set thrown
    // away, and — the subtle one — U2's own in-flight guard is still held.
    expect(screen.getByTestId('failed').textContent).toBe('false');
    expect(onApplied).not.toHaveBeenCalled();
    expect(screen.getByTestId('busy').textContent).toBe('true');

    // Only U2's own attempt may finish it.
    await act(async () => { gate2.resolve(undefined); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('busy').textContent).toBe('false');
  });
});
