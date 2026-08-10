// Build identity, inlined at build time so a served page can say which commit
// produced it. Vercel injects VERCEL_GIT_COMMIT_SHA for every deployment;
// OFE_RELEASE_SHA is the explicit override for other hosts and for local
// prod-like builds. Neither present => empty string, which
// src/lib/build-info.ts reports as unknown. Deliberately no placeholder and
// no local `git rev-parse`: the value must describe the artifact this deploy
// built, not whichever checkout happened to be on the machine.
const RELEASE_SHA = process.env.VERCEL_GIT_COMMIT_SHA
  || process.env.OFE_RELEASE_SHA
  || "";
const RELEASE_ENV = process.env.VERCEL_ENV
  || process.env.OFE_ENVIRONMENT
  || "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Inlined at build time (these are build facts, not runtime configuration —
  // reading them at runtime would report the serving host's environment
  // instead of what this bundle was built from).
  env: {
    NEXT_PUBLIC_RELEASE_SHA: RELEASE_SHA,
    NEXT_PUBLIC_RELEASE_ENV: RELEASE_ENV,
  },
  // Pin the Turbopack workspace root to this directory. A stray lockfile in an
  // ancestor of the repo otherwise makes Next infer the parent as root and scan
  // that whole (on macOS often iCloud-synced) tree — which stalls dev startup.
  turbopack: {
    root: __dirname,
  },
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },
  async rewrites() {
    const isProduction = process.env.VERCEL_ENV === "production"
      || process.env.NODE_ENV === "production";
    const backendUrl = process.env.BACKEND_URL
      || process.env.NEXT_PUBLIC_API_URL
      || (isProduction
        ? "https://opportunity-filter-engine-api.onrender.com"
        : "http://127.0.0.1:8000");
    return {
      fallback: [
        {
          source: "/api/:path*",
          destination: `${backendUrl}/api/:path*`,
        },
      ],
    };
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "X-DNS-Prefetch-Control", value: "on" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
  poweredByHeader: false,
};

module.exports = nextConfig;
