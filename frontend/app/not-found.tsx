// Shown for anything Next cannot serve that proxy.ts did not already send
// home, mostly missing files like /wp-admin/x.php (the proxy skips paths with
// a dot so real icons and images still load). A real 404 status plus a clear
// way back, in the same look as the login page.
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="min-h-screen grid place-items-center bg-[#0a0a0b] text-gray-100 px-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-200">
          <svg className="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          MailNet
        </div>
        <p className="mt-8 text-xs font-medium tracking-widest text-indigo-400">404</p>
        <h1 className="mt-2 text-3xl font-bold leading-tight">This page didn&apos;t make it to the inbox.</h1>
        <p className="mt-3 text-sm text-gray-400">
          The link may be old or mistyped. Everything MailNet does starts from the home screen.
        </p>
        <Link
          href="/"
          className="mt-8 inline-flex items-center justify-center w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium hover:bg-white/10 transition-colors"
        >
          Back to MailNet
        </Link>
      </div>
    </main>
  );
}
