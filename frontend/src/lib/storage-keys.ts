// Single source of truth for web-storage keys used in more than one file.
// Values are persisted in users' browsers — never change them, or existing
// profiles/preferences silently disappear.
export const STORAGE_KEYS = {
  PROFILE: 'ofe_profile',
  // Bumped to _v2 after #226 switched the opt-in rerank from the (regressing)
  // embedding blend to the LLM "AI smart match". A returning user's pre-#226
  // cache held embedding-ranked sets that would otherwise be served — and
  // badged as AI smart match — for up to the 7-day TTL. The cache is
  // regenerable (just match results), so invalidating it is safe.
  MATCH_RESULTS: 'ofe_match_results_v2',
  SEMANTIC_RERANK: 'ofe_semantic_rerank',
  FILTER_PRESETS: 'ofe_filter_presets',
  CUSTOM_IMPORTS: 'ofe_custom_imports',
  EMAIL_HINT: 'ofe_email_hint',
  FAVORITES_FALLBACK: 'ofe_favs_fallback',
  // W6: auth uid that owns the user-scoped local values below. Plain string,
  // written beside the data (never wrapped around it) — see identity-owner.ts.
  LOCAL_IDENTITY_OWNER: 'ofe_local_identity_owner',
  TAILOR_DRAFT_PREFIX: 'ofe_tailor_draft_',
  ANCHOR_3FAV_DISMISSED: 'ofe_anchor_3fav_dismissed',
  JUST_SIGNED_OUT: 'ofe_just_signed_out',
  GUEST_BANNER_DISMISSED: 'ofe_guest_banner_dismissed',
  LOCALE: 'ofe_lang',
  OAUTH_LINK_PROVIDER: 'ofe_oauth_link_provider',
  ONBOARDING_SEEN: 'ofe_onboarding_seen',
  // Flow B: a merge-grant token minted on the anon (source) session right
  // before an existing-account sign-in redirect. Survives the redirect in
  // localStorage and is redeemed once on /auth/callback, then cleared.
  MERGE_GRANT: 'ofe_merge_grant',
  RESULTS_CTA_DISMISSED: 'ofe_results_cta_dismissed',
} as const;

// Window CustomEvent fired when the onboarding school gate sets the campus, so a
// home profile form that already mounted (and already read its profile) updates
// its home_school live instead of waiting for a reload. detail = school slug.
export const HOME_SCHOOL_EVENT = 'ofe:home-school';
