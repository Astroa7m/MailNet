"use client";
import { useEffect, useState, useRef } from "react";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { useSidebar } from "./components/SidebarContext";
import SettingsModal from "./components/SettingsModal";

export default function Home() {
  const [user, setUser] = useState<{ name: string; email: string; picture: string; providers: string[] } | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { open: sidebarOpen, toggle: toggleSidebar } = useSidebar();

  useEffect(() => {
    fetch("http://localhost:8002/me", { credentials: "include" })
      .then((r) => {
        if (r.status === 401) {
          window.location.href = "http://localhost:8002/";
          return null;
        }
        return r.json();
      })
      .then((data) => {
        if (data) setUser({ name: data.name || "", email: data.email || "", picture: data.picture || "", providers: data.providers || [] });
      })
      .catch(() => { window.location.href = "http://localhost:8002/login"; });
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

  return (
    <div className="flex flex-col h-screen bg-white dark:bg-gray-950">
      {/* Header */}
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
                  onClick={() => {
                    window.location.href = "http://localhost:8002/logout";
                  }}
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

      {/* Chat */}
      <div className="flex-1 overflow-hidden">
        <CopilotChat
          className="h-full"
          labels={{ title: "MailNet Assistant" }}
        />
      </div>
    </div>
  );
}
