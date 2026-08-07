import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, writeUserScopedRaw } from '@/lib/identity-owner';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

import EmailMeButton from './EmailMeButton';

const LS_KEY = 'ofe_email_hint';

beforeEach(async () => {
  localStorage.clear();
  advanceOwnerEpoch('email-me-test-uid');
  await syncLocalIdentityOwner('email-me-test-uid');
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

  it('opens the dialog when the trigger is clicked', () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('closes the dialog when ESC is pressed', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('closes the dialog when Cancel is clicked', async () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('prefills the email from localStorage when opening', () => {
    writeUserScopedRaw(LS_KEY, 'cached@example.com', captureOwnerToken());
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    const input = screen.getByRole('textbox') as HTMLInputElement;
    expect(input.value).toBe('cached@example.com');
  });

  function submitForm() {
    const form = document.querySelector('form');
    if (!form) throw new Error('form not found');
    fireEvent.submit(form);
  }

  it('rejects an invalid email and shows error.invalidEmail', async () => {
    const onSend = vi.fn();
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'not-an-email' } });
    submitForm();
    await waitFor(() => expect(screen.getByText('email.invalidEmail')).toBeInTheDocument());
    expect(onSend).not.toHaveBeenCalled();
  });

  it('sends a valid email, persists it, and shows the sent state', async () => {
    const onSend = vi.fn().mockResolvedValue({ ok: true, count: 1 });
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'user@example.com' } });
    submitForm();
    await waitFor(() => expect(onSend).toHaveBeenCalledWith('user@example.com'));
    await waitFor(() => expect(screen.getByText('email.sentMessage')).toBeInTheDocument());
    expect(localStorage.getItem(LS_KEY)).toBe('user@example.com');
  });

  it('a deferred send that resolves AFTER the owner switches does not write the email hint under the new owner', async () => {
    let resolveSend!: (v: { ok: boolean }) => void;
    const onSend = vi.fn(() => new Promise<{ ok: boolean }>((r) => { resolveSend = r; }));
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'user@example.com' } });
    submitForm();
    await waitFor(() => expect(onSend).toHaveBeenCalled());

    advanceOwnerEpoch('email-me-test-uid-2');
    await syncLocalIdentityOwner('email-me-test-uid-2');

    resolveSend({ ok: true });
    await waitFor(() => expect(screen.getByText('email.sentMessage')).toBeInTheDocument());

    // The send itself succeeded (still shows "sent"), but the hint must not
    // be attributed to the NEW owner under the OLD (now-stale) identity's
    // submission — and must not have clobbered the new owner's own slot.
    expect(localStorage.getItem(LS_KEY)).toBeNull();
  });

  it('lowercases and trims the email before sending', async () => {
    const onSend = vi.fn().mockResolvedValue({ ok: true });
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  UPPER@Example.COM  ' } });
    submitForm();
    await waitFor(() => expect(onSend).toHaveBeenCalledWith('upper@example.com'));
  });

  it('maps a 503 error to email.notConfigured', async () => {
    const onSend = vi.fn().mockRejectedValue(new Error('HTTP 503: Email not configured'));
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'user@example.com' } });
    submitForm();
    await waitFor(() => expect(screen.getByText('email.notConfigured')).toBeInTheDocument());
  });

  it('maps a 429 error to email.rateLimit', async () => {
    const onSend = vi.fn().mockRejectedValue(new Error('HTTP 429: Too many requests'));
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'user@example.com' } });
    submitForm();
    await waitFor(() => expect(screen.getByText('email.rateLimit')).toBeInTheDocument());
  });

  it('falls back to email.sendFailed for unrecognised errors', async () => {
    const onSend = vi.fn().mockRejectedValue(new Error('network blowup'));
    render(<EmailMeButton label="Email me" onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'user@example.com' } });
    submitForm();
    await waitFor(() => expect(screen.getByText('email.sendFailed')).toBeInTheDocument());
  });

  it('disables the Send button while idle with an empty email', () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    const sendBtn = screen.getByRole('button', { name: 'email.send' });
    expect(sendBtn).toBeDisabled();
  });

  it('renders aria-modal="true" on the dialog', () => {
    render(<EmailMeButton label="Email me" onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Email me/ }));
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });
});
