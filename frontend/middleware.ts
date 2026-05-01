import { NextRequest, NextResponse } from "next/server";

// ─── Route protection ─────────────────────────────────────────────────────────
// Strategy:
//   - The access token lives in memory (JS), so middleware can't read it.
//   - The refresh token lives in an HttpOnly cookie named "refresh_token",
//     which IS readable by middleware on the server.
//   - We use the presence of the refresh cookie as a lightweight "logged in"
//     signal to decide whether to redirect to /login.
//   - The real auth enforcement is done by the backend (Bearer token required).
//   - On page load, the AuthProvider component calls /auth/refresh to get a
//     fresh access token if the cookie is present.

const COOKIE_NAME    = "refresh_token";
const PUBLIC_PATHS   = ["/login", "/_next", "/favicon.ico", "/api"];
const CANDIDATE_ROOT = "/candidate";
const RECRUITER_ROOT = "/recruiter";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // ── Root redirect ──────────────────────────────────────────────────────────
  if (pathname === "/") {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  // ── Allow public paths through unconditionally ─────────────────────────────
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // ── Check for refresh cookie (proxy for "has a session") ──────────────────
  const hasSession = req.cookies.has(COOKIE_NAME);

  if (!hasSession) {
    // No session at all → send to login
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // ── Zustand persisted role lives in localStorage, not cookies.
  //    We can't read it in middleware, so we skip role enforcement here.
  //    Each role's layout.tsx does a client-side role check and redirects if wrong.
  // ─────────────────────────────────────────────────────────────────────────

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT:
     * - _next/static (static files)
     * - _next/image  (image optimization)
     * - favicon.ico
     * - api routes (handled by Next.js API routes if any)
     */
    "/((?!_next/static|_next/image|favicon.ico|api).*)",
  ],
};
