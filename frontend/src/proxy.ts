import { NextResponse, type NextRequest } from 'next/server';

function httpOrigin(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    return url.origin;
  } catch {
    // Relative values like '/api' stay same-origin and are covered by 'self'.
    return null;
  }
}

function websocketOrigin(origin: string | null): string | null {
  if (!origin) return null;
  return origin.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:');
}

export interface CspOptions {
  isDevelopment?: boolean;
  supabaseUrl?: string | undefined;
  apiUrl?: string | undefined;
}

/**
 * Request-scoped CSP for rendered pages. Scripts require the per-request
 * nonce ('strict-dynamic' lets nonce-approved scripts load their own chunks,
 * which is how Next bootstraps). 'wasm-unsafe-eval' permits pdfjs-dist's WASM
 * decoders without allowing JS eval.
 *
 * style-src deliberately carries 'unsafe-inline' and NO nonce: next/font and
 * React emit inline styles without nonces, and the presence of any nonce in
 * style-src makes browsers ignore 'unsafe-inline'. Script injection is the
 * attack that matters; inline styles are an accepted trade-off.
 *
 * Cross-origin browser connections: the Supabase project (HTTPS for
 * Auth/REST, WSS for Realtime) and the backend API only when
 * NEXT_PUBLIC_API_URL is absolute — the default '/api' rewrite stays
 * same-origin. Unset env vars simply omit the origin.
 */
export function buildContentSecurityPolicy(
  nonce: string,
  {
    isDevelopment = process.env.NODE_ENV === 'development',
    supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL,
    apiUrl = process.env.NEXT_PUBLIC_API_URL,
  }: CspOptions = {},
): string {
  const supabaseOrigin = httpOrigin(supabaseUrl);
  const connectSources = [
    "'self'",
    supabaseOrigin,
    websocketOrigin(supabaseOrigin),
    httpOrigin(apiUrl),
    ...(isDevelopment
      ? ['http://localhost:*', 'http://127.0.0.1:*', 'ws://localhost:*', 'ws://127.0.0.1:*']
      : []),
  ].filter((source): source is string => source !== null);

  const scriptSources = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    "'wasm-unsafe-eval'",
    ...(isDevelopment ? ["'unsafe-eval'"] : []),
  ];

  return [
    "default-src 'self'",
    `script-src ${scriptSources.join(' ')}`,
    "script-src-attr 'none'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    `connect-src ${connectSources.join(' ')}`,
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    ...(isDevelopment ? [] : ['upgrade-insecure-requests']),
  ].join('; ');
}

export function proxy(request: NextRequest) {
  // UUID v4 hex form: 122 unpredictable bits, only nonce-safe characters.
  const nonce = crypto.randomUUID().replaceAll('-', '');
  const contentSecurityPolicy = buildContentSecurityPolicy(nonce);

  // Next reads the CSP request header to discover the nonce and stamps it on
  // its framework/inline scripts; x-nonce lets our own server components read
  // it via headers() if ever needed. Overwrite, never trust, client values.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', contentSecurityPolicy);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set('Content-Security-Policy', contentSecurityPolicy);
  return response;
}

export const config = {
  matcher: [
    {
      // Nonces only make sense on rendered pages. Static assets, the /api
      // rewrite, generated icons/OG images/robots/sitemap and router
      // prefetches are skipped so they keep their normal caching behavior.
      source:
        '/((?!api|_next/static|_next/image|favicon.ico|manifest.json|sw.js|icon-192.png|icon-512.png|icon|apple-icon|opengraph-image|robots.txt|sitemap.xml|pay/|walkthrough/).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
