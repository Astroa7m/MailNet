"""Fake chat models for offline agent tests.

GenericFakeChatModel on the pinned langchain-core (1.4.1) raises
NotImplementedError from bind_tools, and the langchain.agents factory binds
tools on every model call, so every stub overrides bind_tools to return
itself. The override must swallow tool_choice plus arbitrary kwargs: the
factory passes tool_choice and splats request.model_settings into the call.
"""
from typing import Any, Optional

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.outputs import ChatResult
from pydantic import Field


class ScriptedChatModel(GenericFakeChatModel):
    """Plays back a scripted iterator of AIMessages; tool binding is a no-op."""

    def bind_tools(self, tools: Any, *, tool_choice: Optional[Any] = None, **kwargs: Any):
        return self


class RaisingChatModel(ScriptedChatModel):
    """Raises the configured exception on every generate or stream call.

    The default message is the exact shape ChatNVIDIA produces on a rate
    limit: a plain Exception whose text starts with "[429]".
    """

    error_message: str = "[429] Too Many Requests"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise Exception(self.error_message)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        raise Exception(self.error_message)


class RecordingChatModel(ScriptedChatModel):
    """Scripted model that records what it was bound with and asked."""

    bound_tools_log: list = Field(default_factory=list)
    call_log: list = Field(default_factory=list)

    def bind_tools(self, tools: Any, *, tool_choice: Optional[Any] = None, **kwargs: Any):
        self.bound_tools_log.append(list(tools))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.call_log.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
