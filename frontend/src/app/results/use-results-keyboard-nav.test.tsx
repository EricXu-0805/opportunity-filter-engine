import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MatchResult } from '@/lib/types';
import { useResultsKeyboardNav } from './use-results-keyboard-nav';

const noop = () => {};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useResultsKeyboardNav external destination', () => {
  it('opens the canonical faculty profile, never a poisoned application URL', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
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

    expect(open).toHaveBeenCalledWith(
      'https://faculty.example.edu/real-profile',
      '_blank',
      'noopener,noreferrer',
    );
  });
});
