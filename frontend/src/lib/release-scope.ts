/**
 * Public release contract.
 *
 * These switches are deliberately source-controlled and fail closed. An
 * environment variable, stale bookmark, or unfinished UI cannot expose an
 * unaccepted feature. Each switch may only move to `true` in the reviewed
 * acceptance PR for that feature.
 */
export const RELEASE_SCOPE = Object.freeze({
  // Closed again after the released switch was found to change URL/badges but
  // not the /matches/view ranking. Re-open only with server mode attestation,
  // bounded paid concurrency and a real provider-backed acceptance.
  matchAiRefine: false,
  crossSchoolMatching: true,
  // These MTP capabilities stay in the codebase and keep their internal test
  // coverage, but are not part of the accepted MVP surface. Each must reopen
  // in a separate product-acceptance PR.
  compare: false,
  // Accepted — see backend/lib/release_scope.py for why the renovation surface
  // carries no fabrication risk the public /api/tailor does not already carry.
  resumeRenovate: true,
  fellowships: false,
  roadmap: false,
  askAi: false,
  professorSignals: false,
  // Still closed, and for a reason that is not about this codebase: Azure
  // publisher verification requires a verified legal entity, which does not
  // exist yet. Opening it shows students an "unverified publisher" consent
  // screen — worse for a product selling trust than one fewer sign-in button,
  // and Google sign-in is live.
  microsoftSchoolAuth: false,
  // Still closed because the flag is not the missing part. frontend/src/lib/
  // pricing.ts and public/pay/*.png do not exist on main (they live on the
  // unmerged feat/payments-concierge), and migration 026 dropped the orders
  // RLS policies and revoked anon/authenticated access — so flipping this
  // alone yields an API that answers and a database that refuses.
  payments: false,
  conciergePayQr: false,
} as const);

// Included in every server-side cached discovery URL. Bump whenever the public
// record-visibility contract changes so a new Vercel deployment cannot reuse
// an older deployment's Data Cache entries.
//
// Bumped here because the MVP capability close hides fellowships again. A
// cached discovery response minted while they were public must not survive the
// deployment boundary and reintroduce them into any release surface.
export const PUBLIC_RELEASE_CACHE_VERSION =
  'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2';

/** Match a hidden Fellowship preference even when stale storage was written
 * by an older client with different casing or stray whitespace. */
export function isFellowshipPreference(value: unknown): boolean {
  return typeof value === 'string'
    && value.trim().toLowerCase() === 'fellowship';
}

/**
 * Remove preferences for feature families that are outside the public release.
 *
 * Apply this at every profile ingress/egress (stored profile, share URL,
 * account switch, save, and submit). Hiding the selector alone would leave a
 * stale invisible preference able to shape later requests.
 */
export function normalizeProfileForRelease<
  T extends { seeking_types?: string[]; include_cross_school?: boolean },
>(profile: T): T {
  let normalized = profile;
  if (!RELEASE_SCOPE.fellowships && Array.isArray(profile.seeking_types)) {
    const seekingTypes = profile.seeking_types.filter(
      (value) => !isFellowshipPreference(value),
    );
    if (seekingTypes.length !== profile.seeking_types.length) {
      normalized = { ...normalized, seeking_types: seekingTypes };
    }
  }
  if (!RELEASE_SCOPE.crossSchoolMatching && normalized.include_cross_school) {
    normalized = { ...normalized, include_cross_school: false };
  }
  return normalized;
}
