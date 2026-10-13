'use client';

import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { SavedSearchDigest } from '@/lib/saved-searches';
import type { TFunc } from './types';

// Mounted conditionally by the parent (same pattern as KeyboardHelpDialog)
// so each open starts from fresh useState initializers — no reset effect.
export interface SaveSearchDialogProps {
  /** False while migration 013 is unapplied — the digest fields are hidden
   *  entirely and onSave always receives digest: null. */
  digestAvailable: boolean;
  /** The signed-in account's confirmed email: the digest cron sends only
   *  there. Null for an account without one — the digest cannot be turned on. */
  accountEmail?: string | null;
  onCancel: () => void;
  onSave: (input: { name: string; digest: SavedSearchDigest | null }) => void;
  t: TFunc;
}

export function SaveSearchDialog({
  digestAvailable,
  accountEmail = null,
  onCancel,
  onSave,
  t,
}: SaveSearchDialogProps) {
  const [name, setName] = useState('');
  const [optIn, setOptIn] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;
    onSave({
      name: trimmedName,
      digest: digestAvailable && optIn && accountEmail
        ? { email: accountEmail, optIn: true }
        : null,
    });
  };

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="save-search-dialog-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={onCancel} aria-hidden="true" />
      <form
        onSubmit={handleSubmit}
        // Validation is custom (i18n'd inline error) — suppress the
        // browser's native email bubble so the two never fight.
        noValidate
        className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden animate-in"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 id="save-search-dialog-title" className="text-[15px] font-semibold text-gray-900">
            {t('results.saveSearchDialog.title')}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            className="p-2 -mr-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            aria-label={t('results.saveSearchDialog.closeAria')}
          >
            <X className="w-4 h-4 text-gray-400" aria-hidden="true" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <div>
            <label htmlFor="save-search-name" className="block text-[13px] font-medium text-gray-700 mb-1">
              {t('results.saveSearchDialog.nameLabel')}
            </label>
            <input
              ref={nameRef}
              id="save-search-name"
              type="text"
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('results.saveSearchDialog.namePlaceholder')}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 text-[14px] text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-300 outline-none"
            />
          </div>
          {digestAvailable && (
            <div className="rounded-xl bg-gray-50/80 border border-gray-100 px-4 py-3 space-y-2.5">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={optIn}
                  disabled={!accountEmail}
                  onChange={(e) => setOptIn(e.target.checked)}
                  className="mt-0.5 w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-40"
                />
                <span className="text-[13px] text-gray-700">
                  {t('results.saveSearchDialog.digestOptIn')}
                </span>
              </label>
              {accountEmail ? (
                <input
                  type="email"
                  value={accountEmail}
                  readOnly
                  aria-label={t('results.saveSearchDialog.digestEmailLabel')}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-white/60 text-[13px] text-gray-600 outline-none"
                />
              ) : (
                <p className="text-[12px] text-gray-600">
                  {t('results.saveSearchDialog.digestNeedsAccount')}
                </p>
              )}
              <p className="text-[12px] text-gray-500 leading-relaxed">
                {t('results.saveSearchDialog.digestHint')}
              </p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-gray-100 bg-gray-50/50">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-lg text-[13px] font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            {t('results.saveSearchDialog.cancel')}
          </button>
          <button
            type="submit"
            disabled={!name.trim()}
            className="px-4 py-2 rounded-lg text-[13px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {t('results.saveSearchDialog.save')}
          </button>
        </div>
      </form>
    </div>
  );
}
