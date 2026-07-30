/*
 * OnboardingIntro: accepted-release product tour. First-visit gate (localStorage),
 * Back/Next paging, and "Try it" completion. analytics is mocked; i18n returns
 * the key verbatim. localStorage is real in jsdom and cleared between tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockTrack = vi.fn();

vi.mock('@/lib/analytics', () => ({ track: (...args: unknown[]) => mockTrack(...args) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

import OnboardingIntro from './OnboardingIntro';

const SLIDE_COUNT = 6;

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

  it('keeps Skip available through the feature slides and reveals Back only after the first', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-skip'));
    expect(screen.queryByTestId('onboarding-back')).toBeNull();
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    // Skip stays put once advanced; Back now appears alongside it.
    expect(screen.getByTestId('onboarding-skip')).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-back')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('onboarding-back'));
    expect(screen.getByTestId('onboarding-skip')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-back')).toBeNull();
  });

  it('does not advertise dormant Compare or Roadmap slides', async () => {
    render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-intro'));
    expect(screen.getByText(`1 / ${SLIDE_COUNT}`)).toBeInTheDocument();
    expect(screen.queryByText('onboarding.compareTitle')).not.toBeInTheDocument();
    expect(screen.queryByText('onboarding.roadmapTitle')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    expect(screen.getByText('onboarding.exResearch')).toBeInTheDocument();
    expect(screen.queryByText('onboarding.exFellowship')).not.toBeInTheDocument();
  });

  it('pages through to the end and completes via the school gate (default UIUC: seen + tracked + persisted)', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-primary'));
    // Advance to the final (school) slide, then one more click confirms the default.
    for (let k = 0; k < SLIDE_COUNT; k += 1) {
      fireEvent.click(screen.getByTestId('onboarding-primary'));
    }
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).toHaveBeenCalledWith('onboarding_completed', { school: 'uiuc' });
    expect(JSON.parse(localStorage.getItem('ofe_profile') ?? '{}').home_school).toBe('uiuc');
  });

  it('Skip routes to the forced school gate (does not close until a campus is confirmed)', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-skip'));

    // Skip jumps straight to the gate rather than dismissing.
    fireEvent.click(screen.getByTestId('onboarding-skip'));
    expect(screen.getByTestId('onboarding-school-list')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="onboarding-intro"]')).not.toBeNull();
    expect(screen.queryByTestId('onboarding-skip')).toBeNull();
    expect(mockTrack).not.toHaveBeenCalled();

    // Pick a non-default campus, then confirm.
    fireEvent.click(screen.getByTestId('onboarding-school-ucb'));
    fireEvent.click(screen.getByTestId('onboarding-primary'));
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).toHaveBeenCalledWith('onboarding_completed', { school: 'ucb' });
    expect(JSON.parse(localStorage.getItem('ofe_profile') ?? '{}').home_school).toBe('ucb');
  });
});
