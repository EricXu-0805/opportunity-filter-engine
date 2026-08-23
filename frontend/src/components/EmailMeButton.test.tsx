import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ApiError } from '@/lib/api';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

const getAuthState = vi.fn();
vi.mock('@/lib/supabase', () => ({
  getAuthState: (...args: unknown[]) => getAuthState(...args),
}));

const openModal = vi.fn();
vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({ openModal }),
}));

import EmailMeButton from './EmailMeButton';

/** A signed-in account with an address GoTrue reports as confirmed.
 *
 *  `email_confirmed_at` is what makes it confirmed. `getAuthState().email`
 *  carries the raw address either way — the account menu has to show it — so a
 *  mock that omits the stamp is an UNCONFIRMED account, not a confirmed one.
 */
function signedIn(email: string | null = 'user@example.com') {
  getAuthState.mockResolvedValue({
    session: { user: { id: 'u1' } },
    user: { id: 'u1', email, email_confirmed_at: '2026-01-01T00:00:00Z' },
    isAnonymous: false,
    email,
  });
}

/** Signed in, holding an address the account never confirmed.
 *
 *  The real shape of this case: the address is PRESENT and unconfirmed. An
 *  earlier version of these tests simulated it with `email: null`, which
 *  `getAuthState` never returns for a signed-in account — so the gate passed
 *  its test while the production path sent the reader straight to a refusal.
 */
function signedInUnconfirmed(email = 'typo@example.com') {
  getAuthState.mockResolvedValue({
    session: { user: { id: 'u1' } },
    user: { id: 'u1', email, email_confirmed_at: null, confirmed_at: null },
    isAnonymous: false,
    email,
  });
}

function anonymous() {
  getAuthState.mockResolvedValue({
    session: { user: { id: 'anon' } },
    user: { id: 'anon' },
    isAnonymous: true,
    email: null,
  });
}

async function openDialog() {
  fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
  // The recipient resolves asynchronously; every assertion below depends on
  // that having settled, so waiting for it here keeps it out of each test.
  await waitFor(() => expect(getAuthState).toHaveBeenCalled());
}

function submitForm() {
  const form = document.querySelector('form');
  if (!form) throw new Error('form not found');
  fireEvent.submit(form);
}

beforeEach(() => {
  localStorage.clear();
  getAuthState.mockReset();
  openModal.mockReset();
  signedIn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('EmailMeButton', () => {
  it('renders the trigger button with the supplied label', () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Email me/ })).toBeInTheDocument();
  });

  it('honors the disabled prop on the trigger', () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} disabled />);
    expect(screen.getByRole('button', { name: /Email me/ })).toBeDisabled();
  });

  it('closes the dialog when ESC is pressed', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    await openDialog();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('closes the dialog when Cancel is clicked', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    await openDialog();
    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('renders aria-modal="true" on the dialog', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    await openDialog();
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });
});

describe('the recipient is the session, never a typed address', () => {
  it('never offers a free-text recipient field', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    await openDialog();
    // The whole point of the change: an address typed here used to become the
    // send target, which is what let a stranger mail a JoinALab digest to
    // anyone. There is no such field any more, in any of the three states.
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('shows the confirmed session address as the destination', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    await openDialog();
    await waitFor(() =>
      expect(screen.getByText('user@example.com')).toBeInTheDocument());
  });

  it('sends to the session address, normalised', async () => {
    signedIn('  USER@Example.COM  ');
    const onSend = vi.fn().mockResolvedValue({ ok: true, count: 1 });
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    await openDialog();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'email.send' })).toBeEnabled());
    submitForm();
    await waitFor(() => expect(onSend).toHaveBeenCalledWith('user@example.com'));
    await waitFor(() =>
      expect(screen.getByText('email.sentMessage')).toBeInTheDocument());
  });

  it('offers sign-in instead of a send when the visitor is anonymous', async () => {
    anonymous();
    const onSend = vi.fn();
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    await openDialog();
    await waitFor(() =>
      expect(screen.getByText('email.signInRequired')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'email.send' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'email.signInCta' }));
    expect(openModal).toHaveBeenCalledWith({ reason: 'email-digest' });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('asks for confirmation when the account holds an unconfirmed address', async () => {
    // The case this gate exists for, since anyone can type a stranger's
    // address at sign-up. The address is present — it is the missing
    // confirmation stamp that disqualifies it.
    signedInUnconfirmed();
    const onSend = vi.fn();
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    await openDialog();
    await waitFor(() =>
      expect(screen.getByText('email.confirmRequired')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'email.send' })).toBeDisabled();
    submitForm();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('never shows an unconfirmed address as the send target', async () => {
    // The address must not appear where the confirmed one does, or the reader
    // reasonably concludes it is about to be mailed.
    signedInUnconfirmed('typo@example.com');
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    await openDialog();
    await waitFor(() =>
      expect(screen.getByText('email.confirmRequired')).toBeInTheDocument());
    expect(screen.queryByText('typo@example.com')).not.toBeInTheDocument();
  });
});

describe('failures say which one happened', () => {
  async function sendAndExpect(err: unknown, key: string) {
    const onSend = vi.fn().mockRejectedValue(err);
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    await openDialog();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'email.send' })).toBeEnabled());
    submitForm();
    await waitFor(() => expect(screen.getByText(key)).toBeInTheDocument());
  }

  it('maps 503 to email.notConfigured', async () => {
    await sendAndExpect(new Error('HTTP 503: Email not configured'),
                        'email.notConfigured');
  });

  it('maps 429 to email.rateLimit', async () => {
    await sendAndExpect(new Error('HTTP 429: Too many requests'),
                        'email.rateLimit');
  });

  it('maps a 401 to the sign-in prompt rather than a generic failure', async () => {
    // The session can expire between opening the dialog and submitting.
    await sendAndExpect(new ApiError(401, 'SIGN_IN_REQUIRED', 'sign in', false), 'email.signInRequired');
  });

  it('maps a 409 to the not-your-address message', async () => {
    // Unreachable from this UI, but the server refuses rather than silently
    // redirecting, and the page must repeat that rather than say "failed".
    await sendAndExpect(new ApiError(409, 'RECIPIENT_NOT_SELF', 'not self', false), 'email.notSelf');
  });

  it('tells the other 409 apart and asks for confirmation, not a different address', async () => {
    // Both identity refusals are 409. Matching on status alone answered this
    // one with "nothing was sent to the address you entered" — wrong remedy,
    // and about a field the dialog no longer has. The code is the difference.
    await sendAndExpect(new ApiError(409, 'EMAIL_NOT_CONFIRMED', 'confirm first', false),
                        'email.confirmRequired');
  });

  it('falls back to email.sendFailed for unrecognised errors', async () => {
    await sendAndExpect(new Error('network blowup'), 'email.sendFailed');
  });
});
