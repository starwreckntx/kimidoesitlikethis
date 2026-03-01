"""
Telegram bot daemon – the event-driven front-end for the DeepAgent.

Message flow:
  1. User sends message → Telegram delivers update
  2. Handler checks authorisation
  3. If another task is in-progress for this user → queue it
  4. Send immediate acknowledgement ("Got it! Working on it…")
  5. Run DeepAgent (may pause for ask_user clarifications)
  6. Send final response back to Telegram
"""

import asyncio
import logging
from typing import Optional

from telegram import Update, BotCommand
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import Config
from .agent import ConversationHistory, DeepAgent
from .tools.registry import build_tools

logger = logging.getLogger(__name__)

# Maximum characters per Telegram message
TG_MAX_LEN = 4096


def _split_message(text: str, max_len: int = TG_MAX_LEN) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit."""
    chunks = []
    while len(text) > max_len:
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


_VALID_PROVIDERS = ("claude", "kimi", "gemini")


class TelegramBot:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._history = ConversationHistory()
        self._tools = build_tools(config)

        # Per-user state
        # user_id → asyncio.Task (current agent task)
        self._active_tasks: dict[int, asyncio.Task] = {}
        # user_id → asyncio.Future (waiting for ask_user reply)
        self._pending_questions: dict[int, asyncio.Future] = {}
        # user_id → list of queued messages (received while agent is running)
        self._message_queue: dict[int, list[str]] = {}
        # user_id → preferred provider ("claude" | "kimi" | "gemini")
        self._user_provider: dict[int, str] = {}

        self._app: Optional[Application] = None

    # ──────────────────────────────────────────────────────────────────
    # Bot lifecycle
    # ──────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Build the Application and start polling (blocking)."""
        self._app = (
            Application.builder()
            .token(self._config.TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Register commands
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("tools", self._cmd_tools))
        self._app.add_handler(CommandHandler("model", self._cmd_model))

        # Text message handler
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        # Photo handler (pass caption + photo note to agent)
        self._app.add_handler(
            MessageHandler(filters.PHOTO, self._on_photo)
        )

        # Set bot commands in Telegram menu
        await self._app.bot.set_my_commands([
            BotCommand("start", "Start the assistant"),
            BotCommand("help", "Show help"),
            BotCommand("clear", "Clear conversation history"),
            BotCommand("status", "Check if a task is running"),
            BotCommand("tools", "List available tools"),
            BotCommand("model", "Switch AI model (claude/kimi/gemini)"),
        ])

        logger.info("Starting Telegram bot polling…")
        await self._app.run_polling(allowed_updates=Update.ALL_TYPES)

    # ──────────────────────────────────────────────────────────────────
    # Authorisation helper
    # ──────────────────────────────────────────────────────────────────

    def _is_allowed(self, user_id: int) -> bool:
        if not self._config.TELEGRAM_ALLOWED_USER_IDS:
            return True  # open if no whitelist configured
        return user_id in self._config.TELEGRAM_ALLOWED_USER_IDS

    # ──────────────────────────────────────────────────────────────────
    # Command handlers
    # ──────────────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            await update.message.reply_text("You are not authorised to use this bot.")
            return
        tool_names = ", ".join(self._tools.keys()) or "none"
        await update.message.reply_text(
            f"Hello {update.effective_user.first_name}! I'm your personal DeepAgent assistant.\n\n"
            f"Just send me a message describing what you need and I'll take care of it.\n\n"
            f"Active tools: {tool_names}\n\n"
            f"Commands: /help  /clear  /status  /tools",
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "*Personal Assistant – Help*\n\n"
            "Simply send any request in plain English. Examples:\n"
            "• _Send an email to alice@example.com about the meeting_\n"
            "• _Search YouTube for python tutorials and send me the top 3_\n"
            "• _Create a GitHub issue in myrepo titled 'Fix login bug'_\n"
            "• _What's trending on Twitter about AI?_\n"
            "• _Find my latest unread emails and summarise them_\n\n"
            "Commands:\n"
            "/clear – reset conversation memory\n"
            "/status – check if a task is running\n"
            "/tools – list connected integrations",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        self._history.clear(uid)
        self._message_queue.pop(uid, None)
        await update.message.reply_text("Conversation history cleared.")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        task = self._active_tasks.get(uid)
        if task and not task.done():
            await update.message.reply_text("A task is currently running. Please wait.")
        else:
            await update.message.reply_text("No task running. Ready for your next request!")

    async def _cmd_tools(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._tools:
            await update.message.reply_text("No tools are configured yet.")
            return
        lines = [f"• *{name}* – {tool.description[:80]}…" for name, tool in self._tools.items()]
        await update.message.reply_text(
            "*Connected tools:*\n" + "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        if not self._is_allowed(uid):
            await update.message.reply_text("You are not authorised.")
            return

        args = context.args  # list of words after /model
        current = self._user_provider.get(uid, "claude")

        if not args:
            # Show current model + available options
            available = ["claude"]
            if self._config.kimi_configured:
                available.append("kimi")
            if self._config.gemini_configured:
                available.append("gemini")
            await update.message.reply_text(
                f"Current model: *{current}*\n"
                f"Available: {', '.join(available)}\n\n"
                f"Usage: `/model claude` | `/model kimi` | `/model gemini`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        choice = args[0].lower()
        if choice not in _VALID_PROVIDERS:
            await update.message.reply_text(
                f"Unknown provider '{choice}'. Choose from: claude, kimi, gemini"
            )
            return

        if choice == "kimi" and not self._config.kimi_configured:
            await update.message.reply_text("Kimi is not configured. Set KIMI_API_KEY in .env.")
            return
        if choice == "gemini" and not self._config.gemini_configured:
            await update.message.reply_text("Gemini is not configured. Set GEMINI_API_KEY in .env.")
            return

        self._user_provider[uid] = choice
        await update.message.reply_text(f"Model switched to *{choice}*.", parse_mode=ParseMode.MARKDOWN)

    # ──────────────────────────────────────────────────────────────────
    # Message handlers
    # ──────────────────────────────────────────────────────────────────

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        text = update.message.text or ""
        await self._handle_incoming(update, context, uid, text)

    async def _on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        caption = update.message.caption or ""
        text = f"[User sent a photo] Caption: {caption}" if caption else "[User sent a photo with no caption]"
        await self._handle_incoming(update, context, uid, text)

    async def _handle_incoming(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        uid: int,
        text: str,
    ) -> None:
        if not self._is_allowed(uid):
            await update.message.reply_text("You are not authorised to use this bot.")
            return

        # ── Case 1: agent is waiting for ask_user answer ──
        future = self._pending_questions.get(uid)
        if future and not future.done():
            future.set_result(text)
            return  # response routed to the waiting agent loop

        # ── Case 2: another task is already running → queue ──
        task = self._active_tasks.get(uid)
        if task and not task.done():
            self._message_queue.setdefault(uid, []).append(text)
            await update.message.reply_text(
                "I'm still working on your previous task. "
                "Your message has been queued and will be processed next."
            )
            return

        # ── Case 3: start a new task ──
        # Send acknowledgement immediately
        ack = await update.message.reply_text(
            "Got it! Working on it… this may take a moment."
        )

        # Show typing indicator while processing
        await context.bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)

        new_task = asyncio.create_task(
            self._process_task(update, context, uid, text)
        )
        self._active_tasks[uid] = new_task
        new_task.add_done_callback(
            lambda t: asyncio.ensure_future(self._on_task_done(uid, update, context, t))
        )

    async def _process_task(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        uid: int,
        text: str,
    ) -> None:
        """Run the DeepAgent for one user message."""

        async def ask_user_cb(question: str) -> str:
            """Called by DeepAgent when it needs to ask the user something."""
            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            self._pending_questions[uid] = future

            await context.bot.send_message(
                chat_id=uid,
                text=f"I have a question for you:\n\n{question}",
            )
            # Show typing while waiting
            try:
                answer = await asyncio.wait_for(future, timeout=300)  # 5-min timeout
            except asyncio.TimeoutError:
                answer = "(no response – proceeding with best guess)"
            finally:
                self._pending_questions.pop(uid, None)
            return answer

        provider = self._user_provider.get(uid, "claude")
        agent = DeepAgent(self._config, self._tools, self._history, provider=provider)
        result = await agent.run(uid, text, ask_user_cb)

        # Send response (split if too long)
        for chunk in _split_message(result):
            await context.bot.send_message(chat_id=uid, text=chunk)

    async def _on_task_done(
        self,
        uid: int,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        task: asyncio.Task,
    ) -> None:
        """Called when a task finishes. Process queue if any."""
        if task.cancelled():
            await context.bot.send_message(chat_id=uid, text="Task was cancelled.")
        elif task.exception():
            exc = task.exception()
            logger.error("Task failed for user %d: %s", uid, exc, exc_info=exc)
            await context.bot.send_message(
                chat_id=uid,
                text=f"Sorry, an error occurred: {exc}\n\nPlease try again.",
            )

        # Process next queued message if any
        queue = self._message_queue.get(uid, [])
        if queue:
            next_msg = queue.pop(0)
            self._message_queue[uid] = queue
            await context.bot.send_message(
                chat_id=uid,
                text=f"Processing your queued message: {next_msg[:100]}…",
            )
            new_task = asyncio.create_task(
                self._process_task(update, context, uid, next_msg)
            )
            self._active_tasks[uid] = new_task
            new_task.add_done_callback(
                lambda t: asyncio.ensure_future(
                    self._on_task_done(uid, update, context, t)
                )
            )
