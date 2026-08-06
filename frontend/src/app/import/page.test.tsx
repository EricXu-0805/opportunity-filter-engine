import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  const stableT = (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    const parts = Object.entries(vars).map(([, v]) => String(v));
    return parts.length > 0 ? `${key}:${parts.join('|')}` : key;
  };
  return { useT: () => ({ t: stableT, locale: 'en' as const, setLocale: () => {} }) };
});

const { mockImportByUrl } = vi.hoisted(() => ({ mockImportByUrl: vi.fn() }));
vi.mock('@/lib/api', () => ({
  importByUrl: mockImportByUrl,
  importByText: vi.fn(),
}));

import ImportPage from './page';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readCustomImports } from '@/lib/custom-imports';

beforeEach(async () => {
  mockImportByUrl.mockReset();
  localStorage.clear();
  advanceOwnerEpoch('import-page-test-uid');
  await syncLocalIdentityOwner('import-page-test-uid');
});

// A slow extract must not populate the form under an identity the browser
// has since moved away from (sign-out, account switch on a shared device)
// — the stale response is discarded rather than rendered as if it
// belonged to whoever is now current.
describe('ImportPage — identity moves on mid-extract', () => {
  it('discards a URL-extract response that resolves after a live identity switch', async () => {
    let resolveImport!: (v: { ok: boolean; opportunity: { title: string } | null; llm_enriched: boolean }) => void;
    mockImportByUrl.mockReturnValueOnce(new Promise((resolve) => { resolveImport = resolve; }));

    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), {
      target: { value: 'https://example.com/job' },
    });
    fireEvent.click(screen.getByText('import.fetchButton'));

    // Identity switches while the request is still in flight.
    advanceOwnerEpoch('import-page-other-uid');
    await syncLocalIdentityOwner('import-page-other-uid');

    resolveImport({ ok: true, opportunity: { title: 'Stale Result' }, llm_enriched: false });

    // Give the resolved promise's .then chain a tick to run.
    await waitFor(() => expect(mockImportByUrl).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByText('Stale Result')).not.toBeInTheDocument();
  });

  it('still renders the result when the identity has NOT changed', async () => {
    mockImportByUrl.mockResolvedValueOnce({
      ok: true,
      opportunity: { title: 'Fresh Result', organization: 'Acme' },
      llm_enriched: false,
    });

    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), {
      target: { value: 'https://example.com/job' },
    });
    fireEvent.click(screen.getByText('import.fetchButton'));

    expect(await screen.findByText('Fresh Result')).toBeInTheDocument();
  });

  it('a stale extract FAILURE (identity moved on before it rejected) shows no error', async () => {
    let rejectImport!: (e: Error) => void;
    mockImportByUrl.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectImport = reject; }));

    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), {
      target: { value: 'https://example.com/x' },
    });
    fireEvent.click(screen.getByText('import.fetchButton'));

    advanceOwnerEpoch('import-page-fail-u2');
    await syncLocalIdentityOwner('import-page-fail-u2');

    rejectImport(new Error('network down'));
    await waitFor(() => expect(mockImportByUrl).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));

    // Not a real failure of the CURRENT (U2) session — it belongs to an
    // abandoned U1 request and must not surface as an error banner.
    expect(screen.queryByText('import.errorFetch')).not.toBeInTheDocument();
  });

  it('a U1 success followed by a live switch to U2 (before the stale card unmounts) must not let a Save click write into U2\'s list', async () => {
    mockImportByUrl.mockResolvedValueOnce({
      ok: true,
      opportunity: { title: 'U1 Result', source_url: 'https://example.com/u1-only' },
      llm_enriched: false,
    });
    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), {
      target: { value: 'https://example.com/u1-only' },
    });
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('U1 Result');
    const saveButton = screen.getByText('import.saveToList');

    // U2 takes over AFTER the result rendered (and captured U1's origin
    // token) but before the Save click.
    advanceOwnerEpoch('import-page-save-u2');
    await syncLocalIdentityOwner('import-page-save-u2');

    fireEvent.click(saveButton);

    // Whether the click reached the (now-stale) handleSave or the card had
    // already unmounted via the owner-change reset, U2's list must stay
    // completely empty — U1's result must never land in it.
    expect(readCustomImports()).toHaveLength(0);
  });
});
