"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { Markdown } from "@copilotkit/react-ui";
import { useSidebar } from "../components/SidebarContext";
import ToolActions from "../components/ToolActions";
import ToolCard from "../components/ToolCard";
import SettingsModal from "../components/SettingsModal";

function CustomAssistantMessage(props: any) {
  const content: string = props.message?.content ?? props.content ?? "";
  return (
    <div className="ck-markdown">
      <Markdown content={content} />
    </div>
  );
}

interface HistoryMessage {
  id: string;
  role: "user" | "assistant" | "tool_call" | "_suppress";
  content: string;
  args?: Record<string, unknown>;
  result?: string;
}

const HistoryContext = createContext<HistoryMessage[]>([]);

async function uploadAttachment(file: File): Promise<{ type: "url"; value: string; mimeType: string }> {
  if (file.size > 25 * 1024 * 1024) throw new Error(`"${file.name}" exceeds the 25 MB limit.`);
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("http://localhost:8002/upload-attachment", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  const data = await res.json();
  // Return a real URL so CopilotKit can show an image preview; backend strips it to just the file_id
  return { type: "url", value: `http://localhost:8002/attachment-raw/${data.file_id}`, mimeType: file.type || "application/octet-stream" };
}

function MessagesWithHistory({ messages, inProgress, RenderMessage, AssistantMessage, UserMessage, ImageRenderer, onRegenerate, onCopy }: any) {
  const history = useContext(HistoryContext);

  const historyIds = new Set(history.map((h) => h.id));
  const newMessages = messages.filter((m: any) => !historyIds.has(m.id));
  const renderableHistory = history.filter((h) => h.role !== "_suppress");
  const ckHistory = renderableHistory
    .filter((h) => h.role === "user" || h.role === "assistant")
    .map((h) => ({ id: h.id, role: h.role, content: h.content }));

  return (
    <div className="copilotKitMessages">
      <div className="copilotKitMessagesContainer">
        {renderableHistory.map((msg, i) => {
          if (msg.role === "tool_call") {
            return (
              <div key={msg.id} className="px-4 py-1">
                <ToolCard name={msg.content} status="complete" args={msg.args} result={msg.result} />
              </div>
            );
          }
          const ckMsg = { id: msg.id, role: msg.role, content: msg.content };
          return (
            <RenderMessage
              key={msg.id}
              message={ckMsg}
              messages={ckHistory}
              inProgress={false}
              index={i}
              isCurrentMessage={false}
              AssistantMessage={CustomAssistantMessage}
              UserMessage={UserMessage}
              ImageRenderer={ImageRenderer}
              onRegenerate={undefined}
              onCopy={onCopy}
            />
          );
        })}
        {newMessages.map((msg: any, i: number) => (
          <RenderMessage
            key={msg.id ?? i}
            message={msg}
            messages={messages}
            inProgress={inProgress}
            index={renderableHistory.length + i}
            isCurrentMessage={i === newMessages.length - 1}
            AssistantMessage={AssistantMessage}
            UserMessage={UserMessage}
            ImageRenderer={ImageRenderer}
            onRegenerate={onRegenerate}
            onCopy={onCopy}
          />
        ))}
      </div>
    </div>
  );
}

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
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, prompt);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
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
  const [history, setHistory] = useState<HistoryMessage[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setHistory([]);
    fetch(`http://localhost:8002/threads/${threadId}/messages`, { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then(setHistory)
      .catch(() => {});
  }, [threadId]);

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
    <HistoryContext.Provider value={history}>
    <CopilotKit runtimeUrl="/api/copilotkit" agent="mailing_net_agent" threadId={threadId}>
      <ToolActions />
      <AutoSend />
      <div className="flex flex-col h-screen bg-white dark:bg-[#0f0f0f]">
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
              <button
                onClick={() => setDropdownOpen((o) => !o)}
                className="rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-[#0f0f0f]"
              >
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
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                      Settings
                    </button>
                    <button
                      onClick={() => { window.location.href = "http://localhost:8002/logout"; }}
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

        <div className="flex-1 overflow-hidden">
          <CopilotChat
            className="h-full"
            labels={{ title: "MailNet Assistant" }}
            Messages={MessagesWithHistory}
            attachments={{
              enabled: true,
              onUpload: uploadAttachment,
            }}
          />
        </div>
      </div>
    </CopilotKit>
    </HistoryContext.Provider>
  );
}
