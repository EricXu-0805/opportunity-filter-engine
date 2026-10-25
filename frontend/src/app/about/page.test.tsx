import { render, screen } from '@testing-library/react';
import type { ResolvingMetadata } from 'next';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/i18n/server', () => ({ getServerT: async () => (key: string) => key }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

import AboutPage, { generateMetadata } from './page';

/** What the root layout resolves to, as far as a route can see it. */
const ROOT = Promise.resolve({
  openGraph: {
    title: { absolute: 'JoinALab — Research & Internship Matching', template: null },
    siteName: 'JoinALab',
    images: [{ url: 'https://joinalab.com/opengraph-image?v1', width: 1200, height: 630 }],
  },
  twitter: {
    card: 'summary_large_image',
    title: { absolute: 'JoinALab — Research Matching', template: null },
    creator: '@guoyi_eric_xu',
  },
}) as unknown as ResolvingMetadata;

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

  it('links the author\'s own profiles beside the email and website', async () => {
    render(await AboutPage());
    expect(screen.getByRole('link', { name: 'about.websiteLabel' })).toHaveAttribute('rel', 'author');
    for (const [name, href] of [
      ['LinkedIn', 'https://www.linkedin.com/in/guoyi-eric-xu'],
      ['Google Scholar', 'https://scholar.google.com/citations?user=0UGotE4AAAAJ'],
      ['ORCID', 'https://orcid.org/0009-0000-3581-5996'],
    ]) {
      const link = screen.getByRole('link', { name });
      expect(link).toHaveAttribute('href', href);
      expect(link).toHaveAttribute('rel', 'me');
    }
  });
});

describe('About page metadata', () => {
  // The root layout used to name the homepage as every route's canonical, so
  // /about, the one page that says who builds JoinALab, asked not to be
  // indexed on its own and shared as the homepage.
  it('names /about, not the homepage, as its canonical and og:url', async () => {
    const meta = await generateMetadata({}, ROOT);
    expect(meta.alternates?.canonical).toBe('/about');
    expect(meta.openGraph?.url).toBe('/about');
  });

  it('has a title and description of its own', async () => {
    const meta = await generateMetadata({}, ROOT);
    expect(meta.title).toBe('About');
    expect(meta.openGraph?.title).toBe('About · JoinALab');
    expect(meta.twitter?.title).toBe('About · JoinALab');
    expect(meta.description).toMatch(/Guoyi \(Eric\) Xu/);
  });

  it('keeps the root card image, site name and twitter:creator', async () => {
    const meta = await generateMetadata({}, ROOT);
    expect(meta.openGraph?.siteName).toBe('JoinALab');
    expect(meta.openGraph?.images).toEqual([
      expect.objectContaining({ url: 'https://joinalab.com/opengraph-image?v1' }),
    ]);
    expect(meta.twitter).toMatchObject({ card: 'summary_large_image', creator: '@guoyi_eric_xu' });
  });
});
