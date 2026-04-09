"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { CopilotKit } from "@copilotkit/react-core";
import { SidebarContext } from "./SidebarContext";

const API = "http://localhost:8002";

interface Thread {
  thread_id: string;
  name: string;
  created_at: number;
}

export default function ChatProvider({ children }: { children: React.ReactNode }) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string>(() => crypto.randomUUID());
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const initialized = useRef(false);

  const fetchThreads = useCallback(async (): Promise<Thread[]> => {
    const r = await fetch(`${API}/threads`, { credentials: "include" });
    if (!r.ok) return [];
    const data: Thread[] = await r.json();
    setThreads(data);
    return data;
  }, []);

  // initial load
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    fetchThreads().then((data) => {
      if (data.length > 0) setActiveThreadId(data[0].thread_id);
      setLoading(false);
    });
  }, []);

  // poll while active thread is pending (not yet saved to DB)
  useEffect(() => {
    if (!activeThreadId) return;
    const isPending = !threads.find((t) => t.thread_id === activeThreadId);
    if (!isPending) return;

    const interval = setInterval(async () => {
      const data = await fetchThreads();
      if (data.find((t) => t.thread_id === activeThreadId)) {
        clearInterval(interval);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [activeThreadId, threads]);

  function newConversation() {
    setActiveThreadId(crypto.randomUUID());
  }

  function switchThread(id: string) {
    setActiveThreadId(id);
  }

  async function deleteThread(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await fetch(`${API}/threads/${id}`, { method: "DELETE", credentials: "include" });
    const updated = await fetchThreads();
    if (id === activeThreadId) {
      setActiveThreadId(updated.length > 0 ? updated[0].thread_id : crypto.randomUUID());
    }
  }

  function formatDate(ts: number) {
    return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  if (loading) return null;

  return (
    <div className="flex h-full w-full">
      {/* Sidebar */}
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
            {threads.length >= 1 && (
              <button
                onClick={newConversation}
                className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              >
                <span className="text-lg leading-none">+</span> New conversation
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto py-2">
            {threads.map((t) => (
              <div
                key={t.thread_id}
                onClick={() => switchThread(t.thread_id)}
                className={`group flex items-center justify-between px-4 py-2 text-sm cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
                  t.thread_id === activeThreadId ? "bg-gray-200 dark:bg-gray-700 font-medium" : ""
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

      {/* Main */}
      <div className="flex-1 overflow-hidden">
        <SidebarContext.Provider value={{ open: sidebarOpen, toggle: () => setSidebarOpen((o) => !o) }}>
          <CopilotKit runtimeUrl="/api/copilotkit" agent="mailing_net_agent" threadId={activeThreadId}>
            {children}
          </CopilotKit>
        </SidebarContext.Provider>
      </div>
    </div>
  );
}
