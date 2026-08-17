import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { ChatResponse } from '@/lib/api';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (!vars) return key;
      const pairs = Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(',');
      return `${key}{${pairs}}`;
    },
  }),
}));

const mockChat = vi.fn<
  (
    oppId: string,
    msg: string,
    history: unknown[],
    profile: ProfileData | null,
    model?: string,
    onDelta?: (chunk: string) => void,
  ) => Promise<ChatResponse>
>();
const mockGetChatModels = vi.fn<() => Promise<{ id: string; label: string }[]>>();

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public readonly status: number,
      public readonly code: string,
      message: string,
      public readonly retryable: boolean,
    ) {
      super(message);
      this.name = 'ApiError';
    }
  },
  chatWithOpportunity: (
    oppId: string,
    msg: string,
    history: unknown[],
    profile: ProfileData | null,
    model?: string,
    onDelta?: (chunk: string) => void,
  ) => mockChat(oppId, msg, history, profile, model, onDelta),
  getChatModels: () => mockGetChatModels(),
}));

import { ApiError } from '@/lib/api';
import OpportunityChatbot from './OpportunityChatbot';

const OPP: Opportunity = {
  id: 'opp-1',
  title: 'SURF Summer Program',
  organization: 'Beckman',
  opportunity_type: 'summer_program',
  paid: 'yes',
  location: 'Urbana',
  on_campus: true,
  deadline: undefined,
  description_clean: '',
  keywords: [],
  eligibility: {
    international_friendly: 'yes',
    preferred_year: [],
    majors: [],
    skills_required: [],
    citizenship_required: false,
  },
  application: { application_effort: 'medium', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 0.9 },
};

const PROFILE: ProfileData = {
  name: 'Jane',
  college: 'Grainger College of Engineering',
  major: 'CS',
  grade: 'Junior',
  is_international: false,
  skills: [{ name: 'Python', level: 'intermediate' }],
  coursework: ['CS 225'],
  research_interests: 'ML',
  seeking_types: ['research'],
  format_pref: 'on_campus',
  github_url: '',
  linkedin_url: '',
  experience_level: 'beginner',
} as unknown as ProfileData;

beforeEach(() => {
  mockChat.mockReset();
  mockGetChatModels.mockReset();
  // Default: no OpenRouter configured → empty list → picker hidden, so the
  // pre-existing tests render unchanged.
  mockGetChatModels.mockResolvedValue([]);
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('OpportunityChatbot — header + close affordance', () => {
  it('renders the title + subtitle from i18n', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    expect(screen.getByRole('heading', { name: /chatbot.title/ })).toBeInTheDocument();
    expect(screen.getByText(/chatbot.subtitle/)).toBeInTheDocument();
  });

  it('omits the close button when onClose is not supplied', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    expect(screen.queryByRole('button', { name: /chatbot.closeAria/ })).toBeNull();
  });

  it('renders the close button when onClose is supplied and forwards clicks', () => {
    const onClose = vi.fn();
    render(<OpportunityChatbot opportunity={OPP} profile={null} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /chatbot.closeAria/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('OpportunityChatbot — welcome + suggested prompts', () => {
  it('shows the welcome card with opportunity.title interpolated when no messages yet', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    expect(
      screen.getByText(/chatbot.welcome\{title=SURF Summer Program\}/),
    ).toBeInTheDocument();
    expect(screen.getByText(/chatbot.tryAsking/)).toBeInTheDocument();
  });

  it('uses faculty-contact questions and copy instead of application language', async () => {
    mockChat.mockResolvedValue({ reply: 'Verify the source profile.', method: 'local' });
    const faculty = {
      ...OPP,
      source_type: 'faculty_research',
      title: 'Ada Lovelace',
    };
    render(<OpportunityChatbot opportunity={faculty} profile={null} />);

    expect(screen.getByText('chatbot.facultySubtitle')).toBeInTheDocument();
    expect(screen.getByText(/chatbot.facultyWelcome\{title=Ada Lovelace\}/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText('chatbot.facultyPlaceholder')).toBeInTheDocument();
    expect(screen.queryByText('chatbot.suggested.nextSteps')).toBeNull();

    fireEvent.click(screen.getByText('chatbot.facultySuggested.nextSteps'));
    await waitFor(() => {
      expect(mockChat).toHaveBeenCalledWith(
        'opp-1',
        'chatbot.facultySuggested.nextSteps',
        [],
        null,
        undefined,
        expect.any(Function),
      );
    });
  });

  it('renders 4 suggested-prompt buttons', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    expect(screen.getByRole('button', { name: /chatbot.suggested.fit/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /chatbot.suggested.nextSteps/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /chatbot.suggested.skills/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /chatbot.suggested.email/ })).toBeInTheDocument();
  });

  it('clicking a suggested prompt sends it via chatWithOpportunity', async () => {
    mockChat.mockResolvedValue({ reply: 'sure', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    fireEvent.click(screen.getByRole('button', { name: /chatbot.suggested.fit/ }));

    await waitFor(() =>
      // 5th arg is the picked model — undefined when the picker is on "Auto".
      expect(mockChat).toHaveBeenCalledWith(OPP.id, 'chatbot.suggested.fit', [], null, undefined, expect.any(Function)),
    );
  });
});

describe('OpportunityChatbot — send flow', () => {
  it('submitting the form calls chatWithOpportunity with (oppId, text, history, profile)', async () => {
    mockChat.mockResolvedValue({ reply: 'hi back', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={PROFILE} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'tell me more' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() =>
      expect(mockChat).toHaveBeenCalledWith(OPP.id, 'tell me more', [], PROFILE, undefined, expect.any(Function)),
    );
  });

  it('renders the assistant reply after a successful send', async () => {
    mockChat.mockResolvedValue({ reply: 'eligible if junior+', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'am I eligible?' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText('eligible if junior+')).toBeInTheDocument());
    expect(screen.getByText('am I eligible?')).toBeInTheDocument();
  });

  it('shows the thinking spinner while in flight + disables the textarea', async () => {
    let resolve!: (v: ChatResponse) => void;
    mockChat.mockReturnValue(new Promise<ChatResponse>((res) => { resolve = res; }));
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'hello' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/chatbot.thinking/)).toBeInTheDocument());
    expect(textarea).toBeDisabled();

    resolve({ reply: 'pong', method: 'llm' });
    await waitFor(() => expect(screen.getByText('pong')).toBeInTheDocument());
  });

  it('clears the input after a successful send', async () => {
    mockChat.mockResolvedValue({ reply: 'ack', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(mockChat).toHaveBeenCalled());
    expect(textarea.value).toBe('');
  });

  it('whitespace-only input is a no-op (does not call the API)', async () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: '   \n  ' } });
    fireEvent.submit(textarea.closest('form')!);

    await new Promise((r) => setTimeout(r, 10));
    expect(mockChat).not.toHaveBeenCalled();
  });

  it('Send button is disabled when the input is empty or whitespace-only', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    const send = screen.getByRole('button', { name: /chatbot.sendAria/ });
    expect(send).toBeDisabled();

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: '   ' } });
    expect(send).toBeDisabled();

    fireEvent.change(textarea, { target: { value: 'real' } });
    expect(send).toBeEnabled();
  });
});

describe('OpportunityChatbot — error handling', () => {
  it('shows the error banner and restores the input on failure', async () => {
    mockChat.mockRejectedValue(new Error('rate limited'));
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'are you there?' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/rate limited/)).toBeInTheDocument());
    expect(textarea.value).toBe('are you there?');
  });

  it('removes the pending user bubble when the API call fails (no orphan message)', async () => {
    mockChat.mockRejectedValue(new Error('boom'));
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'unique-user-marker' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
    expect(screen.queryAllByText('unique-user-marker').filter((el) => el.tagName !== 'TEXTAREA')).toHaveLength(0);
  });

  it('shows the translated rate-limit message on a 429 instead of the raw API error', async () => {
    mockChat.mockRejectedValue(
      new ApiError(
        429,
        'RATE_LIMITED',
        'The service is busy. Please try again shortly.',
        true,
      ),
    );
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/chatbot.errorRateLimited/)).toBeInTheDocument());
    expect(screen.queryByText(/service is busy/i)).toBeNull();
  });

  it('falls back to the generic error message when the thrown value is not an Error', async () => {
    mockChat.mockRejectedValue('not an Error instance');
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/chatbot.errorGeneric/)).toBeInTheDocument());
  });
});

describe('OpportunityChatbot — profile share toggle', () => {
  it('hides the profile-share row entirely when profile is null', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    expect(screen.queryByText(/chatbot.profileSharedHint/)).toBeNull();
    expect(screen.queryByText(/chatbot.profileNotSharedHint/)).toBeNull();
  });

  it('shows the shared-hint by default when profile is present', () => {
    render(<OpportunityChatbot opportunity={OPP} profile={PROFILE} />);
    expect(screen.getByText(/chatbot.profileSharedHint/)).toBeInTheDocument();
  });

  it('unchecking the share-profile toggle flips the hint AND drops the profile from the next call', async () => {
    mockChat.mockResolvedValue({ reply: 'ok', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={PROFILE} />);

    const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
    expect(checkbox.checked).toBe(true);

    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(false);
    expect(screen.getByText(/chatbot.profileNotSharedHint/)).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(mockChat).toHaveBeenCalledWith(OPP.id, 'hi', [], null, undefined, expect.any(Function)));
  });
});

describe('OpportunityChatbot — keyboard + clear', () => {
  it('Enter (without shift) submits the message', async () => {
    mockChat.mockResolvedValue({ reply: 'ack', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'kbd' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await waitFor(() => expect(mockChat).toHaveBeenCalledWith(OPP.id, 'kbd', [], null, undefined, expect.any(Function)));
  });

  it('Shift+Enter does NOT submit (newline path)', async () => {
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'multi' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

    await new Promise((r) => setTimeout(r, 10));
    expect(mockChat).not.toHaveBeenCalled();
  });

  it('clear button only appears after the first message and resets the conversation', async () => {
    mockChat.mockResolvedValue({ reply: 'ack', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    expect(screen.queryByRole('button', { name: /chatbot.clearAria/ })).toBeNull();

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'first' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText('ack')).toBeInTheDocument());

    const clear = screen.getByRole('button', { name: /chatbot.clearAria/ });
    fireEvent.click(clear);

    expect(screen.queryByText('first')).toBeNull();
    expect(screen.queryByText('ack')).toBeNull();
    expect(screen.getByText(/chatbot.welcome/)).toBeInTheDocument();
  });
});

describe('OpportunityChatbot — chat history propagation', () => {
  it('sends the prior turns as history on the next chatWithOpportunity call', async () => {
    mockChat
      .mockResolvedValueOnce({ reply: 'first-reply', method: 'llm' })
      .mockResolvedValueOnce({ reply: 'second-reply', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);

    fireEvent.change(textarea, { target: { value: 'first-q' } });
    fireEvent.submit(textarea.closest('form')!);
    await waitFor(() => expect(screen.getByText('first-reply')).toBeInTheDocument());

    fireEvent.change(textarea, { target: { value: 'second-q' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() =>
      expect(mockChat).toHaveBeenLastCalledWith(
        OPP.id,
        'second-q',
        [
          { role: 'user', content: 'first-q' },
          { role: 'assistant', content: 'first-reply' },
        ],
        null,
        undefined,
        expect.any(Function),
      ),
    );
  });

  it('caps the request history at the last 20 entries while the UI keeps the full transcript', async () => {
    // 11 completed exchanges = 22 messages in state; the backend rejects
    // history > 20, so the 12th send must trim to the most recent 20.
    for (let i = 0; i < 12; i++) {
      mockChat.mockResolvedValueOnce({ reply: `reply-${i}`, method: 'llm' });
    }
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);

    for (let i = 0; i < 12; i++) {
      fireEvent.change(textarea, { target: { value: `q-${i}` } });
      fireEvent.submit(textarea.closest('form')!);
      await waitFor(() => expect(screen.getByText(`reply-${i}`)).toBeInTheDocument());
    }

    const history = mockChat.mock.calls.at(-1)![2] as { role: string; content: string }[];
    expect(history.length).toBeLessThanOrEqual(20);
    expect(history[0]).toEqual({ role: 'user', content: 'q-1' });
    expect(history.at(-1)).toEqual({ role: 'assistant', content: 'reply-10' });
    expect(screen.getByText('q-0')).toBeInTheDocument();
    expect(screen.getByText('reply-0')).toBeInTheDocument();
  });
});

describe('OpportunityChatbot — model picker', () => {
  it('hides the picker when no models are available', async () => {
    mockGetChatModels.mockResolvedValue([]);
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);
    await waitFor(() => expect(mockGetChatModels).toHaveBeenCalled());
    expect(screen.queryByLabelText(/chatbot.modelAria/)).toBeNull();
  });

  it('shows the picker and sends the chosen model on the next message', async () => {
    mockGetChatModels.mockResolvedValue([
      { id: 'gemini-flash', label: 'Gemini Flash' },
      { id: 'gpt-4o-mini', label: 'GPT-4o mini' },
    ]);
    mockChat.mockResolvedValue({ reply: 'ok', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const select = (await screen.findByLabelText(/chatbot.modelAria/)) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'gpt-4o-mini' } });

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() =>
      expect(mockChat).toHaveBeenCalledWith(OPP.id, 'hi', [], null, 'gpt-4o-mini', expect.any(Function)),
    );
  });

  it('defaults to the first tier and renders i18n labels for auto/thinking', async () => {
    mockGetChatModels.mockResolvedValue([
      { id: 'auto', label: 'Auto' },
      { id: 'thinking', label: 'Thinking' },
    ]);
    mockChat.mockResolvedValue({ reply: 'ok', method: 'llm' });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const select = (await screen.findByLabelText(/chatbot.modelAria/)) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe('auto'));
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toEqual(['chatbot.modelAuto', 'chatbot.modelThinking']);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/);
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() =>
      expect(mockChat).toHaveBeenCalledWith(OPP.id, 'hi', [], null, 'auto', expect.any(Function)),
    );
  });
});

describe('OpportunityChatbot — SSE streaming', () => {
  it('renders partial text progressively and hides the spinner after the first delta', async () => {
    let release!: () => void;
    const gate = new Promise<void>((res) => { release = res; });
    mockChat.mockImplementation(async (_o, _m, _h, _p, _model, onDelta) => {
      onDelta!('The lab');
      await gate;
      onDelta!(' pays $15/hr.');
      return { reply: 'The lab pays $15/hr.', method: 'llm' };
    });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'is it paid?' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText('The lab')).toBeInTheDocument());
    expect(screen.queryByText(/chatbot.thinking/)).toBeNull();
    expect(textarea).toBeDisabled();

    release();
    await waitFor(() => expect(screen.getByText('The lab pays $15/hr.')).toBeInTheDocument());
    await waitFor(() => expect(textarea).toBeEnabled());
    expect(screen.queryAllByText('The lab')).toHaveLength(0);
  });

  it('keeps the partial text and shows the generic error when the result is errored', async () => {
    mockChat.mockImplementation(async (_o, _m, _h, _p, _model, onDelta) => {
      onDelta!('Partial answer');
      return { reply: 'Partial answer', method: 'llm', errored: true };
    });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'stream-err-q' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/chatbot.errorGeneric/)).toBeInTheDocument());
    expect(screen.getByText('Partial answer')).toBeInTheDocument();
    expect(screen.getByText('stream-err-q')).toBeInTheDocument();
  });

  it('keeps the partial bubble (and the user bubble) when the call throws after a delta', async () => {
    mockChat.mockImplementation(async (_o, _m, _h, _p, _model, onDelta) => {
      onDelta!('half a reply');
      throw new Error('stream cut');
    });
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'my question' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/stream cut/)).toBeInTheDocument());
    expect(screen.getByText('half a reply')).toBeInTheDocument();
    expect(screen.getByText('my question')).toBeInTheDocument();
    expect(textarea.value).toBe('');
  });

  it('preserves the legacy failure path when the call throws before any delta', async () => {
    mockChat.mockRejectedValue(new Error('total failure'));
    render(<OpportunityChatbot opportunity={OPP} profile={null} />);

    const textarea = screen.getByPlaceholderText(/chatbot.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'no-delta-q' } });
    fireEvent.submit(textarea.closest('form')!);

    await waitFor(() => expect(screen.getByText(/total failure/)).toBeInTheDocument());
    expect(screen.queryAllByText('no-delta-q').filter((el) => el.tagName !== 'TEXTAREA')).toHaveLength(0);
    expect(textarea.value).toBe('no-delta-q');
  });
});
