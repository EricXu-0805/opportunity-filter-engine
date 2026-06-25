/*
 * FeedbackWidget: launcher → form → submit. submitFeedback + analytics are
 * mocked (same style as account/page.test.tsx); i18n returns the key verbatim.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockSubmitFeedback = vi.fn();
const mockTrack = vi.fn();

vi.mock('@/lib/supabase', () => ({
  submitFeedback: (...args: unknown[]) => mockSubmitFeedback(...args),
}));

vi.mock('@/lib/analytics', () => ({
  track: (...args: unknown[]) => mockTrack(...args),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

import FeedbackWidget from './FeedbackWidget';

beforeEach(() => {
  mockSubmitFeedback.mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('FeedbackWidget', () => {
  it('shows the launcher and hides the panel initially', () => {
    render(<FeedbackWidget />);
    expect(screen.getByTestId('feedback-open')).toBeInTheDocument();
    expect(screen.queryByTestId('feedback-panel')).toBeNull();
  });

  it('opens the panel on launcher click', () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    expect(screen.getByTestId('feedback-panel')).toBeInTheDocument();
  });

  it('keeps send disabled until a message is typed', () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    expect(screen.getByTestId('feedback-send')).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('feedback.placeholder'), {
      target: { value: 'great app' },
    });
    expect(screen.getByTestId('feedback-send')).toBeEnabled();
  });

  it('submits the message + optional email and shows the thanks state', async () => {
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    fireEvent.change(screen.getByPlaceholderText('feedback.placeholder'), {
      target: { value: 'love it' },
    });
    fireEvent.change(screen.getByPlaceholderText('feedback.emailPlaceholder'), {
      target: { value: 'me@x.edu' },
    });
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument());
    expect(mockSubmitFeedback).toHaveBeenCalledWith('love it', 'me@x.edu', expect.any(Object));
    expect(mockTrack).toHaveBeenCalledWith('feedback_submitted');
  });

  it('shows an inline error when the submit fails', async () => {
    mockSubmitFeedback.mockResolvedValue(false);
    render(<FeedbackWidget />);
    fireEvent.click(screen.getByTestId('feedback-open'));
    fireEvent.change(screen.getByPlaceholderText('feedback.placeholder'), {
      target: { value: 'broken' },
    });
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByTestId('feedback-thanks')).toBeNull();
  });
});
