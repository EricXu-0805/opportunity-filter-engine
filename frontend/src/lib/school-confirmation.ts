// W10b one-time school re-confirmation (the INTENT of Codex's school gate,
// built small on main's onboarding): the matching scope is not trustworthy
// until the user has explicitly confirmed their campus once. Choosing a school
// — in the onboarding tour, the profile switcher, or the confirm gate itself —
// IS confirming, so every write path records the same receipt and the gate
// never asks again.

import { clearMatchCache } from './match-cache';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from './storage-keys';
import { writeLocalStorageJSON } from './use-local-storage-json';

export interface SchoolConfirmation {
  slug: string;
  ts: string;
}

export function readSchoolConfirmation(): SchoolConfirmation | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.SCHOOL_CONFIRMED);
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

export function recordSchoolConfirmation(slug: string): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.SCHOOL_CONFIRMED,
      JSON.stringify({ slug, ts: new Date().toISOString() }),
    );
  } catch { /* storage unavailable */ }
}

// The school choice is handed to the home profile form two ways (moved here
// from OnboardingIntro so the confirm gate shares one write path):
//   1. merged into the persisted local profile blob — the same key
//      loadProfile() reads first — so a fresh load opens on the chosen campus;
//   2. broadcast on a window event, because the home form usually mounts and
//      reads its profile before an overlay finishes — a plain localStorage
//      write would never be re-read. The form listens and updates home_school
//      live (see use-profile-form.ts).
// Local-only persistence keeps callers off the supabase client (and their
// jsdom tests trivial); a later form auto-save syncs the full profile.
export function persistHomeSchool(slug: string): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.PROFILE);
    const parsed = raw ? JSON.parse(raw) : null;
    const base = parsed && typeof parsed === 'object' ? parsed : {};
    // writeLocalStorageJSON (not raw setItem): it dispatches the synthetic
    // storage event same-tab readers subscribe to — the confirm gate can
    // render ON TOP of /results, and a raw write left that page showing the
    // previous campus's matches until a manual reload.
    writeLocalStorageJSON(STORAGE_KEYS.PROFILE, { ...base, home_school: slug });
  } catch { /* storage unavailable */ }
  // Switching campus changes the matcher's candidate pool; the cached match
  // set is for the OLD school and must not be served on the next /results
  // visit. (hashProfile also covers home_school — this just frees the ~3 MB
  // immediately and keeps hasMatchCache() honest for the header link.)
  clearMatchCache();
  try {
    window.dispatchEvent(new CustomEvent(HOME_SCHOOL_EVENT, { detail: slug }));
  } catch { /* SSR / no window */ }
}
