import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
    locale: 'en' as const,
    setLocale: vi.fn(),
  }),
}));

const pathnameRef = { current: '/' };
vi.mock('next/navigation', () => ({
  usePathname: () => pathnameRef.current,
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import Header from './Header';

beforeEach(() => {
  pathnameRef.current = '/';
  try { sessionStorage.clear(); } catch { /* private mode */ }
  try { localStorage.clear(); } catch { /* private mode */ }
});

describe('Header', () => {
  it('renders all nav labels in both desktop and mobile panels plus a language switcher', () => {
    render(<Header />);
    for (const key of ['nav.findMatches', 'nav.favorites', 'nav.dashboard', 'nav.import', 'nav.about']) {
      expect(screen.getAllByText(key).length).toBeGreaterThanOrEqual(2);
    }
    expect(screen.getAllByRole('button', { name: 'Switch to Chinese' }).length).toBeGreaterThanOrEqual(1);
  });

  it('exposes a hamburger toggle that is initially collapsed', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('aria-label', 'nav.menuOpen');
    expect(toggle).toHaveAttribute('aria-controls', 'mobile-nav-panel');
  });

  it('toggles the panel open on click and switches the aria-label', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle).toHaveAttribute('aria-label', 'nav.menuClose');
    const panel = document.getElementById('mobile-nav-panel');
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute('aria-hidden', 'false');
  });

  it('renders all 5 nav items inside the panel when open', () => {
    render(<Header />);
    fireEvent.click(screen.getByTestId('mobile-nav-toggle'));
    const matches = screen.getAllByText('nav.findMatches');
    expect(matches.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('nav.favorites').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('nav.about').length).toBeGreaterThanOrEqual(2);
  });

  it('closes the panel when ESC is pressed', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('does not close on unrelated keys', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    fireEvent.keyDown(window, { key: 'a' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('hides panel items from focus traversal when collapsed', () => {
    render(<Header />);
    const allLinks = screen.getAllByRole('link');
    const panel = document.getElementById('mobile-nav-panel');
    const panelLinks = Array.from(panel?.querySelectorAll('a') ?? []);
    for (const link of panelLinks) {
      expect(link.getAttribute('tabindex')).toBe('-1');
    }
    expect(allLinks.length).toBeGreaterThan(0);
  });

  it('reveals panel items to focus traversal when expanded', () => {
    render(<Header />);
    fireEvent.click(screen.getByTestId('mobile-nav-toggle'));
    const panel = document.getElementById('mobile-nav-panel');
    const panelLinks = Array.from(panel?.querySelectorAll('a') ?? []);
    for (const link of panelLinks) {
      expect(link.getAttribute('tabindex')).toBe('0');
    }
  });

  it('marks the desktop nav with aria-label', () => {
    render(<Header />);
    expect(screen.getByLabelText('nav.primary')).toBeInTheDocument();
  });

  it('marks an item active when its href matches the current pathname', () => {
    pathnameRef.current = '/favorites';
    render(<Header />);
    const favoritesLinks = screen
      .getAllByRole('link')
      .filter((el) => el.getAttribute('href') === '/favorites');
    expect(favoritesLinks.length).toBeGreaterThan(0);
    expect(favoritesLinks.every((el) => el.className.includes('bg-black/[0.06]'))).toBe(true);
  });

  it('treats /results as activating the "Find Matches" tab', () => {
    pathnameRef.current = '/results';
    render(<Header />);
    const homeLinks = screen
      .getAllByRole('link')
      .filter((el) => el.getAttribute('href') === '/');
    const navHomeLinks = homeLinks.filter((el) => el.textContent === 'nav.findMatches');
    expect(navHomeLinks.length).toBeGreaterThan(0);
    expect(navHomeLinks.every((el) => el.className.includes('bg-black/[0.06]'))).toBe(true);
  });

  it('closes the panel when a nav link is clicked', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const panel = document.getElementById('mobile-nav-panel');
    const firstLink = panel?.querySelector('a');
    expect(firstLink).not.toBeNull();
    if (firstLink) fireEvent.click(firstLink);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('closes the panel when a mousedown happens outside the header (R47)', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    fireEvent.mouseDown(document.body);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps the panel open when a mousedown happens inside the header (R47)', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    const panel = document.getElementById('mobile-nav-panel');
    const firstLink = panel?.querySelector('a');
    expect(firstLink).not.toBeNull();
    /* mousedown alone (no click) on a panel link must NOT close the panel
       via the click-outside path — the listener excludes elements
       contained by the header. The existing onClick={close} handler is
       what closes the panel on a full click; we're isolating mousedown
       here to verify the boundary check. */
    if (firstLink) fireEvent.mouseDown(firstLink);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('re-attaches the click-outside listener after a reopen (R47)', () => {
    render(<Header />);
    const toggle = screen.getByTestId('mobile-nav-toggle');
    fireEvent.click(toggle);
    fireEvent.mouseDown(document.body);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    fireEvent.mouseDown(document.body);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  // R67 problem #3: when matches are cached in sessionStorage, the
  // "Find Matches" nav should take users to /results (where the
  // matches are) instead of back to / (which shows the profile form
  // with the matches "missing"). The cache itself never invalidates
  // on navigation — only on profile-hash mismatch inside the results
  // page. So the link target switches as the cache appears/disappears.
  it('routes "Find Matches" to / by default (no cache in sessionStorage)', async () => {
    render(<Header />);
    const findMatchesLinks = screen
      .getAllByRole('link')
      .filter((el) => el.textContent === 'nav.findMatches');
    expect(findMatchesLinks.length).toBeGreaterThan(0);
    for (const link of findMatchesLinks) {
      expect(link.getAttribute('href')).toBe('/');
    }
  });

  it('routes "Find Matches" to /results when a match cache is present', async () => {
    localStorage.setItem('ofe_match_results', JSON.stringify({ hash: 'x', semantic: false, savedAt: Date.now(), results: [] }));
    render(<Header />);
    // Wait for the useEffect that reads sessionStorage to run.
    await new Promise((r) => setTimeout(r, 0));
    const findMatchesLinks = screen
      .getAllByRole('link')
      .filter((el) => el.textContent === 'nav.findMatches');
    expect(findMatchesLinks.length).toBeGreaterThan(0);
    for (const link of findMatchesLinks) {
      expect(link.getAttribute('href')).toBe('/results');
    }
  });

  it('keeps active styling on "Find Matches" when on /results, even when href has switched to /results', async () => {
    localStorage.setItem('ofe_match_results', JSON.stringify({ hash: 'x', semantic: false, savedAt: Date.now(), results: [] }));
    pathnameRef.current = '/results';
    render(<Header />);
    await new Promise((r) => setTimeout(r, 0));
    const findMatchesLinks = screen
      .getAllByRole('link')
      .filter((el) => el.textContent === 'nav.findMatches');
    expect(findMatchesLinks.length).toBeGreaterThan(0);
    expect(findMatchesLinks.every((el) => el.className.includes('bg-black/[0.06]'))).toBe(true);
  });

  it('only swaps the Find Matches link — other nav items keep their hrefs', async () => {
    localStorage.setItem('ofe_match_results', JSON.stringify({ hash: 'x', semantic: false, savedAt: Date.now(), results: [] }));
    render(<Header />);
    await new Promise((r) => setTimeout(r, 0));
    const favoritesLinks = screen
      .getAllByRole('link')
      .filter((el) => el.textContent === 'nav.favorites');
    for (const link of favoritesLinks) {
      expect(link.getAttribute('href')).toBe('/favorites');
    }
  });
});
