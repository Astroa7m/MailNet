"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { SidebarContext, AppUser } from "./SidebarContext";
import { API } from "../lib/api";

interface Thread {
  thread_id: string;
  name: string;
  created_at: number;
}

function groupThreads(threads: Thread[]) {
  const now = Date.now();
  const D = 86400000;
  const startOfToday = new Date(); startOfToday.setHours(0,0,0,0);
  const todayMs = startOfToday.getTime();

  const groups: { label: string; items: Thread[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "This week", items: [] },
    { label: "Older", items: [] },
  ];
  for (const t of threads) {
    const age = todayMs - t.created_at;
    if (age < D && t.created_at >= todayMs) groups[0].items.push(t);
    else if (age < 2 * D) groups[1].items.push(t);
    else if (age < 7 * D) groups[2].items.push(t);
    else groups[3].items.push(t);
  }
  return groups.filter(g => g.items.length > 0);
}

export default function ChatProvider({ children }: { children: React.ReactNode }) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);
  const initialized = useRef(false);
  const router = useRouter();
  const pathname = usePathname();
  const currentThreadId = pathname === "/" ? null : pathname.slice(1);

  const fetchThreads = useCallback(async (): Promise<Thread[]> => {
    const r = await fetch(`${API}/threads`, { credentials: "include" });
    if (!r.ok) return [];
    const data: Thread[] = await r.json();
    setThreads(data);
    return data;
  }, []);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    Promise.all([
      fetch(`${API}/me`, { credentials: "include" }).then(async (r) => {
        if (r.status === 401) { window.location.href = `${API}/login`; return; }
        const data = await r.json();
        setUser({ name: data.name || "", email: data.email || "", picture: data.picture || "", providers: data.providers || [] });
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        fetch(`${API}/tz`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tz }) }).catch(() => {});
      }),
      fetchThreads(),
    ]).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!currentThreadId) return;
    const isPending = !threads.find((t) => t.thread_id === currentThreadId);
    if (!isPending) return;
    const interval = setInterval(async () => {
      const data = await fetchThreads();
      if (data.find((t) => t.thread_id === currentThreadId)) clearInterval(interval);
    }, 2000);
    return () => clearInterval(interval);
  }, [currentThreadId, threads]);

  function newConversation() { router.push(`/${crypto.randomUUID()}`); }

  async function deleteThread(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await fetch(`${API}/threads/${id}`, { method: "DELETE", credentials: "include" });
    const updated = await fetchThreads();
    if (id === currentThreadId) router.push(updated.length > 0 ? `/${updated[0].thread_id}` : "/");
  }

  if (loading) return null;

  const groups = groupThreads(threads);

  return (
    <SidebarContext.Provider value={{ open: sidebarOpen, toggle: () => setSidebarOpen((o) => !o), user, setUser }}>
      <div className="flex h-full w-full">
        {sidebarOpen && (
          <aside className="w-64 shrink-0 flex flex-col bg-gray-50 dark:bg-[#111111] border-r border-gray-200 dark:border-[#222222]">
            {/* Sidebar header */}
            <div className="flex items-center gap-2 px-3 py-3 border-b border-gray-200 dark:border-[#222222]">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shrink-0">
                  <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </div>
                <span className="font-semibold text-sm text-gray-900 dark:text-white tracking-tight">MailNet</span>
              </div>
              <button
                onClick={() => setSidebarOpen(false)}
                className="p-1.5 rounded-md hover:bg-gray-200 dark:hover:bg-[#222222] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                title="Close sidebar"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                </svg>
              </button>
            </div>

            {/* New chat button */}
            <div className="px-3 pt-3 pb-2">
              <button
                onClick={newConversation}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors shadow-sm"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                New conversation
              </button>
            </div>

            {/* Thread list */}
            <div className="flex-1 overflow-y-auto px-2 pb-2">
              {groups.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                  <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-[#222222] flex items-center justify-center mb-3">
                    <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  </div>
                  <p className="text-xs text-gray-400 dark:text-gray-500">No conversations yet</p>
                </div>
              ) : (
                groups.map((group) => (
                  <div key={group.label} className="mb-1">
                    <p className="px-2 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-600">
                      {group.label}
                    </p>
                    {group.items.map((t) => (
                      <button
                        key={t.thread_id}
                        onClick={() => router.push(`/${t.thread_id}`)}
                        className={`group w-full flex items-center justify-between px-2 py-2 rounded-lg text-sm cursor-pointer transition-colors text-left ${
                          t.thread_id === currentThreadId
                            ? "bg-gray-200 dark:bg-[#252525] text-gray-900 dark:text-white"
                            : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#1a1a1a] hover:text-gray-900 dark:hover:text-gray-200"
                        }`}
                      >
                        <span className="truncate pr-1 leading-snug">{t.name}</span>
                        <button
                          onClick={(e) => deleteThread(e, t.thread_id)}
                          className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition-all"
                          title="Delete"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </aside>
        )}
        <div className="flex-1 overflow-hidden">{children}</div>
      </div>
    </SidebarContext.Provider>
  );
}
