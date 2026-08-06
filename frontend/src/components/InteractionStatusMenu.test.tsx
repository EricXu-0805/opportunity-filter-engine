/* @vitest-environment jsdom */
import { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (vars && 'title' in vars) return `${key}:${vars.title}`;
      return key;
    },
  }),
}));

import { InteractionStatusMenu } from './InteractionStatusMenu';
import { en, zh } from '@/i18n/dictionaries';

// Simulates a real parent (Tracker/Results page): the callback starts a
// write by synchronously disabling the menu in the SAME batch that the
// menu's own close/confirm action also runs in, then re-enables it once
// the write resolves — exactly the sequence that unmounts the old
// InteractionStatusMenuInner (via the wrapper's disabled-keyed remount)
// before its own effects would otherwise have restored focus. The
// resolution itself is gated EXPLICITLY by the test (via deferRef), not a
// timer — a real timer risks the disabled state flashing for less than one
// observable tick, or being coalesced away entirely by batching.
function DeferredWriteHarness({
  onTrackInteraction,
  deferRef,
}: {
  onTrackInteraction: (id: string, type: string) => void;
  deferRef: { current: (() => void) | null };
}) {
  const [disabled, setDisabled] = useState(false);
  return (
    <InteractionStatusMenu
      opportunityId="opp-7"
      opportunityTitle="Test Lab"
      interaction="rejected"
      disabled={disabled}
      onTrackInteraction={(id, type) => {
        onTrackInteraction(id, type);
        setDisabled(true);
        deferRef.current = () => setDisabled(false);
      }}
    />
  );
}

// Anchored, NON-modal disclosure dialog (role="dialog", not "menu") — see
// InteractionStatusMenu.tsx's doc comment for why role="menu" was dropped:
// the confirm step puts plain <button>s directly inside the popup, which
// is invalid ARIA under role="menu" (children must be
// menuitem/menuitemradio/menuitemcheckbox), and a real menu implementation
// would additionally require the full roving-tabindex + arrow/Home/End
// keyboard model this component never had.

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
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
  });

  it('renders the current status label inside the trigger when interaction is set, AND includes it in the trigger\'s accessible name — aria-label overrides visible text content, so without this a screen reader would never hear the current status at all', () => {
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
    const trigger = screen.getByRole('button', {
      name: /statusMenu\.ariaTrigger:Test Lab: detail\.tracker\.statusLabels\.applied/,
    });
    expect(trigger).toBeInTheDocument();
  });

  it('clicking the trigger opens the dialog and reveals all 5 status options as plain buttons', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={() => {}}
      />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    // 6 status options (W12 added 'contacted'), plain buttons in a non-modal
    // disclosure dialog — no Remove footer yet since no interaction is set.
    expect(within(dialog).getAllByRole('button')).toHaveLength(6);
  });

  it('clicking a status option fires onTrackInteraction(id, type) and closes the dialog', () => {
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
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('marks the active status option with aria-pressed=true (others false)', () => {
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        interaction="applied"
        onTrackInteraction={() => {}}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }),
    );
    const dialog = screen.getByRole('dialog');
    const items = within(dialog).getAllByRole('button');
    const applied = items.find((el) => el.textContent?.includes('detail.tracker.statusLabels.applied'));
    const replied = items.find((el) => el.textContent?.includes('detail.tracker.statusLabels.replied'));
    expect(applied).toHaveAttribute('aria-pressed', 'true');
    expect(replied).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows a "Remove from Tracker" button only when an interaction is currently set', () => {
    const { rerender } = render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={() => {}}
      />,
    );
    fireEvent.click(screen.getByText('results.statusMenu.trigger'));
    expect(screen.queryByText('results.statusMenu.remove')).toBeNull();

    // rerender preserves useState across the same component instance, so
    // the dialog stays open. After we re-supply interaction="applied" it
    // re-renders with a Remove footer; no second click required.
    rerender(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        interaction="applied"
        onTrackInteraction={() => {}}
      />,
    );
    expect(screen.getByText('results.statusMenu.remove')).toBeInTheDocument();
  });

  describe('destructive removal requires an explicit, confirmed footer action', () => {
    it('re-clicking the ALREADY-active status option is a no-op: no callback, marked aria-disabled, dialog stays open', () => {
      const handler = vi.fn();
      render(
        <InteractionStatusMenu
          opportunityId="opp-7"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={handler}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      const dialog = screen.getByRole('dialog');
      const active = within(dialog).getAllByRole('button').find((el) => el.getAttribute('aria-pressed') === 'true')!;
      expect(active).toHaveAttribute('aria-disabled', 'true');
      fireEvent.click(active);
      expect(handler).not.toHaveBeenCalled();
      expect(screen.getByRole('dialog')).toBeInTheDocument(); // still open — nothing happened
    });

    it('clicking "Remove from Tracker" shows a confirmation instead of firing the callback immediately', () => {
      const handler = vi.fn();
      render(
        <InteractionStatusMenu
          opportunityId="opp-7"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={handler}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      fireEvent.click(screen.getByText('results.statusMenu.remove'));
      expect(handler).not.toHaveBeenCalled();
      expect(screen.getByText('results.statusMenu.removeConfirmBody')).toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('the confirm view is its OWN dialog identity, not still labeled "Application status options" — accessible name reflects "Remove from Tracker", and aria-describedby wires up the permanent-deletion warning body', () => {
      render(
        <InteractionStatusMenu
          opportunityId="opp-7"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={() => {}}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      // Before confirming: normal dialog identity.
      expect(screen.getByRole('dialog', { name: /statusMenu\.ariaDialog:Test Lab/ })).toBeInTheDocument();

      fireEvent.click(screen.getByText('results.statusMenu.remove'));
      const dialog = screen.getByRole('dialog', { name: /statusMenu\.remove.*Test Lab/ });
      const descId = dialog.getAttribute('aria-describedby');
      expect(descId).toBeTruthy();
      const desc = document.getElementById(descId!);
      expect(desc).toHaveTextContent('results.statusMenu.removeConfirmBody');
    });

    it('Cancel on the confirmation is a true no-op: zero callback, zero write, and the dialog stays open/usable — going straight back to the status list is possible without re-opening', () => {
      const handler = vi.fn();
      render(
        <InteractionStatusMenu
          opportunityId="opp-7"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={handler}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      fireEvent.click(screen.getByText('results.statusMenu.remove'));
      fireEvent.click(screen.getByText('common.cancel'));
      expect(handler).not.toHaveBeenCalled();
      const dialog = screen.getByRole('dialog');
      expect(dialog).toBeInTheDocument(); // still open
      // back to the normal status list, fully interactive again
      expect(within(dialog).getAllByRole('button')).toHaveLength(7); // 6 statuses + Remove footer
    });

    it('confirming fires onTrackInteraction with the EXACT same-type callback the underlying REMOVE contract expects, then closes the dialog', () => {
      const handler = vi.fn();
      render(
        <InteractionStatusMenu
          opportunityId="opp-7"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={handler}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      fireEvent.click(screen.getByText('results.statusMenu.remove'));
      fireEvent.click(screen.getByText('results.statusMenu.removeConfirmYes'));
      // page.tsx:handleTrackInteraction (and use-tracker-data.ts's
      // changeStatus) treat "same type re-fire" as REMOVE; the confirm
      // button leans on that EXACT existing contract, not a new shape.
      expect(handler).toHaveBeenCalledTimes(1);
      expect(handler).toHaveBeenCalledWith('opp-7', 'rejected');
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });

  it('renders the dialog in a portal on document.body so an overflow-hidden card cannot clip it', () => {
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
    const dialog = screen.getByRole('dialog');
    // The dialog must NOT be nested inside the overflow-hidden card wrapper,
    // and must use fixed positioning to float above sibling content.
    expect(screen.getByTestId('clipping-card').contains(dialog)).toBe(false);
    expect(dialog).toHaveStyle({ position: 'fixed' });
  });

  it('disabled marks the trigger aria-disabled + aria-busy, guards its click handler, but deliberately does NOT use the native `disabled` attribute — it must stay focusable so focus is never lost/stolen across a write\'s lifecycle (see the component doc comment)', () => {
    const handler = vi.fn();
    render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        interaction="applied"
        onTrackInteraction={handler}
        disabled
      />,
    );
    const trigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
    expect(trigger).not.toBeDisabled();
    expect(trigger).toHaveAttribute('aria-disabled', 'true');
    expect(trigger).toHaveAttribute('aria-busy', 'true');
    trigger.focus();
    expect(document.activeElement).toBe(trigger); // still genuinely focusable
    fireEvent.click(trigger);
    expect(screen.queryByRole('dialog')).toBeNull(); // click is inert while disabled
    expect(handler).not.toHaveBeenCalled();
  });

  it('closes an already-open dialog the instant disabled flips true, and returns focus to the SAME (still-present, still-focusable) trigger — a write starting (or the owner/read state going unready) must not leave a clickable portal behind', () => {
    const handler = vi.fn();
    const { rerender } = render(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={handler}
      />,
    );
    const trigger = screen.getByText('results.statusMenu.trigger').closest('button')!;
    fireEvent.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    rerender(
      <InteractionStatusMenu
        opportunityId="opp-1"
        opportunityTitle="Test Lab"
        onTrackInteraction={handler}
        disabled
      />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(handler).not.toHaveBeenCalled();
    // Same DOM node throughout — no remount — so this assertion is only
    // meaningful because nothing ever tore it down.
    expect(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ })).toBe(trigger);
    expect(document.activeElement).toBe(trigger);
  });

  describe('focus management (userEvent — fireEvent does not move real focus)', () => {
    it('opening with NO interaction set focuses the FIRST status option', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          onTrackInteraction={() => {}}
        />,
      );
      await user.click(screen.getByText('results.statusMenu.trigger'));
      const dialog = screen.getByRole('dialog');
      const first = within(dialog).getAllByRole('button')[0];
      expect(document.activeElement).toBe(first);
    });

    it('opening WITH an interaction set focuses the CURRENTLY ACTIVE status option, not the first', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="rejected" // 4th of 5 options — not the first
          onTrackInteraction={() => {}}
        />,
      );
      await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      expect(document.activeElement?.textContent).toContain('detail.tracker.statusLabels.rejected');
      expect(document.activeElement).toHaveAttribute('aria-pressed', 'true');
    });

    it('a BUSY (disabled) trigger is a genuine no-op for real click, Enter, AND Space via userEvent — no callback, no dialog, focus never moves off it', async () => {
      const user = userEvent.setup();
      const handler = vi.fn();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="applied"
          onTrackInteraction={handler}
          disabled
        />,
      );
      const trigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
      trigger.focus();
      expect(document.activeElement).toBe(trigger);

      await user.click(trigger);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(handler).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(trigger);

      await user.keyboard('{Enter}');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(handler).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(trigger);

      await user.keyboard(' ');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(handler).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(trigger);
    });

    it('Enter/Space on the focused, already-active (no-op) status option never fires the callback', async () => {
      const handler = vi.fn();
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={handler}
        />,
      );
      await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      // Focus already lands on the active option (proven above) — a
      // native <button> translates both Enter and Space into a click.
      await user.keyboard('{Enter}');
      expect(handler).not.toHaveBeenCalled();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      await user.keyboard(' ');
      expect(handler).not.toHaveBeenCalled();
    });

    it('Tab from the LAST focusable button wraps around to the FIRST (portal-to-body-end must not leak focus out of the dialog)', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="applied"
          onTrackInteraction={() => {}}
        />,
      );
      await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      const dialog = screen.getByRole('dialog');
      const buttons = within(dialog).getAllByRole('button'); // 6 statuses + Remove footer = 7
      expect(buttons).toHaveLength(7);
      buttons[buttons.length - 1].focus();
      await user.tab();
      expect(document.activeElement).toBe(buttons[0]);
    });

    it('Shift+Tab from the FIRST focusable button wraps around to the LAST', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="applied"
          onTrackInteraction={() => {}}
        />,
      );
      await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      const dialog = screen.getByRole('dialog');
      const buttons = within(dialog).getAllByRole('button');
      buttons[0].focus();
      await user.tab({ shift: true });
      expect(document.activeElement).toBe(buttons[buttons.length - 1]);
    });

    it('the confirm view\'s 2 buttons (Cancel/Remove) cycle the same way', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="applied"
          onTrackInteraction={() => {}}
        />,
      );
      await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      await user.click(screen.getByText('results.statusMenu.remove'));
      const dialog = screen.getByRole('dialog');
      const buttons = within(dialog).getAllByRole('button');
      expect(buttons).toHaveLength(2); // Cancel, Remove
      buttons[1].focus();
      await user.tab();
      expect(document.activeElement).toBe(buttons[0]);
      await user.tab({ shift: true });
      expect(document.activeElement).toBe(buttons[1]);
    });

    it('entering the confirm view focuses Cancel; clicking Cancel returns focus to the Remove footer button', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          interaction="applied"
          onTrackInteraction={() => {}}
        />,
      );
      await user.click(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ }));
      const removeFooter = screen.getByText('results.statusMenu.remove').closest('button')!;
      await user.click(removeFooter);
      expect(document.activeElement).toHaveTextContent('common.cancel');

      await user.click(screen.getByText('common.cancel'));
      expect(document.activeElement).toBe(screen.getByText('results.statusMenu.remove').closest('button'));
    });

    it('Escape closes the dialog and returns focus to the trigger', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-1"
          opportunityTitle="Test Lab"
          onTrackInteraction={() => {}}
        />,
      );
      const trigger = screen.getByText('results.statusMenu.trigger').closest('button')!;
      await user.click(trigger);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(trigger);
    });

    it('selecting a status option closes the dialog and returns focus to the trigger', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-42"
          opportunityTitle="Test Lab"
          onTrackInteraction={() => {}}
        />,
      );
      const trigger = screen.getByText('results.statusMenu.trigger').closest('button')!;
      await user.click(trigger);
      await user.click(screen.getByText('detail.tracker.statusLabels.interviewing'));
      expect(document.activeElement).toBe(trigger);
    });

    it('confirming the destructive removal closes the dialog and returns focus to the trigger', async () => {
      const user = userEvent.setup();
      render(
        <InteractionStatusMenu
          opportunityId="opp-7"
          opportunityTitle="Test Lab"
          interaction="rejected"
          onTrackInteraction={() => {}}
        />,
      );
      const trigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
      await user.click(trigger);
      await user.click(screen.getByText('results.statusMenu.remove'));
      await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));
      expect(document.activeElement).toBe(trigger);
    });

    it('outside click closes the dialog WITHOUT stealing focus from whatever the user just clicked', async () => {
      const user = userEvent.setup();
      render(
        <div>
          <InteractionStatusMenu
            opportunityId="opp-1"
            opportunityTitle="Test Lab"
            onTrackInteraction={() => {}}
          />
          <button type="button" data-testid="outside">outside</button>
        </div>,
      );
      await user.click(screen.getByText('results.statusMenu.trigger'));
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      const outside = screen.getByTestId('outside');
      await user.click(outside);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(outside); // NOT forced back to the trigger
    });

    it('if the user does NOT move focus away during a pending write, it naturally stays on the trigger — the SAME DOM node throughout, since nothing ever remounts it — all the way through resolve', async () => {
      const user = userEvent.setup();
      const handler = vi.fn();
      const deferRef: { current: (() => void) | null } = { current: null };
      render(<DeferredWriteHarness onTrackInteraction={handler} deferRef={deferRef} />);

      const trigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
      await user.click(trigger);
      await user.click(screen.getByText('results.statusMenu.remove'));
      await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));
      expect(handler).toHaveBeenCalledWith('opp-7', 'rejected');
      expect(deferRef.current).not.toBeNull(); // genuinely still pending

      // Confirming closes the dialog and returns focus to the trigger —
      // now aria-disabled (a write is in flight) but the SAME element.
      expect(document.activeElement).toBe(trigger);
      expect(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ })).toBe(trigger);
      expect(trigger).toHaveAttribute('aria-disabled', 'true');

      act(() => { deferRef.current?.(); }); // the write resolves — re-enabled

      expect(document.activeElement).toBe(trigger);
      expect(screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ })).toBe(trigger);
    });

    it('during a pending write, if the user deliberately moves focus AWAY to a different control, resolving the write must NOT steal it back — the P1 this whole redesign exists to fix', async () => {
      const user = userEvent.setup();
      const handler = vi.fn();
      const deferRef: { current: (() => void) | null } = { current: null };
      render(
        <div>
          <DeferredWriteHarness onTrackInteraction={handler} deferRef={deferRef} />
          <button type="button">elsewhere</button>
        </div>,
      );

      const trigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
      await user.click(trigger);
      await user.click(screen.getByText('results.statusMenu.remove'));
      await user.click(screen.getByText('results.statusMenu.removeConfirmYes'));
      expect(handler).toHaveBeenCalledWith('opp-7', 'rejected');
      expect(deferRef.current).not.toBeNull(); // genuinely still pending

      // The user, while the write is pending, moves on to something else
      // entirely (e.g. tabbed past it, or clicked a different card).
      const elsewhere = screen.getByText('elsewhere');
      await user.click(elsewhere);
      expect(document.activeElement).toBe(elsewhere);

      act(() => { deferRef.current?.(); }); // the write resolves — re-enabled

      // Must stay exactly where the user put it — never stolen back.
      expect(document.activeElement).toBe(elsewhere);
    });
  });

  describe('en/zh key parity for the remove-confirm + dialog strings', () => {
    // The broader dictionary-wide parity check lives in
    // src/i18n/translate.test.ts; this is a narrower, component-scoped
    // sanity check that the specific keys THIS component renders exist,
    // are non-empty, and are actually translated (not an accidental
    // English copy-paste into the zh slot).
    it('results.statusMenu.remove / removeConfirmBody / removeConfirmYes / ariaDialog exist and differ between en and zh', () => {
      for (const key of ['remove', 'removeConfirmBody', 'removeConfirmYes', 'ariaDialog'] as const) {
        const enVal = en.results.statusMenu[key];
        const zhVal = zh.results.statusMenu[key];
        expect(enVal).toBeTruthy();
        expect(zhVal).toBeTruthy();
        expect(zhVal).not.toBe(enVal);
      }
    });
  });
});
