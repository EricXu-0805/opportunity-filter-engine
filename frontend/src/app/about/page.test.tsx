import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/i18n/server', () => ({ getServerT: async () => (key: string) => key }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

import AboutPage from './page';

describe('About page', () => {
  // The tour's four screenshots were captured on 2026-07-06: they showed the
  // retired Fellowships and Roadmap nav, an "AI match" toggle that is closed,
  // a real faculty email in full, and a "never stored permanently" résumé
  // claim the privacy section on the same page contradicts.
  it('describes the release product without the outdated screenshots', async () => {
    const { container } = render(await AboutPage());
    expect(container.querySelector('img')).toBeNull();
    for (const step of ['profile', 'matches', 'email', 'tracker']) {
      expect(screen.getByText(`home.walkthrough.steps.${step}.title`)).toBeInTheDocument();
      expect(screen.getByText(`home.walkthrough.steps.${step}.caption`)).toBeInTheDocument();
    }
    expect(screen.queryByText('home.walkthrough.steps.compare.title')).toBeNull();
    expect(screen.queryByText('home.walkthrough.steps.act.title')).toBeNull();
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(4);
  });

  it('no longer holds a place for a portrait that does not exist', async () => {
    render(await AboutPage());
    expect(screen.queryByText('about.photoComing')).toBeNull();
    expect(screen.getByText('about.author')).toBeInTheDocument();
  });
});
