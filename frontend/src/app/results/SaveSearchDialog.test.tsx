/*
 * SaveSearchDialog interaction tests.
 *
 * The core invariant pinned here is the opt-in contract: onSave only ever
 * carries a digest object when the user explicitly checked the opt-in, and
 * then only for the signed-in account's confirmed email — the one address
 * the digest cron sends to. Everything else produces digest: null. Plus the
 * pre-migration degradation: digestAvailable=false hides the digest block
 * entirely.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/lib/supabase', () => ({
  supabase: { from: vi.fn() },
  getDeviceId: vi.fn(),
}));

import { SaveSearchDialog } from './SaveSearchDialog';

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${JSON.stringify(vars)}` : key;

function renderDialog(overrides: Partial<Parameters<typeof SaveSearchDialog>[0]> = {}) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  render(
    <SaveSearchDialog
      digestAvailable
      onCancel={onCancel}
      onSave={onSave}
      t={t}
      {...overrides}
    />,
  );
  return { onSave, onCancel };
}

const nameInput = () =>
  screen.getByPlaceholderText('results.saveSearchDialog.namePlaceholder');
const emailInput = () =>
  screen.queryByLabelText('results.saveSearchDialog.digestEmailLabel');
const optInCheckbox = () => screen.getByRole('checkbox');
const saveButton = () =>
  screen.getByRole('button', { name: 'results.saveSearchDialog.save' });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SaveSearchDialog', () => {
  it('hides the digest block when migration 013 is unavailable', () => {
    const { onSave } = renderDialog({ digestAvailable: false });
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(emailInput()).toBeNull();

    fireEvent.change(nameInput(), { target: { value: 'ML labs' } });
    fireEvent.click(saveButton());
    expect(onSave).toHaveBeenCalledWith({ name: 'ML labs', digest: null });
  });

  it('disables save until a name is entered', () => {
    renderDialog();
    expect(saveButton()).toBeDisabled();
    fireEvent.change(nameInput(), { target: { value: 'X' } });
    expect(saveButton()).not.toBeDisabled();
  });

  it('saves with digest: null when opt-in is unchecked (the default)', () => {
    const { onSave } = renderDialog({ accountEmail: 'me@example.com' });
    expect(optInCheckbox()).not.toBeChecked();

    fireEvent.change(nameInput(), { target: { value: '  Paid ML  ' } });
    fireEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledWith({ name: 'Paid ML', digest: null });
  });

  it('shows the account email read-only and sends the digest only there', () => {
    // The digest cron sends only to the account's confirmed address, so that
    // is the address shown, and it cannot be edited into another one.
    const { onSave } = renderDialog({ accountEmail: 'me@example.com' });
    expect(emailInput()).toHaveValue('me@example.com');
    expect(emailInput()).toHaveAttribute('readonly');

    fireEvent.change(nameInput(), { target: { value: 'Paid ML' } });
    fireEvent.click(optInCheckbox());
    fireEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledWith({
      name: 'Paid ML',
      digest: { email: 'me@example.com', optIn: true },
    });
  });

  it('cannot turn the digest on without a confirmed account email', () => {
    const { onSave } = renderDialog({ accountEmail: null });
    expect(optInCheckbox()).toBeDisabled();
    expect(emailInput()).toBeNull();
    expect(screen.getByText('results.saveSearchDialog.digestNeedsAccount')).toBeInTheDocument();

    fireEvent.change(nameInput(), { target: { value: 'Paid ML' } });
    fireEvent.click(optInCheckbox());
    fireEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledWith({ name: 'Paid ML', digest: null });
  });

  it('cancels via the close button and Escape', () => {
    const { onCancel } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: 'results.saveSearchDialog.closeAria' }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
});
