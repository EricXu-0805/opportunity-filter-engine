/**
 * Public release contract.
 *
 * These switches are deliberately source-controlled and fail closed. An
 * environment variable, stale bookmark, or unfinished UI cannot expose an
 * unaccepted feature. Each switch may only move to `true` in the reviewed
 * acceptance PR for that feature.
 */
export const RELEASE_SCOPE = Object.freeze({
  matchAiRefine: false,
  compare: false,
  resumeRenovate: false,
  fellowships: false,
  roadmap: false,
  askAi: false,
  professorSignals: false,
  microsoftSchoolAuth: false,
  payments: false,
  conciergePayQr: false,
} as const);

// Included in every server-side cached discovery URL. Bump whenever the public
// record-visibility contract changes so a new Vercel deployment cannot reuse
// an older deployment's Data Cache entries.
export const PUBLIC_RELEASE_CACHE_VERSION = 'mvp-route-freeze-v1';

/**
 * Remove preferences for feature families that are outside the public release.
 *
 * Apply this at every profile ingress/egress (stored profile, share URL,
 * account switch, save, and submit). Hiding the selector alone would leave a
 * stale invisible preference able to shape later requests.
 */
export function normalizeProfileForRelease<
  T extends { seeking_types?: string[] },
>(profile: T): T {
  if (RELEASE_SCOPE.fellowships || !Array.isArray(profile.seeking_types)) {
    return profile;
  }
  const seekingTypes = profile.seeking_types.filter(
    (value) => value !== 'fellowship',
  );
  if (seekingTypes.length === profile.seeking_types.length) return profile;
  return { ...profile, seeking_types: seekingTypes };
}
