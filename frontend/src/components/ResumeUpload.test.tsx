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
    render(<ResumeUpload onParsed={vi.fn()} />);
    expect(screen.getByText(/resume.dropHere/)).toBeInTheDocument();
    expect(screen.getByText(/resume.browse/)).toBeInTheDocument();
    expect(screen.getByText(/resume.pdfOnly/)).toBeInTheDocument();
  });

  it('uses a screen-reader-only file input with accept=".pdf"', () => {
    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.getAttribute('accept')).toBe('.pdf');
    expect(input.className).toContain('sr-only');
  });

  it('clicking the dropzone forwards to the hidden file input', () => {
    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');

    fireEvent.click(screen.getByText(/resume.dropHere/).closest('div')!.parentElement!);

    expect(clickSpy).toHaveBeenCalledTimes(1);
  });
});

describe('ResumeUpload — alreadyUploaded prop', () => {
  it('renders the success state from the start when alreadyUploaded is true', async () => {
    render(<ResumeUpload onParsed={vi.fn()} alreadyUploaded />);
    await waitFor(() => expect(screen.getByText(/resume.success/)).toBeInTheDocument());
    expect(screen.getByText('resume.savedFallback')).toBeInTheDocument();
  });

  it('stays in idle when alreadyUploaded is false / omitted', () => {
    render(<ResumeUpload onParsed={vi.fn()} />);
    expect(screen.queryByText(/resume.success/)).toBeNull();
    expect(screen.getByText(/resume.dropHere/)).toBeInTheDocument();
  });
});

describe('ResumeUpload — file validation', () => {
  it('rejects a non-PDF file with errOnlyPdf and does not call parseResumePDF', async () => {
    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [txtFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.errOnlyPdf/)).toBeInTheDocument());
    expect(mockParse).not.toHaveBeenCalled();
  });

  it('rejects a PDF over 5 MB with errTooBig', async () => {
    render(<ResumeUpload onParsed={vi.fn()} />);
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

    render(<ResumeUpload onParsed={onParsed} />);
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

    render(<ResumeUpload onParsed={vi.fn()} />);
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

    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() =>
      expect(screen.getByText(/Could not detect text in the PDF/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/resume.tryAgain/)).toBeInTheDocument();
  });

  it('falls back to resume.errParse when success=false but no message supplied', async () => {
    mockParse.mockResolvedValue({ success: false, extracted: {} } as unknown as ResumeParseResponse);

    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.errParse/)).toBeInTheDocument());
  });

  it('shows the thrown Error.message when parseResumePDF rejects with an Error', async () => {
    mockParse.mockRejectedValue(new Error('PDF.js worker is dead'));

    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/PDF.js worker is dead/)).toBeInTheDocument());
  });

  it('falls back to resume.errFailed when the rejection is not an Error', async () => {
    mockParse.mockRejectedValue('weird-throw');

    render(<ResumeUpload onParsed={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    await waitFor(() => expect(screen.getByText(/resume.errFailed/)).toBeInTheDocument());
  });
});

describe('ResumeUpload — reset / re-upload', () => {
  it('Try-again from the error state returns the dropzone to idle', async () => {
    mockParse.mockResolvedValue({ success: false, message: 'nope', extracted: {} } as unknown as ResumeParseResponse);

    render(<ResumeUpload onParsed={vi.fn()} />);
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

    render(<ResumeUpload onParsed={vi.fn()} />);
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

    render(<ResumeUpload onParsed={vi.fn()} />);
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
    render(<ResumeUpload onParsed={vi.fn()} />);
    const zone = screen.getByText(/resume.dropHere/).closest('div')!.parentElement!;

    fireEvent.dragOver(zone);
    expect(zone.className).toContain('border-indigo-400');

    fireEvent.dragLeave(zone);
    expect(zone.className).not.toContain('border-indigo-400');
  });

  it('drop with a PDF file kicks off the upload', async () => {
    mockParse.mockResolvedValue({ success: true, message: 'ok', extracted: {} } as unknown as ResumeParseResponse);
    render(<ResumeUpload onParsed={vi.fn()} />);

    const zone = screen.getByText(/resume.dropHere/).closest('div')!.parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [pdfFile('drop.pdf')] } });

    await waitFor(() => expect(mockParse).toHaveBeenCalledTimes(1));
  });

  it('drop with no file is a no-op', () => {
    render(<ResumeUpload onParsed={vi.fn()} />);
    const zone = screen.getByText(/resume.dropHere/).closest('div')!.parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [] } });

    expect(mockParse).not.toHaveBeenCalled();
  });
});
