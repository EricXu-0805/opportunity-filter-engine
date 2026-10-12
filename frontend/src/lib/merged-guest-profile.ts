// After a Flow B merge into an account that already had a profile, the server
// keeps the account's row and saves the guest's as a revision-less
// profile_versions entry (migration 034). Nothing is lost, but nothing told
// the student where their guest profile went either. This marker is how
// /auth/callback tells Home: it is written into the ACCOUNT's own user-scoped
// namespace right after the claim, so no other identity ever sees it, and Home
// offers the restore until the student restores the guest profile or chooses
// to keep the account's.
//
// The marker names the one archived row that merge wrote (its id, found right
// after the merge: see findLatestProfileArchive) and carries no profile data.
// Home restores that row and no other (loadArchivedGuestProfile), as one
// revision-checked save of the whole profile (saveWholeProfile in
// profile-sync), never as an edit of the form's.

import { readUserScopedRaw, removeUserScopedRaw, writeUserScopedRaw, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

/** False when the browser refused the write or `token` no longer owns it. */
export function recordMergedGuestProfile(token: OwnerToken, archiveId: string): boolean {
  return writeUserScopedRaw(STORAGE_KEYS.MERGED_GUEST_PROFILE, JSON.stringify({ v: 1, archive: archiveId }), token);
}

/** The archived row the identity that owns this browser right now may still
 *  restore, or null when it has none it has not restored or set aside. */
export function readMergedGuestProfile(): string | null {
  const raw = readUserScopedRaw(STORAGE_KEYS.MERGED_GUEST_PROFILE);
  if (raw === null) return null;
  try {
    const marker = JSON.parse(raw) as { v?: unknown; archive?: unknown } | null;
    return marker?.v === 1 && typeof marker.archive === 'string' && marker.archive ? marker.archive : null;
  } catch {
    return null;
  }
}

export function clearMergedGuestProfile(token: OwnerToken): boolean {
  return removeUserScopedRaw(STORAGE_KEYS.MERGED_GUEST_PROFILE, token);
}
