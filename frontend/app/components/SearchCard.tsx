"use client";
import { useMemo } from "react";

interface Props {
  status: string;
  args?: Record<string, unknown> | unknown;
  result?: string;
}

interface Hit {
  title: string;
  snippet: string;
  url: string;
}

// web_search returns blocks of "- {title}\n  {body}\n  {href}".
function parseHits(result?: string): Hit[] {
  if (!result) return [];
  const blocks = result.split(/\n(?=-\s)/);
  const hits: Hit[] = [];
  for (const block of blocks) {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!lines.length) continue;
    const title = lines[0].replace(/^-\s*/, "");
    const url = lines.find((l) => /^https?:\/\//i.test(l)) || "";
    const snippet = lines.slice(1).filter((l) => l !== url).join(" ");
    if (title) hits.push({ title, snippet, url });
  }
  return hits;
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export default function SearchCard({ status, args, result }: Props) {
  const complete = status === "complete";
  const query = useMemo(() => {
    const q = (args as any)?.query;
    return typeof q === "string" ? q : "";
  }, [args]);
  const hits = useMemo(() => parseHits(result), [result]);
  const failed = complete && (!result || /^No web results|Web search failed/i.test(result || ""));

  return (
    <div className="mn-search my-1.5 overflow-hidden rounded-2xl border border-blue-200/70 dark:border-blue-500/20 bg-gradient-to-b from-blue-50/80 to-white dark:from-[#0a1428] dark:to-[#0a0f1c]">
      {/* Scanning header / the "blue space" */}
      <div className="relative px-4 pt-3.5 pb-3">
        {!complete && (
          <div className="mn-search-field pointer-events-none absolute inset-0 opacity-70" aria-hidden />
        )}
        <div className="relative flex items-center gap-2.5">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full ${
              complete
                ? failed
                  ? "bg-gray-200 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
                  : "bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300"
                : "bg-blue-500/15 text-blue-500 dark:text-blue-300"
            }`}
          >
            {!complete ? (
              <span className="mn-search-orbit relative block h-3.5 w-3.5">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
                  <circle cx="11" cy="11" r="7" />
                  <path strokeLinecap="round" d="M21 21l-4.3-4.3" />
                </svg>
              </span>
            ) : failed ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
                <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} className="h-3.5 w-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            )}
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-gray-800 dark:text-gray-100">
              {!complete ? "Searching the web" : failed ? "No results" : `Found ${hits.length || "results"}`}
            </div>
            {query && (
              <div className="truncate text-xs text-blue-600/80 dark:text-blue-300/70">{query}</div>
            )}
          </div>
          {!complete && (
            <span className="ml-auto flex gap-1">
              <span className="mn-dot h-1.5 w-1.5 rounded-full bg-blue-400/80" />
              <span className="mn-dot mn-dot-2 h-1.5 w-1.5 rounded-full bg-blue-400/80" />
              <span className="mn-dot mn-dot-3 h-1.5 w-1.5 rounded-full bg-blue-400/80" />
            </span>
          )}
        </div>
      </div>

      {/* Results, revealed calmly */}
      {complete && !failed && hits.length > 0 && (
        <div className="border-t border-blue-100/70 dark:border-blue-500/10 divide-y divide-blue-100/60 dark:divide-white/5">
          {hits.slice(0, 4).map((h, i) => (
            <a
              key={i}
              href={h.url || undefined}
              target="_blank"
              rel="noreferrer"
              className="mn-hit block px-4 py-2.5 transition-colors hover:bg-blue-50/60 dark:hover:bg-white/5"
              style={{ animationDelay: `${i * 90}ms` }}
            >
              <div className="flex items-center gap-1.5">
                {hostOf(h.url) && (
                  <span className="truncate text-[11px] text-blue-500/80 dark:text-blue-300/60">{hostOf(h.url)}</span>
                )}
              </div>
              <div className="line-clamp-1 text-[13px] font-medium text-gray-800 dark:text-gray-100">{h.title}</div>
              {h.snippet && (
                <div className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                  {h.snippet}
                </div>
              )}
            </a>
          ))}
        </div>
      )}

      <style>{`
        .mn-search-field {
          background:
            radial-gradient(circle at 18% 40%, rgba(59,130,246,0.20), transparent 42%),
            radial-gradient(circle at 82% 60%, rgba(37,99,235,0.16), transparent 45%);
          -webkit-mask-image: radial-gradient(ellipse at center, black 60%, transparent 100%);
          mask-image: radial-gradient(ellipse at center, black 60%, transparent 100%);
        }
        .mn-search-field::before {
          content: "";
          position: absolute; inset: 0;
          background-image:
            radial-gradient(rgba(59,130,246,0.35) 0.6px, transparent 0.6px);
          background-size: 14px 14px;
          opacity: 0.5;
        }
        .mn-search-field::after {
          content: "";
          position: absolute; top: 0; bottom: 0; width: 40%;
          background: linear-gradient(90deg, transparent, rgba(96,165,250,0.28), transparent);
          animation: mn-scan 1.9s ease-in-out infinite;
        }
        @keyframes mn-scan { 0% { left: -40%; } 100% { left: 100%; } }
        .mn-search-orbit { animation: mn-spin 1.6s linear infinite; }
        @keyframes mn-spin { to { transform: rotate(360deg); } }
        .mn-dot { animation: mn-blink 1.2s ease-in-out infinite; }
        .mn-dot-2 { animation-delay: 0.2s; }
        .mn-dot-3 { animation-delay: 0.4s; }
        @keyframes mn-blink { 0%,100% { opacity: 0.25; } 50% { opacity: 1; } }
        .mn-hit { animation: mn-rise 0.5s ease both; }
        @keyframes mn-rise { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
        @media (prefers-reduced-motion: reduce) {
          .mn-search-field::after, .mn-search-orbit, .mn-dot, .mn-hit { animation: none; }
        }
      `}</style>
    </div>
  );
}
