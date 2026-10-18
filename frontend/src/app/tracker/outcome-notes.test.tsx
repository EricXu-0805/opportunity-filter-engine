/**
 * Outcome notes on the tracker board (checklist M49), through the real page,
 * useTrackerData and useOutcomeNotes; only the Supabase/API boundary is mocked.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

import { OutcomeNoteError, outcomeNoteBodyProblem } from '@/lib/outcome-notes';

const mocks = vi.hoisted(() => ({
  getInteractionsFull: vi.fn(),
  trackInteraction: vi.fn(),
  getAuthState: vi.fn(),
  onAuthChange: vi.fn(),
  getShortlistOpportunities: vi.fn(),
  getOutcomeNotes: vi.fn(),
  appendOutcomeNote: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: mocks.getInteractionsFull,
  trackInteraction: mocks.trackInteraction,
  removeInteraction: vi.fn(),
  updateInteractionDetails: vi.fn(async () => undefined),
  dismissInteraction: vi.fn(),
  getAuthState: mocks.getAuthState,
  onAuthChange: mocks.onAuthChange,
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onStorageStatusChange: () => () => {},
  getOutcomeNotes: mocks.getOutcomeNotes,
  appendOutcomeNote: mocks.appendOutcomeNote,
}));
vi.mock('@/lib/api', () => ({ getShortlistOpportunities: mocks.getShortlistOpportunities }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }) }));
vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key}(${Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(',')})` : key,
  }),
}));

import TrackerPage from './page';

const LIVE_LISTING = {
  source_type: 'campus_program',
  record_kind: 'listing',
  target_truth: {
    listing_state: 'open', reference_only: false, actionable: true,
    accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null,
  },
};

function note(id: string, body: string, recordedAt: string, outcome: string | null = null) {
  return { id, opportunityId: 'o1', body, outcome, recordedAt };
}

function section() {
  return screen.getByRole('region', { name: 'tracker.outcomeNotes.title' });
}

async function renderBoard(type = 'contacted', remind_at?: string) {
  mocks.getInteractionsFull.mockResolvedValue(new Map([['o1', { type, remind_at }]]));
  mocks.getShortlistOpportunities.mockResolvedValue({
    opportunities: [{ id: 'o1', title: 'Opp o1', ...LIVE_LISTING }],
    unavailableIds: [],
  });
  render(<TrackerPage />);
  await screen.findByPlaceholderText('tracker.outcomeNotes.placeholder');
}

function type(text: string) {
  fireEvent.change(screen.getByLabelText('tracker.outcomeNotes.addLabel'), { target: { value: text } });
}

function column(status: string) {
  return document.querySelector(`[data-tracker-column="${status}"]`) as HTMLElement;
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  mocks.getAuthState.mockResolvedValue({ session: null, user: null, isAnonymous: false, email: null });
  mocks.onAuthChange.mockImplementation(() => () => {});
  mocks.getOutcomeNotes.mockResolvedValue(new Map());
});

describe('outcome notes on a tracker card', () => {
  it('shows the saved notes newest first with the date each was saved and the status it set, and offers no edit or delete', async () => {
    mocks.getOutcomeNotes.mockResolvedValue(new Map([['o1', [
      note('00000000-0000-4000-8000-000000000002', 'Correction: it was the lab manager who replied.', '2026-10-12T12:00:00Z'),
      note('00000000-0000-4000-8000-000000000001', 'Professor Lee replied.', '2026-10-10T12:00:00Z', 'replied'),
    ]]]));
    await renderBoard('replied');
    const items = await within(section()).findAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual([
      'tracker.outcomeNotes.notedOn(date=2026-10-12)Correction: it was the lab manager who replied.',
      'tracker.outcomeNotes.notedOn(date=2026-10-10) · tracker.outcomeNotes.statusSet(status=tracker.outcomeNotes.outcome.replied)Professor Lee replied.',
    ]);
    expect(within(section()).getAllByRole('button').map((b) => b.textContent)).toEqual(['tracker.outcomeNotes.save']);
  });

  it('adds a note in the student\'s words, shows it on top and clears the field', async () => {
    mocks.getOutcomeNotes.mockResolvedValue(new Map([['o1', [
      note('00000000-0000-4000-8000-000000000001', 'Older note.', '2026-10-10T12:00:00Z'),
    ]]]));
    mocks.appendOutcomeNote.mockImplementation(async (_id: string, input: { noteId: string; body: string }) => ({
      note: note(input.noteId, input.body, '2026-10-18T12:00:00Z'), status: 'contacted', replayed: false,
    }));
    await renderBoard();
    await within(section()).findByText('Older note.');
    type('  Waiting to hear back after my second email.  ');
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));

    await within(section()).findByText('Waiting to hear back after my second email.');
    expect(mocks.appendOutcomeNote).toHaveBeenCalledWith('o1', {
      noteId: expect.stringMatching(/^[0-9a-f-]{36}$/),
      body: 'Waiting to hear back after my second email.',
      outcome: null,
    }, expect.anything());
    const items = within(section()).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Waiting to hear back after my second email.');
    expect(items[1]).toHaveTextContent('Older note.');
    expect(screen.getByLabelText('tracker.outcomeNotes.addLabel')).toHaveValue('');
    expect(mocks.trackInteraction).not.toHaveBeenCalled();
  });

  it('refuses an empty or too-long note without sending it', async () => {
    await renderBoard();
    type('   ');
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));
    expect(await within(section()).findByRole('alert')).toHaveTextContent('tracker.outcomeNotes.errors.empty');

    type('a'.repeat(301));
    expect(within(section()).queryByRole('alert')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));
    expect(await within(section()).findByRole('alert')).toHaveTextContent('tracker.outcomeNotes.errors.too_long(max=300)');
    expect(screen.getByLabelText('tracker.outcomeNotes.addLabel')).toHaveValue('a'.repeat(301));
    expect(mocks.appendOutcomeNote).not.toHaveBeenCalled();
  });

  it('keeps the text and shows the error when a save fails, and a retry sends the same note id', async () => {
    mocks.appendOutcomeNote.mockRejectedValueOnce(new OutcomeNoteError('unavailable'));
    await renderBoard();
    type('Professor Lee said no for this year.');
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));

    expect(await within(section()).findByRole('alert')).toHaveTextContent('tracker.outcomeNotes.errors.failed');
    expect(screen.getByLabelText('tracker.outcomeNotes.addLabel')).toHaveValue('Professor Lee said no for this year.');
    expect(within(section()).queryByRole('listitem')).toBeNull();
    const firstId = mocks.appendOutcomeNote.mock.calls[0][1].noteId;

    mocks.appendOutcomeNote.mockImplementationOnce(async (_id: string, input: { noteId: string; body: string }) => ({
      note: note(input.noteId, input.body, '2026-10-18T12:00:00Z'), status: 'contacted', replayed: true,
    }));
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));
    await within(section()).findByText('Professor Lee said no for this year.', { selector: 'li p' });
    expect(mocks.appendOutcomeNote.mock.calls[1][1].noteId).toBe(firstId);
    expect(within(section()).queryByRole('alert')).toBeNull();
  });

  it('a note marked rejected moves the card to Rejected with the status the server returned, and its reminder no longer sends', async () => {
    mocks.appendOutcomeNote.mockImplementation(async (_id: string, input: { noteId: string; body: string; outcome: string }) => ({
      note: note(input.noteId, input.body, '2026-10-18T12:00:00Z', input.outcome), status: 'rejected', replayed: false,
    }));
    await renderBoard('applied', '2026-10-01');
    expect(within(column('applied')).getByText(/tracker\.followUpDue/)).toBeInTheDocument();
    type('They filled the position.');
    fireEvent.change(screen.getByLabelText('tracker.outcomeNotes.outcomeLabel'), { target: { value: 'rejected' } });
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));

    await waitFor(() => expect(within(column('rejected')).getByText('Opp o1')).toBeInTheDocument());
    expect(mocks.appendOutcomeNote).toHaveBeenCalledWith('o1', expect.objectContaining({ outcome: 'rejected' }), expect.anything());
    expect(within(column('rejected')).getByText('tracker.reminderWontSend')).toBeInTheDocument();
    expect(within(column('rejected')).getByText('They filled the position.')).toBeInTheDocument();
    // The status came from the note's own transaction, not a second write.
    expect(mocks.trackInteraction).not.toHaveBeenCalled();
  });

  it('"no longer contacting" takes the card off the board only once the server confirms', async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.appendOutcomeNote.mockReturnValue(new Promise((r) => { resolve = r; }));
    await renderBoard('contacted', '2026-10-01');
    type('I decided not to follow up with this lab.');
    fireEvent.change(screen.getByLabelText('tracker.outcomeNotes.outcomeLabel'), { target: { value: 'dismissed' } });
    fireEvent.click(screen.getByRole('button', { name: 'tracker.outcomeNotes.save' }));

    expect(await screen.findByRole('button', { name: 'tracker.outcomeNotes.saving' })).toBeDisabled();
    expect(within(column('contacted')).getByText('Opp o1')).toBeInTheDocument();
    resolve({
      note: note('00000000-0000-4000-8000-000000000009', 'I decided not to follow up with this lab.', '2026-10-18T12:00:00Z', 'dismissed'),
      status: 'dismissed', replayed: false,
    });
    await waitFor(() => expect(screen.queryByText('Opp o1')).toBeNull());
  });

  it('a failed notes read says so with a retry, and the board still renders', async () => {
    mocks.getOutcomeNotes.mockRejectedValueOnce(new Error('read failed'));
    await renderBoard();
    expect(await within(section()).findByRole('alert')).toHaveTextContent('tracker.outcomeNotes.loadError');
    expect(within(section()).queryByText('tracker.outcomeNotes.empty')).toBeNull();
    mocks.getOutcomeNotes.mockResolvedValueOnce(new Map());
    fireEvent.click(within(section()).getByRole('button', { name: 'common.retry' }));
    expect(await within(section()).findByText('tracker.outcomeNotes.empty')).toBeInTheDocument();
  });
});

describe('outcomeNoteBodyProblem matches the SQL CHECK', () => {
  it('counts code points and refuses control characters', () => {
    expect(outcomeNoteBodyProblem('😀'.repeat(300))).toBeNull();
    expect(outcomeNoteBodyProblem('😀'.repeat(301))).toBe('too_long');
    expect(outcomeNoteBodyProblem('two\nlines')).toBe('not_one_line');
    expect(outcomeNoteBodyProblem(' \t ')).toBe('empty');
  });
});
