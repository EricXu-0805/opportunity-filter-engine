import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

const mockRefresh = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mockRefresh, push: vi.fn() }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string) => key,
  }),
}));

import OpportunityUnavailable from './OpportunityUnavailable';

afterEach(() => {
  cleanup();
  mockRefresh.mockReset();
});

describe('OpportunityUnavailable', () => {
  it('renders bilingual-ready copy via translation keys, not a 404 message', () => {
    render(<OpportunityUnavailable />);
    expect(screen.getByText('detail.unavailable.title')).toBeInTheDocument();
    expect(screen.getByText('detail.unavailable.message')).toBeInTheDocument();
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument();
  });

  it('starts idle: the retry control is not busy or disabled before any click', () => {
    render(<OpportunityUnavailable />);
    const button = screen.getByRole('button', { name: 'common.retry' });
    expect(button).toHaveAttribute('aria-busy', 'false');
    expect(button).not.toBeDisabled();
  });

  it('retry invocation is steady: every click calls router.refresh(), repeatedly', () => {
    // router.refresh() returns void in the real App Router — this only
    // proves the control keeps invoking it, not any pending-duration timing.
    // The real busy/disabled/"retrying" window comes from React's transition
    // integration with Next's Suspense-driven refresh, which isn't something
    // a void-returning mock can honestly simulate here.
    render(<OpportunityUnavailable />);
    const button = screen.getByRole('button', { name: 'common.retry' });

    fireEvent.click(button);
    expect(mockRefresh).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(mockRefresh).toHaveBeenCalledTimes(2);
  });
});
