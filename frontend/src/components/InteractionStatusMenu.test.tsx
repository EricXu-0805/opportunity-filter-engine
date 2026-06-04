/* @vitest-environment jsdom */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (vars && 'title' in vars) return `${key}:${vars.title}`;
      return key;
    },
  }),
}));

import { InteractionStatusMenu } from './InteractionStatusMenu';

describe('InteractionStatusMenu (R69-C)', () => {
  it('renders the neutral "Mark status" trigger when no interaction is set', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={() => {}}
      />,
    );
    expect(screen.getByText('results.statusMenu.trigger')).toBeInTheDocument();
    const trigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
  });

  it('renders the current status label inside the trigger when interaction is set', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        interaction="applied"
        onTrackInteraction={() => {}}
      />,
    );
    expect(screen.getByText('detail.tracker.statusLabels.applied')).toBeInTheDocument();
    expect(screen.queryByText('results.statusMenu.trigger')).toBeNull();
  });

  it('clicking the trigger opens the menu and reveals all 5 options', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={() => {}}
      />,
    );
    expect(screen.queryByRole('menu')).toBeNull();
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    // 5 status options carry role=menuitemradio (single-select semantic).
    // Clear is a plain menuitem and only renders when interaction is set.
    expect(screen.getAllByRole('menuitemradio').length).toBe(5);
  });

  it('clicking a menuitem fires onTrackInteraction(id, type) and closes the menu', () => {
    const handler = vi.fn();
    render(
      <InteractionStatusMenu
        opportunityId="opp-42"
        opportunityTitle="Test Lab"
        onTrackInteraction={handler}
      />,
    );
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    fireEvent.click(screen.getByText('detail.tracker.statusLabels.interviewing'));
    expect(handler).toHaveBeenCalledWith('opp-42', 'interviewing');
    // Menu closes after selection.
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('marks the active menuitem with aria-checked=true', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        interaction="applied"
        onTrackInteraction={() => {}}
      />,
    );
    // Trigger shows the applied label; click it via aria-label to open
    // the menu (text query would be ambiguous once the menu renders).
    fireEvent.click(
      screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }),
    );
    const items = screen.getAllByRole('menuitemradio');
    const applied = items.find(
      (el) => el.textContent?.includes('detail.tracker.statusLabels.applied'),
    );
    const replied = items.find(
      (el) => el.textContent?.includes('detail.tracker.statusLabels.replied'),
    );
    expect(applied?.getAttribute('aria-checked')).toBe('true');
    expect(replied?.getAttribute('aria-checked')).toBe('false');
  });

  it('shows a "Clear status" menuitem only when an interaction is currently set', () => {
    const { rerender } = render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={() => {}}
      />,
    );
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    expect(screen.queryByText('results.statusMenu.clear')).toBeNull();

    // rerender preserves useState across the same component instance, so
    // the menu stays open. After we re-supply interaction="applied" the
    // menu re-renders with a Clear footer; no second click required.
    rerender(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        interaction="applied"
        onTrackInteraction={() => {}}
      />,
    );
    expect(screen.getByText('results.statusMenu.clear')).toBeInTheDocument();
  });

  it('clicking "Clear status" re-fires onTrackInteraction with the current type (untoggle contract)', () => {
    const handler = vi.fn();
    render(
      <InteractionStatusMenu
        opportunityId="opp-7"
        opportunityTitle="Test Lab"
        interaction="rejected"
        onTrackInteraction={handler}
      />,
    );
    // Trigger label is 'rejected'; menu items will also include
    // 'rejected'. Target the trigger via its aria-label.
    fireEvent.click(
      screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }),
    );
    fireEvent.click(screen.getByText('results.statusMenu.clear'));
    // page.tsx:handleTrackInteraction treats "same type re-fire" as
    // untoggle; the menu's Clear button leans on that contract instead
    // of inventing a new callback shape.
    expect(handler).toHaveBeenCalledWith('opp-7', 'rejected');
  });

  it('Escape key closes the menu', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={() => {}}
      />,
    );
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('renders the menu in a portal on document.body so an overflow-hidden card cannot clip it', () => {
    render(
      <div style={{ overflow: 'hidden' }} data-testid="clipping-card">
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          onTrackInteraction={() => {}}
        />
      </div>,
    );
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    const menu = screen.getByRole('menu');
    // The menu must NOT be nested inside the overflow-hidden card wrapper, and
    // must use fixed positioning to float above sibling content.
    expect(screen.getByTestId('clipping-card').contains(menu)).toBe(false);
    expect(menu).toHaveStyle({ position: 'fixed' });
  });

  it('outside click closes the menu', () => {
    render(
      <div>
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          onTrackInteraction={() => {}}
        />
        <div data-testid="outside">outside</div>
      </div>,
    );
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId('outside'));
    expect(screen.queryByRole('menu')).toBeNull();
  });
});
