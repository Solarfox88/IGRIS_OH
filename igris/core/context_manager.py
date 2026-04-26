"""Smart context window manager for IGRIS conversations.

Manages how much conversation history and project context fits into the
LLM's context window, adapting the strategy based on the LLM tier:
- Local (Ollama): limited context → summarize old messages, keep recent ones
- API (OpenAI): large context → send full history
- GPU (Vast.ai): same as API
"""

from __future__ import annotations

import logging

from igris.layers.advisory.router import LLMTier
from igris.utils.tokens import estimate_tokens

logger = logging.getLogger("igris.context")

# Context window sizes per model (conservative estimates for input)
MODEL_CONTEXT_SIZES = {
    "mistral": 8000,
    "mistral:7b": 8000,
    "mistral:latest": 8000,
    "qwen2.5-coder:7b": 32000,
    "qwen2.5-coder": 32000,
    "llama3.1:8b": 8000,
    "llama3.2:3b": 8000,
    "codellama:7b": 4000,
    "codellama": 4000,
    "deepseek-coder:6.7b": 16000,
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16000,
}

# Reserve tokens for the LLM's response
RESPONSE_RESERVE = 2000


def get_context_limit(model: str, tier: LLMTier, config_max: int) -> int:
    """Get the effective context token limit for a given model/tier."""
    if tier in (LLMTier.API, LLMTier.VASTAI):
        model_limit = MODEL_CONTEXT_SIZES.get(model, 128000)
    else:
        model_limit = MODEL_CONTEXT_SIZES.get(model, 8000)

    effective = min(model_limit, config_max) if config_max > 0 else model_limit
    return max(effective - RESPONSE_RESERVE, 1000)


def summarize_messages(messages: list[dict]) -> str:
    """Create a concise summary of a list of messages."""
    if not messages:
        return ""

    summary_parts = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            # Keep user requests brief
            text = content[:200] + ("..." if len(content) > 200 else "")
            summary_parts.append(f"Christian ha chiesto: {text}")
        elif role == "assistant":
            # Summarize assistant responses very briefly
            text = content[:150] + ("..." if len(content) > 150 else "")
            summary_parts.append(f"IGRIS ha risposto: {text}")

    return "\n".join(summary_parts)


def build_context_messages(
    system_prompt: str,
    all_messages: list[dict],
    model: str,
    tier: LLMTier,
    config_max_tokens: int,
    project_context: str = "",
) -> list[dict]:
    """Build the optimal message list for the LLM, respecting context limits.

    Strategy:
    1. System prompt (always included, with project context)
    2. If everything fits → send ALL messages (best case)
    3. If not → summarize older messages, keep recent ones in full
    4. For API tier (large context) → almost always sends everything
    """
    context_limit = get_context_limit(model, tier, config_max_tokens)

    # Build system message with project context
    full_system = system_prompt
    if project_context:
        full_system += f"\n\n## Contesto Progetto Corrente\n{project_context}"

    system_tokens = estimate_tokens(full_system)
    available_tokens = context_limit - system_tokens

    if available_tokens <= 0:
        # System prompt alone exceeds limit — truncate project context
        logger.warning("System prompt exceeds context limit, truncating project context")
        full_system = system_prompt
        system_tokens = estimate_tokens(full_system)
        available_tokens = context_limit - system_tokens

    result = [{"role": "system", "content": full_system}]

    if not all_messages:
        return result

    # Calculate total tokens for all messages
    message_tokens = []
    total_msg_tokens = 0
    for msg in all_messages:
        tokens = estimate_tokens(msg["content"])
        message_tokens.append(tokens)
        total_msg_tokens += tokens

    # Case 1: Everything fits — send all messages
    if total_msg_tokens <= available_tokens:
        logger.debug(f"All {len(all_messages)} messages fit in context ({total_msg_tokens}/{available_tokens} tokens)")
        result.extend(all_messages)
        return result

    # Case 2: Need to summarize older messages
    logger.info(f"Context overflow ({total_msg_tokens}/{available_tokens} tokens), summarizing older messages")

    # Find how many recent messages fit (work backwards)
    recent_tokens = 0
    split_index = len(all_messages)
    summary_budget = available_tokens * 0.2  # Reserve 20% for summary

    for i in range(len(all_messages) - 1, -1, -1):
        if recent_tokens + message_tokens[i] > available_tokens - summary_budget:
            split_index = i + 1
            break
        recent_tokens += message_tokens[i]
    else:
        split_index = 0

    # Ensure we keep at least the last 2 messages
    min_recent = min(2, len(all_messages))
    if len(all_messages) - split_index < min_recent:
        split_index = max(0, len(all_messages) - min_recent)

    older_messages = all_messages[:split_index]
    recent_messages = all_messages[split_index:]

    # Create summary of older messages
    if older_messages:
        summary = summarize_messages(older_messages)
        summary_msg = (
            f"[Riassunto delle {len(older_messages)} conversazioni precedenti]\n"
            f"{summary}\n"
            f"[Fine riassunto — {len(recent_messages)} messaggi recenti seguono]"
        )

        # Truncate summary if needed
        summary_tokens = estimate_tokens(summary_msg)
        if summary_tokens > summary_budget:
            max_chars = int(summary_budget * 4)
            summary_msg = summary_msg[:max_chars] + "\n... [riassunto troncato]"

        result.append({"role": "system", "content": summary_msg})

    result.extend(recent_messages)

    logger.info(
        f"Context built: {len(older_messages)} messages summarized, "
        f"{len(recent_messages)} messages in full, "
        f"~{estimate_tokens(str(result))} total tokens"
    )

    return result
