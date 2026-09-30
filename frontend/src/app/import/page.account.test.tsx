import { webcrypto } from 'node:crypto';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '@/i18n/dictionaries';
import type { ImportedOpportunity } from '@/lib/api';
import type { PrivateImportReceipt } from '@/lib/private-import-target-api';
const mocks = vi.hoisted(() => ({ importUrl: vi.fn(), importText: vi.fn(), get: vi.fn(), save: vi.fn(), signIn: vi.fn(), locale: 'en' as 'en' | 'zh' }));
vi.mock('@/lib/api', () => ({ importByUrl: mocks.importUrl, importByText: mocks.importText }));
vi.mock('@/lib/private-import-target-api', () => ({ getPrivateImportTarget: mocks.get, savePrivateImportTarget: mocks.save, PRIVATE_TARGET_TIMEOUT_MS: 30000,
  PrivateTargetError: class extends Error { constructor(readonly code: string) { super(code); } } }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: mocks.signIn }) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: mocks.locale, t: translate }) }));
import ImportPage from './page';
import { PrivateTargetError } from '@/lib/private-import-target-api';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readCustomImports, updateCustomImport } from '@/lib/custom-imports';
const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
function translate(key: string): string { return String(key.split('.').reduce<unknown>((value, part) => (value as Record<string, unknown>)[part], dictionaries[mocks.locale])); }
const source = 'Complete original material. '.repeat(400) + 'FINAL SOURCE RESTRICTION 中文';
function opportunity(): ImportedOpportunity { return { source: 'url_parser', source_url: 'https://example.edu/project', url: 'https://example.edu/project', title: 'Imported project', description_raw: source,
  extra_fields: { description_source: 'page_text', ai_input_scope: 'source_excerpt', llm_enriched: true, suggested_skills: ['Python'] } }; }
function receipt(id: string, revision: number, value = opportunity()): PrivateImportReceipt {
  return { version: 1, replayed: false, target: { id, owner_id: OWNER, revision, created_at: '2026-09-28T12:00:00Z', updated_at: '2026-09-28T12:00:00Z', deleted_at: null,
    target_scope: 'private_import', verification: 'unverified', target_version: `pit1:${revision}`, opportunity: value,
    import_source: { version: 1, description_source: 'page_text', ai_input_scope: 'source_excerpt', llm_enriched: true } } };
}
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); mocks.locale = 'en';
  advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  mocks.importUrl.mockReset().mockResolvedValue({ ok: true, opportunity: opportunity(), llm_enriched: true }); mocks.importText.mockReset();
  mocks.get.mockReset().mockResolvedValue(null); mocks.save.mockReset().mockImplementation(async (id, candidate, expected) => receipt(id, expected + 1, candidate)); mocks.signIn.mockReset();
});
afterEach(() => { vi.unstubAllGlobals(); });
async function savedImport() {
  render(<ImportPage />); fireEvent.change(screen.getByPlaceholderText(translate('import.urlPlaceholder')), { target: { value: opportunity().url } });
  fireEvent.click(screen.getByText(translate('import.fetchButton'))); await screen.findByText('Imported project');
  expect(mocks.get).not.toHaveBeenCalled(); expect(mocks.save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(translate('import.saveToList'))); await screen.findByText(translate('import.saved'));
  expect(mocks.save).not.toHaveBeenCalled();
}
async function prepare() { fireEvent.click(screen.getByText(translate('privateImport.prepareSave'))); await screen.findByRole('region', { name: translate('privateImport.newVersion') }); }

describe('explicit browser import to account UI', () => {
  it.each(['en', 'zh'] as const)('%s uploads only after review confirmation, retains the local copy and links the private history', async (locale) => {
    mocks.locale = locale; await savedImport(); const before = localStorage.getItem('ofe_custom_imports');
    await prepare(); expect(mocks.get).toHaveBeenCalledOnce(); expect(mocks.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(translate('privateImport.keepCopies'))); expect(mocks.save).not.toHaveBeenCalled();
    await prepare();
    const replacement = screen.getByRole('region', { name: translate('privateImport.newVersion') });
    fireEvent.click(within(replacement).getByText(translate('import.expandSource')));
    expect(within(replacement).getByText(/FINAL SOURCE RESTRICTION/).textContent).toBe(source);
    expect(screen.getByText(translate('privateImport.unverified'))).toBeInTheDocument();
    fireEvent.click(screen.getByText(translate('privateImport.confirmSave'))); await screen.findByText(translate('privateImport.saved'));
    expect(mocks.save).toHaveBeenCalledTimes(1); expect(mocks.save.mock.calls[0][1]).toEqual(opportunity()); expect(mocks.save.mock.calls[0][2]).toBe(0);
    expect(localStorage.getItem('ofe_custom_imports')).toBe(before);
    expect(screen.getByRole('link', { name: translate('applicationRecord.viewRecords') })).toHaveAttribute('href', `/private-imports/${encodeURIComponent(mocks.save.mock.calls[0][0])}`);
  });
  it('shows complete cloud/local versions and uses cloud receipt labels instead of forged raw full-source labels', async () => {
    mocks.get.mockImplementation(async id => { const value = receipt(id, 4, { ...opportunity(), title: 'Cloud old', description_raw: 'Old source. '.repeat(500) + 'OLD TAIL', extra_fields: { description_source: 'page_text', ai_input_scope: 'full_source' } });
      value.target.import_source = { version: 1, description_source: 'page_text', ai_input_scope: 'unknown', llm_enriched: false }; return value; });
    await savedImport(); await prepare();
    const old = screen.getByRole('region', { name: translate('privateImport.previousVersion') });
    fireEvent.click(within(old).getByText(translate('import.expandSource')));
    expect(within(old).getByText(/OLD TAIL/)).not.toHaveClass('line-clamp-4');
    expect(within(old).getByText(translate('import.aiInputUnknown'))).toBeInTheDocument();
    expect(within(old).queryByText(translate('import.fullAiInput'))).toBeNull();
    fireEvent.click(screen.getByText(translate('privateImport.confirmUpdate'))); await screen.findByText(translate('privateImport.saved'));
    expect(mocks.save.mock.calls[0][2]).toBe(4);
  });
  it('requires a fresh read and another confirmation after a conflict, without an automatic second write', async () => {
    mocks.get.mockImplementation(async id => receipt(id, mocks.get.mock.calls.length === 1 ? 2 : 3, { ...opportunity(), title: 'Cloud prior version' }));
    mocks.save.mockRejectedValueOnce(new PrivateTargetError('conflict'));
    await savedImport(); const before = localStorage.getItem('ofe_custom_imports'); await prepare();
    fireEvent.click(screen.getByText(translate('privateImport.confirmUpdate'))); await screen.findByText(translate('privateImport.conflict'));
    expect(screen.queryByText(translate('privateImport.confirmUpdate'))).toBeNull(); expect(mocks.save).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByText(translate('privateImport.reread'))); await screen.findByText(translate('privateImport.confirmUpdate'));
    expect(mocks.save).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByText(translate('privateImport.confirmUpdate'))); await screen.findByText(translate('privateImport.saved'));
    expect(mocks.save.mock.calls[1][2]).toBe(3); expect(localStorage.getItem('ofe_custom_imports')).toBe(before);
  });
  it('offers sign in while retaining the browser copy and never invokes a save', async () => {
    mocks.get.mockRejectedValue(new PrivateTargetError('sign_in_required')); await savedImport();
    const before = localStorage.getItem('ofe_custom_imports'); fireEvent.click(screen.getByText(translate('privateImport.prepareSave')));
    await screen.findByText(translate('privateImport.signInRequired'));
    fireEvent.click(screen.getByText(translate('privateImport.signIn'))); expect(mocks.signIn).toHaveBeenCalledWith({ phase: 'signin' });
    expect(mocks.save).not.toHaveBeenCalled(); expect(localStorage.getItem('ofe_custom_imports')).toBe(before);
  });
  it('does not recreate a deleted cloud identity from the browser copy', async () => {
    mocks.get.mockImplementation(async id => ({ ...receipt(id, 5), target: { ...receipt(id, 5).target, opportunity: null, import_source: null, deleted_at: '2026-09-28T12:00:00Z' } }));
    await savedImport(); fireEvent.click(screen.getByText(translate('privateImport.prepareSave')));
    await screen.findAllByText(translate('privateImport.deleted'));
    expect(screen.queryByText(translate('privateImport.confirmSave'))).toBeNull(); expect(screen.queryByText(translate('privateImport.confirmUpdate'))).toBeNull(); expect(mocks.save).not.toHaveBeenCalled();
    expect(readCustomImports()).toHaveLength(1);
  });
  it('offers an explicit new account copy after deletion and saves it only after another review', async () => {
    const tombstoned = new Set<string>();
    mocks.get.mockImplementation(async id => tombstoned.has(id) || !tombstoned.size ? (tombstoned.add(id), { ...receipt(id, 5), target: { ...receipt(id, 5).target, opportunity: null, import_source: null, deleted_at: '2026-09-28T12:00:00Z' } }) : null);
    await savedImport(); fireEvent.click(screen.getByText(translate('privateImport.prepareSave')));
    await screen.findByText(translate('privateImport.newCopyHint'));
    fireEvent.click(screen.getByText(translate('privateImport.saveAsNewCopy')));
    await screen.findByText(translate('privateImport.confirmSave')); expect(mocks.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(translate('privateImport.confirmSave'))); await screen.findByText(translate('privateImport.saved'));
    expect(mocks.save).toHaveBeenCalledOnce(); expect(tombstoned.has(mocks.save.mock.calls[0][0])).toBe(false);
    expect(mocks.save.mock.calls[0][1]).toEqual(opportunity()); expect(mocks.save.mock.calls[0][2]).toBe(0); expect(readCustomImports()).toHaveLength(1);
  });
  it('lets the user reread a changed local record instead of trapping them with an old frozen candidate', async () => {
    await savedImport(); await prepare(); const entry = readCustomImports()[0];
    const changed = { ...entry.opportunity, title: 'Locally revised', description_raw: source + ' EXTRA LOCAL CHANGE' };
    await act(async () => { expect((await updateCustomImport(changed, entry, captureOwnerToken())).ok).toBe(true); });
    await screen.findByText(translate('privateImport.localChanged'));
    fireEvent.click(screen.getByText(translate('privateImport.reread'))); await screen.findByText('Locally revised');
    fireEvent.click(screen.getByText(translate('privateImport.confirmSave'))); await screen.findByText(translate('privateImport.saved'));
    expect(mocks.save.mock.calls[0][1]).toEqual(changed);
  });
  it('clears a pending account review after an owner switch and ignores its late full source', async () => {
    let resolve!: (value: PrivateImportReceipt) => void; mocks.get.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    await savedImport(); fireEvent.click(screen.getByText(translate('privateImport.prepareSave'))); await waitFor(() => expect(mocks.get).toHaveBeenCalledOnce());
    await act(async () => { advanceOwnerEpoch('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'); await syncLocalIdentityOwner('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'); resolve(receipt(mocks.get.mock.calls[0][0], 2, { ...opportunity(), title: 'Old account secret' })); });
    expect(screen.queryByText('Old account secret')).toBeNull(); expect(screen.queryByText(translate('privateImport.confirmUpdate'))).toBeNull(); expect(mocks.save).not.toHaveBeenCalled();
  });
});
