// Single source of truth for the public site origin. Set NEXT_PUBLIC_SITE_URL
// to the production domain once it's live; until then it falls back to the
// current Vercel deployment. Used by metadataBase, canonical / OG URLs, robots,
// and sitemap so switching domains is one env var, not a code edit. Trailing
// slash is stripped so `${SITE_URL}/path` never doubles up.
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || 'https://opportunity-filter-engine.vercel.app'
).replace(/\/+$/, '');
