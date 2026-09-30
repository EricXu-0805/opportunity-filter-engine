import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import fixture from './__fixtures__/import-full-source.json';
import { dictionaries } from '@/i18n/dictionaries';

const localeState = vi.hoisted(() => ({ current: 'en' as 'en' | 'zh' }));
vi.mock('@/i18n/client', async () => {
  const { dictionaries: words } = await import('@/i18n/dictionaries');
  const t = (key: string) => key.split('.').reduce<unknown>((v, k) => (v as Record<string, unknown>)?.[k], words[localeState.current]) as string;
  return { useT: () => ({ t, locale: localeState.current, setLocale: vi.fn() }) };
});
vi.mock('./supabase', () => ({ getRevealAccessToken: async () => null, refreshRevealAccessToken: async () => null }));

const fetchMock = vi.fn();
const t = (key: string) => key.split('.').reduce<unknown>((v, k) => (v as Record<string, unknown>)?.[k], dictionaries[localeState.current]) as string;
const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

beforeEach(() => { localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); vi.resetModules(); });
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

async function mountImport() {
  const owner = await import('./identity-owner');
  owner.advanceOwnerEpoch('b58-fixture-owner');
  await owner.syncLocalIdentityOwner('b58-fixture-owner');
  const { default: ImportPage } = await import('@/app/import/page');
  return render(<ImportPage />);
}

// Actual response bodies enter the real frontend adapter. Only HTTP transport is
// stubbed; the page Save action, owner gate, storage and reopened projection run.
describe.each(['en', 'zh'] as const)('actual local import response → Save → reopen (%s)', (locale) => {
  it.each(['url', 'text'] as const)('retains complete %s original, source scope and suggestions', async (mode) => {
    localeState.current = locale;
    const body = fixture.success[mode];
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
    const mounted = await mountImport();
    if (mode === 'text') fireEvent.click(screen.getByText(t('import.modeText')));
    const original = mode === 'url' ? body.opportunity.source_url : body.opportunity.description_raw;
    fireEvent.change(screen.getByPlaceholderText(t(mode === 'url' ? 'import.urlPlaceholder' : 'import.textPlaceholder')), { target: { value: original } });
    fireEvent.click(screen.getByText(t(mode === 'url' ? 'import.fetchButton' : 'import.extractButton')));
    await screen.findByText(body.opportunity.title);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [endpoint, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toMatch(mode === 'url' ? /\/import-url$/ : /\/import-text$/);
    expect(JSON.parse(request.body as string)).toEqual(mode === 'url' ? { url: original } : { text: original });
    expect(body.opportunity.description_raw.length).toBeGreaterThan(9000);
    const sourceControl = screen.getByRole('button', { name: t('import.expandSource') });
    const source = document.getElementById(sourceControl.getAttribute('aria-controls')!)!;
    expect(source.textContent).toBe(body.opportunity.description_raw);
    expect(screen.getByText(t('import.excerptAiInput'))).toBeInTheDocument();
    expect(screen.queryByText(t('import.fullAiInput'))).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: t('import.expandSource') }));
    expect(source).not.toHaveClass('line-clamp-4');
    fireEvent.click(screen.getByText(t('import.saveToList')));
    expect(await screen.findByText(t('import.saved'))).toBeInTheDocument();
    const stored = localStorage.getItem('ofe_custom_imports');
    mounted.unmount();
    vi.resetModules();
    const freshOwner = await import('./identity-owner');
    freshOwner.advanceOwnerEpoch('b58-fixture-owner');
    await freshOwner.syncLocalIdentityOwner('b58-fixture-owner');
    const { readCustomImports } = await import('./custom-imports');
    const restored = readCustomImports()[0];
    expect(restored.opportunity).toEqual(body.opportunity);
    expect(localStorage.getItem('ofe_custom_imports')).toBe(stored);
    const { customImportToOpp } = await import('@/app/favorites/types');
    const view = customImportToOpp(restored);
    expect(view.import_source?.aiInputScope).toBe('source_excerpt');
    expect(view.import_suggestions?.skills).toEqual(body.opportunity.extra_fields.suggested_skills);
    expect(view.eligibility?.skills_required).toBeUndefined();
    const { OpportunityCard } = await import('@/app/favorites/OpportunityCard');
    render(<OpportunityCard opp={view} selectionMode={false} isSelected={false} selectedSize={0} isExpanded hasProfile={false}
      onToggleExpand={vi.fn()} onToggleSelect={vi.fn()} onRemove={vi.fn()} onOpenEmailModal={vi.fn()} tailorDisabled={false} t={t} />);
    fireEvent.click(screen.getByRole('button', { name: t('import.expandSource') }));
    expect(screen.getByText(/END OF COMPLETE SOURCE:/).textContent).toBe(body.opportunity.description_raw);
    expect(screen.getByText(/END OF COMPLETE SOURCE:/)).not.toHaveClass('line-clamp-4');
    expect(screen.getByText(t('import.excerptAiInput'))).toBeInTheDocument();
    expect(screen.queryByText(t('import.fullAiInput'))).toBeNull();
  });

  it.each(fixture.errors)('keeps input for $name and can retry through the actual adapter', async ({ status, response }) => {
    localeState.current = locale;
    fetchMock.mockResolvedValueOnce(jsonResponse(response, status));
    fetchMock.mockResolvedValueOnce(jsonResponse(fixture.success.url));
    await mountImport();
    const input = screen.getByPlaceholderText(t('import.urlPlaceholder'));
    const original = 'https://example.edu/source-for-retry';
    fireEvent.change(input, { target: { value: original } });
    fireEvent.click(screen.getByText(t('import.fetchButton')));
    await screen.findByText(t(status === 413 ? 'import.errorPageTooLong' : 'import.errorSourceUnreadable'));
    expect(input).toHaveValue(original);
    expect(screen.queryByText(response.detail.message)).toBeNull();
    expect(screen.queryByText(response.detail.reason)).toBeNull();
    expect(screen.queryByText(t('import.errorFetch'))).toBeNull();
    fireEvent.click(screen.getByText(t('import.fetchButton')));
    await screen.findByText(fixture.success.url.opportunity.title);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ url: original });
  });
});
