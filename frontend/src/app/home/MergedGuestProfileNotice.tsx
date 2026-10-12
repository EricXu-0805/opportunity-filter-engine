'use client';

import { useEffect, useRef, useState } from 'react';
import { ArchiveRestore } from 'lucide-react';
import { isOwnerTokenValid, type OwnerToken } from '@/lib/identity-owner';
import { clearMergedGuestProfile, readMergedGuestProfile } from '@/lib/merged-guest-profile';
import { loadArchivedGuestProfile } from '@/lib/supabase';
import type { TFunc } from './types';
import type { GuestRestoreBlocker, GuestRestoreCheck, GuestRestoreOutcome } from './use-profile-form';

type Archived = Record<string, unknown>;
type NoticeState =
  | { kind: 'idle' | 'hidden' | 'failed' | 'restored' | 'gone' }
  // `note`: how the last Restore ended, when it restored nothing (or, for
  // `changed`, when it cannot be told whether it did).
  | { kind: 'offer'; archived: Archived; note: 'conflict' | 'notRestored' | 'changed' | null }
  // The row is read again by its id and saved; the form's saves wait.
  | { kind: 'restoring' }
  // The save came back with no answer, so the stored profile is read to find
  // out whether it was restored; `failed` while that read has not succeeded.
  | { kind: 'checking'; archived: Archived; failed: boolean };

/**
 * After signing in to an account that already had a profile, the merge kept
 * the account's and saved the guest's in the account's history. This says so
 * on Home and offers it back: "Restore my guest profile" reads the archived
 * row the merge wrote — that row, by the id /auth/callback recorded, and no
 * other — and saves it as the whole profile in one revision-checked save
 * outside the form's edits. The form changes only once the server has saved
 * it; when the save fails nothing on the form changes. Until the outcome is
 * known the form's own saves wait (see useProfileForm's restoreHoldRef).
 * Nothing of a restore is ever pending, so "Keep my account profile" only
 * removes the offer.
 * Mount it keyed by identity generation — it belongs to the owner it was
 * rendered for.
 */
export function MergedGuestProfileNotice({
  ready,
  owner,
  blocker,
  onRestore,
  onCheck,
  onStored,
  t,
}: {
  /** The form is hydrated and showing `owner`'s row. */
  ready: boolean;
  owner: OwnerToken | null;
  /** Why a restore cannot be sent now (see guestRestoreBlocker). */
  blocker: (owner: OwnerToken) => GuestRestoreBlocker | null;
  /** Restores the row `read` reads (null: nothing to restore). */
  onRestore: (owner: OwnerToken, read: () => Promise<Archived | null>) => Promise<GuestRestoreOutcome>;
  /** After an `unknown` restore: what the stored profile turned out to be. */
  onCheck: (archived: Archived, owner: OwnerToken) => Promise<GuestRestoreCheck>;
  /** Whether the stored profile already is the archived one restored. */
  onStored: (archived: Archived, owner: OwnerToken) => boolean;
  t: TFunc;
}) {
  const [state, setState] = useState<NoticeState>({ kind: 'idle' });
  // Bumped by "Try again"; each value is read once per owner.
  const [attempt, setAttempt] = useState(0);
  const requestedRef = useRef<string | null>(null);
  // The archived row this notice is about, as the marker named it.
  const archiveIdRef = useRef<string | null>(null);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const ownerKey = owner ? `${owner.uid}:${owner.epoch}:${owner.generation}` : null;
  useEffect(() => {
    if (!ready || !owner || !ownerKey) return;
    const request = `${ownerKey}#${attempt}`;
    if (requestedRef.current === request) return;
    if (!isOwnerTokenValid(owner, owner.uid)) return;
    const archiveId = readMergedGuestProfile();
    if (!archiveId) return;
    requestedRef.current = request;
    archiveIdRef.current = archiveId;
    loadArchivedGuestProfile(owner, archiveId).then(
      (archived) => {
        if (!mountedRef.current) return;
        // Gone, or a later merge archived another guest profile after it:
        // nothing else is offered in its place, and it is not asked for
        // again. Already the stored profile (a restore whose answer was lost,
        // then a reload): it is restored.
        const stored = !!archived && onStored(archived, owner);
        if (!archived || stored) clearMergedGuestProfile(owner);
        setState((current) => (current.kind !== 'idle' ? current
          : stored ? { kind: 'restored' }
            : archived ? { kind: 'offer', archived, note: null } : { kind: 'gone' }));
      },
      () => {
        if (mountedRef.current) setState((current) => (current.kind === 'idle' ? { kind: 'failed' } : current));
      },
    );
  }, [ready, owner, ownerKey, attempt, onStored]);

  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; });
  // What holds Restore back (the connection, a save, the outbox every tab of
  // the account shares) is read at render, so a change to it re-renders.
  const [, setRendered] = useState(0);
  const rerender = () => setRendered((value) => value + 1);

  // Another tab restored it or kept the account's profile: stop offering. A
  // restore or a check already under way here finishes first. Any other
  // change may be another tab's save entering or leaving the outbox.
  useEffect(() => {
    const changed = () => {
      if (readMergedGuestProfile() === archiveIdRef.current) {
        setRendered((value) => value + 1);
        return;
      }
      setState((current) => (current.kind === 'offer' || current.kind === 'failed' ? { kind: 'hidden' } : current));
    };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []);

  /** Reads the stored profile to learn whether a restore with no answer was
   *  saved. Restore and Keep wait for it. */
  const check = (archived: Archived, token: OwnerToken) => {
    setState({ kind: 'checking', archived, failed: false });
    onCheck(archived, token).then(
      (found) => {
        if (!mountedRef.current) return;
        if (found === 'restored') clearMergedGuestProfile(token);
        setState(found === 'restored' ? { kind: 'restored' } : { kind: 'offer', archived, note: found });
      },
      () => {
        if (mountedRef.current) setState({ kind: 'checking', archived, failed: true });
      },
    );
  };
  const checkRef = useRef(check);
  useEffect(() => { checkRef.current = check; });

  // Restore can be sent only online, so the notice follows the connection;
  // a check that could not read is made again once the browser is back.
  useEffect(() => {
    const moved = (event: Event) => {
      setRendered((value) => value + 1);
      const current = stateRef.current;
      if (event.type === 'online' && current.kind === 'checking' && current.failed && owner) {
        checkRef.current(current.archived, owner);
      }
    };
    window.addEventListener('online', moved);
    window.addEventListener('offline', moved);
    return () => {
      window.removeEventListener('online', moved);
      window.removeEventListener('offline', moved);
    };
  }, [owner]);

  const retry = () => {
    setState({ kind: 'idle' });
    setAttempt((value) => value + 1);
  };

  const blocked = state.kind === 'offer' && owner ? blocker(owner) : null;

  const restore = () => {
    const archiveId = archiveIdRef.current;
    if (state.kind !== 'offer' || !owner || !archiveId) return;
    // Held back since this rendered (another tab's save, say): say why.
    if (blocker(owner) !== null) {
      rerender();
      return;
    }
    const { archived: shown } = state;
    setState({ kind: 'restoring' });
    let row: Archived | null = null;
    let ended: NoticeState | null = null;
    // Read again by its id: the row the merge wrote, still the latest one.
    const read = () => loadArchivedGuestProfile(owner, archiveId).then((found) => {
      if (!found) {
        clearMergedGuestProfile(owner);
        ended = { kind: 'gone' };
        return null;
      }
      // Settled in another tab meanwhile: nothing is sent from this one.
      if (readMergedGuestProfile() !== archiveId) {
        ended = { kind: 'hidden' };
        return null;
      }
      row = found;
      return found;
    });
    void onRestore(owner, read).catch((): GuestRestoreOutcome => (row ? 'unknown' : 'refused')).then((outcome) => {
      if (!mountedRef.current) return;
      if (outcome === 'skipped') {
        setState(ended ?? { kind: 'hidden' });
      } else if (outcome === 'restored') {
        clearMergedGuestProfile(owner);
        setState({ kind: 'restored' });
      } else if (outcome === 'unknown' && row) {
        check(row, owner);
      } else {
        setState({ kind: 'offer', archived: row ?? shown,
          note: outcome === 'conflict' ? 'conflict' : outcome === 'refused' ? 'notRestored' : null });
      }
    });
  };

  const keep = () => {
    if (!owner) return;
    clearMergedGuestProfile(owner);
    setState({ kind: 'hidden' });
  };

  const { kind } = state;
  if (kind === 'idle' || kind === 'hidden') return null;
  // Nothing of a restore is pending, so Keep is only held while one is being
  // sent or its outcome is being found out, and says so.
  const busy = kind === 'restoring' || kind === 'checking';
  const recheck = state.kind === 'checking' && state.failed ? state.archived : null;
  const keepReason = !busy ? undefined : recheck ? 'merged-guest-status' : 'merged-guest-keep-waits';
  const textButton = 'text-[12px] font-medium shrink-0 text-indigo-700 hover:text-indigo-900';
  return (
    <div
      data-testid="merged-guest-notice"
      className="max-w-3xl mx-auto mb-8 flex items-start gap-3 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl"
    >
      <ArchiveRestore className="w-4 h-4 text-indigo-600 mt-0.5 shrink-0" aria-hidden="true" />
      <div className="text-[13px] text-indigo-800 leading-relaxed">
        <p id="merged-guest-status" aria-live="polite">
          {kind === 'restored' ? t('home.mergedGuest.restored')
            : kind === 'gone' ? t('home.mergedGuest.gone')
              : kind === 'checking' ? t(state.failed ? 'home.mergedGuest.checkFailed' : 'home.mergedGuest.checking')
                : kind === 'offer' && state.note ? t(`home.mergedGuest.${state.note}`) : (
                  <>
                    <span className="font-semibold">{t('home.mergedGuest.title')}</span>{' '}
                    {kind === 'failed' ? t('home.mergedGuest.loadFailed') : t('home.mergedGuest.body')}
                  </>
                )}
        </p>
        {kind !== 'restored' && kind !== 'gone' && (
          <div className="mt-2 flex flex-wrap items-center gap-4">
            {kind !== 'failed' && (
              // Drawn at full strength when disabled: white on indigo-600
              // keeps its 6.3:1, and the reason is said beside it.
              <button
                type="button"
                data-testid="restore-guest-profile"
                onClick={restore}
                disabled={kind !== 'offer' || blocked !== null}
                aria-describedby={blocked ? 'merged-guest-blocked' : undefined}
                className="text-[12px] font-medium shrink-0 px-3 py-1 rounded-full bg-indigo-600 text-white hover:bg-indigo-700 disabled:cursor-not-allowed"
              >
                {kind === 'restoring' ? t('home.mergedGuest.restoring') : t('home.mergedGuest.restore')}
              </button>
            )}
            {(kind === 'failed' || recheck) && (
              <button
                type="button"
                onClick={recheck ? () => owner && check(recheck, owner) : retry}
                className={textButton}
              >
                {t('common.retry')}
              </button>
            )}
            <button
              type="button"
              data-testid="keep-account-profile"
              onClick={keep}
              disabled={busy}
              aria-describedby={keepReason}
              className={`${textButton} disabled:cursor-not-allowed`}
            >
              {t('home.mergedGuest.keep')}
            </button>
          </div>
        )}
        {busy && !recheck && (
          <p id="merged-guest-keep-waits" className="mt-1 text-[12px]">{t('home.mergedGuest.keepWaits')}</p>
        )}
        {blocked && (
          <p id="merged-guest-blocked" className="mt-1 text-[12px]">{t(`home.mergedGuest.blocked.${blocked}`)}</p>
        )}
        {(kind === 'restored' || kind === 'gone') && (
          <div className="mt-2">
            <button type="button" onClick={() => setState({ kind: 'hidden' })} className={textButton}>
              {t('common.dismiss')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
