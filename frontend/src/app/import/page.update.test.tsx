import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImportedOpportunity } from '@/lib/api';

const mocks = vi.hoisted(() => ({ importUrl: vi.fn(), importText: vi.fn() }));
vi.mock('@/lib/api', () => ({ importByUrl: mocks.importUrl, importByText: mocks.importText }));
vi.mock('@/i18n/client', () => {
  const t = (key: string) => key;
  return { useT: () => ({ t, locale: 'en', setLocale: vi.fn() }) };
});
import ImportPage from './page';
import { addCustomImport, readCustomImports } from '@/lib/custom-imports';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { writeLocalStorageJSON } from '@/lib/use-local-storage-json';

const oldSource = 'OLD MATERIAL. '.repeat(500) + 'OLD FINAL LINE';
const newSource = 'NEW MATERIAL. '.repeat(600) + 'NEW FINAL LINE';
function candidate(): ImportedOpportunity {
  return { source: 'url_parser', source_url: 'https://example.edu/program', url: 'https://example.edu/program', title: 'New source title',
    description_raw: newSource, extra_fields: { description_source: 'page_text', ai_input_scope: 'source_excerpt', suggested_skills: ['Python'], suggested_description: 'New suggestion' } };
}
async function prepare() {
  const next = candidate();
  const saved = await addCustomImport({ ...next, title: 'Old saved title', description_raw: oldSource,
    extra_fields: { description_source: 'page_excerpt', suggested_skills: ['R'], suggested_description: 'Old suggestion' } }, captureOwnerToken());
  if (!saved.ok) throw new Error(saved.reason);
  const old = saved.entry;
  mocks.importUrl.mockResolvedValueOnce({ ok: true, opportunity: next, llm_enriched: true });
  render(<ImportPage />);
  fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: next.url } });
  fireEvent.click(screen.getByText('import.fetchButton'));
  await screen.findByText(next.title);
  return { old, next };
}
beforeEach(async () => {
  localStorage.clear(); mocks.importUrl.mockReset(); mocks.importText.mockReset();
  advanceOwnerEpoch('b59-import-owner'); await syncLocalIdentityOwner('b59-import-owner');
});

describe('review a saved import before replacing it', () => {
  it('shows complete old/new material and keeps the old entry when requested', async () => {
    const { old } = await prepare();
    fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
    const previous = screen.getByRole('region', { name: 'import.previousVersion' });
    const replacement = screen.getByRole('region', { name: 'import.newVersion' });
    expect(within(previous).getByText('Old saved title')).toBeInTheDocument();
    expect(within(replacement).getByText('New source title')).toBeInTheDocument();
    fireEvent.click(within(previous).getByRole('button', { name: 'import.expandSource' }));
    fireEvent.click(within(replacement).getByRole('button', { name: 'import.expandSource' }));
    expect(within(previous).getByText(/OLD FINAL LINE/).textContent).toBe(oldSource);
    expect(within(replacement).getByText(/NEW FINAL LINE/).textContent).toBe(newSource);
    expect(within(replacement).getByText('import.excerptAiInput')).toBeInTheDocument();
    expect(screen.getByText('import.updateDraftsNotice')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'import.keepSaved' }));
    expect(readCustomImports()).toEqual([old]);
    expect(screen.queryByRole('region', { name: 'import.previousVersion' })).toBeNull();
    expect(screen.getByText('New source title')).toBeInTheDocument();
  });

  it('updates the reviewed entry without duplicating it or retaining old input-scope claims', async () => {
    const { old, next } = await prepare();
    fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
    fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
    await screen.findByText('import.updated');
    const saved = readCustomImports();
    expect(saved).toHaveLength(1);
    expect(saved[0].id).toBe(old.id); expect(saved[0].imported_at).toBe(old.imported_at);
    expect(saved[0].opportunity).toEqual(next);
    expect(saved[0].opportunity.extra_fields.ai_input_scope).toBe('source_excerpt');
    expect(screen.queryByText('import.fullAiInput')).toBeNull();
  });

  it('refuses a changed entry until the user reads and confirms the new saved version', async () => {
    const { old, next } = await prepare();
    fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
    const changed = { ...old, opportunity: { ...old.opportunity, title: 'Changed in another tab' } };
    act(() => { writeLocalStorageJSON('ofe_custom_imports', [changed], captureOwnerToken()); });
    fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
    await screen.findByText('import.updateChanged');
    expect(readCustomImports()).toEqual([changed]);
    expect(screen.getByRole('button', { name: 'import.confirmUpdate' })).toBeDisabled();
    expect(within(screen.getByRole('region', { name: 'import.previousVersion' })).getByText('Old saved title')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'import.rereadSaved' }));
    expect(within(screen.getByRole('region', { name: 'import.previousVersion' })).getByText('Changed in another tab')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
    await waitFor(() => expect(readCustomImports()[0].opportunity).toEqual(next));
    expect(readCustomImports()[0].id).toBe(old.id);
  });

  it('does not recreate a deleted entry when a reviewed update is confirmed', async () => {
    await prepare();
    fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
    act(() => { writeLocalStorageJSON('ofe_custom_imports', [], captureOwnerToken()); });
    fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
    await screen.findByText('import.updateMissing');
    expect(readCustomImports()).toEqual([]);
    expect(screen.getByRole('button', { name: 'import.confirmUpdate' })).toBeDisabled();
    expect(within(screen.getByRole('region', { name: 'import.newVersion' })).getByText(/NEW FINAL LINE/)).toBeInTheDocument();
  });

  it('invalidates the review after an account change without copying it to the new account', async () => {
    await prepare();
    fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
    const confirm = screen.getByRole('button', { name: 'import.confirmUpdate' });
    await act(async () => { advanceOwnerEpoch('b59-other-owner'); await syncLocalIdentityOwner('b59-other-owner'); });
    fireEvent.click(confirm);
    expect(readCustomImports()).toEqual([]);
    expect(screen.queryByRole('region', { name: 'import.newVersion' })).toBeNull();
  });

  it('keeps both versions when storage fails, and can retry the same reviewed update', async () => {
    const { old, next } = await prepare();
    fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', { configurable: true, value: {
      get length() { return original.length; }, key: (i: number) => original.key(i), getItem: (key: string) => original.getItem(key),
      setItem: () => { throw new DOMException('Full', 'QuotaExceededError'); }, removeItem: (key: string) => original.removeItem(key), clear: () => original.clear(),
    } });
    try {
      fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
      await screen.findByText('import.updateStorageFailed');
      expect(readCustomImports()).toEqual([old]);
      expect(screen.getByRole('region', { name: 'import.newVersion' })).toBeInTheDocument();
      expect(screen.getByRole('region', { name: 'import.previousVersion' })).toBeInTheDocument();
    } finally { Object.defineProperty(window, 'localStorage', { value: original, configurable: true }); }
    fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
    await waitFor(() => expect(readCustomImports()[0].opportunity).toEqual(next));
  });
});


it('confirms the frozen candidate even if the original response object later changes', async () => {
  const { next } = await prepare();
  const reviewed = structuredClone(next);
  fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
  next.description_raw = 'Unreviewed replacement';
  next.extra_fields.suggested_skills = ['Unreviewed skill'];
  fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
  await waitFor(() => expect(readCustomImports()[0].opportunity).toEqual(reviewed));
  expect(screen.queryByText('Unreviewed replacement')).toBeNull();
});

it('starting another import closes the old review and does not reuse its confirmation', async () => {
  const { old, next } = await prepare();
  fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
  const oldConfirm = screen.getByRole('button', { name: 'import.confirmUpdate' });
  mocks.importUrl.mockResolvedValueOnce({ ok: true, opportunity: { ...next, title: 'Later candidate' }, llm_enriched: true });
  fireEvent.click(screen.getByText('import.fetchButton'));
  await screen.findByText('Later candidate');
  fireEvent.click(oldConfirm);
  expect(readCustomImports()).toEqual([old]);
  expect(screen.queryByRole('button', { name: 'import.confirmUpdate' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
  expect(within(screen.getByRole('region', { name: 'import.newVersion' })).getByText('Later candidate')).toBeInTheDocument();
});


it('preserves an unrelated entry added while the review is open', async () => {
  const { old, next } = await prepare();
  fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
  await act(async () => { await addCustomImport({ ...next, source_url: 'https://example.edu/other', url: 'https://example.edu/other', title: 'Other opportunity' }, captureOwnerToken()); });
  fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
  await screen.findByText('import.updated');
  const saved = readCustomImports();
  expect(saved).toHaveLength(2);
  expect(saved.find((entry) => entry.id === old.id)?.opportunity).toEqual(next);
  expect(saved[0].opportunity.title).toBe('Other opportunity');
});


it('does not claim the candidate remains saved after another tab changes it', async () => {
  const { next } = await prepare();
  expect(screen.getByText('import.savedVersionDiffers')).toBeInTheDocument();
  expect(screen.queryByText('import.saved')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
  fireEvent.click(screen.getByRole('button', { name: 'import.confirmUpdate' }));
  await screen.findByText('import.updated');
  const saved = readCustomImports()[0];
  act(() => { writeLocalStorageJSON('ofe_custom_imports', [{ ...saved, opportunity: { ...next, title: 'A later saved change' } }], captureOwnerToken()); });
  expect(screen.queryByText('import.updated')).toBeNull();
  expect(screen.getByText('import.savedVersionDiffers')).toBeInTheDocument();
});

it('does not describe unreadable storage as a deleted entry when opening review', async () => {
  await prepare();
  // An uncoordinated write can happen before this tab receives a storage event.
  localStorage.setItem('ofe_custom_imports', '{not valid JSON');
  fireEvent.click(screen.getByRole('button', { name: 'import.reviewUpdate' }));
  expect(screen.getAllByText('import.storageDamaged').length).toBeGreaterThan(0);
  expect(screen.queryByText('import.updateMissing')).toBeNull();
  expect(screen.getByText('New source title')).toBeInTheDocument();
  expect(localStorage.getItem('ofe_custom_imports')).toBe('{not valid JSON');
});
