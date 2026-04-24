"use client";
import { useEffect, useState, useRef } from "react";

const API = "http://localhost:8002";

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
};

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
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [isDark, setIsDark] = useState(false);
  const backdropRef = useRef<HTMLDivElement>(null);

  const hasGoogle = providers.includes("google");
  const hasMicrosoft = providers.includes("microsoft");
  const hasMultiple = hasGoogle && hasMicrosoft;
  const missingProvider = hasGoogle ? "microsoft" : "google";

  useEffect(() => {
    if (!open) return;
    setIsDark(document.documentElement.classList.contains("dark"));
    setStatus("idle");
    setLoading(true);
    Promise.all([
      fetch(`${API}/preferences`, { credentials: "include", cache: "no-store" }).then((r) => r.json()),
      fetch(`${API}/me`, { credentials: "include", cache: "no-store" }).then((r) => r.json()),
    ])
      .then(([prefsData, meData]) => {
        const merged = { ...DEFAULTS, ...prefsData };
        if (merged.default_provider) merged.default_provider = merged.default_provider.toLowerCase();
        setPrefs(merged);
        setOriginal(merged);
        setProviders(meData.providers ?? []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open]);

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
    if (Object.keys(changes).length === 0) { onClose(); return; }

    setSaving(true);
    setStatus("idle");
    try {
      const r = await fetch(`${API}/preferences`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changes),
      });
      if (!r.ok) throw new Error();
      setOriginal(prefs);
      setStatus("success");
      setTimeout(onClose, 800);
    } catch {
      setStatus("error");
    } finally {
      setSaving(false);
    }
  }

  function set<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setPrefs((p) => ({ ...p, [key]: value }));
  }

  if (!open) return null;

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
    >
      <div className="relative w-full max-w-lg mx-4 bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 flex flex-col max-h-[90vh]">

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
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <div className="space-y-6">

              {/* Appearance */}
              <div>
                <SectionHeader title="Appearance" />
                <Field label="Dark Mode" fieldKey="theme">
                  <Toggle checked={isDark} onChange={toggleTheme} />
                </Field>
              </div>

              {/* Writing */}
              <div>
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
              <div>
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
              <div>
                <SectionHeader title="Account" />
                <div>
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
                  <Field label="Thread Context" fieldKey="include_thread_context">
                    <Toggle checked={prefs.include_thread_context} onChange={(v) => set("include_thread_context", v)} />
                  </Field>
                </div>
              </div>

            </div>
          )}
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
