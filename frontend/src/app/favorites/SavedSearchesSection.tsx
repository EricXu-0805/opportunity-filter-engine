'use client';

import { useState } from 'react';
import { BellRing, Cloud, Mail, Trash2 } from 'lucide-react';
import Link from 'next/link';
import {
  isValidDigestEmail,
  savedSearchToUrl,
  type SavedSearch,
  type SavedSearchDigest,
} from '@/lib/saved-searches';
import {
  formatSavedSearchTimestamp,
  summarizeSavedSearchFilters,
  type TFunc,
} from './types';

export interface SavedSearchesSectionProps {
  savedSearches: SavedSearch[];
  /** null while loading or when migration 013 is unapplied — digest UI hidden. */
  digests: Map<string, SavedSearchDigest> | null;
  /** W14: the list failed to load — render an inline error note instead of
   *  the empty hint (the user's saved searches still exist server-side). */
  loadError?: boolean;
  onApplyOptimisticClear: (id: string) => void;
  onRemove: (search: SavedSearch) => void;
  onDigestSave: (id: string, digest: SavedSearchDigest) => Promise<boolean>;
  t: TFunc;
}

interface DigestEditorProps {
  initial: SavedSearchDigest;
  onSave: (digest: SavedSearchDigest) => Promise<boolean>;
  onClose: () => void;
  t: TFunc;
}

function DigestEditor({ initial, onSave, onClose, t }: DigestEditorProps) {
  const [email, setEmail] = useState(initial.email);
  const [optIn, setOptIn] = useState(initial.optIn);
  const [error, setError] = useState<'invalid' | 'failed' | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (optIn && !isValidDigestEmail(email)) {
      setError('invalid');
      return;
    }
    setSaving(true);
    const ok = await onSave({ email: email.trim(), optIn });
    setSaving(false);
    if (!ok) {
      setError('failed');
      return;
    }
    onClose();
  };

  return (
    <div className="px-4 pb-3 pt-1 border-t border-gray-100 space-y-2">
      <label className="flex items-start gap-2.5 cursor-pointer">
        <input
          type="checkbox"
          checked={optIn}
          onChange={(e) => { setOptIn(e.target.checked); setError(null); }}
          className="mt-0.5 w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
        <span className="text-[13px] text-gray-700">
          {t('favorites.savedSearches.digestOptIn')}
        </span>
      </label>
      <input
        type="email"
        value={email}
        maxLength={254}
        onChange={(e) => { setEmail(e.target.value); setError(null); }}
        placeholder={t('favorites.savedSearches.digestEmailPlaceholder')}
        aria-label={t('favorites.savedSearches.digestEmailAria')}
        aria-invalid={error === 'invalid'}
        className={`w-full px-3 py-2 rounded-lg border text-[13px] text-gray-800 placeholder:text-gray-400 outline-none focus:ring-2 focus:ring-indigo-500/30 ${error === 'invalid' ? 'border-red-300' : 'border-gray-200 focus:border-indigo-300'}`}
      />
      {error && (
        <p className="text-[12px] text-red-600">
          {t(error === 'invalid'
            ? 'favorites.savedSearches.digestEmailInvalid'
            : 'favorites.savedSearches.digestSaveFailed')}
        </p>
      )}
      <p className="text-[12px] text-gray-400 leading-relaxed">
        {t('favorites.savedSearches.digestHint')}
      </p>
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-gray-600 hover:bg-gray-100 transition-colors"
        >
          {t('favorites.savedSearches.digestCancel')}
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 transition-colors"
        >
          {t('favorites.savedSearches.digestSave')}
        </button>
      </div>
    </div>
  );
}

export function SavedSearchesSection({
  savedSearches,
  digests,
  loadError = false,
  onApplyOptimisticClear,
  onRemove,
  onDigestSave,
  t,
}: SavedSearchesSectionProps) {
  const [editingDigestId, setEditingDigestId] = useState<string | null>(null);
  return (
    <section className="mb-8" aria-labelledby="saved-searches-heading">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h2 id="saved-searches-heading" className="text-[15px] font-semibold text-gray-900 inline-flex items-center gap-2">
            <Cloud className="w-4 h-4 text-indigo-500" aria-hidden="true" />
            {t('favorites.savedSearches.sectionTitle')}
          </h2>
          {savedSearches.length > 0 && (
            <p className="text-[12px] text-gray-400 mt-0.5">
              {t('favorites.savedSearches.sectionHint')}
            </p>
          )}
        </div>
        {savedSearches.length > 0 && (
          <span className="text-[11px] text-gray-400 tabular-nums">
            {t('favorites.savedSearches.itemCount', { count: savedSearches.length })}
          </span>
        )}
      </div>
      {loadError && savedSearches.length === 0 ? (
        // W14 truthful zero states: a failed load is an error note, never
        // the "save one from results" empty hint (the searches still exist).
        <div
          data-testid="saved-searches-load-error"
          className="text-center py-4 px-4 rounded-xl bg-red-50/60 border border-red-100"
        >
          <p className="text-[13px] text-red-700">
            {t('favorites.savedSearches.loadError')}
          </p>
        </div>
      ) : savedSearches.length === 0 ? (
        <div className="text-center py-6 px-4 rounded-xl bg-gray-50/80 border border-dashed border-gray-200">
          <p className="text-[13px] text-gray-500">
            {t('favorites.savedSearches.emptyHint')}
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {savedSearches.map((search) => {
            const summary = summarizeSavedSearchFilters(search, t);
            const timestampLabel = formatSavedSearchTimestamp(search.last_run_at, t);
            const newCount = search.new_match_ids?.length ?? 0;
            const hasNew = newCount > 0;
            const digest = digests?.get(search.id);
            const digestOn = !!digest?.optIn;
            return (
              <li
                key={search.id}
                className="group bg-white rounded-xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] hover:shadow-[0_2px_12px_rgba(0,0,0,0.06)] transition-shadow"
              >
                <div className="flex items-center">
                  <Link
                    href={savedSearchToUrl(
                      search,
                      hasNew
                        ? { highlight: search.new_match_ids, savedSearchId: search.id }
                        : undefined,
                    )}
                    onClick={hasNew ? () => onApplyOptimisticClear(search.id) : undefined}
                    aria-label={t('favorites.savedSearches.applyAria', { name: search.name })}
                    className="flex-1 min-w-0 px-4 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded-l-xl"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[14px] font-medium text-gray-900 truncate">
                        {search.name}
                      </span>
                      {hasNew && (
                        <span
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-100/80 text-amber-700 text-[11px] font-semibold shrink-0"
                          aria-label={t('favorites.savedSearches.newMatchesAria', { count: newCount })}
                        >
                          <BellRing className="w-3 h-3" aria-hidden="true" />
                          {t('favorites.savedSearches.newBadge', { count: newCount })}
                        </span>
                      )}
                      {digestOn && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 text-[11px] font-semibold shrink-0">
                          <Mail className="w-3 h-3" aria-hidden="true" />
                          {t('favorites.savedSearches.digestOnBadge')}
                        </span>
                      )}
                    </div>
                    <p className="text-[12px] text-gray-500 truncate mt-0.5">{summary}</p>
                    <p className="text-[11px] text-gray-400 truncate mt-0.5 tabular-nums">{timestampLabel}</p>
                  </Link>
                  {digests !== null && (
                    <button
                      type="button"
                      onClick={() =>
                        setEditingDigestId((prev) => (prev === search.id ? null : search.id))
                      }
                      aria-label={t('favorites.savedSearches.digestButtonAria', { name: search.name })}
                      aria-expanded={editingDigestId === search.id}
                      className={`p-3 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${digestOn ? 'text-indigo-500 hover:bg-indigo-50' : 'text-gray-300 hover:text-indigo-500 hover:bg-indigo-50'}`}
                    >
                      <Mail className="w-4 h-4" aria-hidden="true" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onRemove(search)}
                    aria-label={t('favorites.savedSearches.deleteAria', { name: search.name })}
                    className="p-3 mr-1 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                  >
                    <Trash2 className="w-4 h-4" aria-hidden="true" />
                  </button>
                </div>
                {editingDigestId === search.id && (
                  <DigestEditor
                    initial={digest ?? { email: '', optIn: false }}
                    onSave={(d) => onDigestSave(search.id, d)}
                    onClose={() => setEditingDigestId(null)}
                    t={t}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
