/* @vitest-environment jsdom */
/*
 * DOM-level, end-to-end proof for the Tracker main page — deliberately
 * NOT mocking useTrackerData (only its data-source boundary, exactly like
 * use-tracker-data.test.ts), so these tests exercise the REAL wiring
 * between the hook and page.tsx/TrackerCard, including React's actual
 * reconciliation behavior across a status-triggered column move.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  getInteractionsFull: vi.fn(),
  trackInteraction: vi.fn(),
  removeInteraction: vi.fn(),
  updateInteractionDetails: vi.fn(),
  dismissInteraction: vi.fn(),
  getAuthState: vi.fn(),
  onAuthChange: vi.fn(),
  getShortlistOpportunities: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: mocks.getInteractionsFull,
  trackInteraction: mocks.trackInteraction,
  removeInteraction: mocks.removeInteraction,
  updateInteractionDetails: mocks.updateInteractionDetails,
  dismissInteraction: mocks.dismissInteraction,
  getAuthState: mocks.getAuthState,
  onAuthChange: mocks.onAuthChange,
  // page.tsx renders <StorageStatusBanner /> unconditionally.
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onStorageStatusChange: () => () => {},
}));

vi.mock('@/lib/api', () => ({
  getShortlistOpportunities: mocks.getShortlistOpportunities,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (vars && 'title' in vars) return `${key}:${vars.title}`;
      return key;
    },
  }),
}));

import TrackerPage from './page';

type AuthCb = (state: { session: unknown; user: { id: string } | null; isAnonymous: boolean; email: string | null }) => void;
let authChangeCallback: AuthCb | null = null;

function authState(uid: string | null) {
  return { session: null, user: uid ? { id: uid } : null, isAnonymous: false, email: null };
}

beforeEach(() => {
  mocks.getInteractionsFull.mockReset();
  mocks.trackInteraction.mockReset();
  mocks.removeInteraction.mockReset();
  mocks.updateInteractionDetails.mockReset();
  mocks.dismissInteraction.mockReset();
  mocks.getAuthState.mockReset();
  mocks.onAuthChange.mockReset();
  mocks.getShortlistOpportunities.mockReset();
  authChangeCallback = null;

  mocks.getAuthState.mockResolvedValue(authState(null));
  mocks.onAuthChange.mockImplementation((cb: AuthCb) => {
    authChangeCallback = cb;
    return () => { authChangeCallback = null; };
  });
  mocks.trackInteraction.mockResolvedValue(undefined);
  mocks.removeInteraction.mockResolvedValue(undefined);
  mocks.updateInteractionDetails.mockResolvedValue(undefined);
  mocks.dismissInteraction.mockResolvedValue(undefined);
});

async function openStatusMenuAndPick(title: string, optionKey: string) {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(`statusMenu\\.ariaTrigger:${title}`) }));
  fireEvent.click(await screen.findByText(`detail.tracker.statusLabels.${optionKey}`));
}

// Re-clicking the currently-active status option is now a no-op —
// destructive removal (which deletes notes/reminder too) is only
// reachable via the menu's explicit "Remove from Tracker" footer, which
// itself requires an explicit confirm before firing the same underlying
// same-type callback (see InteractionStatusMenu.tsx/.test.tsx).
async function openStatusMenuAndClear(title: string) {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(`statusMenu\\.ariaTrigger:${title}`) }));
  fireEvent.click(await screen.findByText('results.statusMenu.remove'));
  fireEvent.click(await screen.findByText('results.statusMenu.removeConfirmYes'));
}

describe('TrackerPage — DOM: a notes draft survives a genuine status-triggered column move', () => {
  it('typing into the textarea (never blurred), then picking a DIFFERENT status: the card unmounts from one column <section> and remounts in another — the SAME text must still be there', async () => {
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    const textarea = await screen.findByPlaceholderText('tracker.notesPlaceholder');

    fireEvent.change(textarea, { target: { value: 'typed but never blurred' } });
    expect(textarea).toHaveValue('typed but never blurred');

    await openStatusMenuAndPick('Opp o1', 'interviewing');

    // Optimistic move — o1 is now under the "interviewing" column, a
    // DIFFERENT parent <section> than "applied". The prior bug: this is a
    // real unmount+remount, and a draft held in component-local state was
    // silently destroyed here, before onSaveNotes was ever called.
    await waitFor(() => expect(mocks.trackInteraction).toHaveBeenCalledWith('o1', 'interviewing', expect.anything()));
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).toHaveValue('typed but never blurred');

    // And it is genuinely still live/committable — blurring now saves it.
    fireEvent.blur(screen.getByPlaceholderText('tracker.notesPlaceholder'));
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledWith(
      'o1', { notes: 'typed but never blurred' }, expect.anything(),
    ));
  });

  it('an ordinary SET that FAILS rolls the card back to its original column, but the textarea stays editable throughout and the draft is never touched', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('boom'));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    const textarea = await screen.findByPlaceholderText('tracker.notesPlaceholder');

    fireEvent.change(textarea, { target: { value: 'typed but never blurred' } });
    await openStatusMenuAndPick('Opp o1', 'interviewing');

    // Ordinary SET is optimistic — the card moves immediately, but the
    // textarea must never be disabled by it (this is NOT a leaving op).
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).not.toBeDisabled();

    await screen.findByText('tracker.statusSaveError');
    // Rolled back to "applied" — the draft survived the whole round-trip.
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).toHaveValue('typed but never blurred');
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).not.toBeDisabled();
  });

  // The two tests above type BEFORE picking a status — a real click on the
  // trigger button would blur (and thus save) whatever the textarea
  // already held first, so they don't fully pin the risk. These two
  // instead type into the FRESHLY REMOUNTED textarea in the NEW column
  // WHILE the status write is still pending — a genuinely un-blurred,
  // never-yet-saved draft racing the write's eventual resolution, in both
  // directions (success stays moved; failure rolls back AND remounts a
  // second time, back to the original column).
  it('deferred SET success: typing into the new column\'s textarea while the write is still pending survives the resolution, and is still committable afterward', async () => {
    let resolveTrack: (() => void) | undefined;
    mocks.trackInteraction.mockReturnValue(new Promise<void>((r) => { resolveTrack = r; }));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');

    await openStatusMenuAndPick('Opp o1', 'interviewing'); // optimistic move, write pending
    expect(mocks.trackInteraction).toHaveBeenCalledWith('o1', 'interviewing', expect.anything());

    // A fresh instance in the new column — type into IT, not blurred, while
    // the write for the move that put it there is still unresolved.
    const textarea = screen.getByPlaceholderText('tracker.notesPlaceholder');
    fireEvent.change(textarea, { target: { value: 'typed post-move, still pending' } });

    await act(async () => { resolveTrack?.(); });
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).toHaveValue('typed post-move, still pending');

    fireEvent.blur(screen.getByPlaceholderText('tracker.notesPlaceholder'));
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledWith(
      'o1', { notes: 'typed post-move, still pending' }, expect.anything(),
    ));
  });

  it('deferred SET failure: typing into the new column\'s textarea while the write is still pending survives BOTH the failure AND the rollback remount back to the original column', async () => {
    let rejectTrack: ((e: Error) => void) | undefined;
    mocks.trackInteraction.mockReturnValue(new Promise<void>((_res, rej) => { rejectTrack = rej; }));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');

    await openStatusMenuAndPick('Opp o1', 'interviewing'); // optimistic move, write pending

    const textarea = screen.getByPlaceholderText('tracker.notesPlaceholder');
    fireEvent.change(textarea, { target: { value: 'typed post-move, still pending' } });

    await act(async () => { rejectTrack?.(new Error('boom')); }); // rollback — a SECOND remount, back to "applied"
    await screen.findByText('tracker.statusSaveError');
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).toHaveValue('typed post-move, still pending');

    fireEvent.blur(screen.getByPlaceholderText('tracker.notesPlaceholder'));
    await waitFor(() => expect(mocks.updateInteractionDetails).toHaveBeenCalledWith(
      'o1', { notes: 'typed post-move, still pending' }, expect.anything(),
    ));
  });
});

describe('TrackerPage — DOM: REMOVE/dismiss pending disables the notes textarea (a new edit has nowhere safe to land)', () => {
  it('while a REMOVE (untoggling the active status) is pending, the textarea is disabled and typing into it via a real DOM event produces no draft/save call', async () => {
    mocks.removeInteraction.mockReturnValue(new Promise<void>(() => {})); // never resolves — stays pending
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');
    await openStatusMenuAndClear('Opp o1'); // re-selecting the active status -> REMOVE
    await waitFor(() => expect(mocks.removeInteraction).toHaveBeenCalled());

    const textarea = await screen.findByPlaceholderText('tracker.notesPlaceholder');
    expect(textarea).toBeDisabled();
    fireEvent.change(textarea, { target: { value: 'a new edit with nowhere to land' } });
    fireEvent.blur(textarea);
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
  });

  it('while a dismiss is pending, the textarea is disabled and typing into it via a real DOM event produces no draft/save call', async () => {
    mocks.dismissInteraction.mockReturnValue(new Promise<void>(() => {})); // never resolves — stays pending
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');
    await openStatusMenuAndPick('Opp o1', 'dismissed');
    await waitFor(() => expect(mocks.dismissInteraction).toHaveBeenCalled());

    const textarea = await screen.findByPlaceholderText('tracker.notesPlaceholder');
    expect(textarea).toBeDisabled();
    fireEvent.change(textarea, { target: { value: 'a new edit with nowhere to land' } });
    fireEvent.blur(textarea);
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
    expect(mocks.dismissInteraction).toHaveBeenCalledTimes(1); // no second/late call produced either
  });

  it('a visible notes-save error/Retry from BEFORE the REMOVE was clicked stays visible, but the Retry button itself is disabled for the duration of the pending REMOVE', async () => {
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('boom'));
    mocks.removeInteraction.mockReturnValue(new Promise<void>(() => {})); // never resolves — stays pending
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    const textarea = await screen.findByPlaceholderText('tracker.notesPlaceholder');
    fireEvent.change(textarea, { target: { value: 'a note that failed to save' } });
    fireEvent.blur(textarea);
    await screen.findByText('tracker.notesSaveError');
    const retryBtn = screen.getByText('common.retry');
    expect(retryBtn).not.toBeDisabled();

    await openStatusMenuAndClear('Opp o1'); // re-selecting the active status -> REMOVE, pending
    await waitFor(() => expect(mocks.removeInteraction).toHaveBeenCalled());

    expect(screen.getByText('tracker.notesSaveError')).toBeInTheDocument(); // still visible
    expect(screen.getByText('common.retry')).toBeDisabled();
    fireEvent.click(screen.getByText('common.retry'));
    expect(mocks.updateInteractionDetails).toHaveBeenCalledTimes(1); // no second (retry) call produced
  });
});

describe('TrackerPage — DOM: dismissing WITH a dirty, never-blurred draft includes it in the SAME atomic dismissInteraction call — never a separate flush-then-track pair', () => {
  it('the draft is sent as part of the ONE dismissInteraction call — no separate updateInteractionDetails call is ever produced', async () => {
    let resolveDismiss: (() => void) | undefined;
    mocks.dismissInteraction.mockReturnValue(new Promise<void>((r) => { resolveDismiss = r; }));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    const textarea = await screen.findByPlaceholderText('tracker.notesPlaceholder');
    fireEvent.change(textarea, { target: { value: 'dirty, never blurred' } }); // no blur — pure live draft

    await openStatusMenuAndPick('Opp o1', 'dismissed');
    await waitFor(() => expect(mocks.dismissInteraction).toHaveBeenCalledWith(
      'o1', 'dirty, never blurred', expect.anything(),
    ));
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled(); // no separate flush call — ever

    await act(async () => { resolveDismiss?.(); });
    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
  });
});

describe('TrackerPage — DOM: dismissing a normal card is pessimistic', () => {
  it('the card stays fully visible (original title, original column) until the write confirms — only then does it disappear from the board', async () => {
    let resolveDismiss: (() => void) | undefined;
    mocks.dismissInteraction.mockReturnValue(new Promise<void>((r) => { resolveDismiss = r; }));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');

    await openStatusMenuAndPick('Opp o1', 'dismissed');
    expect(mocks.dismissInteraction).toHaveBeenCalledWith('o1', undefined, expect.anything());
    // Still visible — not yet confirmed.
    expect(screen.getByText('Opp o1')).toBeInTheDocument();

    await act(async () => { resolveDismiss?.(); });
    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
  });

  it('a failed dismiss leaves the card fully visible with a retryable error — never silently vanishes', async () => {
    mocks.dismissInteraction.mockRejectedValueOnce(new Error('boom'));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');

    await openStatusMenuAndPick('Opp o1', 'dismissed');
    await screen.findByText('tracker.statusSaveError');
    expect(screen.getByText('Opp o1')).toBeInTheDocument();

    mocks.dismissInteraction.mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByText('common.retry'));
    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
  });
});

describe('TrackerPage — DOM: unavailable interaction rows', () => {
  it('an ENTIRELY unavailable tracker does not show the empty-state CTA — the Unavailable section renders instead', async () => {
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({ opportunities: [], unavailableIds: ['o1'] });
    render(<TrackerPage />);
    await screen.findByText('tracker.unavailable.title');
    expect(screen.queryByText('tracker.emptyTitle')).toBeNull();
  });

  it('a PARTIALLY unavailable tracker shows both the real card and the placeholder', async () => {
    mocks.getInteractionsFull.mockResolvedValue(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'interviewing' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: ['o2'],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');
    expect(screen.getByText('tracker.unavailable.title')).toBeInTheDocument();
    expect(screen.getByText('tracker.unavailable.body')).toBeInTheDocument();
  });

  it('the placeholder stays visible with its Remove button disabled while pending, and disappears only once the delete confirms', async () => {
    let resolveRemove: (() => void) | undefined;
    mocks.removeInteraction.mockReturnValue(new Promise<void>((r) => { resolveRemove = r; }));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o2', { type: 'interviewing' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({ opportunities: [], unavailableIds: ['o2'] });
    render(<TrackerPage />);
    await screen.findByText('tracker.unavailable.title');

    const removeBtn = screen.getByText('tracker.unavailable.remove').closest('button')!;
    fireEvent.click(removeBtn);
    expect(mocks.removeInteraction).toHaveBeenCalledWith('o2', expect.anything());
    expect(removeBtn).toBeDisabled();
    expect(screen.getByText('tracker.unavailable.title')).toBeInTheDocument(); // still there

    await act(async () => { resolveRemove?.(); });
    await waitFor(() => expect(screen.queryByText('tracker.unavailable.title')).toBeNull());
  });

  it('a failed placeholder removal shows a visible, retryable error — the placeholder is never silently dropped', async () => {
    mocks.removeInteraction.mockRejectedValueOnce(new Error('boom'));
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o2', { type: 'interviewing' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({ opportunities: [], unavailableIds: ['o2'] });
    render(<TrackerPage />);
    await screen.findByText('tracker.unavailable.title');

    fireEvent.click(screen.getByText('tracker.unavailable.remove'));
    await screen.findByText('tracker.statusSaveError');
    expect(screen.getByText('tracker.unavailable.title')).toBeInTheDocument();

    mocks.removeInteraction.mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByText('common.retry'));
    await waitFor(() => expect(screen.queryByText('tracker.unavailable.title')).toBeNull());
  });
});

describe('TrackerPage — DOM: a REAL REMOVE unmounts the card — focus must go somewhere sensible, not be silently lost to <body>', () => {
  it('removing a card from the middle of a column moves focus to whatever card is NOW at that same index — not the one that stayed put, and not nothing', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockResolvedValue(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'applied' }],
      ['o3', { type: 'applied' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [
        { id: 'o1', title: 'Opp o1' },
        { id: 'o2', title: 'Opp o2' },
        { id: 'o3', title: 'Opp o3' },
      ],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o2');

    // Remove the MIDDLE card (index 1) — o3 will slide into index 1.
    await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o2/ }));
    await user.click(screen.getByText('results.statusMenu.remove'));
    await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));

    await waitFor(() => expect(screen.queryByText('Opp o2')).toBeNull());
    const trigger3 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o3/ });
    expect(document.activeElement).toBe(trigger3);
  });

  it('removing the LAST remaining card moves focus to the visible empty-state CTA — never left stranded on <body>', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o1');

    await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ }));
    await user.click(screen.getByText('results.statusMenu.remove'));
    await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));

    await waitFor(() => expect(screen.getByText('tracker.emptyTitle')).toBeInTheDocument());
    expect(document.activeElement).toBe(screen.getByText('tracker.emptyCta'));
  });

  it('removing the ONLY card in a column, while another column still has cards, lands focus on a REAL actionable card — never an invisible tabIndex=-1 header', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockResolvedValue(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'interviewing' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [
        { id: 'o1', title: 'Opp o1' },
        { id: 'o2', title: 'Opp o2' },
      ],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o2');

    // o1 is the only card in "applied" — removing it empties that column
    // entirely, while "interviewing" (o2) still has a card.
    await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ }));
    await user.click(screen.getByText('results.statusMenu.remove'));
    await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));

    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
    const trigger2 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o2/ });
    expect(document.activeElement).toBe(trigger2);
  });
});

describe('TrackerPage — DOM: a fallback focus() must RE-ARM tracking, not clear it — a chained, keyboard-only follow-up action still needs a correct redirect', () => {
  it('REMOVE o1 auto-focuses o2 (fallback); WITHOUT any click, a pure-keyboard status change on o2 (Enter to open, Tab to a different option, Enter to select) still lands focus on o2\'s NEW column trigger', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockResolvedValue(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'applied' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [
        { id: 'o1', title: 'Opp o1' },
        { id: 'o2', title: 'Opp o2' },
      ],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o2');

    // Remove o1 (mouse) — o2 slides into its slot and, per the REMOVE
    // fallback, receives focus automatically.
    await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ }));
    await user.click(screen.getByText('results.statusMenu.remove'));
    await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));
    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
    const trigger2 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o2/ });
    expect(document.activeElement).toBe(trigger2);

    // PURE KEYBOARD from here on — no click ever re-establishes focus, so
    // this only works if the fallback focus() above re-armed focusIntentRef
    // to o2 rather than clearing it.
    await user.keyboard('{Enter}'); // opens o2's dialog — focus lands on the active ("applied") option
    await user.tab(); // -> replied
    await user.tab(); // -> interviewing
    await user.keyboard('{Enter}'); // selects "interviewing" — o2 moves columns (a MOVE, not a REMOVE)

    await waitFor(() => expect(mocks.trackInteraction).toHaveBeenCalledWith('o2', 'interviewing', expect.anything()));
    const trigger2New = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o2/ });
    expect(document.activeElement).toBe(trigger2New);
  });

  it('REMOVE o1 auto-focuses o2 (fallback); WITHOUT any click, a pure-keyboard REMOVE of o2 itself (Enter, Tab to the footer, confirm) still lands focus on the empty-state CTA', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockResolvedValue(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'applied' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [
        { id: 'o1', title: 'Opp o1' },
        { id: 'o2', title: 'Opp o2' },
      ],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o2');

    await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ }));
    await user.click(screen.getByText('results.statusMenu.remove'));
    await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));
    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
    const trigger2 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o2/ });
    expect(document.activeElement).toBe(trigger2);

    // PURE KEYBOARD from here on: open, Tab past all 5 status options to
    // reach the "Remove from Tracker" footer, confirm.
    await user.keyboard('{Enter}'); // opens — focus on the active ("applied") option
    await user.tab(); // replied
    await user.tab(); // interviewing
    await user.tab(); // rejected
    await user.tab(); // dismissed
    await user.tab(); // Remove from Tracker footer
    await user.keyboard('{Enter}'); // enters the confirm sub-state — focus moves to Cancel
    await user.tab(); // -> the red "Remove" confirm button
    await user.keyboard('{Enter}'); // confirms — REMOVE o2, the last remaining card

    await waitFor(() => expect(screen.getByText('tracker.emptyTitle')).toBeInTheDocument());
    expect(document.activeElement).toBe(screen.getByText('tracker.emptyCta'));
  });
});

describe('TrackerPage — DOM: an ordinary cross-column SET (a MOVE, not a REMOVE) must never be misread as a removal', () => {
  it('SET on o1 (Applied -> Interviewing), with o2 staying put in Applied, moves focus to o1\'s trigger in ITS NEW column — never to o2, never to a column header, never lost to <body>', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockResolvedValue(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'applied' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [
        { id: 'o1', title: 'Opp o1' },
        { id: 'o2', title: 'Opp o2' },
      ],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o2');

    await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ }));
    await user.click(screen.getByText('detail.tracker.statusLabels.interviewing'));

    await waitFor(() => expect(mocks.trackInteraction).toHaveBeenCalledWith('o1', 'interviewing', expect.anything()));
    // o1's trigger in the "applied" section was unmounted (a real remount
    // into "interviewing", never a DOM move) — focus must land on the NEW
    // instance, not be misattributed as a REMOVE that fell back to o2.
    const trigger1 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ });
    expect(document.activeElement).toBe(trigger1);
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o2/ }));
  });
});

describe('TrackerPage — DOM: an identity switch (or a retry/loading boundary) must never reuse a stale snapshot to guess a focus redirect', () => {
  it('switching to a different identity with a smaller/different item set does not redirect focus onto an unrelated new-identity card', async () => {
    const user = userEvent.setup();
    mocks.getAuthState.mockResolvedValue(authState('user-1'));
    mocks.getInteractionsFull.mockResolvedValueOnce(new Map([
      ['o1', { type: 'applied' }],
      ['o2', { type: 'interviewing' }],
    ]));
    mocks.getShortlistOpportunities.mockResolvedValueOnce({
      opportunities: [
        { id: 'o1', title: 'Opp o1' },
        { id: 'o2', title: 'Opp o2' },
      ],
      unavailableIds: [],
    });
    render(<TrackerPage />);
    await screen.findByText('Opp o2');

    const trigger1 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ });
    await user.click(trigger1);
    await user.keyboard('{Escape}'); // a real, deliberate focus on o1's trigger — not an operation on it
    expect(document.activeElement).toBe(trigger1);

    // A DIFFERENT identity logs in — a smaller, unrelated item set: o1/o2
    // are both gone, only o3 (never seen before) exists now.
    mocks.getInteractionsFull.mockResolvedValueOnce(new Map([['o3', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValueOnce({
      opportunities: [{ id: 'o3', title: 'Opp o3' }],
      unavailableIds: [],
    });
    await act(async () => { authChangeCallback?.(authState('user-2')); });
    await screen.findByText('Opp o3');

    // The stale generation-1 snapshot (o1 in "applied") must never be
    // compared against generation-2's layout — that would misread "o1 is
    // gone" as a removal and redirect focus onto o3, a completely unrelated
    // card from a different identity's data.
    const trigger3 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o3/ });
    expect(document.activeElement).not.toBe(trigger3);
  });

  it('a retry (loading true -> false for the SAME identity) after an error clears any stale focus intent — a fresh, possibly different item set is never diffed against a pre-error snapshot', async () => {
    const user = userEvent.setup();
    mocks.getInteractionsFull.mockRejectedValueOnce(new Error('boom'));
    render(<TrackerPage />);
    await screen.findByText('tracker.loadError');

    // Nothing was ever on-board to have focus tracked against (the error
    // page pre-empted the board entirely) — this exercises the SAME
    // `[identityGeneration, loading]` reset effect the identity-switch test
    // above does, just via the `loading` half of its dependency array
    // rather than the `identityGeneration` half, proving neither half was
    // dropped from the dependency list.
    mocks.getInteractionsFull.mockResolvedValueOnce(new Map([['o1', { type: 'applied' }]]));
    mocks.getShortlistOpportunities.mockResolvedValueOnce({
      opportunities: [{ id: 'o1', title: 'Opp o1' }],
      unavailableIds: [],
    });
    await user.click(screen.getByText('common.retry'));
    await screen.findByText('Opp o1');

    // No crash, and nothing forced focus anywhere — it lands wherever the
    // browser's own default post-navigation behavior leaves it, never on a
    // card the redirect logic decided for itself with no real basis.
    const trigger1 = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Opp o1/ });
    expect(document.activeElement).not.toBe(trigger1);
  });
});
