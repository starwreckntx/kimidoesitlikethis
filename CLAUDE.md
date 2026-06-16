# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`kimidoesitlikethis` is a single-process **Telegram-triggered personal assistant daemon**. A user messages a Telegram bot; the message drives an agentic Claude tool-use loop ("DeepAgent") with extended thinking, which calls integration tools (Gmail, Drive, YouTube, Slack, Twitter/X, GitHub, a Playwright browser, and a persistent "Mnemosyne" memory ledger) and replies back in the chat. It runs as one long-lived asyncio process polling Telegram — there is no web server, database, or HTTP API.

## Commands

```bash
bash setup.sh                 # venv + deps + `playwright install chromium` + .env scaffold
source .venv/bin/activate
python main.py                # start the daemon (long-running, polls Telegram)

# One-time Google OAuth refresh token (paste result into .env as GOOGLE_REFRESH_TOKEN)
python get_google_token.py --client-id <id> --client-secret <secret>
```

There is **no test suite, linter, or build step** in this repo. `main.py` is the only entry point. Config is validated on startup (`config.validate()` requires `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY`); everything else degrades gracefully.

## Architecture (the parts that span files)

The request lifecycle crosses three layers — read these together:

1. **`bot/telegram_bot.py` — front-end / concurrency manager.** Owns all per-user runtime state as `dict[user_id, ...]`: the in-flight `asyncio.Task`, a `Future` for a pending `ask_user` question, a queued-message list, and the chosen provider. The non-obvious control flow lives in `_handle_incoming`, which routes an incoming message to one of three cases: (a) it's the answer to an `ask_user` question → resolve the waiting Future; (b) a task is already running for this user → queue it; (c) otherwise → ack immediately and spawn a new task. Each task chains the next queued message via the `_on_task_done` done-callback. There is no cross-process locking — concurrency is purely per-user in-memory, so the daemon is single-instance by design.

2. **`bot/agent.py` — the agentic loop.** `DeepAgent._agent_loop` is the core Claude `messages.create` loop: it appends full assistant content (preserving `thinking` blocks), and on `stop_reason == "tool_use"` runs `_execute_tools` and feeds `tool_result` blocks back. Two subtleties to preserve when editing:
   - **`ask_user` is a pseudo-tool**, not a `BaseTool`. It's injected into the tool list as `ASK_USER_TOOL` and dispatched specially — it calls back into the Telegram layer (`ask_user_cb`), which pauses the loop until the user replies (5-min timeout). All *other* tools in a turn run concurrently via `asyncio.gather`; `ask_user` is always run sequentially after them.
   - **Extended thinking** is enabled when `THINKING_BUDGET > 0`, which forces `max_tokens > budget`; a `BadRequestError` retries once without thinking for models that don't support it.
   - **Provider fallback:** `FallbackAgent` reimplements the same loop against an **OpenAI-compatible** endpoint (Kimi via Moonshot, or Gemini via its OpenAI-compat URL) and is used when the user picks a provider with `/model` or when Claude raises `RateLimitError`. History is translated between Anthropic and OpenAI message formats (`_history_to_openai` strips thinking blocks). Gemini can authenticate with a dedicated key *or* fall back to Google OAuth (`gemini_uses_oauth`).
   - **`ConversationHistory`** is in-memory only, keyed by user, with a 30-min TTL (`CONVERSATION_TTL`) and trimming to the last 20 turn-pairs. `/clear` resets it. Nothing is persisted across restarts except via the Mnemosyne tool.

3. **`bot/tools/` — integrations.** Every tool subclasses `BaseTool` (`base.py`): class-level `name` / `description` / `input_schema`, one `async def execute(**kwargs) -> str` that **must return a string**, and `to_anthropic_tool()` which the agent maps into Anthropic *or* OpenAI tool schemas. `registry.build_tools(config)` is the single wiring point — it instantiates **only** the tools whose credentials are configured (gated by the `*_configured` properties on `Config`) and logs/skips the rest. `browser` (Playwright + BeautifulSoup) needs no credentials and is always present.

### Adding a tool

Create `bot/tools/<name>_tool.py` subclassing `BaseTool`, add a `<name>_configured` property to `Config` if it needs credentials, and register it in `build_tools`. That's the whole contract — the agent loop and both providers pick it up automatically.

### Mnemosyne ledger (`mnemosyne_tool.py`)

Persistent cross-session memory backed by a **separate git repository** at `MNEMOSYNE_LEDGER_PATH` (not this repo). Reads/writes Markdown files (`LEDGER.md`, `TIMELINE.md`, `nodes/kali_context.md`, `sessions/*.md`) and **auto-commits and pushes** on every write via `subprocess` git calls (push failure is non-fatal). All paths are confined to the ledger root by `_path()`'s traversal check. The system prompt instructs the agent to hydrate memory at task start and write a ledger entry at task end, so changes here directly affect Claude's behavior across sessions.

## Conventions & gotchas

- **`Config` is the single source of truth** for credentials and capability gating. Don't read `os.getenv` elsewhere; add a field + a `*_configured` property and gate on it.
- **Default model** is `claude-opus-4-6` (override via `CLAUDE_MODEL` in `.env`). The latest Claude models are in the Opus/Sonnet/Haiku 4.x and Fable 5 families — prefer the newest available when changing the default.
- **The README is partially stale**: it omits the Kimi/Gemini fallback providers, the `/model` command, and the Mnemosyne tool. Treat this file and the code as authoritative over the README's architecture diagram.
- Telegram messages are capped at 4096 chars; `_split_message` chunks long replies. Tool errors are caught and returned as strings (never raised into the loop) so one failing tool doesn't abort the turn.
- The bot is **open to all users when `TELEGRAM_ALLOWED_USER_IDS` is empty** — that whitelist is the only auth boundary.

## Lessons-learned training pairs

`lessons-learned/` holds a JSONL training-pair set that ties observed model outputs to their corrections (see `lessons-learned/README.md` for the schema). When you fix a real bug here or catch one in review, **append a record** pairing the exact buggy output with the fix and naming the pattern — keep the set current rather than silently patching.
