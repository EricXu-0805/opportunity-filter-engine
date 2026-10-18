'use client';

import { useState } from 'react';
import { BellRing, Cloud, Mail, Trash2 } from 'lucide-react';
import Link from 'next/link';
import {
  digestWillSend,
  savedSearchToUrl,
  type SavedSearch,
  type SavedSearchDigest,
} from '@/lib/saved-searches';
import {
  formatSavedSearchEmailState,
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
  /** Re-run the failed read. */
  onRetry?: () => void;
  onApplyOptimisticClear: (id: string) => void;
  onRemove: (search: SavedSearch) => void;
  onDigestSave: (id: string, digest: SavedSearchDigest) => Promise<boolean>;
  /** The signed-in account's confirmed email: the digest cron sends only
   *  there. Null for a guest or an account without one — the digest cannot
   *  be turned on. */
  accountEmail?: string | null;
  t: TFunc;
}

interface DigestEditorProps {
  initial: SavedSearchDigest;
  accountEmail: string | null;
  onSave: (digest: SavedSearchDigest) => Promise<boolean>;
  onClose: () => void;
  t: TFunc;
}

function DigestEditor({ initial, accountEmail, onSave, onClose, t }: DigestEditorProps) {
  const [optIn, setOptIn] = useState(initial.optIn);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  // Without a confirmed address the digest can be turned off, never on.
  const blocked = optIn && !accountEmail;

  const handleSave = async () => {
    if (blocked) return;
    setSaving(true);
    const ok = await onSave({ email: accountEmail ?? initial.email, optIn });
    setSaving(false);
    if (!ok) {
      setFailed(true);
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
          disabled={!accountEmail && !optIn}
          onChange={(e) => { setOptIn(e.target.checked); setFailed(false); }}
          className="mt-0.5 w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-40"
        />
        <span className="text-[13px] text-gray-700">
          {t('favorites.savedSearches.digestOptIn')}
        </span>
      </label>
      {accountEmail ? (
        <input
          type="email"
          value={accountEmail}
          readOnly
          aria-label={t('favorites.savedSearches.digestEmailAria')}
          className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-gray-50 text-[13px] text-gray-600 outline-none"
        />
      ) : (
        <p className="text-[12px] text-gray-600">
          {t('favorites.savedSearches.digestNeedsAccount')}
        </p>
      )}
      {failed && (
        <p className="text-[12px] text-red-600">
          {t('favorites.savedSearches.digestSaveFailed')}
        </p>
      )}
      <p className="text-[12px] text-gray-500 leading-relaxed">
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
          disabled={saving || blocked}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 transition-colors"
        >
          {t('favorites.savedSearches.digestSave')}
        </button>
      </div>
    </div>
  );
}

interface DigestNotSentNoteProps {
  storedEmail: string;
  accountEmail: string | null;
  onSwitch: (digest: SavedSearchDigest) => Promise<boolean>;
  t: TFunc;
}

/** An opted-in row the cron will not send: its stored address is not the
 *  account's confirmed one, or there is no confirmed one. */
function DigestNotSentNote({ storedEmail, accountEmail, onSwitch, t }: DigestNotSentNoteProps) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const handleSwitch = async () => {
    if (!accountEmail) return;
    setSaving(true);
    setFailed(false);
    const ok = await onSwitch({ email: accountEmail, optIn: true });
    setSaving(false);
    if (!ok) setFailed(true);
  };

  return (
    <div className="px-4 pb-3 -mt-1 space-y-1.5">
      <p className="text-[12px] text-amber-700">
        {accountEmail
          ? t('favorites.savedSearches.digestNotSentOtherAddress', { email: storedEmail })
          : t('favorites.savedSearches.digestNotSentNeedsAccount')}
      </p>
      {accountEmail && (
        <button
          type="button"
          onClick={handleSwitch}
          disabled={saving}
          className="text-[12px] font-semibold text-indigo-700 hover:text-indigo-800 disabled:opacity-40"
        >
          {t('favorites.savedSearches.digestSwitchToAccount', { email: accountEmail })}
        </button>
      )}
      {failed && (
        <p className="text-[12px] text-red-600">
          {t('favorites.savedSearches.digestSaveFailed')}
        </p>
      )}
    </div>
  );
}

export function SavedSearchesSection({
  savedSearches,
  digests,
  loadError = false,
  onRetry,
  onApplyOptimisticClear,
  onRemove,
  onDigestSave,
  accountEmail = null,
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
            <p className="text-[12px] text-gray-600 mt-0.5">
              {t('favorites.savedSearches.sectionHint')}
            </p>
          )}
        </div>
        {savedSearches.length > 0 && (
          <span className="text-[11px] text-gray-600 tabular-nums">
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
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 text-[13px] font-semibold text-indigo-700"
            >
              {t('common.retry')}
            </button>
          )}
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
            // Only a row the cron will actually send is shown as on.
            const digestOn = digestWillSend(digest, accountEmail);
            const digestNotSent = !!digest?.optIn && !digestOn;
            const emailState = formatSavedSearchEmailState(digest, t);
            // The refresh does not score: new results are counted before the
            // saved minimum score, which /results applies when they open. Read
            // as /results reads the link's `min`: truncated and held to 0..100.
            const savedMin = Number(String(search.filters.minScore ?? 0));
            const minScore = Number.isFinite(savedMin)
              ? Math.min(100, Math.max(0, Math.trunc(savedMin)))
              : 0;
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
                    {hasNew && minScore > 0 && (
                      <p className="text-[11px] text-amber-700 mt-0.5">
                        {t('favorites.savedSearches.newBeforeMinScore', { min: minScore })}
                      </p>
                    )}
                    <p className="text-[11px] text-gray-500 truncate mt-0.5 tabular-nums">
                      {emailState ? `${timestampLabel} · ${emailState}` : timestampLabel}
                    </p>
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
                {digestNotSent && digest && (
                  <DigestNotSentNote
                    storedEmail={digest.email}
                    accountEmail={accountEmail}
                    onSwitch={(d) => onDigestSave(search.id, d)}
                    t={t}
                  />
                )}
                {editingDigestId === search.id && (
                  <DigestEditor
                    initial={digest ?? { email: '', optIn: false }}
                    accountEmail={accountEmail}
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
