// W10b one-time school re-confirmation (the INTENT of Codex's school gate,
// built small on main's onboarding): the matching scope is not trustworthy
// until the user has explicitly confirmed their campus once. Choosing a school
// — in the onboarding tour, the profile switcher, or the confirm gate itself —
// IS confirming, so every write path records the same receipt and the gate
// never asks again.

import { clearMatchCache } from './match-cache';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from './storage-keys';
import { writeLocalStorageJSON } from './use-local-storage-json';
import { isOwnerTokenValid, readUserScopedRaw, type OwnerToken } from './identity-owner';
import {
  commitProfileAction,
  SCHOOL_WRITER,
  type ProfileSaveResult,
  type ProfileViewSnapshot,
} from './profile-sync';
import type { ProfileData } from './types';

export interface SchoolConfirmation {
  slug: string;
  ts: string;
}

export function readSchoolConfirmation(): SchoolConfirmation | null {
  try {
    const raw = readUserScopedRaw(STORAGE_KEYS.SCHOOL_CONFIRMED);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed && typeof parsed === 'object'
      && typeof (parsed as SchoolConfirmation).slug === 'string'
      && (parsed as SchoolConfirmation).slug
    ) {
      return parsed as SchoolConfirmation;
    }
    return null;
  } catch {
    return null;
  }
}

/** Whether the stored confirmation covers this campus. A confirmation for a
 *  DIFFERENT slug does not count — a school changed by a flow that skipped
 *  the receipt (e.g. an imported cloud profile) should be re-confirmed. */
export function isSchoolConfirmed(slug: string): boolean {
  return readSchoolConfirmation()?.slug === slug;
}

// `token` MUST be captured (via captureOwnerToken()) at the moment the
// caller's own confirm intent began — see writeLocalStorageJSON's own doc
// comment. Returns whether the receipt actually landed — a caller MUST
// check this before treating the confirm as successful (tracking it,
// closing its modal): a stale/no-longer-current token means nothing was
// written, and showing success anyway would let the user believe a school
// is confirmed when the gate will just ask again next visit.
export function recordSchoolConfirmation(slug: string, token: OwnerToken): boolean {
  return writeLocalStorageJSON(
    STORAGE_KEYS.SCHOOL_CONFIRMED,
    { slug, ts: new Date().toISOString() },
    token,
  );
}

export type PersistHomeSchoolResult =
  | {
    ok: true;
    /** False when there is no cloud backend right now: the campus is on this
     *  device only and will sync when one is available. */
    synced: boolean;
    /** False when the cached match set could not be verifiably removed. Not
     *  a correctness failure — the cache key includes home_school (see
     *  hashProfile), so the OLD school's entry can never be served for the
     *  new one — but hasMatchCache() will keep reporting a cached set that
     *  belongs to the previous campus, and the ~3 MB stays allocated. */
    cacheCleared: boolean;
  }
  | { ok: false; reason: ProfileSaveResult['status'] | 'receipt-failed'
    | 'baseline-stale' };

/**
 * The school choice reaches the home profile form two ways:
 *   1. as a PATCH of the single `home_school` key through the profile-sync
 *      coordinator — which is what persists it locally AND in the cloud. The
 *      one-field patch matters: this caller holds only a localStorage
 *      snapshot, which on a second device may predate a résumé removal, and
 *      the pre-CAS full-row write brought that résumé back.
 *   2. broadcast on a window event, because the home form usually mounts and
 *      reads its profile before an overlay finishes — a plain storage write
 *      would never be re-read. The form listens and updates home_school live.
 *
 * Everything after the persist is ORDERED and gated on it: the confirmation
 * receipt (optional, but written BEFORE the broadcast so the gate that the
 * broadcast wakes already sees this campus as confirmed), then the match-cache
 * invalidation, then the broadcast. A failed persist performs NONE of them —
 * a receipt or an event for a school that was never saved is a false record
 * the gate would then hide behind forever.
 */
export async function persistHomeSchool(
  slug: string,
  /** The one view the caller displayed when the person chose. It carries the
   *  baseline, the revision, the owner and the identity generation together;
   *  there is no separate token parameter and no fallback, because either of
   *  those is a way to pair values that were never true at the same moment. */
  view: ProfileViewSnapshot,
  opts: { confirm?: boolean } = {},
): Promise<PersistHomeSchoolResult> {
  // Preflight — before ANY read. A stale caller (U1's confirm click resolving
  // after the browser has switched to U2, or a surface that stayed mounted
  // across the switch and still holds U1's view) must produce ZERO profile
  // reads, ZERO cache clears and ZERO event dispatches.
  const { token } = view;
  if (!isOwnerTokenValid(token, token.uid)) return { ok: false, reason: 'abandoned' };

  // The full document as SHOWN, patched with the campus: a write built from
  // the bare baseline would drop every field the row does not carry and
  // truncate this device's mirror. The CAS base is a different document
  // entirely (view.baseProfile) and commitProfileAction takes it from the
  // view itself — precisely so these two cannot be swapped.
  const desired = { ...view.renderedProfile, home_school: slug } as ProfileData;
  // Durable first: a campus the person picked must not exist only in the
  // pending request. If it cannot be recorded, nothing is sent and the gate
  // is told so rather than closing on a promise.
  const action = await commitProfileAction({
    keys: ['home_school'],
    view,
    desiredAfter: desired,
    writer: SCHOOL_WRITER,
  });
  if (!action.durable || !action.result) {
    return { ok: false, reason: action.reason === 'stale-view' ? 'baseline-stale' : 'device-failed' };
  }
  const result = action.result;
  // 'staged-local' is a real success for this caller: the campus is durably
  // recorded on this device and goes out with the first complete profile
  // create. A brand-new account has no row to patch yet, and refusing here is
  // what left the onboarding tour unable to close.
  const landed = result.status === 'saved' || result.status === 'already-saved'
    || result.status === 'local-only' || result.status === 'staged-local';
  if (!landed) return { ok: false, reason: result.status };

  if (opts.confirm && !recordSchoolConfirmation(slug, token)) {
    // The campus landed but the receipt did not. Do NOT broadcast: the gate
    // would re-open on the next evaluation anyway, and firing the event now
    // would make it re-open while its own trigger says "already confirmed".
    return { ok: false, reason: 'receipt-failed' };
  }

  // Switching campus changes the matcher's candidate pool; the cached match
  // set is for the OLD school. This is NOT load-bearing for correctness —
  // hashProfile covers home_school, so the old entry cannot be served for the
  // new campus either way — it frees the ~3 MB and keeps hasMatchCache()
  // honest for the header link. Reported rather than assumed: the old comment
  // claimed the cache was cleared while ignoring the return value.
  const cacheCleared = clearMatchCache(token);
  try {
    window.dispatchEvent(new CustomEvent(HOME_SCHOOL_EVENT, { detail: slug }));
  } catch { /* SSR / no window */ }
  return {
    ok: true,
    synced: result.status === 'saved' || result.status === 'already-saved',
    cacheCleared,
  };
}
