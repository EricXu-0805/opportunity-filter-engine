/* @vitest-environment jsdom */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { InteractionPills } from './InteractionPills';
import type { ReminderSuggestion } from '@/lib/status-suggestions';
import type { TFunc } from './types';

const t: TFunc = ((key: string, vars?: Record<string, string | number>) => {
  if (vars && 'date' in vars) return `${key}:${vars.date}`;
  return key;
}) as TFunc;

const suggestion: ReminderSuggestion = { reason: 'thank_you_after_interview', date: '2030-01-01', daysAhead: 3 };

describe('InteractionPills — status pills', () => {
  it('disables every status pill while suggestionSaving is true, even if interaction/read state is otherwise ready', () => {
    render(
      <InteractionPills
        interaction={undefined}
        suggestion={null}
        onTrack={() => {}}
        onUseSuggestion={() => {}}
        onDismissSuggestion={() => {}}
        suggestionSaving
        t={t}
      />,
    );
    for (const btn of screen.getAllByRole('button')) {
      expect(btn).toBeDisabled();
    }
  });
});

describe('InteractionPills — suggestion banner', () => {
  it('disables both Use and Dismiss while suggestionSaving, and marks Use aria-busy', () => {
    render(
      <InteractionPills
        interaction="interviewing"
        suggestion={suggestion}
        onTrack={() => {}}
        onUseSuggestion={() => {}}
        onDismissSuggestion={() => {}}
        suggestionSaving
        t={t}
      />,
    );
    const useBtn = screen.getByText(/detail.tracker.suggestions.useButton/);
    const dismissBtn = screen.getByText(/detail.tracker.suggestions.dismissButton/);
    expect(useBtn).toBeDisabled();
    expect(useBtn).toHaveAttribute('aria-busy', 'true');
    expect(dismissBtn).toBeDisabled();
  });

  it('disables both Use and Dismiss while a status write (statusSaving) is in flight — mutual exclusion, not just suggestionSaving', () => {
    render(
      <InteractionPills
        interaction="interviewing"
        suggestion={suggestion}
        statusSaving
        onTrack={() => {}}
        onUseSuggestion={() => {}}
        onDismissSuggestion={() => {}}
        t={t}
      />,
    );
    expect(screen.getByText(/detail.tracker.suggestions.useButton/)).toBeDisabled();
    expect(screen.getByText(/detail.tracker.suggestions.dismissButton/)).toBeDisabled();
  });

  it('a failed suggestion save shows a visible error, keeps the suggestion present, and Use remains clickable (real retry) once no longer saving', () => {
    const onUseSuggestion = vi.fn();
    render(
      <InteractionPills
        interaction="interviewing"
        suggestion={suggestion}
        onTrack={() => {}}
        onUseSuggestion={onUseSuggestion}
        onDismissSuggestion={() => {}}
        suggestionError
        t={t}
      />,
    );
    expect(screen.getByText('detail.tracker.suggestions.saveError')).toBeInTheDocument();
    const useBtn = screen.getByText(/detail.tracker.suggestions.useButton/);
    expect(useBtn).not.toBeDisabled(); // not currently saving — a real retry is possible
    fireEvent.click(useBtn);
    expect(onUseSuggestion).toHaveBeenCalledTimes(1);
  });

  it('no error line renders when suggestionError is false', () => {
    render(
      <InteractionPills
        interaction="interviewing"
        suggestion={suggestion}
        onTrack={() => {}}
        onUseSuggestion={() => {}}
        onDismissSuggestion={() => {}}
        t={t}
      />,
    );
    expect(screen.queryByText('detail.tracker.suggestions.saveError')).toBeNull();
  });

  it('clicking Use/Dismiss calls the respective handler when not disabled', () => {
    const onUseSuggestion = vi.fn();
    const onDismissSuggestion = vi.fn();
    render(
      <InteractionPills
        interaction="interviewing"
        suggestion={suggestion}
        onTrack={() => {}}
        onUseSuggestion={onUseSuggestion}
        onDismissSuggestion={onDismissSuggestion}
        t={t}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.suggestions.useButton/));
    fireEvent.click(screen.getByText(/detail.tracker.suggestions.dismissButton/));
    expect(onUseSuggestion).toHaveBeenCalledTimes(1);
    expect(onDismissSuggestion).toHaveBeenCalledTimes(1);
  });
});


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
        suggestion={null}
        onTrack={onTrack}
        onUseSuggestion={() => {}}
        onDismissSuggestion={() => {}}
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
        suggestion={null}
        onTrack={vi.fn()}
        onUseSuggestion={() => {}}
        onDismissSuggestion={() => {}}
        t={t}
      />,
    );
    expect(screen.queryByText('results.statusMenu.remove')).toBeNull();
  });
});
