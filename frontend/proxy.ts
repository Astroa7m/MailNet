// Runs before every page request. MailNet has exactly three kinds of page:
// the home screen, a conversation at /<uuid>, and /admin. Anything else is a
// typo, a stale link, or someone probing, and goes straight back home instead
// of seeing a 404 page that confirms what does and does not exist.
//
// Only page routes pass through here: the matcher below skips Next's own
// assets, the CopilotKit route, and files with an extension (icons, images).
// API paths never reach Next in production, because nginx sends them to
// FastAPI first.
import { NextResponse, type NextRequest } from "next/server";

// Conversation ids come from crypto.randomUUID() (ChatProvider, page.tsx).
const THREAD = /^\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PAGES = new Set(["/", "/admin"]);

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PAGES.has(pathname) || THREAD.test(pathname)) return NextResponse.next();
  return NextResponse.redirect(new URL("/", request.url));
}

export const config = {
  matcher: ["/((?!_next/|api/copilotkit|.*\\..*).*)"],
};
