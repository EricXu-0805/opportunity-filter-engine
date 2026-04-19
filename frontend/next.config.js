/** @type {import('next').NextConfig} */
const nextConfig = {
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
