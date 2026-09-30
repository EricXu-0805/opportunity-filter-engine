import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '@/i18n/dictionaries';
import { useCustomImportStorageState } from '@/lib/custom-imports';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import CustomImportStorageNotice from './CustomImportStorageNotice';
const feed = vi.hoisted(() => ({ locale: 'en' as 'en' | 'zh' }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: feed.locale, t: (key: string) => String(key.split('.').reduce<unknown>((v, part) => (v as Record<string, unknown>)[part], dictionaries[feed.locale])) }) }));
function Wrapper() { const state = useCustomImportStorageState(); return <><CustomImportStorageNotice state={state} /><output>{state.status}</output></>; }
const raw = JSON.stringify([{ id: 'valid', imported_at: '2026-09-28', opportunity: { source: 'paste', title: 'Readable entry', description_raw: 'Retain original' } }, { malformed: true }]);
beforeEach(async () => { localStorage.clear(); feed.locale = 'en'; advanceOwnerEpoch('b60-recovery'); await syncLocalIdentityOwner('b60-recovery'); });
afterEach(() => { vi.restoreAllMocks(); });
function damage(value = raw) { localStorage.setItem('ofe_custom_imports', value); }
function t(key: keyof typeof dictionaries.en.import) { return dictionaries[feed.locale].import[key]; }

describe('damaged import recovery requires a separate explicit decision', () => {
  it.each(['en', 'zh'] as const)('%s explains loss, permits cancellation, and resets only imports after confirmation', async (locale) => {
    feed.locale = locale; damage(); localStorage.setItem('ofe_profile', 'profile sentinel'); localStorage.setItem('ofe_cold_email_draft:test', 'draft sentinel');
    render(<Wrapper />);
    expect(screen.getByText(t('storagePreserved'))).toBeInTheDocument();
    expect(screen.queryByText(t('confirmReset'))).toBeNull();
    fireEvent.click(screen.getByText(t('reviewReset')));
    expect(screen.getByText(t('resetWarning'))).toBeInTheDocument();
    expect(localStorage.getItem('ofe_custom_imports')).toBe(raw);
    fireEvent.click(screen.getByText(t('cancelReset')));
    expect(localStorage.getItem('ofe_custom_imports')).toBe(raw);
    fireEvent.click(screen.getByText(t('reviewReset')));
    fireEvent.click(screen.getByText(t('confirmReset')));
    await screen.findByText('ready');
    expect(localStorage.getItem('ofe_custom_imports')).toBe('[]');
    expect(localStorage.getItem('ofe_profile')).toBe('profile sentinel');
    expect(localStorage.getItem('ofe_cold_email_draft:test')).toBe('draft sentinel');
  });
  it('exports the exact damaged value as data and never resets it or claims the backup was saved', async () => {
    const damaged = '{broken with lone surrogate ' + String.fromCharCode(0xd800); damage(damaged);
    let file!: Blob;
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn((blob: Blob) => { file = blob; return 'blob:backup'; }) });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<Wrapper />); fireEvent.click(screen.getByText(t('exportBackup')));
    expect(click).toHaveBeenCalledTimes(1);
    const text = await new Promise<string>((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(file); });
    expect(JSON.parse(text)).toEqual({ format: 'ofe-imports-recovery-v1', raw: damaged });
    expect(screen.getByText(t('backupRequested'))).toBeInTheDocument();
    expect(screen.queryByText(t('confirmReset'))).toBeNull();
    expect(localStorage.getItem('ofe_custom_imports')).toBe(damaged);
  });
  it('refuses a changed raw snapshot, keeps the replacement, and requires a new review', async () => {
    damage(); render(<Wrapper />); fireEvent.click(screen.getByText(t('reviewReset')));
    act(() => { damage('changed malformed data'); window.dispatchEvent(new Event('storage')); });
    fireEvent.click(screen.getByText(t('confirmReset')));
    await screen.findByText(t('storageChanged'));
    expect(localStorage.getItem('ofe_custom_imports')).toBe('changed malformed data');
    expect(screen.getByText(t('confirmReset'))).toBeDisabled();
    fireEvent.click(screen.getByText(t('rereadReset')));
    fireEvent.click(screen.getByText(t('confirmReset')));
    await screen.findByText('ready');
  });
  it('retains the review after quota failure and retries without deleting other data', async () => {
    damage(); render(<Wrapper />); fireEvent.click(screen.getByText(t('reviewReset')));
    const original = window.localStorage.setItem;
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(function (key, value) {
      if (key === 'ofe_custom_imports') throw new DOMException('Full', 'QuotaExceededError');
      original.call(window.localStorage, key, value);
    });
    fireEvent.click(screen.getByText(t('confirmReset'))); await screen.findByText(t('storageFailed'));
    expect(localStorage.getItem('ofe_custom_imports')).toBe(raw);
    spy.mockRestore(); fireEvent.click(screen.getByText(t('confirmReset'))); await screen.findByText('ready');
  });
  it('closes the old recovery review on account change', async () => {
    damage(); render(<Wrapper />); fireEvent.click(screen.getByText(t('reviewReset')));
    const oldConfirm = screen.getByText(t('confirmReset'));
    await act(async () => { advanceOwnerEpoch('b60-other'); await syncLocalIdentityOwner('b60-other'); damage('new owner damaged'); window.dispatchEvent(new Event('storage')); });
    fireEvent.click(oldConfirm);
    expect(screen.queryByText(t('confirmReset'))).toBeNull();
    expect(localStorage.getItem('ofe_custom_imports')).toBe('new owner damaged');
  });
  it('does not offer destructive recovery when storage coordination is unavailable', async () => {
    damage(); const previous = navigator.locks;
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    try {
      render(<Wrapper />);
      expect(screen.getByText(t('storageCoordinationUnavailable'))).toBeInTheDocument();
      expect(screen.queryByText(t('reviewReset'))).toBeNull();
      expect(screen.queryByText(t('exportBackup'))).toBeNull();
      Object.defineProperty(navigator, 'locks', { configurable: true, value: previous });
      fireEvent.click(screen.getByText(dictionaries.en.common.retry));
      await screen.findByText('damaged');
      expect(localStorage.getItem('ofe_custom_imports')).toBe(raw);
    } finally { Object.defineProperty(navigator, 'locks', { configurable: true, value: previous }); }
  });
});
