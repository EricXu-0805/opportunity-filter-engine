import { describe, it, expect } from 'vitest';
import sitemap from './sitemap';
import robots from './robots';
import { SITE_URL } from '@/lib/site';

describe('SITE_URL', () => {
  it('is an absolute https origin with no trailing slash', () => {
    expect(SITE_URL).toMatch(/^https:\/\/[^/]+$/);
  });
});

describe('sitemap', () => {
  it('lists public content routes as absolute URLs under SITE_URL', () => {
    const urls = sitemap().map((e) => e.url);
    expect(urls).toContain(SITE_URL); // home
    expect(urls).toContain(`${SITE_URL}/privacy`);
    expect(urls).toContain(`${SITE_URL}/terms`);
    expect(urls.every((u) => u.startsWith(SITE_URL))).toBe(true);
  });

  it('excludes per-user and admin pages', () => {
    const urls = sitemap().map((e) => e.url);
    for (const p of ['/account', '/dashboard', '/favorites', '/tracker', '/admin', '/results']) {
      expect(urls.some((u) => u.endsWith(p))).toBe(false);
    }
  });

  it('lists the accepted public product routes', () => {
    // The sitemap builds its list from RELEASE_SCOPE for a reason: a crawler
    // pointed at a route the release gate 404s is the one place a closed
    // feature leaks to strangers who never touched the UI.
    const urls = sitemap().map((e) => e.url);
    expect(urls).toContain(`${SITE_URL}/fellowships`);
    expect(urls).toContain(`${SITE_URL}/roadmap`);
  });
});

describe('robots', () => {
  it('allows crawling, disallows admin + api, and points at the sitemap', () => {
    const r = robots();
    expect(r.sitemap).toBe(`${SITE_URL}/sitemap.xml`);
    const rule = Array.isArray(r.rules) ? r.rules[0] : r.rules!;
    expect(rule.allow).toBe('/');
    expect(rule.disallow).toEqual(expect.arrayContaining(['/admin', '/api']));
  });
});
