import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImportedOpportunity } from '@/lib/api';
const api = vi.hoisted(() => ({ url: vi.fn(), text: vi.fn() }));
vi.mock('@/lib/api', () => ({ importByUrl: api.url, importByText: api.text }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
import ImportPage from './page';
import { addCustomImport, readCustomImports } from '@/lib/custom-imports';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, PRIVATE_STORAGE_LOCK } from '@/lib/identity-owner';
const opportunity = (title = 'Current import'): ImportedOpportunity => ({ source: 'url_parser', source_url: 'https://example.edu/program',
  url: 'https://example.edu/program', title, description_raw: 'Complete original with final restriction.', extra_fields: { description_source: 'page_text', ai_input_scope: 'source_excerpt' } });
beforeEach(async () => {
  localStorage.clear(); api.url.mockReset(); api.text.mockReset();
  advanceOwnerEpoch('b60-ui'); await syncLocalIdentityOwner('b60-ui');
});
async function show(value = opportunity()) {
  api.url.mockResolvedValueOnce({ ok: true, opportunity: value, llm_enriched: true });
  render(<ImportPage />);
  fireEvent.change(screen.getByPlaceholderText('import.urlPlaceholder'), { target: { value: value.url } });
  fireEvent.click(screen.getByText('import.fetchButton'));
  await screen.findByText(value.title);
}
async function blockWrites() {
  let release!: () => void;
  const held = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => new Promise<void>((resolve) => { release = resolve; }));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  return async () => { release(); await held; };
}
describe('import writes wait for the shared transaction', () => {
  it('blocks double Save and waits for the actual write before reporting success', async () => {
    await show(); const release = await blockWrites();
    try {
      const save = screen.getByText('import.saveToList');
      fireEvent.click(save); fireEvent.click(save);
      expect(screen.getByRole('button', { name: 'import.saving' })).toBeDisabled();
      expect(readCustomImports()).toEqual([]);
      expect(screen.queryByText('import.saved')).toBeNull();
    } finally { await act(release); }
    await screen.findByText('import.saved');
    expect(readCustomImports()).toHaveLength(1);
  });
  it('does not replace a newer import with an old queued update completion', async () => {
    expect((await addCustomImport(opportunity('Saved original'), captureOwnerToken())).ok).toBe(true);
    await show(); fireEvent.click(screen.getByText('import.reviewUpdate'));
    const release = await blockWrites();
    try {
      fireEvent.click(screen.getByText('import.confirmUpdate'));
      expect(screen.getByText('import.keepSaved')).toBeDisabled();
      api.url.mockResolvedValueOnce({ ok: true, opportunity: opportunity('Newer import'), llm_enriched: true });
      fireEvent.click(screen.getByText('import.fetchButton'));
      await screen.findByText('Newer import');
    } finally { await act(release); }
    await waitFor(() => expect(readCustomImports()[0].opportunity.title).toBe('Current import'));
    expect(screen.getByText('Newer import')).toBeInTheDocument();
    expect(screen.queryByText('import.updated')).toBeNull();
    expect(screen.getByText('import.savedVersionDiffers')).toBeInTheDocument();
  });
  it('does not put a late Save result back after changing import mode', async () => {
    await show(); const release = await blockWrites();
    try {
      fireEvent.click(screen.getByText('import.saveToList'));
      fireEvent.click(screen.getByRole('tab', { name: 'import.modeText' }));
      expect(screen.getByPlaceholderText('import.textPlaceholder')).toBeInTheDocument();
    } finally { await act(release); }
    await waitFor(() => expect(readCustomImports()).toHaveLength(1));
    expect(screen.queryByText('Current import')).toBeNull();
    expect(screen.queryByText('import.saved')).toBeNull();
  });
  it('rejects a queued write when the account changes, without exposing its old error', async () => {
    await show(); const release = await blockWrites();
    let ownerSwitch!: Promise<unknown>;
    try {
      fireEvent.click(screen.getByText('import.saveToList'));
      act(() => { advanceOwnerEpoch('b60-next'); ownerSwitch = syncLocalIdentityOwner('b60-next'); });
    } finally { await act(async () => { await release(); await ownerSwitch; }); }
    expect(readCustomImports()).toEqual([]);
    expect(screen.queryByText('Current import')).toBeNull();
    expect(screen.queryByText('import.saveFailed')).toBeNull();
    expect(screen.queryByText('import.saving')).toBeNull();
  });
  it('keeps the result and offers a visible retry when queued storage fails', async () => {
    await show(); const release = await blockWrites();
    const original = window.localStorage.setItem;
    let restore!: () => void;
    try {
      fireEvent.click(screen.getByText('import.saveToList'));
      const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(function (key, value) {
        if (key === 'ofe_custom_imports') throw new DOMException('Full', 'QuotaExceededError');
        original.call(window.localStorage, key, value);
      }); restore = () => spy.mockRestore();
    } finally { await act(release); }
    await screen.findByText('import.saveFailed');
    restore();
    expect(screen.getByText('Current import')).toBeInTheDocument();
    expect(readCustomImports()).toEqual([]);
    fireEvent.click(screen.getByText('import.saveToList'));
    await screen.findByText('import.saved');
  });
  it('shows damaged storage explicitly and keeps the new candidate', async () => {
    localStorage.setItem('ofe_custom_imports', '{broken');
    await show();
    expect(screen.getByText('import.storageDamaged')).toBeInTheDocument();
    expect(screen.getByText('import.saveToList')).toBeDisabled();
    expect(screen.getByText('Current import')).toBeInTheDocument();
    expect(localStorage.getItem('ofe_custom_imports')).toBe('{broken');
  });
});
