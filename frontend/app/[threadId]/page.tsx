"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { Markdown } from "@copilotkit/react-ui";
import { useSidebar } from "../components/SidebarContext";
import { API } from "../lib/api";
import ToolActions from "../components/ToolActions";
import ToolCallRenderer, { HIDDEN_TOOLS } from "../components/ToolCallRenderer";
import SettingsModal from "../components/SettingsModal";
import ApprovalInterrupt from "../components/ApprovalInterrupt";
import { InterruptProvider } from "../components/InterruptContext";
import BufferedInput from "../components/BufferedInput";

function CustomAssistantMessage(props: any) {
  const content: string = props.message?.content ?? props.content ?? "";
  return (
    <div className="ck-markdown">
      <Markdown content={content} />
    </div>
  );
}

interface AttachmentToken { id: string; filename: string; isImage: boolean }

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "avif", "heic"]);
function looksLikeImage(filename: string, mimeType?: string): boolean {
  if (mimeType?.startsWith("image/")) return true;
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return IMAGE_EXTS.has(ext);
}

function parseAttachments(raw: unknown): { clean: string; attachments: AttachmentToken[] } {
  if (typeof raw !== "string") return { clean: "", attachments: [] };
  const re = /\[Attached file ID:\s*([^\s\]()]+)(?:\s*\(([^)]*)\))?\]/g;
  const attachments: AttachmentToken[] = [];
  const clean = raw.replace(re, (_, id, filename) => {
    const name = filename ?? id;
    attachments.push({ id, filename: name, isImage: looksLikeImage(name) });
    return "";
  }).trim();
  return { clean, attachments };
}

// Handles both history string content and live CopilotKit multimodal arrays.
function parseContent(raw: unknown): { clean: string; attachments: AttachmentToken[] } {
  if (Array.isArray(raw)) {
    const textParts: string[] = [];
    const attachments: AttachmentToken[] = [];
    for (const part of raw) {
      const t = part?.type;
      if (t === "text") {
        textParts.push(part?.text ?? "");
      } else if (["image", "image_url", "file", "url", "document", "audio", "video", "binary"].includes(t)) {
        const url = part?.source?.value ?? part?.image_url?.url ?? part?.url ?? part?.value ?? "";
        if (typeof url === "string" && url) {
          const id = url.includes("/attachment-raw/") ? url.split("/attachment-raw/").pop()! : url;
          const filename = part?.metadata?.filename ?? "";
          const mime = part?.source?.mimeType ?? part?.mimeType ?? "";
          const name = filename || id;
          attachments.push({ id, filename: name, isImage: t === "image" || looksLikeImage(name, mime) });
        }
      }
    }
    return { clean: textParts.join(" ").trim(), attachments };
  }
  return parseAttachments(raw);
}

const USER_BUBBLE: React.CSSProperties = {
  background: "#3b82f6",
  color: "#ffffff",
  borderRadius: "16px 16px 4px 16px",
  fontSize: "0.875rem",
  padding: "10px 14px",
  maxWidth: "78%",
  boxShadow: "0 1px 3px rgba(59,130,246,0.3)",
  wordBreak: "break-word",
};

const THUMB: React.CSSProperties = {
  width: 96, height: 96, objectFit: "cover", borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.2)", flexShrink: 0, display: "block", cursor: "zoom-in",
};

function ImageLightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", zIndex: 9999,
        display: "flex", alignItems: "center", justifyContent: "center", cursor: "zoom-out" }}
    >
      <img
        src={src} alt={alt}
        onClick={e => e.stopPropagation()}
        style={{ maxWidth: "90vw", maxHeight: "90vh", objectFit: "contain", borderRadius: 10,
          boxShadow: "0 8px 40px rgba(0,0,0,0.6)" }}
      />
    </div>
  );
}

function PdfThumbnail({ src, filename, onClick }: { src: string; filename: string; onClick: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const pdfjs: any = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
        const doc = await pdfjs.getDocument({ url: src, withCredentials: true }).promise;
        if (cancelled) return;
        const page = await doc.getPage(1);
        const viewport = page.getViewport({ scale: 1 });
        const scale = 96 / viewport.width;
        const scaled = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = scaled.width;
        canvas.height = scaled.height;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        await page.render({ canvasContext: ctx, viewport: scaled, canvas }).promise;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [src]);

  if (failed) {
    return <FileChip src={src} filename={filename} />;
  }
  return (
    <canvas
      ref={canvasRef}
      title={filename}
      onClick={onClick}
      style={{ ...THUMB, background: "white" }}
    />
  );
}

function FileChip({ src, filename }: { src: string; filename: string }) {
  return (
    <a href={src} target="_blank" rel="noopener noreferrer" download={filename}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 10px", borderRadius: 8,
        background: "rgba(255,255,255,0.18)", fontSize: "0.75rem", color: "white", textDecoration: "none",
        border: "1px solid rgba(255,255,255,0.25)", maxWidth: 180, overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap" }}
      title={filename}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} style={{ flexShrink: 0 }}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8" />
      </svg>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{filename}</span>
    </a>
  );
}

function isPdf(filename: string): boolean {
  return filename.toLowerCase().endsWith(".pdf");
}

function AttachmentChip({ id, filename, isImage }: AttachmentToken) {
  const [imgFailed, setImgFailed] = useState(false);
  const [lightbox, setLightbox] = useState(false);
  const src = `${API}/attachment-raw/${id}`;
  const showImage = isImage && !imgFailed;
  const showPdf = !isImage && isPdf(filename);
  return (
    <>
      {lightbox && <ImageLightbox src={src} alt={filename} onClose={() => setLightbox(false)} />}
      {showImage ? (
        <img src={src} alt={filename} title={filename} style={THUMB}
          onError={() => setImgFailed(true)} onClick={() => setLightbox(true)} />
      ) : showPdf ? (
        <PdfThumbnail src={src} filename={filename} onClick={() => window.open(src, "_blank")} />
      ) : (
        <FileChip src={src} filename={filename} />
      )}
    </>
  );
}

function ConstrainedImageRenderer({ src, alt }: any) {
  const [lightbox, setLightbox] = useState(false);
  return (
    <>
      {lightbox && <ImageLightbox src={src} alt={alt ?? "attachment"} onClose={() => setLightbox(false)} />}
      <img src={src} alt={alt ?? "attachment"}
        style={{ ...THUMB, marginTop: 6 }} onClick={() => setLightbox(true)} />
    </>
  );
}

function CustomUserMessage(props: any) {
  const content = props.message?.content ?? props.content ?? "";
  const { clean, attachments } = parseContent(content);
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", width: "100%", padding: "2px 0" }}>
      <div style={USER_BUBBLE}>
        {clean && <span>{clean}</span>}
        {attachments.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: clean ? 8 : 0 }}>
            {attachments.map((att) => <AttachmentChip key={att.id} {...att} />)}
          </div>
        )}
      </div>
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
  const res = await fetch(`${API}/upload-attachment`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  const data = await res.json();
  // Return a real URL so CopilotKit can show an image preview; backend strips it to just the file_id
  return { type: "url", value: `${API}/attachment-raw/${data.file_id}`, mimeType: file.type || "application/octet-stream" };
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
            if (HIDDEN_TOOLS.has(msg.content)) return null;
            return (
              <div key={msg.id} className="px-4 py-1">
                <ToolCallRenderer name={msg.content} status="complete" args={msg.args} result={msg.result} />
              </div>
            );
          }
          if (msg.role === "user") {
            return <CustomUserMessage key={msg.id} message={{ content: msg.content }} />;
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
              UserMessage={CustomUserMessage}
              ImageRenderer={ConstrainedImageRenderer}
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
            UserMessage={CustomUserMessage}
            ImageRenderer={ConstrainedImageRenderer}
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
    fetch(`${API}/threads/${threadId}/messages`, { credentials: "include" })
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
    <InterruptProvider>
      <ToolActions />
      <ApprovalInterrupt threadId={threadId} />
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

        <div className="flex-1 overflow-hidden">
          <CopilotChat
            className="h-full"
            labels={{ title: "MailNet Assistant" }}
            Messages={MessagesWithHistory}
            Input={BufferedInput}
            attachments={{
              enabled: true,
              onUpload: uploadAttachment,
            }}
          />
        </div>
      </div>
    </InterruptProvider>
    </CopilotKit>
    </HistoryContext.Provider>
  );
}
