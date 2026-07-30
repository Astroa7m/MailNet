// The proactive "catch me up" trigger. Sent as a normal message so the agent
// runs a real inbox read + triage, but the user bubble for this exact string is
// hidden in the chat (see CustomUserMessage), so the agent appears to open the
// conversation on its own with a briefing of what needs attention.
export const BRIEFING_PROMPT =
  "Give me a quick briefing. Check my inbox now and open by telling me about the single most urgent or important email, in a natural conversational tone, like you're catching me up in a sentence or two: who it's from and why it matters. If nothing is urgent, say my inbox looks calm. Then briefly offer to help with it.";
