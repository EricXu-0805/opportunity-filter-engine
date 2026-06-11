// Single source of truth for web-storage keys used in more than one file.
// Values are persisted in users' browsers — never change them, or existing
// profiles/preferences silently disappear.
export const STORAGE_KEYS = {
  PROFILE: 'ofe_profile',
  MATCH_RESULTS: 'ofe_match_results',
  SEMANTIC_RERANK: 'ofe_semantic_rerank',
  FILTER_PRESETS: 'ofe_filter_presets',
  CUSTOM_IMPORTS: 'ofe_custom_imports',
  EMAIL_HINT: 'ofe_email_hint',
  TAILOR_DRAFT_PREFIX: 'ofe_tailor_draft_',
  ANCHOR_3FAV_DISMISSED: 'ofe_anchor_3fav_dismissed',
  JUST_SIGNED_OUT: 'ofe_just_signed_out',
  GUEST_BANNER_DISMISSED: 'ofe_guest_banner_dismissed',
  LOCALE: 'ofe_lang',
} as const;
