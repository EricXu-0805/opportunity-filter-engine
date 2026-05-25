import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

const getStorageStatus = vi.fn();
const onStorageStatusChange = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getStorageStatus: () => getStorageStatus(),
  onStorageStatusChange: (cb: () => void) => onStorageStatusChange(cb),
}));

import StorageStatusBanner from './StorageStatusBanner';

beforeEach(() => {
  getStorageStatus.mockReset();
  onStorageStatusChange.mockReset();
  onStorageStatusChange.mockReturnValue(() => {});
});

describe('StorageStatusBanner', () => {
  it('renders nothing when status is unknown', () => {
    getStorageStatus.mockReturnValue({ status: 'unknown', error: null });
    const { container } = render(<StorageStatusBanner />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when status is synced', () => {
    getStorageStatus.mockReturnValue({ status: 'synced', error: null });
    const { container } = render(<StorageStatusBanner />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the warning role + headline when status is local-only', () => {
    getStorageStatus.mockReturnValue({ status: 'local-only', error: null });
    render(<StorageStatusBanner />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Saved locally only/i)).toBeInTheDocument();
    expect(screen.getByText(/won't appear on other devices/i)).toBeInTheDocument();
  });

  it('omits the monospace error block when error is null', () => {
    getStorageStatus.mockReturnValue({ status: 'local-only', error: null });
    const { container } = render(<StorageStatusBanner />);
    expect(container.querySelector('p.font-mono')).toBeNull();
  });

  it('renders the error string in a monospace block when present', () => {
    getStorageStatus.mockReturnValue({
      status: 'local-only',
      error: 'Anonymous sign-ins are disabled for this Supabase project.',
    });
    render(<StorageStatusBanner />);
    expect(
      screen.getByText('Anonymous sign-ins are disabled for this Supabase project.'),
    ).toBeInTheDocument();
  });

  it('subscribes to onStorageStatusChange on mount and unsubscribes on unmount', () => {
    getStorageStatus.mockReturnValue({ status: 'unknown', error: null });
    const unsubscribe = vi.fn();
    onStorageStatusChange.mockReturnValue(unsubscribe);

    const { unmount } = render(<StorageStatusBanner />);

    expect(onStorageStatusChange).toHaveBeenCalledTimes(1);
    expect(unsubscribe).not.toHaveBeenCalled();

    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('re-renders when the status callback fires after a status change', () => {
    let storedCallback: (() => void) | null = null;
    getStorageStatus.mockReturnValue({ status: 'unknown', error: null });
    onStorageStatusChange.mockImplementation((cb: () => void) => {
      storedCallback = cb;
      return () => {};
    });

    const { container } = render(<StorageStatusBanner />);
    expect(container.firstChild).toBeNull();

    getStorageStatus.mockReturnValue({ status: 'local-only', error: 'network down' });
    act(() => {
      storedCallback?.();
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('network down')).toBeInTheDocument();
  });
});
