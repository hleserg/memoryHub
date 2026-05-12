"""
Universal memory injection for Atman agent sessions.

Provides inject_memory() — a single function that inserts recalled context
into the agent's awareness. The injection mode controls where the content
lands, allowing Atman to work as an overlay on top of third-party agent
systems that may or may not expose their system prompt.

Modes
-----
assistant_message (default)
    Injected as a ModelResponse — the agent reads it as its own prior output,
    making recall feel like remembering rather than being told by someone.
    Works in any pydantic-ai agent without special permissions.

user_message
    Injected as a UserPromptPart with a neutral marker. Use when the host
    system only allows adding user-side turns to message history.

system_prompt
    Returns the content string for the caller to append to instructions.
    Requires access to the agent's system prompt / instructions lambda.
    Use inject_memory() return value to update AtmanDeps.injected_context;
    build_instructions() will pick it up automatically.

Usage
-----
Session wake-up (start of session):
    inject_memory(wake_up_text, mode=config.memory_injection_mode,
                  history=message_history)

Entity recall (mid-session, before next agent.run()):
    inject_memory(entity_memories, mode=config.memory_injection_mode,
                  history=history, prepend=False)

System-prompt mode:
    extra = inject_memory(text, mode="system_prompt")
    if extra:
        deps = replace(deps, injected_context=extra)
    # build_instructions(deps) will append it automatically
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

MemoryInjectionMode = Literal["system_prompt", "assistant_message", "user_message"]


def inject_memory(
    content: str,
    *,
    mode: MemoryInjectionMode,
    history: list | None = None,
    prepend: bool = True,
) -> str | None:
    """
    Inject memory context into agent awareness.

    For history-based modes (assistant_message, user_message):
        Modifies ``history`` in-place. Returns None.
        ``history`` must be provided.

    For system_prompt mode:
        Returns ``content`` as a string. ``history`` is ignored.
        Caller should set ``deps = replace(deps, injected_context=returned_value)``
        so that build_instructions() appends it to the system prompt.

    Args:
        content: Memory text to inject. Should be framed in the agent's
            own voice for assistant_message mode.
        mode: Where to inject the content.
        history: pydantic-ai message list. Required for history modes.
        prepend: If True (default), insert at the beginning of history
            (use for session wake-up). If False, append to the end
            (use for mid-session entity recall, injected before next run).

    Returns:
        str for system_prompt mode, None otherwise.
    """
    if not content:
        return None

    if mode == "system_prompt":
        return content

    if history is None:
        raise ValueError(f"inject_memory: history required for mode={mode!r}")

    if mode == "assistant_message":
        msg = ModelResponse(parts=[TextPart(content=content)])
    else:  # user_message
        msg = ModelRequest(parts=[UserPromptPart(content=content)])

    if prepend:
        history.insert(0, msg)
    else:
        history.append(msg)

    return None
