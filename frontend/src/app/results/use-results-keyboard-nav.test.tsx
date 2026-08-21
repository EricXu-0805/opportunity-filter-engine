import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MatchResult } from '@/lib/types';
import { useResultsKeyboardNav } from './use-results-keyboard-nav';

const noop = () => {};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useResultsKeyboardNav external destination', () => {
  it('goes to the in-app detail page, never straight out to an external URL', () => {
    // Enter must not be an unlabelled Apply. Whatever the record's posture, it
    // lands on the detail page, where the user can read the target's status
    // before choosing an action.
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const assign = vi.fn();
    const original = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, assign },
    });
    const faculty = {
      opportunity: {
        id: 'faculty-ada',
        source_type: 'faculty_research',
        url: 'https://faculty.example.edu/real-profile',
        application: { application_url: 'https://fake.example.edu/apply' },
      },
    } as MatchResult;
    const { result } = renderHook(() => useResultsKeyboardNav({
      paginated: [faculty],
      emailModalOpen: false,
      onCloseEmailModal: noop,
      onToggleFavorite: noop,
      onOpenHelp: noop,
    }));

    act(() => result.current.setFocusedIdx(0));
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' })));

    expect(assign).toHaveBeenCalledWith('/opportunities/faculty-ada');
    expect(open).not.toHaveBeenCalled();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: original,
    });
  });
});
