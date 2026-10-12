import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useSyncExternalStore } from 'react';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
// Next feeds replaceState/pushState and popstate into useSearchParams; this
// stand-in reads window.location the same way.
vi.mock('next/navigation', () => ({
  useSearchParams: () => {
    const search = useSyncExternalStore(
      (notify) => {
        window.addEventListener('popstate', notify);
        window.addEventListener('mock-url-change', notify);
        return () => { window.removeEventListener('popstate', notify); window.removeEventListener('mock-url-change', notify); };
      },
      () => window.location.search,
      () => '',
    );
    return new URLSearchParams(search);
  },
}));

import ResourcesTabs from './ResourcesTabs';

function mount(initialTab: 'guides' | 'import') {
  return render(
    <ResourcesTabs
      initialTab={initialTab}
      guides={<p>guides content</p>}
      importPanel={<input aria-label="import field" />}
    />,
  );
}

/** What a header link click or Back/Forward does to the URL, as the router would report it. */
function navigate(url: string, how: 'push' | 'pop' = 'push') {
  act(() => {
    window.history.pushState(null, '', url);
    window.dispatchEvent(new Event(how === 'pop' ? 'popstate' : 'mock-url-change'));
  });
}

afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});

describe('ResourcesTabs', () => {
  it('opens on the guides and does not mount Import until it is chosen', () => {
    mount('guides');
    expect(screen.getByRole('tab', { name: 'resources.tabGuides' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('guides content')).toBeVisible();
    expect(screen.queryByLabelText('import field')).toBeNull();
  });

  it('opens on Import when the page was asked for it', () => {
    window.history.replaceState(null, '', '/resources?tab=import');
    mount('import');
    expect(screen.getByRole('tab', { name: 'resources.tabImport' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('import field')).toBeVisible();
    expect(screen.getByText('guides content')).not.toBeVisible();
  });

  it('switches tabs, mirrors the tab to ?tab= keeping other params, and keeps Import mounted', () => {
    window.history.replaceState(null, '', '/resources?lab=wet#tips-card-wet');
    mount('guides');
    fireEvent.click(screen.getByRole('tab', { name: 'resources.tabImport' }));
    act(() => { window.dispatchEvent(new Event('mock-url-change')); });
    expect(window.location.search).toBe('?lab=wet&tab=import');
    expect(window.location.hash).toBe('#tips-card-wet');
    const field = screen.getByLabelText('import field');
    fireEvent.change(field, { target: { value: 'half typed' } });

    fireEvent.click(screen.getByRole('tab', { name: 'resources.tabGuides' }));
    act(() => { window.dispatchEvent(new Event('mock-url-change')); });
    expect(window.location.search).toBe('?lab=wet');
    expect(screen.getByText('guides content')).toBeVisible();

    fireEvent.click(screen.getByRole('tab', { name: 'resources.tabImport' }));
    act(() => { window.dispatchEvent(new Event('mock-url-change')); });
    expect(screen.getByLabelText('import field')).toBe(field);
    expect(field).toHaveValue('half typed');
  });

  it('follows the URL: the header Resources link from ?tab=import shows the guides', () => {
    window.history.replaceState(null, '', '/resources?tab=import');
    mount('import');
    expect(screen.getByRole('tab', { name: 'resources.tabImport' })).toHaveAttribute('aria-selected', 'true');
    navigate('/resources');
    expect(screen.getByRole('tab', { name: 'resources.tabGuides' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('guides content')).toBeVisible();
    expect(screen.getByLabelText('import field')).not.toBeVisible();
  });

  it('follows Back and Forward between ?tab=import and the plain URL', () => {
    window.history.replaceState(null, '', '/resources');
    mount('guides');
    navigate('/resources?tab=import');
    expect(screen.getByRole('tab', { name: 'resources.tabImport' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('import field')).toBeVisible();
    navigate('/about');
    navigate('/resources', 'pop');
    expect(screen.getByRole('tab', { name: 'resources.tabGuides' })).toHaveAttribute('aria-selected', 'true');
    navigate('/resources?tab=import', 'pop');
    expect(screen.getByRole('tab', { name: 'resources.tabImport' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('guides content')).not.toBeVisible();
  });

  it('moves between the tabs with the arrow keys', () => {
    mount('guides');
    const guidesTab = screen.getByRole('tab', { name: 'resources.tabGuides' });
    fireEvent.keyDown(guidesTab, { key: 'ArrowRight' });
    act(() => { window.dispatchEvent(new Event('mock-url-change')); });
    const importTab = screen.getByRole('tab', { name: 'resources.tabImport' });
    expect(importTab).toHaveAttribute('aria-selected', 'true');
    expect(importTab).toHaveFocus();
    fireEvent.keyDown(importTab, { key: 'ArrowRight' });
    act(() => { window.dispatchEvent(new Event('mock-url-change')); });
    expect(guidesTab).toHaveAttribute('aria-selected', 'true');
    expect(guidesTab).toHaveFocus();
  });
});
