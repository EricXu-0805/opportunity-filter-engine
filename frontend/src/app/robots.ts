import type { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/site';

// Allow crawling of the public content; keep crawlers out of the admin surface
// and the API. Points at the env-driven sitemap so a domain switch needs no edit.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: '*', allow: '/', disallow: ['/admin', '/api'] },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
