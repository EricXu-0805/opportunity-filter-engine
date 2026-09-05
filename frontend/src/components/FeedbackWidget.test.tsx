/*
 * FeedbackWidget: launcher → form → submit. submitFeedback + analytics are
 * mocked (same style as account/page.test.tsx); i18n returns the key verbatim
 * (with any interpolation vars appended so counters stay assertable).
 *
 * W15 pins, beyond the original launcher/submit flow:
 *   - the draft survives a reload AND a failed send, and is cleared ONLY
 *     after a confirmed insert;
 *   - a retry reuses the SAME client_token, so the server can dedupe it;
 *   - a 23505 duplicate is a SUCCESS with the existing reference, never an
 *     error and never a claim that a second ticket was opened;
 *   - a hung insert times out into the error state with the draft intact and
 *     the button usable again (pre-W15 it wedged 'sending' forever);
 *   - an invalid reply address is refused inline instead of being stored.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  advanceOwnerEpoch,
  isLocalOwnerReady,
  readUserScopedRaw,
  syncLocalIdentityOwner,
} from '@/lib/identity-owner';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockSubmitFeedback = vi.fn();
const mockTrack = vi.fn();

vi.mock('@/lib/supabase', () => ({
  submitFeedback: (...args: unknown[]) => mockSubmitFeedback(...args),
}));

vi.mock('@/lib/analytics', () => ({
  track: (...args: unknown[]) => mockTrack(...args),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) =>
      (vars ? [key, ...Object.values(vars)].join(' ') : key),
  }),
}));

import FeedbackWidget from './FeedbackWidget';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const TICKET_ID = '7c9e6679-7425-40de-944b-e07fc1f90ae7';

interface StoredDraft {
  message: string;
  email: string;
  category: string;
  subject: string;
  clientToken: string;
}

function storedDraft(): StoredDraft | null {
  // FEEDBACK_DRAFT is user-scoped: the mirror lives in the owner's
  // namespace, never at the bare key (which the next account could read).
  const raw = readUserScopedRaw(STORAGE_KEYS.FEEDBACK_DRAFT);
  return raw ? (JSON.parse(raw) as StoredDraft) : null;
}

function openAndType(message: string) {
  fireEvent.click(screen.getByTestId('feedback-open'));
  fireEvent.change(screen.getByPlaceholderText('feedback.placeholder'), {
    target: { value: message },
  });
}

function tokenOfCall(i: number): string {
  return (mockSubmitFeedback.mock.calls[i][0] as { clientToken: string }).clientToken;
}

const OWNER_UID = 'fw-owner-uid';

beforeEach(async () => {
  localStorage.clear();
  // The widget's mirror is an owner-scoped write; in the app an owner always
  // exists (ensureAnonSession). Claim one here or every write fails closed.
  advanceOwnerEpoch(OWNER_UID);
  await syncLocalIdentityOwner(OWNER_UID);
  for (let i = 0; i < 200 && !isLocalOwnerReady(OWNER_UID); i += 1) {
    await new Promise((r) => setTimeout(r, 0));
  }
  expect(isLocalOwnerReady(OWNER_UID)).toBe(true);
  mockSubmitFeedback.mockResolvedValue({ ok: true, reason: 'created', id: TICKET_ID });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('FeedbackWidget', () => {
  it('shows the launcher and hides the panel initially', () => {
    render(<FeedbackWidget />);
    expect(screen.getByTestId('feedback-open')).toBeInTheDocument();
    expect(screen.queryByTestId('feedback-panel')).toBeNull();
  });

  it('opens the panel on launcher click', () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    expect(screen.getByTestId('feedback-panel')).toBeInTheDocument();
  });

  it('keeps send disabled until a message is typed', () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    expect(screen.getByTestId('feedback-send')).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('feedback.placeholder'), {
      target: { value: 'great app' },
    });
    expect(screen.getByTestId('feedback-send')).toBeEnabled();
  });

  it('submits message + email + category + subject and shows the thanks state', async () => {
    render(<FeedbackWidget />);
    openAndType('love it');
    fireEvent.change(screen.getByPlaceholderText('feedback.emailPlaceholder'), {
      target: { value: 'me@x.edu' },
    });
    fireEvent.change(screen.getByTestId('feedback-category'), { target: { value: 'idea' } });
    fireEvent.change(screen.getByTestId('feedback-subject'), { target: { value: 'dark mode' } });
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(mockSubmitFeedback).toHaveBeenCalledWith(expect.objectContaining({
      message: 'love it',
      email: 'me@x.edu',
      category: 'idea',
      subject: 'dark mode',
      clientToken: expect.any(String),
    }));
    expect(mockTrack).toHaveBeenCalledWith('feedback_submitted');
  });

  it('sends an unclassified report as category null rather than guessing "other"', async () => {
    render(<FeedbackWidget />);
    openAndType('no topic chosen');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(mockSubmitFeedback).toHaveBeenCalledWith(expect.objectContaining({ category: null }));
  });

  it('shows an inline error when the submit fails', async () => {
    mockSubmitFeedback.mockResolvedValue({ ok: false, reason: 'error' });
    render(<FeedbackWidget />);
    openAndType('broken');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-error')).toBeInTheDocument());
    expect(screen.getByTestId('feedback-error')).toHaveTextContent('feedback.error');
    expect(screen.queryByTestId('feedback-thanks')).toBeNull();
  });

  it('distinguishes a missing session from a generic failure', async () => {
    mockSubmitFeedback.mockResolvedValue({ ok: false, reason: 'no-session' });
    render(<FeedbackWidget />);
    openAndType('offline?');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-error')).toBeInTheDocument());
    expect(screen.getByTestId('feedback-error')).toHaveTextContent('feedback.errorOffline');
  });
});

describe('draft persistence', () => {
  it('writes the draft to localStorage and restores it on a remount', () => {
    const { unmount } = render(<FeedbackWidget />);
    openAndType('half-written thought');
    fireEvent.change(screen.getByTestId('feedback-subject'), { target: { value: 'a subject' } });

    const saved = storedDraft();
    expect(saved?.message).toBe('half-written thought');
    expect(saved?.subject).toBe('a subject');
    expect(saved?.clientToken).toBeTruthy();

    unmount();
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    expect(screen.getByPlaceholderText('feedback.placeholder')).toHaveValue('half-written thought');
    expect(screen.getByTestId('feedback-subject')).toHaveValue('a subject');
  });

  it('leaves storage untouched for a user who never types', () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    expect(readUserScopedRaw(STORAGE_KEYS.FEEDBACK_DRAFT)).toBeNull();
  });

  it('keeps the draft after a FAILED submit', async () => {
    mockSubmitFeedback.mockResolvedValue({ ok: false, reason: 'error' });
    render(<FeedbackWidget />);
    openAndType('please do not eat this');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-error')).toBeInTheDocument());
    expect(storedDraft()?.message).toBe('please do not eat this');
    expect(screen.getByPlaceholderText('feedback.placeholder')).toHaveValue('please do not eat this');
  });

  it('clears the draft only after a confirmed submit', async () => {
    render(<FeedbackWidget />);
    openAndType('ship it');
    expect(storedDraft()?.message).toBe('ship it');

    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    // The clear happens in a passive effect, so "thanks is on screen" does not
    // yet imply "storage is empty" — reading it synchronously here passes on an
    // idle machine and fails under load. Wait for the state being asserted.
    await waitFor(() =>
      expect(readUserScopedRaw(STORAGE_KEYS.FEEDBACK_DRAFT)).toBeNull(),
    );
  });
});

describe('idempotency token', () => {
  it('reuses the same clientToken across a retry of the same message', async () => {
    mockSubmitFeedback.mockResolvedValueOnce({ ok: false, reason: 'error' });
    render(<FeedbackWidget />);
    openAndType('retry me');
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-error')).toBeInTheDocument());

    const firstToken = tokenOfCall(0);
    expect(firstToken).toBeTruthy();
    expect(storedDraft()?.clientToken).toBe(firstToken);

    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(mockSubmitFeedback).toHaveBeenCalledTimes(2);
    expect(tokenOfCall(1)).toBe(firstToken);
  });

  it('mints a fresh token for the next message after a success', async () => {
    render(<FeedbackWidget />);
    openAndType('first message');
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());

    fireEvent.click(screen.getByText('feedback.close'));
    openAndType('second message');
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(mockSubmitFeedback).toHaveBeenCalledTimes(2));
    expect(tokenOfCall(1)).not.toBe(tokenOfCall(0));
  });
});

describe('ticket reference', () => {
  it('shows the first 8 chars of the ticket UUID', async () => {
    render(<FeedbackWidget />);
    openAndType('reference me');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-reference')).toBeInTheDocument());
    expect(screen.getByTestId('feedback-reference')).toHaveTextContent('7c9e6679');
  });

  it('copies the FULL uuid to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<FeedbackWidget />);
    openAndType('copy me');
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-copy-reference')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('feedback-copy-reference'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(TICKET_ID));
  });

  it('treats a 23505 duplicate as success: same reference, no error, no double count', async () => {
    mockSubmitFeedback.mockResolvedValue({ ok: true, reason: 'duplicate', id: TICKET_ID });
    render(<FeedbackWidget />);
    openAndType('already landed');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(screen.queryByTestId('feedback-error')).toBeNull();
    expect(screen.getByTestId('feedback-reference')).toHaveTextContent('7c9e6679');
    expect(screen.getByTestId('feedback-duplicate-note')).toBeInTheDocument();
    // The ticket was counted when it was created; a retry must not re-count it.
    expect(mockTrack).not.toHaveBeenCalled();
    // Same passive-effect timing as the clear-on-submit case above.
    await waitFor(() =>
      expect(readUserScopedRaw(STORAGE_KEYS.FEEDBACK_DRAFT)).toBeNull(),
    );
  });

  it('still thanks the user when the duplicate re-read could not fetch the id', async () => {
    mockSubmitFeedback.mockResolvedValue({ ok: true, reason: 'duplicate', id: null });
    render(<FeedbackWidget />);
    openAndType('no reference available');
    fireEvent.click(screen.getByTestId('feedback-send'));

    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(screen.queryByTestId('feedback-reference')).toBeNull();
  });
});

describe('validation', () => {
  it('blocks the submit on a malformed email and shows an inline field error', () => {
    render(<FeedbackWidget />);
    openAndType('valid message');
    fireEvent.change(screen.getByPlaceholderText('feedback.emailPlaceholder'), {
      target: { value: 'not-an-email' },
    });
    fireEvent.click(screen.getByTestId('feedback-send'));

    expect(mockSubmitFeedback).not.toHaveBeenCalled();
    expect(screen.getByTestId('feedback-email-error')).toBeInTheDocument();
    expect(screen.getByTestId('feedback-email')).toHaveAttribute('aria-invalid', 'true');
    // The draft is untouched — a validation refusal must not eat the text.
    expect(storedDraft()?.message).toBe('valid message');
  });

  it('clears the email error once the address is corrected and sends', async () => {
    render(<FeedbackWidget />);
    openAndType('valid message');
    const email = screen.getByPlaceholderText('feedback.emailPlaceholder');
    fireEvent.change(email, { target: { value: 'nope' } });
    fireEvent.click(screen.getByTestId('feedback-send'));
    expect(screen.getByTestId('feedback-email-error')).toBeInTheDocument();

    fireEvent.change(email, { target: { value: 'me@x.edu' } });
    expect(screen.queryByTestId('feedback-email-error')).toBeNull();
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
  });

  it('sends with an empty email without complaining (it is optional)', async () => {
    render(<FeedbackWidget />);
    openAndType('anonymous note');
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(mockSubmitFeedback).toHaveBeenCalledWith(expect.objectContaining({ email: null }));
  });

  it('caps the message at 4000 chars and counts what is typed', () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    const textarea = screen.getByPlaceholderText('feedback.placeholder');
    expect(textarea).toHaveAttribute('maxLength', '4000');
    expect(screen.getByTestId('feedback-subject')).toHaveAttribute('maxLength', '120');

    fireEvent.change(textarea, { target: { value: 'x'.repeat(12) } });
    const counter = screen.getByTestId('feedback-counter');
    expect(counter).toHaveTextContent('12');
    expect(counter).toHaveTextContent('4000');
  });
});

describe('timeout escape', () => {
  it('never wedges in sending: a hung insert lands in error with the draft intact', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // Never resolves — the pre-W15 widget stayed disabled forever here.
    mockSubmitFeedback.mockReturnValue(new Promise(() => {}));
    render(<FeedbackWidget />);
    openAndType('hangs forever');
    fireEvent.click(screen.getByTestId('feedback-send'));
    expect(screen.getByTestId('feedback-send')).toBeDisabled();

    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });

    expect(screen.getByTestId('feedback-error')).toHaveTextContent('feedback.errorTimeout');
    expect(screen.getByTestId('feedback-send')).toBeEnabled();
    expect(screen.getByPlaceholderText('feedback.placeholder')).toHaveValue('hangs forever');
    expect(storedDraft()?.message).toBe('hangs forever');
  });
});

describe('a draft written before the page could know who you are', () => {
  async function resolveOwnership() {
    advanceOwnerEpoch(OWNER_UID);
    await syncLocalIdentityOwner(OWNER_UID);
    for (let i = 0; i < 200 && !isLocalOwnerReady(OWNER_UID); i += 1) {
      await new Promise((r) => setTimeout(r, 0));
    }
  }

  it('comes back once ownership resolves, instead of being overwritten', async () => {
    // The widget is in the root layout, so it mounts during the first client
    // render — before ensureAnonSession resolves. The scoped read returned
    // null and useState froze that for the life of the page: the widget opened
    // empty, and one keystroke overwrote the stored draft.
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    fireEvent.change(screen.getByPlaceholderText('feedback.placeholder'), {
      target: { value: 'half-written thought' },
    });
    expect(storedDraft()?.message).toBe('half-written thought');

    // A reload: unmount, and start the next document with nothing resolved.
    cleanup();
    advanceOwnerEpoch(null);

    render(<FeedbackWidget />);
    await act(async () => { await resolveOwnership(); });
    await waitFor(() => {});

    fireEvent.click(screen.getByTestId('feedback-open'));
    const box = screen.getByPlaceholderText('feedback.placeholder') as HTMLTextAreaElement;
    expect(box.value).toBe('half-written thought');
  });
});
