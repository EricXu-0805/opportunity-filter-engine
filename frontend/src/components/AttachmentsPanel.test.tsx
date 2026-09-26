import { StrictMode } from 'react';
import { AttachmentRequestError } from '@/lib/attachment-request';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  onAuthChange: () => () => {},
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
import { advanceOwnerEpoch, isLocalOwnerReady, OwnerMismatchError, syncLocalIdentityOwner } from '@/lib/identity-owner';

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
    { reason: 'unknown', msg: 'oops', needle: /detail.attachments.uploadUnknown/ },
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

describe('AttachmentsPanel — the upload is bound to the account that picked the file', () => {
  async function claimOwner(uid: string): Promise<void> {
    advanceOwnerEpoch(uid);
    await syncLocalIdentityOwner(uid);
    for (let i = 0; i < 200 && !isLocalOwnerReady(uid); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(isLocalOwnerReady(uid)).toBe(true);
  }

  it('a refusal for the SAME account requires checking the list before another upload', async () => {
    await claimOwner('11111111-1111-4111-8111-111111111111');
    mockUpload.mockRejectedValue(new OwnerMismatchError());
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileFromMime('mine.pdf', 'application/pdf')] } });

    await waitFor(() => expect(screen.getByText(/detail.attachments.uploadUnknown/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'detail.attachments.addButton' })).toBeDisabled();
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('a signed URL that resolves after the account switched is not opened in the next account\'s tab', async () => {
    await claimOwner('11111111-1111-4111-8111-111111111111');
    mockList.mockResolvedValue([makeAttachment({ name: 'u1.pdf' })]);
    let resolveUrl: (v: string | null) => void = () => {};
    mockSigned.mockImplementation(() => new Promise<string | null>((r) => { resolveUrl = r; }));
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(screen.getByText('u1.pdf')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /detail.attachments.openAria\{name=u1.pdf\}/ }));
    await waitFor(() => expect(mockSigned).toHaveBeenCalled());

    await act(async () => { await claimOwner('22222222-2222-4222-8222-222222222222'); });
    await act(async () => { resolveUrl('https://signed.example/u1'); });

    expect(openSpy).not.toHaveBeenCalled();
  });

  it('a raced owner switch neither refreshes U1\'s list for U2 nor leaves U2 a disabled upload button', async () => {
    await claimOwner('11111111-1111-4111-8111-111111111111');
    let resolveUpload!: (v: AttachmentUploadResult) => void;
    mockUpload.mockReturnValue(new Promise<AttachmentUploadResult>((res) => { resolveUpload = res; }));
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileFromMime('u1.pdf', 'application/pdf')] } });
    await waitFor(() => expect(screen.getByRole('button', { name: /detail.attachments.uploading/ })).toBeDisabled());

    await act(async () => { await claimOwner('22222222-2222-4222-8222-222222222222'); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'detail.attachments.addButton' })).not.toBeDisabled());
    const readsAfterSwitch = mockList.mock.calls.length;
    expect(readsAfterSwitch).toBeGreaterThan(1);
    await act(async () => { resolveUpload({ ok: true, name: 'u1.pdf' }); });

    expect(mockList).toHaveBeenCalledTimes(readsAfterSwitch);
    expect(screen.getByRole('button', { name: 'detail.attachments.addButton' })).not.toBeDisabled();
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
  it('confirmed delete removes the row and refreshes its list', async () => {
    mockList.mockResolvedValue([
      makeAttachment({ name: 'gone.pdf' }),
      makeAttachment({ name: 'stays.pdf' }),
    ]);
    mockDelete.mockResolvedValue(true);
    mockList.mockResolvedValueOnce([makeAttachment({ name: 'gone.pdf' }), makeAttachment({ name: 'stays.pdf' })]).mockResolvedValue([makeAttachment({ name: 'stays.pdf' })]);

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
      expect(screen.getByText(/detail.attachments.deleteUnknown/)).toBeInTheDocument(),
    );
    expect(screen.getByText('oops.pdf')).toBeInTheDocument();
  });
});


describe('AttachmentsPanel — honest reads and recovery', () => {
  function upload(name = 'resume.pdf') {
    fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [fileFromMime(name, 'application/pdf')] } });
  }
  it('a rejected list is not empty and retry only reads', async () => {
    mockList.mockRejectedValueOnce(new Error('private SDK detail')).mockResolvedValueOnce([makeAttachment()]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    expect(await screen.findByTestId('tracker-attachments-error')).toBeInTheDocument();
    expect(screen.queryByTestId('tracker-attachments-empty')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'detail.attachments.addButton' })).toBeDisabled();
    expect(screen.queryByText('private SDK detail')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'detail.attachments.retryList' }));
    expect(await screen.findByText('resume.pdf')).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledTimes(2); expect(mockUpload).not.toHaveBeenCalled(); expect(mockDelete).not.toHaveBeenCalled();
  });
  it('signed out is distinct from failure and Check again recovers', async () => {
    mockList.mockRejectedValueOnce(new AttachmentRequestError('unauthenticated')).mockResolvedValueOnce([]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    expect(await screen.findByTestId('tracker-attachments-signed-out')).toBeInTheDocument();
    expect(screen.queryByTestId('tracker-attachments-error')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tracker-attachments-empty')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'detail.attachments.checkAgain' }));
    expect(await screen.findByTestId('tracker-attachments-empty')).toBeInTheDocument();
  });
  it.each(['upload', 'delete'] as const)('confirmed %s plus failed refresh preserves both facts, retry never repeats the write', async kind => {
    mockList.mockResolvedValueOnce([makeAttachment()]).mockRejectedValueOnce(new Error('list offline')).mockResolvedValueOnce(kind === 'upload' ? [makeAttachment()] : []);
    mockUpload.mockResolvedValue({ ok: true, name: 'resume.pdf' }); mockDelete.mockResolvedValue(true);
    render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
    if (kind === 'upload') upload(); else fireEvent.click(screen.getByRole('button', { name: /detail.attachments.deleteAria/ }));
    expect(await screen.findByTestId('tracker-attachments-error')).toBeInTheDocument();
    expect(screen.getByTestId('tracker-attachments-notice')).toHaveTextContent(kind === 'upload' ? 'detail.attachments.uploaded' : 'detail.attachments.deleted');
    expect(screen.getByRole('button', { name: 'detail.attachments.addButton' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'detail.attachments.retryList' }));
    await waitFor(() => expect(screen.queryByTestId('tracker-attachments-error')).not.toBeInTheDocument());
    expect(kind === 'upload' ? mockUpload : mockDelete).toHaveBeenCalledTimes(1);
    expect(kind === 'upload' ? mockDelete : mockUpload).not.toHaveBeenCalled();
  });
  it.each(['upload', 'delete'] as const)('uncertain %s outcome says check list, not success, and requires read recovery', async kind => {
    mockList.mockResolvedValue([makeAttachment()]);
    mockUpload.mockRejectedValue(new AttachmentRequestError('timeout')); mockDelete.mockRejectedValue(new Error('offline secret'));
    render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
    if (kind === 'upload') upload(); else fireEvent.click(screen.getByRole('button', { name: /detail.attachments.deleteAria/ }));
    expect(await screen.findByText(new RegExp(`detail.attachments.${kind}Unknown`))).toBeInTheDocument();
    expect(screen.queryByTestId('tracker-attachments-notice')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'detail.attachments.retryList' }));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
    expect(kind === 'upload' ? mockUpload : mockDelete).toHaveBeenCalledTimes(1);
  });
  it('a delayed list for the previous opportunity cannot replace the new list', async () => {
    let complete!: (value: Attachment[]) => void;
    mockList.mockReturnValueOnce(new Promise(resolve => { complete = resolve; })).mockResolvedValue([makeAttachment({ name: 'new-target.pdf' })]);
    const view = render(<AttachmentsPanel opportunityId={OPP_ID} />);
    view.rerender(<AttachmentsPanel opportunityId="different-target" />);
    await screen.findByText('new-target.pdf');
    await act(async () => { complete([makeAttachment({ name: 'old-target.pdf' })]); });
    expect(screen.queryByText('old-target.pdf')).not.toBeInTheDocument();
  });
  it('a signed URL for the previous opportunity is not opened after navigation', async () => {
    let complete!: (value: string) => void;
    mockList.mockResolvedValue([makeAttachment()]); mockSigned.mockReturnValue(new Promise(resolve => { complete = resolve; }));
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const view = render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
    fireEvent.click(screen.getByRole('button', { name: /detail.attachments.openAria/ }));
    view.rerender(<AttachmentsPanel opportunityId="other" />);
    await act(async () => { complete('https://signed.example/old'); }); expect(open).not.toHaveBeenCalled();
  });
  it('duplicate mutation clicks issue one request and lock file actions until completion', async () => {
    let complete!: (value: boolean) => void;
    mockList.mockResolvedValue([makeAttachment()]); mockDelete.mockReturnValue(new Promise(resolve => { complete = resolve; }));
    render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
    const button = screen.getByRole('button', { name: /detail.attachments.deleteAria/ });
    fireEvent.click(button); fireEvent.click(button); expect(mockDelete).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /detail.attachments.openAria/ })).toBeDisabled();
    await act(async () => { complete(true); });
  });
  it('unmount observes late open rejection without opening a window', async () => {
    let fail!: (error: Error) => void;
    mockList.mockResolvedValue([makeAttachment()]); mockSigned.mockReturnValue(new Promise((_, reject) => { fail = reject; }));
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const view = render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
    fireEvent.click(screen.getByRole('button', { name: /detail.attachments.openAria/ })); view.unmount();
    await act(async () => { fail(new Error('late')); }); expect(open).not.toHaveBeenCalled();
  });
  it('StrictMode first read cannot overwrite its replacement', async () => {
    let complete!: (value: Attachment[]) => void;
    mockList.mockReturnValueOnce(new Promise(resolve => { complete = resolve; })).mockResolvedValue([makeAttachment({ name: 'current.pdf' })]);
    render(<StrictMode><AttachmentsPanel opportunityId={OPP_ID} /></StrictMode>); await screen.findByText('current.pdf');
    await act(async () => { complete([makeAttachment({ name: 'obsolete.pdf' })]); });
    expect(screen.queryByText('obsolete.pdf')).not.toBeInTheDocument();
  });
});


describe('AttachmentsPanel — account and request replacement', () => {
  async function claim(uid: string | null) {
    advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  }
  it('account switch hides the old list immediately and drops its late read', async () => {
    await claim('11111111-1111-4111-8111-111111111111');
    let complete!: (files: Attachment[]) => void;
    mockList.mockReturnValueOnce(new Promise(resolve => { complete = resolve; })).mockResolvedValue([makeAttachment({ name: 'new-owner.pdf' })]);
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    await act(async () => { await claim('22222222-2222-4222-8222-222222222222'); });
    await screen.findByText('new-owner.pdf');
    await act(async () => { complete([makeAttachment({ name: 'old-owner.pdf' })]); });
    expect(screen.queryByText('old-owner.pdf')).not.toBeInTheDocument();
  });
  it('logout clears visible files before an unresolved new read', async () => {
    await claim('11111111-1111-4111-8111-111111111111');
    mockList.mockResolvedValueOnce([makeAttachment({ name: 'private.pdf' })]).mockReturnValue(new Promise(() => {}));
    render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('private.pdf');
    await act(async () => { await claim(null); });
    expect(screen.queryByText('private.pdf')).not.toBeInTheDocument();
    expect(screen.getByTestId('tracker-attachments-loading')).toBeInTheDocument();
  });
  it('retry replaces the button with loading and cannot issue duplicate reads', async () => {
    mockList.mockRejectedValueOnce(new Error('offline')).mockReturnValue(new Promise(() => {}));
    render(<AttachmentsPanel opportunityId={OPP_ID} />);
    const retry = await screen.findByRole('button', { name: 'detail.attachments.retryList' });
    fireEvent.click(retry); fireEvent.click(retry);
    expect(mockList).toHaveBeenCalledTimes(2); expect(screen.getByTestId('tracker-attachments-loading')).toBeInTheDocument();
    expect(mockUpload).not.toHaveBeenCalled(); expect(mockDelete).not.toHaveBeenCalled();
  });
  it('open failure is visible and allows an explicit new open', async () => {
    mockList.mockResolvedValue([makeAttachment()]); mockSigned.mockRejectedValueOnce(new Error('private failure')).mockResolvedValueOnce('https://signed.example/file');
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
    fireEvent.click(screen.getByRole('button', { name: /detail.attachments.openAria/ }));
    await screen.findByText(/detail.attachments.errOpen/); expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /detail.attachments.openAria/ }));
    await waitFor(() => expect(open).toHaveBeenCalledTimes(1));
  });
});


it('old rendered controls cannot borrow the new owner token before React redraws', async () => {
  advanceOwnerEpoch('11111111-1111-4111-8111-111111111111');
  await syncLocalIdentityOwner('11111111-1111-4111-8111-111111111111');
  mockList.mockResolvedValue([makeAttachment()]);
  render(<AttachmentsPanel opportunityId={OPP_ID} />); await screen.findByText('resume.pdf');
  const open = screen.getByRole('button', { name: /detail.attachments.openAria/ });
  const remove = screen.getByRole('button', { name: /detail.attachments.deleteAria/ });
  await act(async () => {
    advanceOwnerEpoch('22222222-2222-4222-8222-222222222222');
    open.click(); remove.click();
    await syncLocalIdentityOwner('22222222-2222-4222-8222-222222222222');
  });
  expect(mockSigned).not.toHaveBeenCalled(); expect(mockDelete).not.toHaveBeenCalled();
});
