"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { useSidebar } from "../components/SidebarContext";
import ToolActions from "../components/ToolActions";
import SettingsModal from "../components/SettingsModal";

function AutoSend() {
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    const prompt = new URLSearchParams(window.location.search).get("prompt");
    if (!prompt) return;
    sent.current = true;
    window.history.replaceState({}, "", window.location.pathname);

    const fill = (retries = 20) => {
      const textarea = document.querySelector(".copilotKitInput textarea") as HTMLTextAreaElement | null;
      if (!textarea) {
        if (retries > 0) setTimeout(() => fill(retries - 1), 100);
        return;
      }
      // Set value through React's internal setter so onChange fires
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, prompt);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      // Give React a tick to update state, then submit
      setTimeout(() => {
        textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      }, 50);
    };

    setTimeout(fill, 300);
  }, []);

  return null;
}

export default function ThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  const { user, open: sidebarOpen, toggle: toggleSidebar } = useSidebar();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
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
    <CopilotKit runtimeUrl="/api/copilotkit" agent="mailing_net_agent" threadId={threadId}>
      <ToolActions />
      <AutoSend />
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

        <div className="flex-1 overflow-hidden">
          <CopilotChat
            className="h-full"
            labels={{ title: "MailNet Assistant" }}
          />
        </div>
      </div>
    </CopilotKit>
  );
}
