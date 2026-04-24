"use client";
import { useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSidebar } from "./components/SidebarContext";
import SettingsModal from "./components/SettingsModal";

const SUGGESTIONS = [
  { icon: "✉️", label: "Read my latest emails" },
  { icon: "✍️", label: "Draft a professional reply" },
  { icon: "🔍", label: "Search for an email" },
  { icon: "📅", label: "Schedule an email for tomorrow" },
];

export default function Home() {
  const { user, open: sidebarOpen, toggle: toggleSidebar } = useSidebar();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error") === "missing_scopes") {
      setConnectError("Mail access was not granted. Please allow all permissions when connecting an account.");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function startConversation(prompt?: string) {
    const id = crypto.randomUUID();
    router.push(prompt ? `/${id}?prompt=${encodeURIComponent(prompt)}` : `/${id}`);
  }

  const firstName = user?.name?.split(" ")[0] ?? "";

  return (
    <div className="flex flex-col h-screen bg-white dark:bg-gray-950">
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          {!sidebarOpen && (
            <button onClick={toggleSidebar} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500" title="Open sidebar">
              &#9776;
            </button>
          )}
          <span className="font-semibold text-lg">MailNet</span>
        </div>
        {user && (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen((o) => !o)}
              className="flex items-center gap-2 rounded-full focus:outline-none"
            >
              {user.picture ? (
                <img src={user.picture} alt={user.name} className="w-8 h-8 rounded-full" referrerPolicy="no-referrer" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-sm font-semibold">
                  {user.name.charAt(0).toUpperCase()}
                </div>
              )}
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 p-4">
                <div className="flex items-center gap-3 mb-3">
                  {user.picture ? (
                    <img src={user.picture} alt={user.name} className="w-10 h-10 rounded-full" referrerPolicy="no-referrer" />
                  ) : (
                    <div className="w-10 h-10 rounded-full bg-blue-500 flex items-center justify-center text-white font-semibold">
                      {user.name.charAt(0).toUpperCase()}
                    </div>
                  )}
                  <div>
                    <p className="font-medium text-sm">{user.name}</p>
                    <p className="text-xs text-gray-500 truncate">{user.email}</p>
                  </div>
                </div>
                <hr className="border-gray-200 dark:border-gray-700 mb-2" />
                <button
                  onClick={() => { setSettingsOpen(true); setDropdownOpen(false); }}
                  className="block w-full text-left text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white py-1 transition-colors"
                >
                  Settings
                </button>
                <button
                  onClick={() => { window.location.href = "http://localhost:8002/logout"; }}
                  className="block text-sm text-red-500 hover:text-red-600 py-1"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        )}
      </header>

      {settingsOpen && <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} providers={user?.providers ?? []} />}

      {connectError && (
        <div className="flex items-center gap-2 px-4 py-2 bg-red-50 dark:bg-red-950 border-b border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm">
          <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none">
            <path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          <span>{connectError}</span>
          <button onClick={() => setConnectError(null)} className="ml-auto text-red-400 hover:text-red-600 dark:hover:text-red-200">&#x2715;</button>
        </div>
      )}

      <main className="flex-1 flex flex-col items-center justify-center px-4 gap-10">
        <div className="text-center">
          <h1 className="text-3xl font-semibold text-gray-900 dark:text-white mb-2">
            {firstName ? `Welcome back, ${firstName}` : "Welcome to MailNet"}
          </h1>
          <p className="text-gray-500 dark:text-gray-400 text-base">
            Your AI email assistant. What would you like to do today?
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 w-full max-w-lg">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.label}
              onClick={() => startConversation(s.label)}
              className="flex items-center gap-3 px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 text-sm text-left transition-colors shadow-sm"
            >
              <span className="text-xl">{s.icon}</span>
              <span className="text-gray-700 dark:text-gray-300">{s.label}</span>
            </button>
          ))}
        </div>

        <button
          onClick={() => startConversation()}
          className="flex items-center gap-2 px-6 py-2.5 rounded-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors shadow"
        >
          <span className="text-lg leading-none">+</span> New conversation
        </button>
      </main>
    </div>
  );
}
