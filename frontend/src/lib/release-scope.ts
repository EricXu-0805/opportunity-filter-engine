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
  compare: true,
  resumeRenovate: true,
  fellowships: true,
  roadmap: true,
  askAi: true,
  professorSignals: true,
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
// Bumped here because fellowships changes exactly that: opportunity_visible_in_release
// stopped filtering `fellowship` records out of every public surface, so a
// cached discovery response minted under the old contract is missing rows the
// new one publishes.
export const PUBLIC_RELEASE_CACHE_VERSION =
  'mvp-scope-open-v1-contact-trust-v1-faculty-trust-v1';

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
      (value) => value !== 'fellowship',
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
