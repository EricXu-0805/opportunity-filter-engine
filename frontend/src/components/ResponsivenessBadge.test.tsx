import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/api', () => ({
  getResponsivenessSignals: vi.fn(),
}));

vi.mock('@/lib/responsiveness', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/responsiveness')>();
  return { ...actual, getResponsivenessSignal: vi.fn() };
});

import { getResponsivenessSignals } from '@/lib/api';
import {
  getResponsivenessSignal,
  showsHeardBackBadge,
  RESPONSIVENESS_MIN_CONTACTED,
} from '@/lib/responsiveness';
import ResponsivenessBadge from './ResponsivenessBadge';

const mockSignal = vi.mocked(getResponsivenessSignal);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('showsHeardBackBadge', () => {
  it('requires at least 3 contacted devices', () => {
    expect(RESPONSIVENESS_MIN_CONTACTED).toBe(3);
    expect(showsHeardBackBadge({ contacted_n: 2, replied_n: 2 })).toBe(false);
    expect(showsHeardBackBadge({ contacted_n: 3, replied_n: 1 })).toBe(true);
  });

  it('requires at least one reply', () => {
    expect(showsHeardBackBadge({ contacted_n: 5, replied_n: 0 })).toBe(false);
  });

  it('is false for missing signals', () => {
    expect(showsHeardBackBadge(null)).toBe(false);
    expect(showsHeardBackBadge(undefined)).toBe(false);
  });
});

describe('ResponsivenessBadge', () => {
  it('renders the anonymous aggregate badge at N>=3 with a reply', async () => {
    mockSignal.mockResolvedValue({ contacted_n: 3, replied_n: 1 });
    render(<ResponsivenessBadge opportunityId="opp-1" />);
    expect(await screen.findByText('Students recently heard back')).toBeInTheDocument();
  });

  it('renders nothing below the N>=3 gate', async () => {
    mockSignal.mockResolvedValue({ contacted_n: 2, replied_n: 2 });
    const { container } = render(<ResponsivenessBadge opportunityId="opp-2" />);
    await waitFor(() => expect(mockSignal).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing without any reply', async () => {
    mockSignal.mockResolvedValue({ contacted_n: 6, replied_n: 0 });
    const { container } = render(<ResponsivenessBadge opportunityId="opp-3" />);
    await waitFor(() => expect(mockSignal).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when no signal exists for the opportunity', async () => {
    mockSignal.mockResolvedValue(null);
    const { container } = render(<ResponsivenessBadge opportunityId="opp-4" />);
    await waitFor(() => expect(mockSignal).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it('never shows raw counts or rates', async () => {
    mockSignal.mockResolvedValue({ contacted_n: 12, replied_n: 9 });
    render(<ResponsivenessBadge opportunityId="opp-5" />);
    await screen.findByText('Students recently heard back');
    expect(screen.queryByText(/12|9|%/)).toBeNull();
  });
});

describe('shared fetch cache', () => {
  it('fetches the bulk map once for many badge lookups', async () => {
    const actual =
      await vi.importActual<typeof import('@/lib/responsiveness')>('@/lib/responsiveness');
    vi.mocked(getResponsivenessSignals).mockResolvedValue({
      'opp-a': { contacted_n: 4, replied_n: 2 },
    });
    const [a, b] = await Promise.all([
      actual.getResponsivenessSignal('opp-a'),
      actual.getResponsivenessSignal('opp-b'),
    ]);
    expect(a).toEqual({ contacted_n: 4, replied_n: 2 });
    expect(b).toBeNull();
    expect(getResponsivenessSignals).toHaveBeenCalledTimes(1);
  });
});
