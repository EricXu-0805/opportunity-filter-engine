import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));

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
    mount('import');
    expect(screen.getByRole('tab', { name: 'resources.tabImport' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('import field')).toBeVisible();
    expect(screen.getByText('guides content')).not.toBeVisible();
  });

  it('switches tabs, mirrors the tab to ?tab= keeping other params, and keeps Import mounted', () => {
    window.history.replaceState(null, '', '/resources?lab=wet#tips-card-wet');
    mount('guides');
    fireEvent.click(screen.getByRole('tab', { name: 'resources.tabImport' }));
    expect(window.location.search).toBe('?lab=wet&tab=import');
    expect(window.location.hash).toBe('#tips-card-wet');
    const field = screen.getByLabelText('import field');
    fireEvent.change(field, { target: { value: 'half typed' } });

    fireEvent.click(screen.getByRole('tab', { name: 'resources.tabGuides' }));
    expect(window.location.search).toBe('?lab=wet');
    expect(screen.getByText('guides content')).toBeVisible();

    fireEvent.click(screen.getByRole('tab', { name: 'resources.tabImport' }));
    expect(screen.getByLabelText('import field')).toBe(field);
    expect(field).toHaveValue('half typed');
  });

  it('moves between the tabs with the arrow keys', () => {
    mount('guides');
    const guidesTab = screen.getByRole('tab', { name: 'resources.tabGuides' });
    fireEvent.keyDown(guidesTab, { key: 'ArrowRight' });
    const importTab = screen.getByRole('tab', { name: 'resources.tabImport' });
    expect(importTab).toHaveAttribute('aria-selected', 'true');
    expect(importTab).toHaveFocus();
    fireEvent.keyDown(importTab, { key: 'ArrowRight' });
    expect(guidesTab).toHaveAttribute('aria-selected', 'true');
    expect(guidesTab).toHaveFocus();
  });
});
