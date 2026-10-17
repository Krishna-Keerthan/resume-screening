// The browser calls /api/v1/* on this app's own domain and Next.js forwards
// the request to the backend. That keeps the refresh-token cookie first-party.
//
// API_PROXY_TARGET is the backend origin WITHOUT /api/v1. Rewrites are fixed at
// build time, so it must be set when `next build` runs (Vercel project
// settings, docker build arg).
function resolveProxyTarget() {
  const isProduction = process.env.NODE_ENV === "production";
  const raw = process.env.API_PROXY_TARGET || (isProduction ? "" : "http://localhost:5000");

  if (!raw) {
    throw new Error(
      "API_PROXY_TARGET is not set. Set it to the backend origin without /api/v1 " +
        "(for example https://your-service.onrender.com) before building."
    );
  }

  const target = raw.replace(/\/+$/, "");
  if (target.endsWith("/api/v1")) {
    throw new Error(
      `API_PROXY_TARGET must not end in /api/v1 (got ${raw}); the path is added once by the rewrite.`
    );
  }
  return target;
}

const apiProxyTarget = resolveProxyTarget();

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: { unoptimized: true },
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiProxyTarget}/api/v1/:path*` }];
  },
};
module.exports = nextConfig;
