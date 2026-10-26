import type { Metadata, ResolvingMetadata } from 'next';

// Single source of truth for the public site origin. Set NEXT_PUBLIC_SITE_URL
// to the production domain once it's live; until then it falls back to the
// current Vercel deployment. Used by metadataBase, canonical / OG URLs, robots,
// and sitemap so switching domains is one env var, not a code edit. Trailing
// slash is stripped so `${SITE_URL}/path` never doubles up.
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || 'https://opportunity-filter-engine.vercel.app'
).replace(/\/+$/, '');

/**
 * generateMetadata for a public route: its own metadata plus a canonical and
 * og:url naming the route itself. The root layout sets neither, because every
 * route that did not override a root value inherited it, 404s included, and
 * so told crawlers and link previews it was the homepage.
 *
 * A route's openGraph and twitter replace the parent's whole object rather
 * than merging into it, so the root's (site name, locale, the generated card
 * image, twitter:creator) are carried over from `parent` first.
 */
export function selfReferencingMetadata(path: string, own: Metadata = {}) {
  return async (_props: unknown, parent: ResolvingMetadata): Promise<Metadata> => {
    const inherited = await parent;
    return {
      ...own,
      alternates: { canonical: path },
      openGraph: { ...inherited.openGraph, ...own.openGraph, url: path },
      ...(own.twitter && { twitter: { ...inherited.twitter, ...own.twitter } }),
    };
  };
}
