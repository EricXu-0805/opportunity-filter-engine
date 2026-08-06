import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { ConciergeCta } from './ConciergeCta';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, writeUserScopedRaw } from '@/lib/identity-owner';

vi.mock('@/lib/analytics', () => ({
  track: vi.fn(),
  trackOnce: vi.fn(),
}));

const t = (key: string) => key;

describe('ConciergeCta', () => {
  beforeEach(async () => {
    localStorage.clear();
    advanceOwnerEpoch('concierge-test-uid');
    await syncLocalIdentityOwner('concierge-test-uid');
  });

  it('renders title, description, and a link to /account', () => {
    render(<ConciergeCta t={t} />);
    expect(screen.getByTestId('concierge-cta')).toBeInTheDocument();
    expect(screen.getByText('results.conciergeCta.title')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'results.conciergeCta.button' })).toHaveAttribute(
      'href',
      '/account',
    );
  });

  it('dismiss hides the card and persists across mounts', () => {
    const { unmount } = render(<ConciergeCta t={t} />);
    fireEvent.click(screen.getByTestId('concierge-cta-dismiss'));
    expect(screen.queryByTestId('concierge-cta')).not.toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEYS.RESULTS_CTA_DISMISSED)).toBe('1');
    unmount();
    render(<ConciergeCta t={t} />);
    expect(screen.queryByTestId('concierge-cta')).not.toBeInTheDocument();
  });

  it('a DIFFERENT owner\'s existing dismissal is not shown to a fresh, un-dismissed owner (post-sweep)', async () => {
    writeUserScopedRaw(STORAGE_KEYS.RESULTS_CTA_DISMISSED, '1', captureOwnerToken());
    advanceOwnerEpoch('concierge-test-uid-2');
    await syncLocalIdentityOwner('concierge-test-uid-2');
    render(<ConciergeCta t={t} />);
    expect(screen.getByTestId('concierge-cta')).toBeInTheDocument();
  });

  it('the previous owner\'s raw dismiss value, still sitting in storage mid-transition (BEFORE the sweep has run), is never shown to the incoming owner', () => {
    // Real ordering: advanceOwnerEpoch fires SYNCHRONOUSLY and blocks
    // readiness immediately; syncLocalIdentityOwner (which sweeps the old
    // value) only runs afterward, at whatever choke point observes the new
    // uid. In between, the OLD raw bytes are still genuinely in localStorage
    // — only the readiness gate stands between them and the new owner.
    writeUserScopedRaw(STORAGE_KEYS.RESULTS_CTA_DISMISSED, '1', captureOwnerToken());
    advanceOwnerEpoch('concierge-test-uid-2'); // blocked — sweep has NOT run yet
    expect(localStorage.getItem(STORAGE_KEYS.RESULTS_CTA_DISMISSED)).toBe('1'); // sanity: still raw-present

    render(<ConciergeCta t={t} />);
    expect(screen.getByTestId('concierge-cta')).toBeInTheDocument();
  });

  it('dismissing while the identity is mid-transition (blocked) does not hide the card — writeUserScopedRaw\'s own gate rejects the write, and the re-read resolves the same truth regardless of the dispatch', () => {
    render(<ConciergeCta t={t} />);
    advanceOwnerEpoch('concierge-test-uid-2'); // real transition, not yet synced -> blocked
    fireEvent.click(screen.getByTestId('concierge-cta-dismiss'));
    expect(screen.getByTestId('concierge-cta')).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEYS.RESULTS_CTA_DISMISSED)).toBeNull();
  });

  it('records the intent click', async () => {
    const analytics = await import('@/lib/analytics');
    render(<ConciergeCta t={t} />);
    fireEvent.click(screen.getByRole('link', { name: 'results.conciergeCta.button' }));
    expect(analytics.track).toHaveBeenCalledWith('intent_clicked', { source: 'results' });
  });
});
