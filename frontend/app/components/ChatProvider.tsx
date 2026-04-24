"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { SidebarContext, AppUser } from "./SidebarContext";

const API = "http://localhost:8002";

interface Thread {
  thread_id: string;
  name: string;
  created_at: number;
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
        if (r.status === 401) { window.location.href = `${API}/`; return; }
        const data = await r.json();
        const u: AppUser = { name: data.name || "", email: data.email || "", picture: data.picture || "", providers: data.providers || [] };
        setUser(u);
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        fetch(`${API}/tz`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tz }) });
      }),
      fetchThreads(),
    ]).finally(() => setLoading(false));
  }, []);

  // poll while current thread is not yet saved to DB
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

  function newConversation() {
    router.push(`/${crypto.randomUUID()}`);
  }

  async function deleteThread(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await fetch(`${API}/threads/${id}`, { method: "DELETE", credentials: "include" });
    const updated = await fetchThreads();
    if (id === currentThreadId) {
      router.push(updated.length > 0 ? `/${updated[0].thread_id}` : "/");
    }
  }

  function formatDate(ts: number) {
    return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  if (loading) return null;

  return (
    <SidebarContext.Provider value={{ open: sidebarOpen, toggle: () => setSidebarOpen((o) => !o), user, setUser }}>
      <div className="flex h-full w-full">
        {sidebarOpen && (
          <aside className="w-64 shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900">
            <div className="p-3 flex items-center gap-2 border-b border-gray-200 dark:border-gray-800">
              <button
                onClick={() => setSidebarOpen(false)}
                className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500"
                title="Close sidebar"
              >
                &#x2715;
              </button>
              <button
                onClick={newConversation}
                className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              >
                <span className="text-lg leading-none">+</span> New conversation
              </button>
            </div>
            <div className="flex-1 overflow-y-auto py-2">
              {threads.map((t) => (
                <div
                  key={t.thread_id}
                  onClick={() => router.push(`/${t.thread_id}`)}
                  className={`group flex items-center justify-between px-4 py-2 text-sm cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
                    t.thread_id === currentThreadId ? "bg-gray-200 dark:bg-gray-700 font-medium" : ""
                  }`}
                >
                  <div className="overflow-hidden">
                    <div className="truncate">{t.name}</div>
                    <div className="text-xs text-gray-400">{formatDate(t.created_at)}</div>
                  </div>
                  <button
                    onClick={(e) => deleteThread(e, t.thread_id)}
                    className="ml-2 shrink-0 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-opacity"
                    title="Delete conversation"
                  >
                    &#x2715;
                  </button>
                </div>
              ))}
            </div>
          </aside>
        )}
        <div className="flex-1 overflow-hidden">{children}</div>
      </div>
    </SidebarContext.Provider>
  );
}
