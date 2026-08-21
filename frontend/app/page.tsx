"use client";
import { useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSidebar } from "./components/SidebarContext";
import SettingsModal from "./components/SettingsModal";
import { API } from "./lib/api";
import { BRIEFING_PROMPT, PENDING_PROMPT_KEY } from "./lib/briefing";

const SUGGESTIONS = [
  {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
    label: "Read my latest emails",
  },
  {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    ),
    label: "Draft a professional reply",
  },
  {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
    label: "Search for an email",
  },
  {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
      </svg>
    ),
    label: "Send an email",
  },
];

interface PendingAttachment { id: string; name: string; isImage: boolean }

const IMAGE_EXTS = new Set(["png","jpg","jpeg","gif","webp","bmp","svg","avif","heic"]);
function isImageFile(file: File): boolean {
  if (file.type.startsWith("image/")) return true;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return IMAGE_EXTS.has(ext);
}

export default function Home() {
  const { user, open: sidebarOpen, toggle: toggleSidebar } = useSidebar();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  async function uploadFiles(files: FileList | File[]) {
    setUploadError(null);
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        if (file.size > 20 * 1024 * 1024) {
          setUploadError(`"${file.name}" exceeds the 20 MB limit.`);
          continue;
        }
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${API}/upload-attachment`, {
          method: "POST",
          credentials: "include",
          body: form,
        });
        if (!res.ok) {
          setUploadError(`Upload failed for "${file.name}" (${res.status})`);
          continue;
        }
        const data = await res.json();
        setAttachments((prev) => [...prev, { id: data.file_id, name: file.name, isImage: isImageFile(file) }]);
      }
    } finally {
      setUploading(false);
    }
  }

  function removeAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error") === "missing_scopes") {
      setConnectError("Mail access was not granted. Please allow all permissions when connecting.");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setDropdownOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function startConversation(prompt?: string) {
    const id = crypto.randomUUID();
    const text = prompt?.trim() ?? "";
    const markers = attachments.map((a) => `[Attached file ID: ${a.id} (${a.name})]`).join(" ");
    const combined = [text, markers].filter(Boolean).join(" ");
    if (!combined && attachments.length === 0) {
      router.push(`/${id}`);
      return;
    }
    try {
    window.sessionStorage.setItem(PENDING_PROMPT_KEY, combined);
  } catch {
    // storage unavailable (private mode): fall through, the thread just opens empty
  }
  router.push(`/${id}`);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (inputValue.trim() || attachments.length > 0) startConversation(inputValue);
    }
  }

  const firstName = user?.name?.split(" ")[0] ?? "";

  return (
    <div className="flex flex-col h-screen bg-white dark:bg-[#0f0f0f] overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-gray-100 dark:border-[#1e1e1e] shrink-0">
        <div className="flex items-center gap-2.5">
          {!sidebarOpen && (
            <>
              <button
                onClick={toggleSidebar}
                className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-[#1e1e1e] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
              <div className="w-6 h-6 rounded-md bg-blue-600 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
            </>
          )}
        </div>
        {user && (
          <div className="relative" ref={dropdownRef}>
            <button onClick={() => setDropdownOpen((o) => !o)} className="rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-[#0f0f0f]">
              {user.picture ? (
                <img src={user.picture} alt={user.name} className="w-8 h-8 rounded-full" referrerPolicy="no-referrer" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-semibold">
                  {user.name.charAt(0).toUpperCase()}
                </div>
              )}
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-[#2a2a2a] rounded-xl shadow-lg z-50 overflow-hidden">
                <div className="flex items-center gap-3 p-4 border-b border-gray-100 dark:border-[#2a2a2a]">
                  {user.picture ? (
                    <img src={user.picture} alt={user.name} className="w-9 h-9 rounded-full" referrerPolicy="no-referrer" />
                  ) : (
                    <div className="w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center text-white font-semibold text-sm">
                      {user.name.charAt(0).toUpperCase()}
                    </div>
                  )}
                  <div className="min-w-0">
                    <p className="font-medium text-sm text-gray-900 dark:text-white truncate">{user.name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{user.email}</p>
                  </div>
                </div>
                <div className="p-1.5">
                  <button
                    onClick={() => { setSettingsOpen(true); setDropdownOpen(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#252525] transition-colors"
                  >
                    <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    Settings
                  </button>
                  <button
                    onClick={() => { window.location.href = `${API}/logout`; }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                    </svg>
                    Sign out
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </header>

      {settingsOpen && <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} providers={user?.providers ?? []} />}

      {connectError && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-red-50 dark:bg-red-950/30 border-b border-red-100 dark:border-red-900/50 text-red-600 dark:text-red-400 text-sm">
          <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <span>{connectError}</span>
          <button onClick={() => setConnectError(null)} className="ml-auto text-red-400 hover:text-red-600 dark:hover:text-red-300 transition-colors">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* Main */}
      <main className="flex-1 flex flex-col items-center justify-center px-4 pb-8 relative overflow-hidden">
        {/* Subtle grid background */}
        <div className="absolute inset-0 pointer-events-none" style={{
          backgroundImage: "radial-gradient(circle, rgba(59,130,246,0.06) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }} />

        <div className="relative w-full max-w-xl flex flex-col items-center gap-8">
          {/* Logo + greeting */}
          <div className="text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600 shadow-lg shadow-blue-500/25 mb-5">
              <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white mb-1.5">
              {firstName ? `Good to see you, ${firstName}` : "Welcome to MailNet"}
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Your AI email assistant. What would you like to do?
            </p>
            {/* Proactive briefing: the agent leads by triaging your inbox */}
            <button
              onClick={() => startConversation(BRIEFING_PROMPT)}
              className="mt-5 inline-flex items-center gap-2 px-4 py-2 rounded-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium shadow-lg shadow-blue-500/25 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Catch me up
            </button>
          </div>

          {/* Composer input */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files);
            }}
            className={`w-full bg-white dark:bg-[#1a1a1a] border rounded-2xl shadow-sm overflow-hidden transition-colors ${
              dragOver ? "border-blue-500 ring-2 ring-blue-500/20" : "border-gray-200 dark:border-[#2a2a2a]"
            }`}
          >
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 px-3 pt-3">
                {attachments.map((a) => (
                  <div key={a.id} className="flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-md bg-gray-100 dark:bg-[#252525] text-xs text-gray-700 dark:text-gray-300 max-w-[200px]">
                    <span title={a.name} className="truncate">{a.isImage ? "🖼" : "📎"} {a.name}</span>
                    <button
                      onClick={() => removeAttachment(a.id)}
                      className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-[#333] text-gray-500"
                      title="Remove"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
                {uploading && <span className="text-xs text-gray-500 self-center">Uploading…</span>}
              </div>
            )}
            <textarea
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={dragOver ? "Drop files to attach…" : "Ask anything about your emails…"}
              rows={3}
              className="w-full px-4 pt-4 pb-2 text-sm text-gray-800 dark:text-gray-200 bg-transparent resize-none outline-none placeholder-gray-400 dark:placeholder-gray-600 leading-relaxed"
            />
            <div className="flex items-center justify-between px-3 pb-3 pt-1">
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-400 dark:text-gray-600">Press Enter to send</span>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files?.length) uploadFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  title="Attach files"
                  className="p-1.5 rounded-md text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-950/30 transition-colors disabled:opacity-50"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.586-6.586a4 4 0 00-5.656-5.656L5.757 10.757a6 6 0 008.485 8.485L19 14" />
                  </svg>
                </button>
              </div>
              <button
                onClick={() => (inputValue.trim() || attachments.length > 0) && startConversation(inputValue)}
                disabled={!inputValue.trim() && attachments.length === 0}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
                Send
              </button>
            </div>
          </div>
          {uploadError && (
            <div className="w-full text-xs text-red-500 -mt-4">{uploadError}</div>
          )}

          {/* Suggestion chips */}
          <div className="grid grid-cols-2 gap-2 w-full">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                onClick={() => startConversation(s.label)}
                className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl border border-gray-200 dark:border-[#252525] bg-white dark:bg-[#161616] hover:bg-gray-50 dark:hover:bg-[#1e1e1e] hover:border-blue-300 dark:hover:border-blue-800 text-sm text-left transition-all group"
              >
                <span className="text-gray-400 dark:text-gray-500 group-hover:text-blue-500 transition-colors">{s.icon}</span>
                <span className="text-gray-600 dark:text-gray-400 group-hover:text-gray-900 dark:group-hover:text-gray-200 transition-colors leading-snug">{s.label}</span>
              </button>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
