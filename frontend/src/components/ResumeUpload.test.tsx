import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ResumeParseResponse } from '@/lib/types';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

const mockParse = vi.fn<(file: File) => Promise<ResumeParseResponse>>();
vi.mock('@/lib/pdf-parser', () => ({
  parseResumePDF: (file: File) => mockParse(file),
}));

import ResumeUpload from './ResumeUpload';

function pdfFile(name = 'resume.pdf', size = 200_000): File {
  const f = new File(['%PDF-1.4'], name, { type: 'application/pdf' });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

function txtFile(name = 'note.txt', size = 200): File {
  const f = new File(['hello'], name, { type: 'text/plain' });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

beforeEach(() => {
  mockParse.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResumeUpload — idle state', () => {
  it('renders the dropzone with browse + pdf-only copy when idle', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText(/resume.dropHere/)).toBeInTheDocument();
    expect(screen.getByText(/resume.browse/)).toBeInTheDocument();
    expect(screen.getByText(/resume.pdfOnly/)).toBeInTheDocument();
  });

  it('uses a screen-reader-only file input with accept=".pdf"', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.getAttribute('accept')).toBe('.pdf');
    expect(input.className).toContain('sr-only');
  });

  it('clicking the dropzone forwards to the hidden file input', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');

    fireEvent.click(screen.getByText(/resume.dropHere/).closest('div')!.parentElement!);

    expect(clickSpy).toHaveBeenCalledTimes(1);
  });
});

describe('ResumeUpload — alreadyUploaded prop', () => {
  it('renders the success state from the start when alreadyUploaded is true', async () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} alreadyUploaded />);
    await waitFor(() => expect(screen.getByText(/resume.success/)).toBeInTheDocument());
    expect(screen.getByText('resume.savedFallback')).toBeInTheDocument();
  });

  it('stays in idle when alreadyUploaded is false / omitted', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.queryByText(/resume.success/)).toBeNull();
    expect(screen.getByText(/resume.dropHere/)).toBeInTheDocument();
  });
});

describe('ResumeUpload — file validation', () => {
  it('rejects a non-PDF file with errOnlyPdf and does not call parseResumePDF', async () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [txtFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.errOnlyPdf/)).toBeInTheDocument());
    expect(mockParse).not.toHaveBeenCalled();
  });

  it('rejects a PDF over 5 MB with errTooBig', async () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('huge.pdf', 6 * 1024 * 1024)] } });

    await waitFor(() => expect(screen.getByText(/resume.errTooBig/)).toBeInTheDocument());
    expect(mockParse).not.toHaveBeenCalled();
  });
});

describe('ResumeUpload — upload happy path', () => {
  it('uploads → parses → calls onParsed → shows success', async () => {
    const parsed: ResumeParseResponse = {
      success: true,
      message: 'parsed',
      extracted: { hard_skills: [{ name: 'Python', level: 'intermediate' }] },
    } as unknown as ResumeParseResponse;
    mockParse.mockResolvedValue(parsed);
    const onParsed = vi.fn();

    render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('me.pdf')] } });

    await waitFor(() => expect(onParsed).toHaveBeenCalledWith(parsed));
    expect(screen.getByText('me.pdf')).toBeInTheDocument();
    expect(screen.getByText(/resume.success/)).toBeInTheDocument();
  });

  it('shows the uploading state with the filename while in flight', async () => {
    vi.useFakeTimers();
    let resolveParse!: (v: ResumeParseResponse) => void;
    mockParse.mockReturnValue(new Promise<ResumeParseResponse>((res) => { resolveParse = res; }));

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('cv.pdf')] } });

    expect(screen.getByText('cv.pdf')).toBeInTheDocument();
    expect(screen.getByText(/0%/)).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(900); });
    expect(screen.getByText(/45%/)).toBeInTheDocument();

    vi.useRealTimers();
    await act(async () => {
      resolveParse({ success: true, message: 'ok', extracted: {} } as unknown as ResumeParseResponse);
      await Promise.resolve();
    });
  });
});

describe('ResumeUpload — failure paths', () => {
  it('shows the server-side parse-failure message when success=false', async () => {
    mockParse.mockResolvedValue({
      success: false,
      message: 'Could not detect text in the PDF',
      extracted: {},
    } as unknown as ResumeParseResponse);

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() =>
      expect(screen.getByText(/Could not detect text in the PDF/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/resume.tryAgain/)).toBeInTheDocument();
  });

  it('falls back to resume.errParse when success=false but no message supplied', async () => {
    mockParse.mockResolvedValue({ success: false, extracted: {} } as unknown as ResumeParseResponse);

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.errParse/)).toBeInTheDocument());
  });

  it('shows the thrown Error.message when parseResumePDF rejects with an Error', async () => {
    mockParse.mockRejectedValue(new Error('PDF.js worker is dead'));

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/PDF.js worker is dead/)).toBeInTheDocument());
  });

  it('falls back to resume.errFailed when the rejection is not an Error', async () => {
    mockParse.mockRejectedValue('weird-throw');

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.errFailed/)).toBeInTheDocument());
  });
});

describe('ResumeUpload — reset / re-upload', () => {
  it('Try-again from the error state returns the dropzone to idle', async () => {
    mockParse.mockResolvedValue({ success: false, message: 'nope', extracted: {} } as unknown as ResumeParseResponse);

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });
    await waitFor(() => expect(screen.getByText(/resume.tryAgain/)).toBeInTheDocument());

    fireEvent.click(screen.getByText(/resume.tryAgain/));

    expect(screen.getByText(/resume.dropHere/)).toBeInTheDocument();
    expect(screen.queryByText(/resume.tryAgain/)).toBeNull();
  });

  it('Remove button from the success state returns the dropzone to idle + clears input value', async () => {
    const parsed = { success: true, message: 'ok', extracted: {} } as unknown as ResumeParseResponse;
    mockParse.mockResolvedValue(parsed);

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.success/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /resume.removeAria/ }));

    expect(screen.getByText(/resume.dropHere/)).toBeInTheDocument();
    expect(input.value).toBe('');
  });

  it('Remove button click does not bubble into the dropzone click handler', async () => {
    const parsed = { success: true, message: 'ok', extracted: {} } as unknown as ResumeParseResponse;
    mockParse.mockResolvedValue(parsed);

    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.change(input, { target: { files: [pdfFile()] } });
    await waitFor(() => expect(screen.getByText(/resume.success/)).toBeInTheDocument());

    clickSpy.mockClear();
    fireEvent.click(screen.getByRole('button', { name: /resume.removeAria/ }));

    expect(clickSpy).not.toHaveBeenCalled();
  });
});

describe('ResumeUpload — drag and drop', () => {
  it('drag-over flips the dropzone styling + onDragLeave clears it', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const zone = screen.getByText(/resume.dropHere/).closest('div')!.parentElement!;

    fireEvent.dragOver(zone);
    expect(zone.className).toContain('border-indigo-400');

    fireEvent.dragLeave(zone);
    expect(zone.className).not.toContain('border-indigo-400');
  });

  it('drop with a PDF file kicks off the upload', async () => {
    mockParse.mockResolvedValue({ success: true, message: 'ok', extracted: {} } as unknown as ResumeParseResponse);
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);

    const zone = screen.getByText(/resume.dropHere/).closest('div')!.parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [pdfFile('drop.pdf')] } });

    await waitFor(() => expect(mockParse).toHaveBeenCalledTimes(1));
  });

  it('drop with no file is a no-op', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const zone = screen.getByText(/resume.dropHere/).closest('div')!.parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [] } });

    expect(mockParse).not.toHaveBeenCalled();
  });
});

describe('ResumeUpload — latest file wins', () => {
  it('a slower earlier parse never overwrites the newer file\'s result', async () => {
    const resolvers: Array<(v: ResumeParseResponse) => void> = [];
    mockParse.mockImplementation(
      () => new Promise<ResumeParseResponse>((resolve) => { resolvers.push(resolve); }),
    );
    const onParsed = vi.fn();
    render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } }); // A
    await waitFor(() => expect(resolvers).toHaveLength(1));
    // A drop still reaches the handler while "uploading" — only the click
    // path is blocked — so B genuinely overlaps A.
    fireEvent.drop(input.parentElement!.querySelector('div')!, {
      dataTransfer: { files: [pdfFile('b.pdf')] },
    });
    await waitFor(() => expect(resolvers).toHaveLength(2));

    await act(async () => {
      resolvers[1]({ success: true, message: 'B' } as unknown as ResumeParseResponse);
    });
    expect(onParsed).toHaveBeenCalledTimes(1);
    expect((onParsed.mock.calls[0][0] as ResumeParseResponse).message).toBe('B');

    await act(async () => {
      resolvers[0]({ success: true, message: 'A' } as unknown as ResumeParseResponse);
    });
    expect(onParsed).toHaveBeenCalledTimes(1); // A wrote nothing
    expect(screen.getByText('b.pdf')).toBeInTheDocument();
  });

  it('a parse superseded by a second file writes nothing when it finally lands', async () => {
    const resolvers: Array<(v: ResumeParseResponse) => void> = [];
    mockParse.mockImplementation(
      () => new Promise<ResumeParseResponse>((resolve) => { resolvers.push(resolve); }),
    );
    const onParsed = vi.fn();
    render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } });
    await waitFor(() => expect(resolvers).toHaveLength(1));

    fireEvent.drop(input.parentElement!.querySelector('div')!, {
      dataTransfer: { files: [pdfFile('b.pdf')] },
    });
    await waitFor(() => expect(resolvers).toHaveLength(2));

    await act(async () => {
      resolvers[0]({ success: true, message: 'A' } as unknown as ResumeParseResponse);
    });

    expect(onParsed).not.toHaveBeenCalled();
    expect(screen.getByText('b.pdf')).toBeInTheDocument();
  });

  it('Cancel during an upload returns to idle and the abandoned parse writes nothing', async () => {
    const resolvers: Array<(v: ResumeParseResponse) => void> = [];
    mockParse.mockImplementation(
      () => new Promise<ResumeParseResponse>((resolve) => { resolvers.push(resolve); }),
    );
    const onParsed = vi.fn();
    render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } });
    await waitFor(() => expect(screen.getByText('a.pdf')).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText('resume.cancelAria'));
    expect(screen.getByText('resume.dropHere')).toBeInTheDocument(); // back to idle
    expect(input.value).toBe('');

    await act(async () => {
      resolvers[0]({ success: true, message: 'A' } as unknown as ResumeParseResponse);
    });

    expect(onParsed).not.toHaveBeenCalled();
    expect(screen.getByText('resume.dropHere')).toBeInTheDocument();
    expect(screen.queryByText('resume.errParse')).toBeNull();
  });

  it('a parse resolving after unmount writes nothing', async () => {
    const resolvers: Array<(v: ResumeParseResponse) => void> = [];
    mockParse.mockImplementation(
      () => new Promise<ResumeParseResponse>((resolve) => { resolvers.push(resolve); }),
    );
    const onParsed = vi.fn();
    const { unmount } = render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } });
    await waitFor(() => expect(resolvers).toHaveLength(1));

    unmount();
    await act(async () => {
      resolvers[0]({ success: true, message: 'A' } as unknown as ResumeParseResponse);
    });

    expect(onParsed).not.toHaveBeenCalled();
  });
});

describe('ResumeUpload — a rejected new file still supersedes the parse in flight', () => {
  it('a non-PDF dropped over a running parse leaves the error standing when that parse lands', async () => {
    const resolvers: Array<(v: ResumeParseResponse) => void> = [];
    mockParse.mockImplementation(
      () => new Promise<ResumeParseResponse>((resolve) => { resolvers.push(resolve); }),
    );
    const onParsed = vi.fn();
    render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } });
    await waitFor(() => expect(resolvers).toHaveLength(1));

    fireEvent.drop(input.parentElement!.querySelector('div')!, {
      dataTransfer: { files: [txtFile('notes.txt')] },
    });
    expect(screen.getByText('resume.errOnlyPdf')).toBeInTheDocument();

    await act(async () => {
      resolvers[0]({ success: true, message: 'A' } as unknown as ResumeParseResponse);
    });

    expect(onParsed).not.toHaveBeenCalled();
    expect(screen.getByText('resume.errOnlyPdf')).toBeInTheDocument();
    expect(mockParse).toHaveBeenCalledTimes(1);
  });
});

describe('ResumeUpload — the progress timer never outlives its own attempt', () => {
  it('Cancel and unmount both clear the interval, observed on the timer itself', async () => {
    const clearSpy = vi.spyOn(globalThis, 'clearInterval');
    mockParse.mockImplementation(() => new Promise<ResumeParseResponse>(() => {}));
    const { unmount } = render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } });
    await waitFor(() => expect(screen.getByText('a.pdf')).toBeInTheDocument());
    const beforeCancel = clearSpy.mock.calls.length;
    fireEvent.click(screen.getByLabelText('resume.cancelAria'));
    expect(clearSpy.mock.calls.length).toBeGreaterThan(beforeCancel);

    fireEvent.change(input, { target: { files: [pdfFile('b.pdf')] } });
    await waitFor(() => expect(screen.getByText('b.pdf')).toBeInTheDocument());
    const beforeUnmount = clearSpy.mock.calls.length;
    unmount();
    expect(clearSpy.mock.calls.length).toBeGreaterThan(beforeUnmount);

    clearSpy.mockRestore();
  });
});

describe('ResumeUpload — Remove is a real removal, not a UI reset', () => {
  it('tells the parent to remove it, and does not bounce back to "on file"', async () => {
    const onRemove = vi.fn();
    const { rerender } = render(
      <ResumeUpload onParsed={vi.fn()} onRemove={onRemove} alreadyUploaded />,
    );
    expect(screen.getByText('resume.savedFallback')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('resume.removeAria'));

    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(screen.getByText('resume.dropHere')).toBeInTheDocument();
    // The parent's prop has not been re-rendered yet — the badge must not
    // reappear in the meantime.
    rerender(<ResumeUpload onParsed={vi.fn()} onRemove={onRemove} alreadyUploaded />);
    expect(screen.getByText('resume.dropHere')).toBeInTheDocument();
  });

  it('states what removal actually does while a résumé is on file', () => {
    render(<ResumeUpload onParsed={vi.fn()} onRemove={vi.fn()} alreadyUploaded />);
    expect(screen.getByText('resume.removeNote')).toBeInTheDocument();
  });

  it('a new upload after a removal restores the on-file state', async () => {
    mockParse.mockResolvedValue({ success: true, message: 'ok' } as unknown as ResumeParseResponse);
    const onParsed = vi.fn();
    render(<ResumeUpload onParsed={onParsed} onRemove={vi.fn()} alreadyUploaded />);
    fireEvent.click(screen.getByLabelText('resume.removeAria'));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('new.pdf')] } });

    await waitFor(() => expect(onParsed).toHaveBeenCalledTimes(1));
    expect(screen.getByText('new.pdf')).toBeInTheDocument();
  });

  it('Try again from an error state does NOT remove the profile copy', async () => {
    mockParse.mockRejectedValue(new Error('nope'));
    const onRemove = vi.fn();
    render(<ResumeUpload onParsed={vi.fn()} onRemove={onRemove} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile('a.pdf')] } });
    await waitFor(() => expect(screen.getByText('nope')).toBeInTheDocument());

    fireEvent.click(screen.getByText('resume.tryAgain'));
    expect(onRemove).not.toHaveBeenCalled();
  });
});

describe('ResumeUpload — the copy matches what the code actually does', () => {
  it('EN and ZH removal copy promise current-profile removal, never deletion of stored history', async () => {
    const en = (await import('@/i18n/dictionaries')).dictionaries.en;
    const zh = (await import('@/i18n/dictionaries')).dictionaries.zh;
    const enNote = (en.resume as Record<string, string>).removeNote;
    const zhNote = (zh.resume as Record<string, string>).removeNote;

    expect(enNote).toContain('current profile');
    expect(enNote).toContain('Earlier saved versions');
    expect(enNote).not.toMatch(/permanently|all copies|erase everything/i);
    expect(zhNote).toContain('当前的档案');
    expect(zhNote).toContain('历史版本');

    const enPrivacy = ((en.home as Record<string, unknown>).cards as Record<string, string>).resumePrivacy;
    const zhPrivacy = ((zh.home as Record<string, unknown>).cards as Record<string, string>).resumePrivacy;
    // The old copy claimed the text was "never stored permanently" while
    // saveProfile writes it to the profile row AND profile_versions.
    expect(enPrivacy).not.toMatch(/never stored/i);
    expect(enPrivacy).toContain('saved with your profile');
    expect(zhPrivacy).not.toContain('永不永久存储');
    expect(zhPrivacy).toContain('随档案一起保存');
  });
});
