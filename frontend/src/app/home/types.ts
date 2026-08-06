import type { ProfileData } from '@/lib/types';
import type { useT } from '@/i18n/client';
import { RELEASE_SCOPE } from '@/lib/release-scope';

export type TFunc = ReturnType<typeof useT>['t'];

export const DEFAULT_PROFILE: ProfileData = {
  name: '',
  institution: 'UIUC - University of Illinois Urbana-Champaign',
  home_school: 'uiuc',
  college: '',
  major: '',
  additional_majors: [],
  grade: '',
  is_international: false,
  research_interests: '',
  skills: [],
  search_weight: 50,
};

export const SEEKING_TYPES = [
  'research',
  'summer_program',
  'internship',
  ...(RELEASE_SCOPE.fellowships ? (['fellowship'] as const) : []),
] as const;
export type SeekingType = typeof SEEKING_TYPES[number];


// Outcomes of SAVING. Whether this identity's row has been READ at all is
// a separate axis — see HydrationState — because "we never loaded your
// profile, so nothing is being saved" and "your save failed" are different
// things to tell someone, with different fixes.
// 'cloud-failed' = the local copy is up to date but the cloud one is NOT.
// Distinct from 'error' (nothing landed anywhere) because the fix is
// different: the change is safe on this device and needs re-syncing, and
// until it does the next load can bring the old row back.
// 'conflict' = another device changed the same fields; NOTHING was written
//              remotely and the edit is still on screen, unsaved.
// 'stale'    = the row this edit belongs to no longer exists (deleted, or the
//              account was merged into another one). Nothing is retried —
//              recreating it would resurrect a dead identity's data.
export type SaveStatus =
  | 'idle' | 'saving' | 'saved' | 'error'
  | 'device-only' | 'cloud-failed' | 'device-failed'
  | 'conflict' | 'stale'
  // The answer was about a question that no longer exists — the row moved, a
  // candidate appeared or disappeared, another tab settled it. Nothing was
  // written or sent; the current question is being shown instead. Distinct
  // from 'cloud-failed', which says the network let the user down.
  | 'conflict-stale';

// 'loading' → this identity's stored row has not come back yet
// 'ready'   → it has (a row, or a confirmed-absent one); edits persist
// 'failed'  → the read itself failed; nothing is persisted, and the row is
//             NOT assumed empty (see useProfileForm's hydration gate)
export type HydrationState = 'loading' | 'ready' | 'failed';
