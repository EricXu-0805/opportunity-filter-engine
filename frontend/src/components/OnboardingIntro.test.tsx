/*
 * OnboardingIntro: first-visit gate (localStorage) + CTA/skip dismissal.
 * analytics is mocked; i18n returns the key verbatim. localStorage is real in
 * jsdom and cleared between tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockTrack = vi.fn();

vi.mock('@/lib/analytics', () => ({ track: (...args: unknown[]) => mockTrack(...args) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

import OnboardingIntro from './OnboardingIntro';

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

  it('CTA marks seen, tracks completion, and closes', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByTestId('onboarding-cta'));
    fireEvent.click(screen.getByTestId('onboarding-cta'));
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).toHaveBeenCalledWith('onboarding_completed');
  });

  it('Skip marks seen and closes without tracking completion', async () => {
    const { container } = render(<OnboardingIntro />);
    await waitFor(() => screen.getByText('onboarding.skip'));
    fireEvent.click(screen.getByText('onboarding.skip'));
    await waitFor(() =>
      expect(container.querySelector('[data-testid="onboarding-intro"]')).toBeNull(),
    );
    expect(localStorage.getItem('ofe_onboarding_seen')).toBe('1');
    expect(mockTrack).not.toHaveBeenCalled();
  });
});
