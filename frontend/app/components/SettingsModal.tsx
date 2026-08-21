"use client";
import { useEffect, useState, useRef } from "react";

import { API } from "../lib/api";

interface Preferences {
  language: string;
  tone: string;
  writing_style: string;
  character_limit: number;
  auto_adjust_tone: boolean;
  sender_name: string;
  organization_name: string;
  preferred_greeting: string;
  include_signature: boolean;
  signature: string;
  default_provider: string;
  include_thread_context: boolean;
  auto_approve_tools: string[];
  memory_enabled: boolean;
}

const DEFAULTS: Preferences = {
  language: "en",
  tone: "formal",
  writing_style: "clear_and_concise",
  character_limit: 1000,
  auto_adjust_tone: true,
  sender_name: "",
  organization_name: "",
  preferred_greeting: "Dear {{recipient_name}},",
  include_signature: true,
  signature: "Best regards,\n{{sender_name}}",
  default_provider: "google",
  include_thread_context: true,
  auto_approve_tools: [],
  memory_enabled: true,
};

// Sensitive actions that prompt for confirmation, shown in the Approvals tab.
const SENSITIVE_ACTIONS = [
  { id: "send_email", label: "Send email" },
  { id: "reply_to_email", label: "Reply to email" },
  { id: "send_draft", label: "Send draft" },
  { id: "delete_email", label: "Delete email" },
];

const DEFINED_OPTIONS: Record<string, string[]> = {
  language: ["en", "ar", "fr", "es", "de", "it", "pt"],
  tone: ["formal", "casual", "friendly", "professional", "assertive", "empathetic"],
  writing_style: ["clear_and_concise", "detailed", "bullet_points", "narrative"],
};

const FIELD_INFO: Record<string, string> = {
  language: 'The language the AI uses when composing emails. Example: select "French" for emails sent to French-speaking contacts.',
  tone: 'Overall tone of composed emails. Example: "Formal" for business partners, "Friendly" for teammates, or type a custom tone like "Diplomatic".',
  writing_style: '"Clear & Concise" = short and direct. "Bullet Points" = structured lists. "Detailed" = thorough explanations. Or type your own.',
  character_limit: "Maximum length of composed emails. ~150 words ≈ 1000 characters. Keeps the AI's responses focused and readable.",
  auto_adjust_tone: "Allows the AI to slightly adapt the tone based on context. E.g., a casual incoming email may get a slightly less formal reply.",
  sender_name: 'Your name used in signatures and greetings. Use {{sender_name}} in your signature template to insert it automatically.',
  organization_name: "Your company or organization name. Referenced in email content when relevant.",
  preferred_greeting: 'How emails begin. Use {{recipient_name}} as a placeholder. Example: "Dear {{recipient_name}},"',
  include_signature: "Automatically appends your signature at the end of every composed email.",
  signature: 'Your closing signature. Use {{sender_name}} and {{organization_name}} as placeholders.\nExample: "Best regards,\\n{{sender_name}}\\n{{organization_name}}"',
  default_provider: "Which email account the AI uses by default when no provider is specified in your request.",
  include_thread_context: "Includes previous emails in the thread when composing replies so the AI has full conversation context.",
  chat_provider: "Which AI model powers your conversation. The app provides a shared key by default; add your own to skip usage limits.",
  chat_key: "Your API key for the selected chat provider. Stored encrypted. Leave blank to keep using the app's shared key.",
  chat_model: "Optional. Override the default model name for the selected provider (e.g. a specific GPT or Claude version).",
  embed_provider: "Powers personalization and smarter replies. Uses the app's shared key by default; add your own to avoid limits.",
  embed_key: "Your API key for smart features. Stored encrypted. Leave blank to keep using the app's shared key.",
};

// ── Sub-components ─────────────────────────────────────────────────────────

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
        disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"
      } ${checked && !disabled ? "bg-blue-500" : "bg-gray-200 dark:bg-gray-600"}`}
    >
      <span
        className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 ${
          checked ? "translate-x-4" : "translate-x-0"
        }`}
      />
    </button>
  );
}

function InfoIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0a8 8 0 100 16A8 8 0 008 0zm.75 11.5h-1.5v-4.5h1.5v4.5zm0-6h-1.5v-1.5h1.5v1.5z" />
    </svg>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 shrink-0">{title}</span>
      <div className="flex-1 h-px bg-gray-100 dark:bg-gray-800" />
    </div>
  );
}

function KeyBadge({ yours }: { yours: boolean }) {
  return (
    <span
      className={`shrink-0 text-[10px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${
        yours
          ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
          : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400"
      }`}
    >
      {yours ? "Using your key" : "Shared key"}
    </span>
  );
}

function CheckLine({ state, okText }: { state: { loading: boolean; error: string | null }; okText?: string }) {
  if (state.loading) return <p className="text-xs text-gray-400 dark:text-gray-500">Verifying…</p>;
  if (state.error) return <p className="text-xs text-red-500 leading-relaxed">{state.error}</p>;
  if (okText) return <p className="text-xs text-green-600 dark:text-green-400">✓ {okText}</p>;
  return null;
}

function Field({
  label,
  fieldKey,
  children,
}: {
  label: string;
  fieldKey: string;
  children: React.ReactNode;
}) {
  const [showInfo, setShowInfo] = useState(false);
  const info = FIELD_INFO[fieldKey];

  return (
    <div className="py-1.5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-1 shrink-0 w-40">
          <span className="text-sm text-gray-600 dark:text-gray-300">{label}</span>
          {info && (
            <button
              type="button"
              onClick={() => setShowInfo((v) => !v)}
              className={`transition-colors ${showInfo ? "text-blue-500" : "text-gray-300 dark:text-gray-600 hover:text-blue-400"}`}
              aria-label={`Info about ${label}`}
            >
              <InfoIcon />
            </button>
          )}
        </div>
        <div className="flex-1">{children}</div>
      </div>
      {info && showInfo && (
        <p className="mt-1.5 ml-[10.5rem] text-xs text-gray-400 dark:text-gray-500 leading-relaxed whitespace-pre-line">
          {info}
        </p>
      )}
    </div>
  );
}

const selectClass =
  "w-full text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent";

const inputClass =
  "w-full text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder-gray-300 dark:placeholder-gray-600";

const TABS = [
  { id: "general", label: "General" },
  { id: "ai", label: "AI Models" },
  { id: "writing", label: "Writing" },
  { id: "identity", label: "Identity" },
  { id: "account", label: "Account" },
  { id: "approvals", label: "Approvals" },
  { id: "memories", label: "Memories" },
  { id: "scheduled", label: "Scheduled" },
  { id: "contribute", label: "Contribute" },
];

interface MemoryItem { id: string; memory: string; created_at?: string; }

interface ScheduledJob {
  job_id: string;
  to: string;
  subject: string;
  type: "one_time" | "recurring";
  trigger: string;
  next_run_time: string | null;
}

// ── SelectOrOther ───────────────────────────────────────────────────────────

function SelectOrOther({
  fieldKey,
  value,
  onChange,
  options,
}: {
  fieldKey: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const isCustom = !options.find((o) => o.value === value);
  const [showCustom, setShowCustom] = useState(isCustom);

  useEffect(() => {
    setShowCustom(!options.find((o) => o.value === value));
  }, [value]);

  return (
    <div className="space-y-1.5">
      <select
        className={selectClass}
        value={showCustom ? "__other__" : value}
        onChange={(e) => {
          if (e.target.value === "__other__") {
            setShowCustom(true);
            onChange("");
          } else {
            setShowCustom(false);
            onChange(e.target.value);
          }
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
        <option value="__other__">Other…</option>
      </select>
      {showCustom && (
        <input
          type="text"
          className={inputClass}
          placeholder={`Custom ${fieldKey.replace(/_/g, " ")}…`}
          value={isCustom ? value : ""}
          autoFocus
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

export default function SettingsModal({
  open,
  onClose,
  providers: initialProviders = [],
}: {
  open: boolean;
  onClose: () => void;
  providers?: string[];
}) {
  const [prefs, setPrefs] = useState<Preferences>(DEFAULTS);
  const [original, setOriginal] = useState<Preferences>(DEFAULTS);
  const [providers, setProviders] = useState<string[]>(initialProviders);
  // Live per-provider token health: "connected" | "expired" (undefined = unknown).
  const [connStatus, setConnStatus] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [isDark, setIsDark] = useState(false);
  const backdropRef = useRef<HTMLDivElement>(null);

  // AI Models (bring-your-own-key). Keys are write-only from the client: the
  // server never returns them, only whether one is saved (has_key).
  const [chatProvider, setChatProvider] = useState("groq");
  const [chatModel, setChatModel] = useState("");
  const [chatHasKey, setChatHasKey] = useState(false);
  const [chatKeyInput, setChatKeyInput] = useState("");
  const [embedProvider, setEmbedProvider] = useState("google");
  const [embedHasKey, setEmbedHasKey] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [embedKeyInput, setEmbedKeyInput] = useState("");
  const [aiOriginal, setAiOriginal] = useState({ chatProvider: "groq", chatModel: "", embedProvider: "google" });
  // Live model list + per-slot validation feedback.
  const [chatModels, setChatModels] = useState<string[]>([]);
  const [chatCheck, setChatCheck] = useState<{ loading: boolean; error: string | null }>({ loading: false, error: null });
  const [embedCheck, setEmbedCheck] = useState<{ loading: boolean; error: string | null }>({ loading: false, error: null });
  const [activeTab, setActiveTab] = useState("general");
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState("");
  const [memLoading, setMemLoading] = useState(false);

  const hasGoogle = providers.includes("google");
  const hasMicrosoft = providers.includes("microsoft");
  const hasMultiple = hasGoogle && hasMicrosoft;
  const missingProvider = hasGoogle ? "microsoft" : "google";

  useEffect(() => {
    if (!open) return;
    setIsDark(document.documentElement.classList.contains("dark"));
    setStatus("idle");
    setActiveTab("general");
    setLoading(true);
    Promise.all([
      fetch(`${API}/preferences`, { credentials: "include", cache: "no-store" }).then((r) => r.json()),
      fetch(`${API}/me`, { credentials: "include", cache: "no-store" }).then((r) => r.json()),
      fetch(`${API}/api-keys`, { credentials: "include", cache: "no-store" }).then((r) => r.json()),
    ])
      .then(([prefsData, meData, keysData]) => {
        const merged = { ...DEFAULTS, ...prefsData };
        if (merged.default_provider) merged.default_provider = merged.default_provider.toLowerCase();
        setPrefs(merged);
        setOriginal(merged);
        setProviders(meData.providers ?? []);
        setIsAdmin(!!meData.is_admin);

        // Probe real token health in the background (it does live refreshes, so
        // it is slower than /me). Badges update from "Connected" assumption to
        // the true state once this resolves.
        fetch(`${API}/connection-status`, { credentials: "include", cache: "no-store" })
          .then((r) => (r.ok ? r.json() : {}))
          .then((cs) => setConnStatus(cs || {}))
          .catch(() => {});

        const cp = keysData?.chat?.provider || "groq";
        const cm = keysData?.chat?.model || "";
        const ep = keysData?.embeddings?.provider || "google";
        setChatProvider(cp);
        setChatModel(cm);
        setChatHasKey(!!keysData?.chat?.has_key);
        setChatKeyInput("");
        setEmbedProvider(ep);
        setEmbedHasKey(!!keysData?.embeddings?.has_key);
        setEmbedKeyInput("");
        setAiOriginal({ chatProvider: cp, chatModel: cm, embedProvider: ep });
        setChatModels([]);
        setChatCheck({ loading: false, error: null });
        setEmbedCheck({ loading: false, error: null });
        // Preload the model list using the saved or shared key so the dropdown
        // is populated as soon as the section opens.
        loadChatModels(cp, undefined, cm);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open]);

  // Validate a chat key and fetch its model list. Pass a key to test a freshly
  // typed one; omit it to use the saved/shared key. preferModel keeps the user's
  // current selection if it is still offered.
  async function loadChatModels(provider: string, key?: string, preferModel?: string) {
    setChatCheck({ loading: true, error: null });
    try {
      const r = await fetch(`${API}/provider-models`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot: "chat", provider, ...(key ? { key } : {}) }),
      });
      const d = await r.json();
      if (d.ok) {
        const models: string[] = d.models || [];
        setChatModels(models);
        setChatModel((cur) => {
          const wanted = preferModel || cur;
          return wanted && models.includes(wanted) ? wanted : models[0] || "";
        });
        setChatCheck({ loading: false, error: null });
      } else {
        setChatModels([]);
        setChatCheck({ loading: false, error: d.message || "Couldn't verify this key." });
      }
    } catch {
      setChatModels([]);
      setChatCheck({ loading: false, error: "Network error verifying the key." });
    }
  }

  async function verifyEmbedKey(provider: string, key?: string) {
    setEmbedCheck({ loading: true, error: null });
    try {
      const r = await fetch(`${API}/provider-models`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot: "embeddings", provider, ...(key ? { key } : {}) }),
      });
      const d = await r.json();
      setEmbedCheck({ loading: false, error: d.ok ? null : d.message || "Couldn't verify this key." });
    } catch {
      setEmbedCheck({ loading: false, error: "Network error verifying the key." });
    }
  }

  function toggleTheme(dark: boolean) {
    setIsDark(dark);
    if (dark) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("mailnet-theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("mailnet-theme", "light");
    }
  }

  async function handleSave() {
    const changes: Partial<Preferences> = {};
    for (const key of Object.keys(prefs) as (keyof Preferences)[]) {
      if (prefs[key] !== original[key]) (changes as any)[key] = prefs[key];
    }
    const aiChanged =
      chatProvider !== aiOriginal.chatProvider ||
      chatModel !== aiOriginal.chatModel ||
      embedProvider !== aiOriginal.embedProvider ||
      !!chatKeyInput ||
      !!embedKeyInput;

    if (Object.keys(changes).length === 0 && !aiChanged) { onClose(); return; }

    setSaving(true);
    setStatus("idle");
    try {
      if (Object.keys(changes).length > 0) {
        const r = await fetch(`${API}/preferences`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(changes),
        });
        if (!r.ok) throw new Error();
      }
      if (aiChanged) {
        const body = {
          chat: { provider: chatProvider, model: chatModel || null, ...(chatKeyInput ? { key: chatKeyInput } : {}) },
          embeddings: { provider: embedProvider, ...(embedKeyInput ? { key: embedKeyInput } : {}) },
        };
        const r2 = await fetch(`${API}/api-keys`, {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r2.ok) {
          // 400 carries which slot failed validation; keep the modal open and
          // show the error inline so the user can fix the key.
          let detail: any = null;
          try { detail = (await r2.json()).detail; } catch { /* ignore */ }
          const msg = detail?.message || "That key didn't work. Please check it.";
          if (detail?.slot === "embeddings") setEmbedCheck({ loading: false, error: msg });
          else setChatCheck({ loading: false, error: msg });
          setStatus("error");
          setSaving(false);
          return;
        }
        if (chatKeyInput) setChatHasKey(true);
        if (embedKeyInput) setEmbedHasKey(true);
        setChatKeyInput("");
        setEmbedKeyInput("");
        setChatCheck({ loading: false, error: null });
        setEmbedCheck({ loading: false, error: null });
        setAiOriginal({ chatProvider, chatModel, embedProvider });
      }
      setOriginal(prefs);
      setStatus("success");
      setTimeout(onClose, 800);
    } catch {
      setStatus("error");
    } finally {
      setSaving(false);
    }
  }

  async function removeKey(slot: "chat" | "embeddings") {
    try {
      await fetch(`${API}/api-keys/${slot}`, { method: "DELETE", credentials: "include" });
    } catch { /* best effort */ }
    if (slot === "chat") {
      setChatHasKey(false);
      setChatProvider("groq");
      setChatModel("");
      setChatKeyInput("");
      setChatCheck({ loading: false, error: null });
      setAiOriginal((a) => ({ ...a, chatProvider: "groq", chatModel: "" }));
      loadChatModels("groq");
    } else {
      setEmbedHasKey(false);
      setEmbedProvider("google");
      setEmbedKeyInput("");
      setEmbedCheck({ loading: false, error: null });
      setAiOriginal((a) => ({ ...a, embedProvider: "google" }));
    }
  }

  function set<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setPrefs((p) => ({ ...p, [key]: value }));
  }

  function toggleAutoApprove(toolId: string, on: boolean) {
    setPrefs((p) => {
      const cur = new Set(p.auto_approve_tools || []);
      if (on) cur.add(toolId); else cur.delete(toolId);
      return { ...p, auto_approve_tools: Array.from(cur) };
    });
  }

  // Load memories the first time the Memories tab is opened.
  useEffect(() => {
    if (open && activeTab === "memories") loadMemories();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeTab]);

  async function loadMemories() {
    setMemLoading(true);
    try {
      const r = await fetch(`${API}/memories`, { credentials: "include", cache: "no-store" });
      const d = await r.json();
      setMemories(d.memories || []);
    } catch {
      setMemories([]);
    } finally {
      setMemLoading(false);
    }
  }

  async function deleteMemory(id: string) {
    setMemories((m) => m.filter((x) => x.id !== id));
    try { await fetch(`${API}/memories/${id}`, { method: "DELETE", credentials: "include" }); } catch { /* best effort */ }
  }

  // Load scheduled emails the first time the Scheduled tab is opened.
  useEffect(() => {
    if (open && activeTab === "scheduled") loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeTab]);

  async function loadJobs() {
    setJobsLoading(true);
    setJobsError("");
    try {
      const r = await fetch(`${API}/schedules`, { credentials: "include", cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      setJobs(d.jobs || []);
    } catch {
      setJobs([]);
      setJobsError("Couldn't load your scheduled emails. Try again in a moment.");
    } finally {
      setJobsLoading(false);
    }
  }

  async function cancelJob(jobId: string) {
    const previous = jobs;
    setJobs((j) => j.filter((x) => x.job_id !== jobId));
    try {
      const r = await fetch(`${API}/schedules/${encodeURIComponent(jobId)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!r.ok) throw new Error(String(r.status));
    } catch {
      // Put the row back rather than implying a send was cancelled when it was not.
      setJobs(previous);
      setJobsError("Couldn't cancel that email. It is still scheduled.");
    }
  }

  function formatRun(iso: string | null) {
    if (!iso) return "Not scheduled";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      weekday: "short", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  }

  async function clearAllMemories() {
    if (!window.confirm("Delete all saved memories? This can't be undone.")) return;
    setMemories([]);
    try { await fetch(`${API}/memories`, { method: "DELETE", credentials: "include" }); } catch { /* best effort */ }
  }

  if (!open) return null;

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
    >
      <div className="relative w-full max-w-2xl mx-4 bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-800 shrink-0">
          <h2 className="font-semibold text-gray-900 dark:text-white">Email Settings</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors p-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 min-h-0">
          {/* Tab rail */}
          <nav className="w-32 shrink-0 border-r border-gray-100 dark:border-gray-800 p-2 space-y-0.5 overflow-y-auto">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`w-full text-left text-sm px-3 py-1.5 rounded-md transition-colors ${
                  activeTab === t.id
                    ? "bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 font-medium"
                    : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <div className="space-y-6">

              {/* Appearance */}
              <div className={activeTab === "general" ? "" : "hidden"}>
                <SectionHeader title="Appearance" />
                <Field label="Dark Mode" fieldKey="theme">
                  <Toggle checked={isDark} onChange={toggleTheme} />
                </Field>
              </div>

              {/* AI Models */}
              <div className={activeTab === "ai" ? "" : "hidden"}>
                <SectionHeader title="AI Models" />

                {/* Transparency notice */}
                <div className="mb-3 rounded-lg border border-blue-100 dark:border-blue-900/40 bg-blue-50/60 dark:bg-blue-900/20 px-3 py-2.5 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
                  By default MailNet runs on a <span className="font-medium">shared developer key</span> that's free but rate-limited. Add your own key below to remove limits.
                  Your key is <span className="font-medium">encrypted before it's stored</span>, so it's never kept in plain text and stays protected if the database is exposed.
                  Don't take our word for it: read the exact{" "}
                  <a href="https://github.com/Astroa7m/MailNet/blob/1d56b0af68758ebf8100896e5337d78a8245989d/app/common.py#L176-L184" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">encryption code</a>{" "}
                  and{" "}
                  <a href="https://github.com/Astroa7m/MailNet/blob/1d56b0af68758ebf8100896e5337d78a8245989d/app/api.py#L995-L1025" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">where your key is stored</a>{" "}
                  in the open source.
                </div>

                <div>
                  <Field label="Chat" fieldKey="chat_provider">
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <select
                          className={selectClass}
                          value={chatProvider}
                          onChange={(e) => { const v = e.target.value; setChatProvider(v); setChatModel(""); setChatModels([]); loadChatModels(v); }}
                        >
                          <option value="groq">Groq</option>
                          <option value="google_genai">Google (Gemini)</option>
                          <option value="openai">OpenAI</option>
                          <option value="anthropic">Anthropic</option>
                          <option value="ollama_cloud">Ollama Cloud</option>
                        </select>
                        <KeyBadge yours={chatHasKey} />
                      </div>
                    </div>
                  </Field>
                  <Field label="Chat API Key" fieldKey="chat_key">
                    <div className="space-y-1.5">
                      <input
                        type="password"
                        autoComplete="off"
                        className={inputClass}
                        placeholder={chatHasKey ? "•••••••• saved, type to replace" : "Paste your API key (optional)"}
                        value={chatKeyInput}
                        onChange={(e) => setChatKeyInput(e.target.value)}
                        onBlur={(e) => { const k = e.target.value.trim(); if (k) loadChatModels(chatProvider, k); }}
                      />
                      <CheckLine state={chatCheck} okText={chatModels.length > 0 ? `${chatModels.length} models available` : ""} />
                      {chatHasKey && (
                        <button type="button" onClick={() => removeKey("chat")} className="text-xs text-red-500 hover:underline">
                          Remove saved key
                        </button>
                      )}
                    </div>
                  </Field>
                  <Field label="Chat Model" fieldKey="chat_model">
                    <select
                      className={selectClass}
                      value={chatModel}
                      onChange={(e) => setChatModel(e.target.value)}
                      disabled={chatModels.length === 0}
                    >
                      {chatModels.length === 0
                        ? <option value="">{chatCheck.loading ? "Loading models…" : "Add or verify a key to load models"}</option>
                        : chatModels.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </Field>
                  <p className="ml-[10.5rem] -mt-1 mb-1 text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                    Pick a model that supports tool calling (e.g. GPT, Claude, Gemini, Llama 3.3, gpt-oss). Some models like Gemma can't reliably use tools, so actions and memory may not work.
                  </p>
                  {!["groq", "google_genai"].includes(chatProvider) && !chatHasKey && !chatKeyInput.trim() && (
                    <p className="ml-[10.5rem] -mt-1 mb-1 text-xs text-amber-600 dark:text-amber-500 leading-relaxed">
                      No key added for this provider. We only host shared keys for Groq and Google, so chat will fall back to the shared Groq model until you add your own {chatProvider === "openai" ? "OpenAI" : chatProvider === "anthropic" ? "Anthropic" : "Ollama Cloud"} key above.
                    </p>
                  )}

                  <Field label="Smart Features" fieldKey="embed_provider">
                    <div className="flex items-center gap-2">
                      <select
                        className={selectClass}
                        value={embedProvider}
                        onChange={(e) => { const v = e.target.value; setEmbedProvider(v); setEmbedCheck({ loading: false, error: null }); verifyEmbedKey(v); }}
                      >
                        <option value="google">Google (Gemini)</option>
                        <option value="openai">OpenAI</option>
                        <option value="ollama">Ollama</option>
                      </select>
                      <KeyBadge yours={embedHasKey} />
                    </div>
                  </Field>
                  <p className="ml-[10.5rem] -mt-1 mb-1 text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                    Powers personalization by remembering your preferences and recurring contacts to tailor replies.
                  </p>
                  <Field label="Smart Features Key" fieldKey="embed_key">
                    <div className="space-y-1.5">
                      <input
                        type="password"
                        autoComplete="off"
                        className={inputClass}
                        placeholder={embedHasKey ? "•••••••• saved, type to replace" : "Paste your API key (optional)"}
                        value={embedKeyInput}
                        onChange={(e) => setEmbedKeyInput(e.target.value)}
                        onBlur={(e) => { const k = e.target.value.trim(); if (k) verifyEmbedKey(embedProvider, k); }}
                      />
                      <CheckLine state={embedCheck} okText="Key verified" />
                      {embedHasKey && (
                        <button type="button" onClick={() => removeKey("embeddings")} className="text-xs text-red-500 hover:underline">
                          Remove saved key
                        </button>
                      )}
                    </div>
                  </Field>
                </div>
              </div>

              {/* Writing */}
              <div className={activeTab === "writing" ? "" : "hidden"}>
                <SectionHeader title="Writing" />
                <div>
                  <Field label="Language" fieldKey="language">
                    <SelectOrOther
                      fieldKey="language"
                      value={prefs.language}
                      onChange={(v) => set("language", v)}
                      options={[
                        { value: "en", label: "English" },
                        { value: "ar", label: "Arabic" },
                        { value: "fr", label: "French" },
                        { value: "es", label: "Spanish" },
                        { value: "de", label: "German" },
                        { value: "it", label: "Italian" },
                        { value: "pt", label: "Portuguese" },
                      ]}
                    />
                  </Field>
                  <Field label="Tone" fieldKey="tone">
                    <SelectOrOther
                      fieldKey="tone"
                      value={prefs.tone}
                      onChange={(v) => set("tone", v)}
                      options={[
                        { value: "formal", label: "Formal" },
                        { value: "casual", label: "Casual" },
                        { value: "friendly", label: "Friendly" },
                        { value: "professional", label: "Professional" },
                        { value: "assertive", label: "Assertive" },
                        { value: "empathetic", label: "Empathetic" },
                      ]}
                    />
                  </Field>
                  <Field label="Writing Style" fieldKey="writing_style">
                    <SelectOrOther
                      fieldKey="writing_style"
                      value={prefs.writing_style}
                      onChange={(v) => set("writing_style", v)}
                      options={[
                        { value: "clear_and_concise", label: "Clear & Concise" },
                        { value: "detailed", label: "Detailed" },
                        { value: "bullet_points", label: "Bullet Points" },
                        { value: "narrative", label: "Narrative" },
                      ]}
                    />
                  </Field>
                  <Field label="Character Limit" fieldKey="character_limit">
                    <input
                      type="number"
                      min={100}
                      max={5000}
                      className={inputClass}
                      value={prefs.character_limit}
                      onChange={(e) => set("character_limit", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Auto-adjust Tone" fieldKey="auto_adjust_tone">
                    <Toggle checked={prefs.auto_adjust_tone} onChange={(v) => set("auto_adjust_tone", v)} />
                  </Field>
                </div>
              </div>

              {/* Identity */}
              <div className={activeTab === "identity" ? "" : "hidden"}>
                <SectionHeader title="Identity" />
                <div>
                  <Field label="Sender Name" fieldKey="sender_name">
                    <input
                      type="text"
                      className={inputClass}
                      placeholder="Your name"
                      value={prefs.sender_name}
                      onChange={(e) => set("sender_name", e.target.value)}
                    />
                  </Field>
                  <Field label="Organization" fieldKey="organization_name">
                    <input
                      type="text"
                      className={inputClass}
                      placeholder="Your organization"
                      value={prefs.organization_name}
                      onChange={(e) => set("organization_name", e.target.value)}
                    />
                  </Field>
                  <Field label="Greeting" fieldKey="preferred_greeting">
                    <>
                      <input
                        type="text"
                        list="greeting-suggestions"
                        className={inputClass}
                        value={prefs.preferred_greeting}
                        onChange={(e) => set("preferred_greeting", e.target.value)}
                      />
                      <datalist id="greeting-suggestions">
                        <option value="Dear {{recipient_name}}," />
                        <option value="Hi {{recipient_name}}," />
                        <option value="Hello {{recipient_name}}," />
                        <option value="To Whom It May Concern," />
                      </datalist>
                    </>
                  </Field>
                  <Field label="Include Signature" fieldKey="include_signature">
                    <Toggle checked={prefs.include_signature} onChange={(v) => set("include_signature", v)} />
                  </Field>
                  <Field label="Signature" fieldKey="signature">
                    <textarea
                      rows={4}
                      className={`${inputClass} resize-none transition-opacity ${!prefs.include_signature ? "opacity-40 cursor-not-allowed" : ""}`}
                      disabled={!prefs.include_signature}
                      value={prefs.signature}
                      onChange={(e) => set("signature", e.target.value)}
                    />
                  </Field>
                </div>
              </div>

              {/* Account */}
              <div className={activeTab === "account" ? "" : "hidden"}>
                <SectionHeader title="Account" />
                <div>
                  <Field label="Connected Accounts" fieldKey="connected_accounts">
                    <div className="space-y-2">
                      {(["google", "microsoft"] as const).map((p) => {
                        const linked = providers.includes(p);
                        // Real health once probed: "connected" | "expired".
                        // Before the probe resolves, assume a linked account is ok.
                        const health = connStatus[p] ?? (linked ? "connected" : "not_connected");
                        const label = p === "google" ? "Google (Gmail)" : "Microsoft (Outlook)";
                        const badge =
                          health === "connected"
                            ? { text: "Connected", cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400" }
                            : health === "expired"
                              ? { text: "Reconnect needed", cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" }
                              : { text: "Not connected", cls: "bg-gray-100 text-gray-500 dark:bg-[#2a2a2a] dark:text-gray-400" };
                        return (
                          <div
                            key={p}
                            className="flex items-center justify-between px-3 py-2 rounded-lg border border-gray-200 dark:border-[#2a2a2a]"
                          >
                            <span className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                              {label}
                              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${badge.cls}`}>
                                {badge.text}
                              </span>
                            </span>
                            <a
                              href={`${API}/connect/${p}`}
                              className="text-xs font-medium text-blue-500 hover:underline"
                            >
                              {linked ? "Reconnect" : "Connect"}
                            </a>
                          </div>
                        );
                      })}
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-1.5 leading-relaxed">
                      Reconnect if reading or sending stops working (an account's sign-in can expire). This re-authorizes that mailbox without signing you out.
                    </p>
                  </Field>
                  <Field label="Default Provider" fieldKey="default_provider">
                    {hasMultiple ? (
                      <select
                        className={selectClass}
                        value={prefs.default_provider}
                        onChange={(e) => set("default_provider", e.target.value)}
                      >
                        {hasGoogle && <option value="google">Google</option>}
                        {hasMicrosoft && <option value="microsoft">Microsoft</option>}
                      </select>
                    ) : (
                      <div className="space-y-1.5">
                        <select className={`${selectClass} opacity-50 cursor-not-allowed`} disabled value={prefs.default_provider}>
                          {hasGoogle && <option value="google">Google</option>}
                          {hasMicrosoft && <option value="microsoft">Microsoft</option>}
                        </select>
                        <p className="text-xs text-gray-400 dark:text-gray-500">
                          Only one provider connected.{" "}
                          <a
                            href={`${API}/connect/${missingProvider}`}
                            className="text-blue-500 hover:underline"
                          >
                            Connect {missingProvider === "google" ? "Google" : "Microsoft"}
                          </a>{" "}
                          to switch between providers.
                        </p>
                      </div>
                    )}
                  </Field>
                </div>
              </div>

              {/* Approvals */}
              <div className={activeTab === "approvals" ? "" : "hidden"}>
                <SectionHeader title="Approvals" />
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-3 leading-relaxed">
                  Sensitive actions ask for your confirmation before running. Turn on auto-approve for the ones you trust to skip the prompt. You can change this anytime, and "Don't ask again" on a confirmation does the same thing.
                </p>
                <div className="flex items-center justify-end gap-3 mb-2">
                  <button
                    onClick={() => set("auto_approve_tools", SENSITIVE_ACTIONS.map((a) => a.id))}
                    className="text-xs text-blue-500 hover:underline"
                  >
                    Auto-approve all
                  </button>
                  <button
                    onClick={() => set("auto_approve_tools", [])}
                    className="text-xs text-gray-400 dark:text-gray-500 hover:underline"
                  >
                    Require confirmation for all
                  </button>
                </div>
                <div>
                  {SENSITIVE_ACTIONS.map((a) => (
                    <Field key={a.id} label={a.label} fieldKey={`approve_${a.id}`}>
                      <div className="flex items-center gap-2">
                        <Toggle
                          checked={(prefs.auto_approve_tools || []).includes(a.id)}
                          onChange={(v) => toggleAutoApprove(a.id, v)}
                        />
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          {(prefs.auto_approve_tools || []).includes(a.id) ? "Auto-approved" : "Asks first"}
                        </span>
                      </div>
                    </Field>
                  ))}
                </div>
              </div>

              {/* Memories */}
              <div className={activeTab === "memories" ? "" : "hidden"}>
                <div className="flex items-center justify-between mb-3">
                  <SectionHeader title="Memories" />
                  {memories.length > 0 && (
                    <button onClick={clearAllMemories} className="shrink-0 text-xs text-red-500 hover:underline ml-3">
                      Clear all
                    </button>
                  )}
                </div>
                {/* Memory master switch: BYOK-only, locked without an own key */}
                <div className="mb-4 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 px-3 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-200">Memory</span>
                    <div className="flex items-center gap-2">
                      <Toggle
                        checked={(embedHasKey || isAdmin) && prefs.memory_enabled !== false}
                        disabled={!embedHasKey && !isAdmin}
                        onChange={(v) => set("memory_enabled", v)}
                      />
                      <span className="text-xs text-gray-400 dark:text-gray-500">
                        {!embedHasKey && !isAdmin ? "Off" : prefs.memory_enabled !== false ? "On" : "Paused"}
                      </span>
                    </div>
                  </div>
                  {!embedHasKey && !isAdmin ? (
                    <p className="mt-2 text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                      Memory is off. It runs AI extraction and recall on your conversations, which
                      MailNet's free shared keys don't cover. To enable it, add your own{" "}
                      <button type="button" onClick={() => setActiveTab("ai")} className="text-blue-500 hover:underline">
                        Smart Features key
                      </button>{" "}
                      (Google, OpenAI, or Ollama), then flip this switch.
                    </p>
                  ) : prefs.memory_enabled !== false ? (
                    <p className="mt-2 text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                      MailNet remembers durable facts about you (recurring contacts, standing
                      instructions) and recalls them to personalize replies.
                    </p>
                  ) : (
                    <p className="mt-2 text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                      Memory is paused. MailNet won't save new facts or recall existing ones until
                      you turn it back on. Your saved memories below are kept.
                    </p>
                  )}
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-3 leading-relaxed">
                  Durable facts MailNet has learned about you to personalize replies. Remove anything you don't want it to keep.
                </p>
                {memLoading ? (
                  <div className="flex items-center justify-center py-10">
                    <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : memories.length === 0 ? (
                  <p className="text-sm text-gray-400 dark:text-gray-500 py-6 text-center">No memories saved yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {memories.map((m) => (
                      <li key={m.id} className="flex items-start justify-between gap-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 px-3 py-2">
                        <span className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{m.memory}</span>
                        <button
                          onClick={() => deleteMemory(m.id)}
                          aria-label="Delete memory"
                          className="shrink-0 text-gray-300 hover:text-red-500 dark:text-gray-600 dark:hover:text-red-400 transition-colors"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Scheduled */}
              <div className={activeTab === "scheduled" ? "" : "hidden"}>
                <div className="flex items-center justify-between">
                  <SectionHeader title="Scheduled emails" />
                  <button
                    onClick={loadJobs}
                    className="text-xs text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors"
                  >
                    Refresh
                  </button>
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-3 leading-relaxed">
                  Emails MailNet is holding to send later, including recurring ones. Cancel any you no longer want sent.
                </p>
                {jobsError && (
                  <p className="text-xs text-red-500 dark:text-red-400 mb-3">{jobsError}</p>
                )}
                {jobsLoading ? (
                  <div className="flex items-center justify-center py-10">
                    <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : jobs.length === 0 ? (
                  <p className="text-sm text-gray-400 dark:text-gray-500 py-6 text-center">Nothing scheduled right now.</p>
                ) : (
                  <ul className="space-y-2">
                    {jobs.map((j) => (
                      <li key={j.job_id} className="flex items-start justify-between gap-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 px-3 py-2">
                        <div className="min-w-0">
                          <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug truncate">
                            {j.subject || "(no subject)"}
                          </p>
                          <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
                            To {j.to || "(no recipient)"}
                          </p>
                          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                            {j.type === "recurring" ? "Repeats, next " : "Sends "}
                            {formatRun(j.next_run_time)}
                          </p>
                        </div>
                        <button
                          onClick={() => cancelJob(j.job_id)}
                          aria-label="Cancel scheduled email"
                          className="shrink-0 text-gray-300 hover:text-red-500 dark:text-gray-600 dark:hover:text-red-400 transition-colors"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Contribute */}
              <div className={activeTab === "contribute" ? "" : "hidden"}>
                <SectionHeader title="Contribute" />
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-3 leading-relaxed">
                  MailNet is open source. Read the code, verify how your data is handled, report bugs, or suggest features.
                </p>
                <div className="space-y-2">
                  <a
                    href="https://github.com/Astroa7m/MailNet"
                    target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 px-3 py-2.5 hover:border-blue-300 dark:hover:border-blue-800 transition-colors"
                  >
                    <svg className="w-4 h-4 text-gray-700 dark:text-gray-300 shrink-0" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
                    </svg>
                    <span className="text-sm text-gray-700 dark:text-gray-200">View the source on GitHub</span>
                  </a>
                  <a
                    href="https://github.com/Astroa7m/MailNet/blob/1d56b0af68758ebf8100896e5337d78a8245989d/app/common.py#L176-L184"
                    target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 px-3 py-2.5 hover:border-blue-300 dark:hover:border-blue-800 transition-colors"
                  >
                    <svg className="w-4 h-4 text-gray-700 dark:text-gray-300 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                    </svg>
                    <span className="text-sm text-gray-700 dark:text-gray-200">See how your keys and tokens are encrypted</span>
                  </a>
                  <a
                    href="https://github.com/Astroa7m/MailNet/issues"
                    target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 px-3 py-2.5 hover:border-blue-300 dark:hover:border-blue-800 transition-colors"
                  >
                    <svg className="w-4 h-4 text-gray-700 dark:text-gray-300 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span className="text-sm text-gray-700 dark:text-gray-200">Report a bug or request a feature</span>
                  </a>
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-3 leading-relaxed">
                  Found something off in how data is handled? Open an issue and it will be fixed or explained.
                </p>
              </div>

            </div>
          )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 dark:border-gray-800 shrink-0">
          <span className="text-sm">
            {status === "success" && <span className="text-green-500">Saved successfully</span>}
            {status === "error" && <span className="text-red-500">Failed to save. Try again.</span>}
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-sm rounded-md border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || loading}
              className="px-4 py-1.5 text-sm rounded-md bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
