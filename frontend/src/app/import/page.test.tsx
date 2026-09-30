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

const { mockImportByUrl, mockImportByText } = vi.hoisted(() => ({ mockImportByUrl: vi.fn(), mockImportByText: vi.fn() }));
vi.mock('@/lib/api', () => ({
  importByUrl: mockImportByUrl,
  importByText: mockImportByText,
}));

import ImportPage from './page';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readCustomImports } from '@/lib/custom-imports';

beforeEach(async () => {
  mockImportByUrl.mockReset();
  mockImportByText.mockReset();
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


describe('ImportPage — unverified model suggestions', () => {
  it('separates new suggestions, keeps source text and saves the original response', async () => {
    const opportunity = {
      source: 'url_parser', source_url: 'https://example.com/terms', url: 'https://example.com/terms',
      title: 'Source project', description_raw: 'Original source wording.',
      extra_fields: { description_source: 'page_excerpt', suggested_skills: ['Python', 'R'], suggested_description: 'AI summary wording.', needs_manual_review: true },
    };
    mockImportByUrl.mockResolvedValueOnce({ ok: true, opportunity, llm_enriched: true });
    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: opportunity.url } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('Source project');
    expect(screen.getByText('import.pageExcerpt')).toBeInTheDocument();
    expect(screen.getByText('import.suggestionsNote')).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('AI summary wording.')).toBeInTheDocument();
    expect(screen.queryByText('import.fieldSkillsReq')).toBeNull();
    fireEvent.click(screen.getByText('import.saveToList'));
    await waitFor(() => expect(readCustomImports()[0]?.opportunity).toEqual(opportunity));
  });

  it('does not call historical saved model arrays confirmed requirements', async () => {
    mockImportByUrl.mockResolvedValueOnce({ ok: true, llm_enriched: true,
      opportunity: { title: 'Older response', extra_fields: { skills_required: ['Java'], skills_preferred: ['R'], needs_manual_review: false } },
    });
    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: 'https://example.com/old' } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('Older response');
    expect(screen.getByText('Java')).toBeInTheDocument();
    expect(screen.getByText('R')).toBeInTheDocument();
    expect(screen.queryByText('import.fieldSkillsReq')).toBeNull();
    expect(screen.queryByText('import.fieldSkillsPref')).toBeNull();
  });
});


describe('ImportPage — failure keeps review material', () => {
  it('keeps full pasted input after a failed model extraction', async () => {
    mockImportByText.mockResolvedValueOnce({ ok: false, error: 'controlled failure' });
    render(<ImportPage />);
    fireEvent.click(screen.getByText('import.modeText'));
    const source = 'Original material. ' + 'Keep every sentence. '.repeat(250) + ' FINAL SENTENCE.';
    fireEvent.change(screen.getByPlaceholderText('import.textPlaceholder'), { target: { value: source } });
    fireEvent.click(screen.getByText('import.extractButton'));
    await screen.findByText('import.errorExtract');
    expect(screen.getByPlaceholderText('import.textPlaceholder')).toHaveValue(source);
    expect(mockImportByText).toHaveBeenCalledWith(source);
  });

  it('keeps source and suggestions on a failed Save', async () => {
    mockImportByUrl.mockResolvedValueOnce({ ok: true, llm_enriched: true,
      opportunity: { title: 'Unsaved result', description_raw: 'Keep this source.', source_url: 'https://example.com/fail-save',
        extra_fields: { suggested_skills: ['Java'], suggested_description: 'Keep this suggestion.' } },
    });
    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: 'https://example.com/fail-save' } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('Unsaved result');
    const originalStorage = window.localStorage;
    Object.defineProperty(window, 'localStorage', { configurable: true, value: {
      get length() { return originalStorage.length; },
      key: (index: number) => originalStorage.key(index),
      getItem: (key: string) => originalStorage.getItem(key),
      setItem: () => { throw new DOMException('Full', 'QuotaExceededError'); },
      removeItem: (key: string) => originalStorage.removeItem(key),
      clear: () => originalStorage.clear(),
    } });
    try {
      fireEvent.click(screen.getByText('import.saveToList'));
      expect(await screen.findByText('import.saveFailed')).toBeInTheDocument();
      expect(screen.getByText('Unsaved result')).toBeInTheDocument();
      expect(screen.getByText('Java')).toBeInTheDocument();
      expect(screen.getByText('Keep this suggestion.')).toBeInTheDocument();
      expect(readCustomImports()).toEqual([]);
    } finally { Object.defineProperty(window, 'localStorage', { value: originalStorage, configurable: true }); }
  });
});


describe('ImportPage — actionable input errors', () => {
  it('says the site blocked the fetch, keeps the link, and permits retry', async () => {
    mockImportByUrl.mockResolvedValueOnce({
      ok: false, error_code: 'import_source_unreadable', error_reason: 'access_page', llm_enriched: false,
    });
    mockImportByUrl.mockResolvedValueOnce({ ok: true, opportunity: { title: 'Retried source', extra_fields: {} }, llm_enriched: false });
    render(<ImportPage />);
    const input = screen.getByPlaceholderText('import.urlPlaceholder');
    fireEvent.change(input, { target: { value: 'https://researchops.example.edu/opportunity' } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('import.errorSourceBlocked');
    expect(screen.queryByText('import.errorSourceUnreadable')).toBeNull();
    expect(screen.queryByText('import.saveToList')).toBeNull();
    expect(input).toHaveValue('https://researchops.example.edu/opportunity');
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('Retried source');
  });


  it.each([
    ['url', 'import_input_too_large', 'import.errorPageTooLong'],
    ['url', 'import_source_unreadable', 'import.errorSourceUnreadable'],
    ['text', 'import_input_too_large', 'import.errorTextTooLong'],
  ] as const)('keeps %s input after %s, then permits retry', async (mode, code, expectedKey) => {
    const importer = mode === 'url' ? mockImportByUrl : mockImportByText;
    importer.mockResolvedValueOnce({ ok: false, error_code: code, llm_enriched: false });
    importer.mockResolvedValueOnce({ ok: true, opportunity: { title: 'Retried source', extra_fields: {} }, llm_enriched: false });
    render(<ImportPage />);
    if (mode === 'text') fireEvent.click(screen.getByText('import.modeText'));
    const input = screen.getByPlaceholderText(mode === 'url' ? 'import.urlPlaceholder' : 'import.textPlaceholder');
    const original = mode === 'url' ? 'https://example.com/long' : 'Keep the full original input. '.repeat(250) + 'LAST LINE';
    fireEvent.change(input, { target: { value: original } });
    const submit = screen.getByText(mode === 'url' ? 'import.fetchButton' : 'import.extractButton');
    fireEvent.click(submit);
    await screen.findByText(expectedKey);
    expect(input).toHaveValue(original);
    expect(screen.queryByText('import.errorFetch')).toBeNull();
    expect(screen.queryByText('import.errorExtract')).toBeNull();
    fireEvent.click(screen.getByText(mode === 'url' ? 'import.fetchButton' : 'import.extractButton'));
    await screen.findByText('Retried source');
    expect(importer).toHaveBeenLastCalledWith(original);
  });
});


it.each(['full_source', 'source_excerpt'] as const)('shows the full source and saves the exact %s input-scope marker', async (scope) => {
  const text = 'Readable body.\n'.repeat(600) + 'LATE SOURCE RESTRICTION';
  const opportunity = { source: 'url_parser', source_url: 'https://example.com/full', url: 'https://example.com/full',
    title: 'Full body preview', description_raw: text,
    extra_fields: { description_source: 'page_text', ai_input_scope: scope, suggested_skills: ['Python'] } };
  mockImportByUrl.mockResolvedValueOnce({ ok: true, opportunity, llm_enriched: true });
  render(<ImportPage />);
  fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: opportunity.url } });
  fireEvent.click(screen.getByText('import.fetchButton'));
  await screen.findByText('Full body preview');
  expect(screen.getByText(scope === 'full_source' ? 'import.fullAiInput' : 'import.excerptAiInput')).toBeInTheDocument();
  expect(screen.getByText('import.pageText')).toBeInTheDocument();
  const source = screen.getByText(/LATE SOURCE RESTRICTION/);
  fireEvent.click(screen.getByRole('button', { name: 'import.expandSource' }));
  expect(source).not.toHaveClass('line-clamp-4');
  expect(source.textContent).toBe(text);
  fireEvent.click(screen.getByText('import.saveToList'));
  await waitFor(() => expect(readCustomImports()[0]?.opportunity).toEqual(opportunity));
});


describe('ImportPage — current request wins within one account', () => {
  it('discards an older URL response after changing mode and completing a text request', async () => {
    let finishOld!: (value: unknown) => void;
    mockImportByUrl.mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve; }));
    mockImportByText.mockResolvedValueOnce({ ok: true, llm_enriched: false, opportunity: { title: 'Current text result', extra_fields: {} } });
    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: 'https://example.com/old-request' } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    fireEvent.click(screen.getByText('import.modeText'));
    fireEvent.change(screen.getByPlaceholderText('import.textPlaceholder'), { target: { value: 'Current pasted source. '.repeat(6) } });
    fireEvent.click(screen.getByText('import.extractButton'));
    await screen.findByText('Current text result');
    finishOld({ ok: true, llm_enriched: false, opportunity: { title: 'Late old URL result', extra_fields: {} } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText('Current text result')).toBeInTheDocument();
    expect(screen.queryByText('Late old URL result')).toBeNull();
  });

  it('discards an older error after two URL requests resolve out of order', async () => {
    let failOld!: (error: Error) => void;
    mockImportByUrl.mockReturnValueOnce(new Promise((_resolve, reject) => { failOld = reject; }));
    mockImportByUrl.mockResolvedValueOnce({ ok: true, llm_enriched: false, opportunity: { title: 'Current URL result', extra_fields: {} } });
    render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: 'https://example.com/old-request' } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    fireEvent.click(screen.getByText('import.modeText'));
    fireEvent.click(screen.getByText('import.modeUrl'));
    fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: 'https://example.com/new-request' } });
    fireEvent.click(screen.getByText('import.fetchButton'));
    await screen.findByText('Current URL result');
    failOld(new Error('Late failure'));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText('Current URL result')).toBeInTheDocument();
    expect(screen.queryByText('import.errorFetch')).toBeNull();
  });
});
