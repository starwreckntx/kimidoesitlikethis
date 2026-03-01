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
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

import anthropic

logger = logging.getLogger(__name__)

# Conversation entry TTL in seconds (30 minutes of inactivity → reset)
CONVERSATION_TTL = 1800


SYSTEM_PROMPT = """\
You are an intelligent personal assistant that operates via Telegram. \
You have access to a rich set of tools covering Gmail, Google Drive, Slack, \
Twitter/X, YouTube, GitHub, and a web browser. Use them proactively to \
complete the user's requests accurately and efficiently.

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
    """

    def __init__(self, config, tools: dict, history: ConversationHistory) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self._model = config.CLAUDE_MODEL
        self._thinking_budget = config.THINKING_BUDGET
        self._tools_map = tools  # name → BaseTool instance
        self._history = history

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
        The ask_user_cb coroutine is called when the agent needs clarification;
        it should send the question to Telegram and await the user's reply.
        """
        # Build tool list for Anthropic
        anthropic_tools = [t.to_anthropic_tool() for t in self._tools_map.values()]
        anthropic_tools.append(ASK_USER_TOOL)

        # Add user message to history
        self._history.append(user_id, {"role": "user", "content": message})
        messages = list(self._history.get(user_id))

        # Trim before sending to avoid context overflow
        self._history.trim(user_id)

        response_text = await self._agent_loop(
            messages=messages,
            tools=anthropic_tools,
            ask_user_cb=ask_user_cb,
            user_id=user_id,
        )

        # Store assistant final response in history
        self._history.append(user_id, {"role": "assistant", "content": response_text})
        return response_text

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
