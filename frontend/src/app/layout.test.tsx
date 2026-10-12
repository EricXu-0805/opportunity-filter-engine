import { describe, expect, it, vi } from 'vitest';

vi.mock('next/font/google', () => ({
  Inter: () => ({ className: 'inter', variable: '--font-inter' }),
}));
vi.mock('@/i18n/server', () => ({ getServerLocale: async () => 'en' }));
vi.mock('@/components/AuthModal', () => ({ default: () => null }));
vi.mock('@/components/BackendWaker', () => ({ default: () => null }));
vi.mock('@/components/GuestBanner', () => ({ default: () => null }));
vi.mock('@/components/FeedbackWidget', () => ({ default: () => null }));
vi.mock('@/components/OnboardingIntro', () => ({ default: () => null }));
vi.mock('@/components/SchoolConfirmGate', () => ({ default: () => null }));
vi.mock('@/components/Header', () => ({ default: () => null }));

import { viewport } from './layout';

describe('root layout viewport', () => {
  // A soft keyboard must shrink the layout viewport on every page, so dvh-sized
  // dialogs such as the cold-email editor re-fit above it.
  it('asks phones to resize the page content when the keyboard opens', () => {
    expect(viewport.interactiveWidget).toBe('resizes-content');
  });
});
