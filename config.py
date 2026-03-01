import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_ALLOWED_USER_IDS: list[int] = [
        int(uid.strip())
        for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if uid.strip().isdigit()
    ]

    # Anthropic / DeepAgent
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
    THINKING_BUDGET: int = int(os.getenv("THINKING_BUDGET", "8000"))

    # Google (Gmail + Drive + YouTube)
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REFRESH_TOKEN: str = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

    # Slack
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_WORKSPACE: str = os.getenv("SLACK_WORKSPACE", "")

    # Twitter / X
    TWITTER_API_KEY: str = os.getenv("TWITTER_API_KEY", "")
    TWITTER_API_SECRET: str = os.getenv("TWITTER_API_SECRET", "")
    TWITTER_ACCESS_TOKEN: str = os.getenv("TWITTER_ACCESS_TOKEN", "")
    TWITTER_ACCESS_SECRET: str = os.getenv("TWITTER_ACCESS_SECRET", "")
    TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")

    # GitHub
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_USERNAME: str = os.getenv("GITHUB_USERNAME", "")

    # Browser
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

    def validate(self) -> None:
        """Raise if critical config is missing."""
        if not self.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required")

    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.GOOGLE_REFRESH_TOKEN)

    @property
    def slack_configured(self) -> bool:
        return bool(self.SLACK_BOT_TOKEN)

    @property
    def twitter_configured(self) -> bool:
        return bool(self.TWITTER_API_KEY and self.TWITTER_API_SECRET
                    and self.TWITTER_ACCESS_TOKEN and self.TWITTER_ACCESS_SECRET)

    @property
    def github_configured(self) -> bool:
        return bool(self.GITHUB_TOKEN)

    @property
    def youtube_configured(self) -> bool:
        return bool(self.YOUTUBE_API_KEY or self.google_configured)
