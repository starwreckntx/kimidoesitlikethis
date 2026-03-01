#!/usr/bin/env python3
"""
kimidoesitlikethis – Telegram Personal Assistant Daemon
========================================================
Entry point. Validates config and starts the bot polling loop.

Usage:
    python main.py

Environment:
    Copy .env.example → .env and fill in your credentials.
"""

import asyncio
import logging
import sys

from config import Config
from bot.telegram_bot import TelegramBot

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s – %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)

# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main() -> None:
    config = Config()
    try:
        config.validate()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        logger.error("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    logger.info("Starting kimidoesitlikethis bot (model: %s)", config.CLAUDE_MODEL)
    bot = TelegramBot(config)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
