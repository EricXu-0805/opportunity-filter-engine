/*
 * SaveSearchDialog interaction tests.
 *
 * The core invariant pinned here is the opt-in contract: onSave only ever
 * carries a digest object when the user explicitly checked the opt-in AND
 * supplied a valid email — everything else produces digest: null. Plus the
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
  screen.queryByPlaceholderText('results.saveSearchDialog.digestEmailPlaceholder');
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
    const { onSave } = renderDialog();
    expect(optInCheckbox()).not.toBeChecked();

    fireEvent.change(nameInput(), { target: { value: '  Paid ML  ' } });
    // A typed email WITHOUT the checkbox must not opt the user in.
    fireEvent.change(emailInput()!, { target: { value: 'user@example.com' } });
    fireEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledWith({ name: 'Paid ML', digest: null });
  });

  it('blocks save and shows an error when opted in with an invalid email', () => {
    const { onSave } = renderDialog();
    fireEvent.change(nameInput(), { target: { value: 'Paid ML' } });
    fireEvent.click(optInCheckbox());
    fireEvent.change(emailInput()!, { target: { value: 'not-an-email' } });
    fireEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText('results.saveSearchDialog.digestEmailInvalid')).toBeInTheDocument();
  });

  it('passes the digest through when opted in with a valid email', () => {
    const { onSave } = renderDialog();
    fireEvent.change(nameInput(), { target: { value: 'Paid ML' } });
    fireEvent.click(optInCheckbox());
    fireEvent.change(emailInput()!, { target: { value: ' user@example.com ' } });
    fireEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledWith({
      name: 'Paid ML',
      digest: { email: 'user@example.com', optIn: true },
    });
  });

  it('clears the email error once the user edits again', () => {
    renderDialog();
    fireEvent.change(nameInput(), { target: { value: 'Paid ML' } });
    fireEvent.click(optInCheckbox());
    fireEvent.change(emailInput()!, { target: { value: 'bad' } });
    fireEvent.click(saveButton());
    expect(screen.getByText('results.saveSearchDialog.digestEmailInvalid')).toBeInTheDocument();

    fireEvent.change(emailInput()!, { target: { value: 'user@example.com' } });
    expect(screen.queryByText('results.saveSearchDialog.digestEmailInvalid')).toBeNull();
  });

  it('cancels via the close button and Escape', () => {
    const { onCancel } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: 'results.saveSearchDialog.closeAria' }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
});
