'use client';

import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { isValidDigestEmail, type SavedSearchDigest } from '@/lib/saved-searches';
import type { TFunc } from './types';

// Mounted conditionally by the parent (same pattern as KeyboardHelpDialog)
// so each open starts from fresh useState initializers — no reset effect.
export interface SaveSearchDialogProps {
  /** False while migration 013 is unapplied — the digest fields are hidden
   *  entirely and onSave always receives digest: null. */
  digestAvailable: boolean;
  onCancel: () => void;
  onSave: (input: { name: string; digest: SavedSearchDigest | null }) => void;
  t: TFunc;
}

export function SaveSearchDialog({
  digestAvailable,
  onCancel,
  onSave,
  t,
}: SaveSearchDialogProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [optIn, setOptIn] = useState(false);
  const [emailError, setEmailError] = useState(false);
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
    if (digestAvailable && optIn && !isValidDigestEmail(email)) {
      setEmailError(true);
      return;
    }
    onSave({
      name: trimmedName,
      digest: digestAvailable && optIn
        ? { email: email.trim(), optIn: true }
        : null,
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
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
            className="p-2 -mr-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
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
                  onChange={(e) => { setOptIn(e.target.checked); setEmailError(false); }}
                  className="mt-0.5 w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-[13px] text-gray-700">
                  {t('results.saveSearchDialog.digestOptIn')}
                </span>
              </label>
              <input
                type="email"
                value={email}
                maxLength={254}
                onChange={(e) => { setEmail(e.target.value); setEmailError(false); }}
                placeholder={t('results.saveSearchDialog.digestEmailPlaceholder')}
                aria-label={t('results.saveSearchDialog.digestEmailLabel')}
                aria-invalid={emailError}
                className={`w-full px-3 py-2 rounded-lg border text-[13px] text-gray-800 placeholder:text-gray-400 outline-none focus:ring-2 focus:ring-indigo-500/30 ${emailError ? 'border-red-300' : 'border-gray-200 focus:border-indigo-300'}`}
              />
              {emailError && (
                <p className="text-[12px] text-red-600">
                  {t('results.saveSearchDialog.digestEmailInvalid')}
                </p>
              )}
              <p className="text-[12px] text-gray-400 leading-relaxed">
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
