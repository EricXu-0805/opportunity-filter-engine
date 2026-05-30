import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Attachment, AttachmentUploadResult } from '@/lib/supabase';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (!vars) return key;
      const pairs = Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(',');
      return `${key}{${pairs}}`;
    },
  }),
}));

const mockList = vi.fn<(oppId: string) => Promise<Attachment[]>>();
const mockUpload = vi.fn<(oppId: string, file: File) => Promise<AttachmentUploadResult>>();
const mockDelete = vi.fn<(oppId: string, name: string) => Promise<boolean>>();
const mockSigned = vi.fn<(oppId: string, name: string) => Promise<string | null>>();

vi.mock('@/lib/supabase', () => ({
  ATTACHMENTS_MAX_BYTES: 5 * 1024 * 1024,
  ATTACHMENTS_ALLOWED_MIME: new Set([
    'application/pdf',
    'image/png',
    'image/jpeg',
    'text/plain',
  ]),
  listAttachments: (oppId: string) => mockList(oppId),
  uploadAttachment: (oppId: string, file: File) => mockUpload(oppId, file),
  deleteAttachment: (oppId: string, name: string) => mockDelete(oppId, name),
  getAttachmentSignedUrl: (oppId: string, name: string) => mockSigned(oppId, name),
}));

import AttachmentsPanel from './AttachmentsPanel';

const OPP_ID = 'opp-42';

function makeAttachment(overrides: Partial<Attachment> = {}): Attachment {
  return {
    name: 'resume.pdf',
    sizeBytes: 12345,
    mimeType: 'application/pdf',
    createdAt: '2026-05-01T10:00:00Z',
    ...overrides,
  };
}

function fileFromMime(name: string, mime: string, size = 100): File {
  const file = new File(['x'.repeat(size)], name, { type: mime });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

beforeEach(() => {
  mockList.mockReset();
  mockUpload.mockReset();
  mockDelete.mockReset();
  mockSigned.mockReset();
  mockList.mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AttachmentsPanel — lifecycle', () => {
  it('shows the loading state on first render', () => {
    mockList.mockReturnValue(new Promise(() => {}));
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    expect(screen.getByText(/detail.attachments.loading/)).toBeInTheDocument();
  });

  it('calls listAttachments with the opportunityId on mount', async () => {
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledWith(OPP_ID));
  });

  it('renders the empty-state copy when listAttachments returns []', async () => {
    mockList.mockResolvedValue([]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText(/detail.attachments.empty/)).toBeInTheDocument());
  });
});

describe('AttachmentsPanel — rendering', () => {
  it('renders one row per attachment with the filename, open + delete affordances', async () => {
    mockList.mockResolvedValue([
      makeAttachment({ name: 'resume.pdf', sizeBytes: 50_000 }),
      makeAttachment({ name: 'offer-letter.png', sizeBytes: 1_500_000 }),
    ]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('resume.pdf')).toBeInTheDocument());

    expect(screen.getByText('offer-letter.png')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /detail.attachments.openAria\{name=resume.pdf\}/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /detail.attachments.deleteAria\{name=resume.pdf\}/ }),
    ).toBeInTheDocument();
  });

  it('formats byte sizes: <1KB → bytes, <1MB → KB, ≥1MB → MB', async () => {
    mockList.mockResolvedValue([
      makeAttachment({ name: 'tiny.txt', sizeBytes: 512 }),
      makeAttachment({ name: 'mid.png', sizeBytes: 64 * 1024 }),
      makeAttachment({ name: 'big.pdf', sizeBytes: 2 * 1024 * 1024 }),
    ]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('tiny.txt')).toBeInTheDocument());

    expect(screen.getByText(/detail.attachments.sizeBytes\{n=512\}/)).toBeInTheDocument();
    expect(screen.getByText(/detail.attachments.sizeKB\{n=64\}/)).toBeInTheDocument();
    expect(screen.getByText(/detail.attachments.sizeMB\{n=2\.0\}/)).toBeInTheDocument();
  });

  it('shows the add-attachment button + hint with the max-MB value substituted', async () => {
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText(/detail.attachments.empty/)).toBeInTheDocument());

    expect(screen.getByRole('button', { name: /detail.attachments.addButton/ })).toBeInTheDocument();
    expect(screen.getByText(/detail.attachments.hint\{mb=5\}/)).toBeInTheDocument();
  });
});

describe('AttachmentsPanel — upload flow', () => {
  it('selecting a file calls uploadAttachment with (opportunityId, file)', async () => {
    mockUpload.mockResolvedValue({ ok: true, name: 'resume.pdf' });
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = fileFromMime('resume.pdf', 'application/pdf');
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockUpload).toHaveBeenCalledWith(OPP_ID, file));
  });

  it('shows the uploading label while the upload is in flight + disables the button', async () => {
    let resolveUpload!: (v: AttachmentUploadResult) => void;
    mockUpload.mockReturnValue(new Promise<AttachmentUploadResult>((res) => { resolveUpload = res; }));
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = fileFromMime('mid.pdf', 'application/pdf');
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByText(/detail.attachments.uploading\{name=mid.pdf\}/)).toBeInTheDocument(),
    );
    const button = screen.getByRole('button', { name: /detail.attachments.uploading/ });
    expect(button).toBeDisabled();

    resolveUpload({ ok: true, name: 'mid.pdf' });
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('refreshes the list when the upload succeeds', async () => {
    mockUpload.mockResolvedValue({ ok: true, name: 'r.pdf' });
    mockList.mockResolvedValueOnce([]).mockResolvedValueOnce([makeAttachment({ name: 'r.pdf' })]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileFromMime('r.pdf', 'application/pdf')] } });

    await waitFor(() => expect(screen.getByText('r.pdf')).toBeInTheDocument());
    expect(mockList).toHaveBeenCalledTimes(2);
  });

  it('clears the file input value after selection so the same file can be re-picked', async () => {
    mockUpload.mockResolvedValue({ ok: true, name: 'a.pdf' });
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileFromMime('a.pdf', 'application/pdf')] } });
    await waitFor(() => expect(mockUpload).toHaveBeenCalled());

    expect(input.value).toBe('');
  });

  it('ignores a change event with no file (defensive guard)', async () => {
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [] } });

    expect(mockUpload).not.toHaveBeenCalled();
  });
});

describe('AttachmentsPanel — upload error paths', () => {
  const cases: Array<{
    reason: 'too_large' | 'wrong_type' | 'duplicate' | 'unauthenticated' | 'unknown';
    msg?: string;
    needle: RegExp;
  }> = [
    { reason: 'too_large', needle: /detail.attachments.errTooLarge/ },
    { reason: 'wrong_type', needle: /detail.attachments.errWrongType/ },
    { reason: 'duplicate', needle: /detail.attachments.errDuplicate\{name=foo.pdf\}/ },
    { reason: 'unauthenticated', needle: /detail.attachments.errUnauth/ },
    { reason: 'unknown', msg: 'oops', needle: /detail.attachments.errUpload\{msg=oops\}/ },
  ];

  for (const { reason, msg, needle } of cases) {
    it(`surfaces the correct banner when upload returns reason=${reason}`, async () => {
      mockUpload.mockResolvedValue({ ok: false, reason, message: msg });
      render(<AttachmentsPanel opportunityId={OPP_ID} />);
      await waitFor(() => expect(mockList).toHaveBeenCalled());

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(input, { target: { files: [fileFromMime('foo.pdf', 'application/pdf')] } });

      await waitFor(() => expect(screen.getByText(needle)).toBeInTheDocument());
    });
  }

  it('does not refresh the list when the upload failed', async () => {
    mockUpload.mockResolvedValue({ ok: false, reason: 'too_large' });
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileFromMime('big.pdf', 'application/pdf')] } });

    await waitFor(() => expect(screen.getByText(/errTooLarge/)).toBeInTheDocument());
    expect(mockList).toHaveBeenCalledTimes(1);
  });
});

describe('AttachmentsPanel — open / signed URL', () => {
  it('clicking open calls getAttachmentSignedUrl with (oppId, name) and opens the URL in a new tab', async () => {
    mockList.mockResolvedValue([makeAttachment({ name: 'doc.pdf' })]);
    mockSigned.mockResolvedValue('https://signed.example/doc');
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);

    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('doc.pdf')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('button', { name: /detail.attachments.openAria\{name=doc.pdf\}/ }),
    );

    await waitFor(() => expect(mockSigned).toHaveBeenCalledWith(OPP_ID, 'doc.pdf'));
    expect(openSpy).toHaveBeenCalledWith('https://signed.example/doc', '_blank', 'noopener,noreferrer');
  });

  it('shows an error banner when the signed-URL helper returns null', async () => {
    mockList.mockResolvedValue([makeAttachment({ name: 'broken.png' })]);
    mockSigned.mockResolvedValue(null);
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);

    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('broken.png')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('button', { name: /detail.attachments.openAria\{name=broken.png\}/ }),
    );

    await waitFor(() =>
      expect(
        screen.getByText(/detail.attachments.errOpen\{name=broken.png\}/),
      ).toBeInTheDocument(),
    );
    expect(openSpy).not.toHaveBeenCalled();
  });
});

describe('AttachmentsPanel — delete', () => {
  it('clicking delete calls deleteAttachment with (oppId, name) and removes the row optimistically on success', async () => {
    mockList.mockResolvedValue([
      makeAttachment({ name: 'gone.pdf' }),
      makeAttachment({ name: 'stays.pdf' }),
    ]);
    mockDelete.mockResolvedValue(true);

    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('gone.pdf')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('button', { name: /detail.attachments.deleteAria\{name=gone.pdf\}/ }),
    );

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(OPP_ID, 'gone.pdf'));
    await waitFor(() => expect(screen.queryByText('gone.pdf')).toBeNull());
    expect(screen.getByText('stays.pdf')).toBeInTheDocument();
  });

  it('shows an error banner and keeps the row when deleteAttachment fails', async () => {
    mockList.mockResolvedValue([makeAttachment({ name: 'oops.pdf' })]);
    mockDelete.mockResolvedValue(false);

    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('oops.pdf')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('button', { name: /detail.attachments.deleteAria\{name=oops.pdf\}/ }),
    );

    await waitFor(() =>
      expect(screen.getByText(/detail.attachments.errDelete\{name=oops.pdf\}/)).toBeInTheDocument(),
    );
    expect(screen.getByText('oops.pdf')).toBeInTheDocument();
  });
});
