"""
DeepAgent – Claude-powered agentic loop with extended thinking.

Flow:
  user message
     └─► DeepAgent.run()
           ├─ builds messages + tool definitions
           ├─ calls Claude (extended thinking enabled)
           ├─ if stop_reason == "tool_use":
           │      ├─ executes tools (including ask_user which Telegram-pauses the loop)
           │      └─ loops
           └─ returns final text to caller
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

import anthropic

logger = logging.getLogger(__name__)

# ── OpenAI-compatible provider configs ────────────────────────────────────────
_PROVIDER_BASE_URLS = {
    "kimi": "https://api.moonshot.cn/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


def _openai_tools(tools_map: dict, ask_user_schema: dict) -> list:
    """Convert BaseTool instances + ask_user schema to OpenAI function-tool format."""
    result = []
    for tool in tools_map.values():
        t = tool.to_anthropic_tool()
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        })
    # ask_user
    result.append({
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": ask_user_schema["description"],
            "parameters": ask_user_schema["input_schema"],
        },
    })
    return result


def _history_to_openai(anthropic_messages: list) -> list:
    """Convert Anthropic-format history to OpenAI text-only messages (strips thinking blocks)."""
    result = []
    for msg in anthropic_messages:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                if btype == "text":
                    parts.append(getattr(block, "text", None) or block.get("text", ""))
            text = "\n".join(parts).strip()
        else:
            text = str(content)
        if text:
            result.append({"role": role, "content": text})
    return result


# ── Fallback agent (Kimi / Gemini via OpenAI-compatible API) ──────────────────

class FallbackAgent:
    """
    Minimal agentic tool-use loop targeting an OpenAI-compatible endpoint.
    Used when Claude usage is exhausted or the user manually selects another provider.
    """

    def __init__(self, config, tools_map: dict, provider: str) -> None:
        from openai import AsyncOpenAI  # lazy import – optional dependency
        api_key = config.KIMI_API_KEY if provider == "kimi" else config.GEMINI_API_KEY
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=_PROVIDER_BASE_URLS[provider],
        )
        self._model = config.KIMI_MODEL if provider == "kimi" else config.GEMINI_MODEL
        self._provider = provider
        self._tools_map = tools_map

    async def run(
        self,
        history: list,
        user_message: str,
        ask_user_cb: "AskUserCallback",
    ) -> str:
        """Run the tool-use loop. `history` is the existing Anthropic-format history."""
        openai_tools = _openai_tools(self._tools_map, ASK_USER_TOOL)

        # Seed messages: convert prior history + current user message
        messages = _history_to_openai(history)
        # Ensure the latest user message is present
        if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != user_message:
            messages.append({"role": "user", "content": user_message})

        max_iterations = 30
        for _ in range(max_iterations):
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )

            choice = response.choices[0]
            msg = choice.message
            finish_reason = choice.finish_reason

            # Append assistant turn
            messages.append(msg.model_dump(exclude_unset=True))

            if finish_reason == "stop" or not msg.tool_calls:
                return msg.content or ""

            if finish_reason in ("tool_calls", "function_call") or msg.tool_calls:
                tool_results = await self._run_tool_calls(msg.tool_calls, ask_user_cb)
                messages.extend(tool_results)
                continue

            return msg.content or "Done."

        return "Reached maximum processing iterations."

    async def _run_tool_calls(self, tool_calls, ask_user_cb) -> list:
        async def run_one(tc) -> dict:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            logger.info("[%s] Tool call: %s | args: %s", self._provider, name, args)

            if name == "ask_user":
                try:
                    result = await ask_user_cb(args.get("question", ""))
                except Exception as e:
                    result = f"Failed to get user input: {e}"
            elif name in self._tools_map:
                try:
                    result = await self._tools_map[name].execute(**args)
                except Exception as e:
                    logger.error("Tool %s raised: %s", name, e, exc_info=True)
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {name}"

            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            }

        ask_calls = [tc for tc in tool_calls if tc.function.name == "ask_user"]
        other_calls = [tc for tc in tool_calls if tc.function.name != "ask_user"]

        results = []
        if other_calls:
            results.extend(await asyncio.gather(*(run_one(tc) for tc in other_calls)))
        for tc in ask_calls:
            results.append(await run_one(tc))
        return results

# Conversation entry TTL in seconds (30 minutes of inactivity → reset)
CONVERSATION_TTL = 1800


SYSTEM_PROMPT = """\
You are an intelligent personal assistant that operates via Telegram. \
You have access to a rich set of tools covering Gmail, Google Drive, Slack, \
Twitter/X, YouTube, GitHub, a web browser, and the Mnemosyne Ledger. \
Use them proactively to complete the user's requests accurately and efficiently.

IMPORTANT GUIDELINES:
- Always reason through the task step-by-step before acting.
- Prefer using tools over guessing; if you need live data, fetch it.
- When you need clarification from the user, use the ask_user tool – it will \
  pause the task and send a message back to them on Telegram.
- Summarise what you did and the outcome clearly in your final response.
- Be concise but complete. Use bullet points or numbered lists when helpful.
- If a task involves multiple services (e.g. "email me the top YouTube trend"), \
  chain the tools automatically.
- Never expose raw API tokens or credentials in your responses.

MNEMOSYNE LEDGER (persistent memory):
- The mnemosyne tool gives you cross-session memory backed by local files + git.
- At the START of tasks referencing past context or ongoing projects, call \
  mnemosyne(action="read_ledger") and mnemosyne(action="read_node_context") \
  to hydrate your memory before acting.
- At the END of significant tasks, call mnemosyne(action="write_ledger_entry") \
  with a concise summary, and mnemosyne(action="update_node_context") if your \
  understanding of the user's goals or state has meaningfully changed.
- Use mnemosyne(action="write_session") to record detailed session logs when \
  explicitly asked or when the session contains complex multi-step work worth \
  preserving (filename format: YYYY-MM-DD_short-description.md).
"""

# Schema for the special ask_user tool (executed by the Telegram handler)
ASK_USER_TOOL = {
    "name": "ask_user",
    "description": (
        "Ask the user a clarifying question via Telegram when you need more "
        "information to complete a task. The task will be paused until they reply."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            }
        },
        "required": ["question"],
    },
}


class ConversationHistory:
    """Per-user multi-turn conversation history with TTL-based expiry."""

    def __init__(self, ttl: int = CONVERSATION_TTL) -> None:
        self._ttl = ttl
        # user_id → {"messages": list, "last_active": float}
        self._store: dict[int, dict] = defaultdict(lambda: {"messages": [], "last_active": 0.0})

    def get(self, user_id: int) -> list:
        entry = self._store[user_id]
        if time.time() - entry["last_active"] > self._ttl:
            entry["messages"] = []
        entry["last_active"] = time.time()
        return entry["messages"]

    def append(self, user_id: int, message: dict) -> None:
        self.get(user_id)  # refresh TTL
        self._store[user_id]["messages"].append(message)

    def clear(self, user_id: int) -> None:
        self._store[user_id]["messages"] = []
        self._store[user_id]["last_active"] = time.time()

    def trim(self, user_id: int, max_turns: int = 20) -> None:
        """Keep only the last max_turns assistant+user pairs."""
        msgs = self._store[user_id]["messages"]
        if len(msgs) > max_turns * 2:
            self._store[user_id]["messages"] = msgs[-(max_turns * 2):]


# Type alias for the ask_user callback
AskUserCallback = Callable[[str], Coroutine[Any, Any, str]]


class DeepAgent:
    """
    Wraps Claude in an agentic tool-use loop with optional extended thinking.
    Falls back to Kimi or Gemini when Claude is rate-limited / out of usage.
    """

    def __init__(
        self,
        config,
        tools: dict,
        history: ConversationHistory,
        provider: str = "claude",
    ) -> None:
        self._config = config
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self._model = config.CLAUDE_MODEL
        self._thinking_budget = config.THINKING_BUDGET
        self._tools_map = tools  # name → BaseTool instance
        self._history = history
        self._provider = provider  # "claude" | "kimi" | "gemini"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        user_id: int,
        message: str,
        ask_user_cb: AskUserCallback,
    ) -> str:
        """
        Process a user message and return the final assistant text response.
        If provider is not 'claude', or Claude fails with a rate-limit error,
        the request is routed to the configured fallback provider.
        """
        # Add user message to history
        self._history.append(user_id, {"role": "user", "content": message})
        messages = list(self._history.get(user_id))
        self._history.trim(user_id)

        # ── Route to fallback immediately if user chose one ──
        if self._provider in ("kimi", "gemini"):
            response_text = await self._run_fallback(self._provider, messages, message, ask_user_cb)
            self._history.append(user_id, {"role": "assistant", "content": response_text})
            return response_text

        # ── Try Claude ──
        anthropic_tools = [t.to_anthropic_tool() for t in self._tools_map.values()]
        anthropic_tools.append(ASK_USER_TOOL)
        try:
            response_text = await self._agent_loop(
                messages=messages,
                tools=anthropic_tools,
                ask_user_cb=ask_user_cb,
                user_id=user_id,
            )
        except anthropic.RateLimitError as e:
            logger.warning("Claude rate-limited (%s) – trying fallback.", e)
            response_text = await self._handle_claude_limit(messages, message, ask_user_cb)

        self._history.append(user_id, {"role": "assistant", "content": response_text})
        return response_text

    async def _handle_claude_limit(
        self,
        messages: list,
        message: str,
        ask_user_cb: AskUserCallback,
    ) -> str:
        """Auto-fallback when Claude is rate-limited, using FALLBACK_PROVIDER config."""
        provider = self._config.FALLBACK_PROVIDER
        if provider == "kimi" and self._config.kimi_configured:
            return await self._run_fallback("kimi", messages, message, ask_user_cb)
        if provider == "gemini" and self._config.gemini_configured:
            return await self._run_fallback("gemini", messages, message, ask_user_cb)
        return (
            "Claude is currently rate-limited and no fallback provider is configured. "
            "Set FALLBACK_PROVIDER=kimi or FALLBACK_PROVIDER=gemini (with the matching "
            "API key) in your .env to enable automatic fallback."
        )

    async def _run_fallback(
        self,
        provider: str,
        history: list,
        message: str,
        ask_user_cb: AskUserCallback,
    ) -> str:
        try:
            agent = FallbackAgent(self._config, self._tools_map, provider)
            return await agent.run(history, message, ask_user_cb)
        except Exception as e:
            logger.error("Fallback provider %s failed: %s", provider, e, exc_info=True)
            return f"Fallback provider ({provider}) also failed: {e}"

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _agent_loop(
        self,
        messages: list,
        tools: list,
        ask_user_cb: AskUserCallback,
        user_id: int,
    ) -> str:
        """Main Claude tool-use loop. Returns final text response."""

        max_iterations = 30  # safety cap
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Build create-message kwargs
            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 8192,
                "system": SYSTEM_PROMPT,
                "tools": tools,
                "messages": messages,
            }

            # Enable extended thinking when budget is set
            if self._thinking_budget > 0:
                create_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self._thinking_budget,
                }
                # Extended thinking requires max_tokens > budget
                create_kwargs["max_tokens"] = max(16000, self._thinking_budget + 4096)

            try:
                response = await self._client.messages.create(**create_kwargs)
            except anthropic.BadRequestError as e:
                # Fall back without thinking if the model doesn't support it
                logger.warning("Extended thinking failed (%s), retrying without.", e)
                create_kwargs.pop("thinking", None)
                create_kwargs["max_tokens"] = 8192
                response = await self._client.messages.create(**create_kwargs)

            stop_reason = response.stop_reason
            content = response.content  # list of content blocks

            # Append full assistant content to conversation (preserves thinking blocks)
            messages.append({"role": "assistant", "content": content})

            if stop_reason == "end_turn":
                return self._extract_text(content)

            if stop_reason == "tool_use":
                tool_results = await self._execute_tools(content, ask_user_cb)
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason
            logger.warning("Unexpected stop_reason: %s", stop_reason)
            return self._extract_text(content) or "Task completed."

        return "Reached maximum processing iterations. Partial result may be incomplete."

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tools(
        self,
        content: list,
        ask_user_cb: AskUserCallback,
    ) -> list:
        """Execute all tool_use blocks concurrently and return tool_result list."""

        tool_use_blocks = [b for b in content if getattr(b, "type", None) == "tool_use"]

        async def run_one(block) -> dict:
            tool_name = block.name
            tool_input = block.input or {}
            logger.info("Executing tool: %s | input: %s", tool_name, tool_input)

            if tool_name == "ask_user":
                question = tool_input.get("question", "")
                try:
                    answer = await ask_user_cb(question)
                    result = answer
                except Exception as e:
                    result = f"Failed to get user input: {e}"

            elif tool_name in self._tools_map:
                try:
                    result = await self._tools_map[tool_name].execute(**tool_input)
                except Exception as e:
                    logger.error("Tool %s raised: %s", tool_name, e, exc_info=True)
                    result = f"Tool error: {e}"

            else:
                result = f"Unknown tool: {tool_name}"

            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result),
            }

        # Run all tools concurrently EXCEPT ask_user (must be sequential with user)
        ask_blocks = [b for b in tool_use_blocks if b.name == "ask_user"]
        other_blocks = [b for b in tool_use_blocks if b.name != "ask_user"]

        results: list[dict] = []

        # Run non-ask_user tools concurrently
        if other_blocks:
            other_results = await asyncio.gather(*(run_one(b) for b in other_blocks))
            results.extend(other_results)

        # Run ask_user tools sequentially
        for b in ask_blocks:
            results.append(await run_one(b))

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(content: list) -> str:
        """Extract text from content blocks (skip thinking blocks)."""
        parts = []
        for block in content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "\n\n".join(parts).strip()
