"use client";
import { useRef, useState, useCallback, useEffect } from "react";
import type { InputProps } from "@copilotkit/react-ui";
import { useChatContext } from "@copilotkit/react-ui";
import { useCopilotChatInternal } from "@copilotkit/react-core";

// Optimistic send with cancel-and-continue.
//
// Behavior the user wants:
//   - Every message sends immediately and shows as its OWN bubble (one per send).
//   - If you send another WHILE the agent is still responding, the in-flight run
//     is cancelled and a fresh run starts. Because that fresh run sees the whole
//     conversation, the agent reads all the messages you just fired together and
//     answers once (they are "concatenated" in context, but still shown as
//     separate bubbles).
//   - Once a response has fully finished, the next message is a normal new turn.
//
// We do NOT rewrite or remove bubbles; each send is a plain message. That keeps
// the history clean and avoids the disappearing/duplicated-bubble issues.
//
// Why a custom Input: the default one blocks sending while a response is
// streaming, so it could never trigger the cancel-and-continue. The attachment
// preview queue and hidden file input are rendered by CopilotChat above the
// Input, so we only reproduce the textarea + controls (and keep the
// .copilotKitInput markup so styling and the AutoSend selector keep working).

export default function BufferedInput({
  inProgress,
  onSend,
  onStop,
  onUpload,
  hideStopButton,
  chatReady,
}: InputProps) {
  const context = useChatContext();
  const { stopGeneration, isLoading } = useCopilotChatInternal() as any;
  const [text, setText] = useState("");
  const [isComposing, setIsComposing] = useState(false);
  const [merging, setMerging] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Clear the merge hint once the (re)started run settles.
  useEffect(() => {
    if (!isLoading) setMerging(false);
  }, [isLoading]);

  const autoresize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  const submit = useCallback(async () => {
    // Read the textarea's live DOM value, not just React `text` state. A
    // programmatic fill (AutoSend for ?prompt= links / suggestion chips) sets
    // .value and dispatches Enter before React's onChange has synced `text`, so
    // reading state alone would send nothing. The DOM value is the source of
    // truth and covers both typed and injected input.
    const t = (textareaRef.current?.value ?? text).trim();
    if (!t) return;
    setText("");
    if (textareaRef.current) textareaRef.current.value = "";
    requestAnimationFrame(autoresize);
    textareaRef.current?.focus();

    // If a response is still streaming, cancel it; the new send starts a fresh
    // run over the full history so the agent answers everything together.
    if (isLoading) {
      setMerging(true);
      stopGeneration();
    }
    await onSend(t);
  }, [text, isLoading, autoresize, onSend, stopGeneration]);

  const handleDivClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest("button")) return;
    if (target.tagName === "TEXTAREA") return;
    textareaRef.current?.focus();
  };

  // Sending is allowed even while a response streams (that is how you pile on
  // more messages). The button only acts as Stop when the box is empty.
  const hasText = text.trim().length > 0;
  const showStop = !hasText && inProgress && !hideStopButton;
  const buttonIcon = !chatReady
    ? context.icons.spinnerIcon
    : showStop
      ? context.icons.stopIcon
      : context.icons.sendIcon;
  const sendDisabled = !hasText && !showStop;

  return (
    <div className="copilotKitInputContainer">
      {merging && (
        <div className="flex items-center justify-center gap-1.5 mb-2 text-xs text-gray-500 dark:text-gray-400">
          <span className="flex gap-0.5">
            <span className="w-1 h-1 rounded-full bg-blue-500 animate-pulse" />
            <span className="w-1 h-1 rounded-full bg-blue-500 animate-pulse [animation-delay:150ms]" />
            <span className="w-1 h-1 rounded-full bg-blue-500 animate-pulse [animation-delay:300ms]" />
          </span>
          taking your new message into account
        </div>
      )}
      <div className="copilotKitInput" onClick={handleDivClick}>
        <textarea
          ref={textareaRef}
          placeholder={context.labels.placeholder}
          autoFocus={false}
          rows={1}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            autoresize();
          }}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !isComposing) {
              event.preventDefault();
              // Gate on the live DOM value so a programmatic Enter (AutoSend)
              // fires even before React `text` state has caught up.
              const cur = (event.currentTarget.value ?? text).trim();
              if (cur.length > 0) submit();
            }
          }}
          style={{ resize: "none" }}
        />
        <div className="copilotKitInputControls">
          {onUpload && (
            <button onClick={onUpload} className="copilotKitInputControlButton">
              {context.icons.uploadIcon}
            </button>
          )}

          <div style={{ flexGrow: 1 }} />

          <button
            disabled={sendDisabled}
            onClick={showStop ? onStop : submit}
            data-copilotkit-in-progress={inProgress}
            data-test-id={inProgress ? "copilot-chat-request-in-progress" : "copilot-chat-ready"}
            className="copilotKitInputControlButton"
            aria-label={showStop ? "Stop" : "Send"}
          >
            {buttonIcon}
          </button>
        </div>
      </div>
    </div>
  );
}
