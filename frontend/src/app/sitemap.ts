import type { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/site';

// Public, indexable content routes only. Excludes the per-user / tool pages
// (account, dashboard, favorites, tracker, results, compare, import, restore,
// auth) — they need a signed-in user's own data and would be thin/duplicate to
// a crawler — and the admin surface.
const ROUTES = ['', '/about', '/fellowships', '/resources', '/roadmap', '/privacy', '/terms'];

export default function sitemap(): MetadataRoute.Sitemap {
  return ROUTES.map((path) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency: path === '' ? 'daily' : 'monthly',
    priority: path === '' ? 1 : 0.6,
  }));
}
