// Runs before every page request, and does two jobs.
//
// 1. Routing. MailNet has three kinds of page: the home screen, a
//    conversation at /<uuid>, and /admin. Anything else is a typo, a stale
//    link, or someone probing, and goes back home.
//
// 2. Content Security Policy. Each request gets a fresh random nonce (a
//    one-time password for scripts). The CSP header tells the browser to run
//    only scripts carrying that nonce, so a script someone manages to inject
//    into the page cannot run: it does not know this request's nonce. Next.js
//    reads the policy from the request headers and stamps the nonce on its own
//    scripts; the layout's inline theme script reads it from x-nonce.
//
// Only page routes pass through here: the matcher skips Next's own assets,
// the CopilotKit route, and files with an extension (icons, images). API
// paths never reach Next in production, because nginx sends them to FastAPI.
import { NextResponse, type NextRequest } from "next/server";

// Conversation ids come from crypto.randomUUID() (ChatProvider, page.tsx).
const THREAD = /^\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PAGES = new Set(["/", "/admin"]);

// Where the FastAPI backend lives. Same origin as the site in production
// (nginx serves both), http://localhost:8002 in local dev.
const API_ORIGIN = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8002").origin;
const DEV = process.env.NODE_ENV !== "production";

export function buildCsp(nonce: string): string {
  return [
    "default-src 'self'",
    // strict-dynamic: scripts loaded BY a nonce-carrying script are trusted
    // too, which is how Next loads its chunks. Dev mode needs eval for
    // hot reload; production never gets it.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${DEV ? " 'unsafe-eval'" : ""}`,
    // Inline style attributes are used throughout (React style={{}}). Styles
    // cannot run code, so allowing them is the accepted trade-off.
    "style-src 'self' 'unsafe-inline'",
    // Avatars come from Google; attachments and thumbnails from our API.
    `img-src 'self' data: blob: ${API_ORIGIN} https://*.googleusercontent.com`,
    "font-src 'self' data:",
    `connect-src 'self' ${API_ORIGIN}`,
    "object-src 'none'",
    "base-uri 'self'",
    `form-action 'self' ${API_ORIGIN}`,
    "frame-ancestors 'none'",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (!(PAGES.has(pathname) || THREAD.test(pathname))) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Skip Next internals, the CopilotKit API route, and real static-asset
  // extensions at the END of the path (security review F8). The old rule
  // excluded any path containing a dot anywhere, so /x.png bypassed the CSP
  // and the route guard entirely.
  matcher: [
    "/((?!_next/|api/copilotkit|.*\\.(?:ico|png|jpg|jpeg|gif|webp|svg|css|js|mjs|map|woff2?|ttf|otf|json|txt|xml|webmanifest|pdf)$).*)",
  ],
};
