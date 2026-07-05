import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { ConciergeCta } from './ConciergeCta';
import { STORAGE_KEYS } from '@/lib/storage-keys';

vi.mock('@/lib/analytics', () => ({
  track: vi.fn(),
  trackOnce: vi.fn(),
}));

const t = (key: string) => key;

describe('ConciergeCta', () => {
  beforeEach(() => localStorage.clear());

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

  it('records the intent click', async () => {
    const analytics = await import('@/lib/analytics');
    render(<ConciergeCta t={t} />);
    fireEvent.click(screen.getByRole('link', { name: 'results.conciergeCta.button' }));
    expect(analytics.track).toHaveBeenCalledWith('intent_clicked', { source: 'results' });
  });
});
