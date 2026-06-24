/*
 * OnboardingIntro: 8-slide product tour. First-visit gate (localStorage),
 * Back/Next paging, and "Try it" completion. analytics is mocked; i18n returns
 * the key verbatim. localStorage is real in jsdom and cleared between tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockTrack = vi.fn();

vi.mock('@/lib/analytics', () => ({ track: (...args: unknown[]) => mockTrack(...args) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

import OnboardingIntro from './OnboardingIntro';

const SLIDE_COUNT = 8;

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('OnboardingIntro', () => {
  it('shows on first visit when no seen flag is set', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => expect(screen.getByTestId('onboarding-intro')).toBeInTheDocument());
  });

  it('stays hidden once the seen flag is set', async () => {
    localStorage.setItem('ofe_onboarding_seen', '1');
    const { container } = render(<OnboardingIntro />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull();
  });

  it('starts on the first slide with Skip, and reveals Back after advancing', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-skip'));
    expect(screen.queryByTestId('onboarding-back')).toBeNull();
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    expect(screen.getByTestId('onboarding-back')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('onboarding-back'));
    expect(screen.getByTestId('onboarding-skip')).toBeInTheDocument();
  });

  it('pages through to the end and completes via "Try it" (marks seen + tracks)', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-primary'));
    // Advance to the last slide, then one more click completes the tour.
    for (let k = 0; k < SLIDE_COUNT; k += 1) {
      fireEvent.click(screen.getByTestId('onboarding-primary'));
    }
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).toHaveBeenCalledWith('onboarding_completed');
  });

  it('Skip on the first slide marks seen and closes without tracking completion', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-skip'));
    fireEvent.click(screen.getByTestId('onboarding-skip'));
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).not.toHaveBeenCalled();
  });
});
