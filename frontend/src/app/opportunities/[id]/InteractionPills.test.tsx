/* @vitest-environment jsdom */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { InteractionPills } from './InteractionPills';
import type { TFunc } from './types';

const t: TFunc = ((key: string) => key) as TFunc;

describe('InteractionPills — removing a tracked status is deliberate', () => {
  // Re-clicking the highlighted pill used to delete the whole tracker row —
  // status, notes, reminder, and the last_contacted_at that Confirm Contact
  // writes — with no confirmation, because the pill reads as an on-toggle.
  // InteractionStatusMenu made that gesture a no-op on the results and tracker
  // surfaces; the detail page, which owns the notes, never got the same fix.
  const setup = (onTrack = vi.fn()) => {
    render(
      <InteractionPills
        interaction="applied"
        onTrack={onTrack}
        t={t}
      />,
    );
    return onTrack;
  };

  it('re-clicking the active pill writes nothing', () => {
    const onTrack = setup();
    fireEvent.click(screen.getByText('detail.interactions.applied'));
    expect(onTrack).not.toHaveBeenCalled();
  });

  it('picking a different status still works', () => {
    const onTrack = setup();
    fireEvent.click(screen.getByText('detail.interactions.replied'));
    expect(onTrack).toHaveBeenCalledWith('replied');
  });

  it('removal is reachable, but only after confirming', () => {
    const onTrack = setup();
    fireEvent.click(screen.getByText('results.statusMenu.remove'));
    // The warning names what is about to be destroyed.
    expect(screen.getByText('results.statusMenu.removeConfirmBody')).toBeInTheDocument();
    expect(onTrack).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('results.statusMenu.removeConfirmYes'));
    // The same same-type callback the remove contract already expects.
    expect(onTrack).toHaveBeenCalledWith('applied');
  });

  it('cancelling writes nothing and keeps the status', () => {
    const onTrack = setup();
    fireEvent.click(screen.getByText('results.statusMenu.remove'));
    fireEvent.click(screen.getByText('common.cancel'));
    expect(onTrack).not.toHaveBeenCalled();
    expect(screen.queryByText('results.statusMenu.removeConfirmBody')).toBeNull();
  });

  it('offers no remove control when nothing is tracked', () => {
    render(
      <InteractionPills
        interaction={undefined}
        onTrack={vi.fn()}
        t={t}
      />,
    );
    expect(screen.queryByText('results.statusMenu.remove')).toBeNull();
  });
});
