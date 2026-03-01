"""
Tool registry – builds only the tools whose credentials are configured.
"""
import logging

logger = logging.getLogger(__name__)


def build_tools(config) -> dict:
    """
    Returns a dict of {tool_name: BaseTool} for all configured integrations.
    Tools with missing credentials are skipped with a warning.
    """
    tools: dict = {}

    # Browser (no credentials needed – always available)
    try:
        from .browser_tool import BrowserTool
        tools["browser"] = BrowserTool(headless=config.BROWSER_HEADLESS)
        logger.info("Tool registered: browser")
    except Exception as e:
        logger.warning("Browser tool unavailable: %s", e)

    # Gmail
    if config.google_configured:
        try:
            from .gmail_tool import GmailTool
            tools["gmail"] = GmailTool(config)
            logger.info("Tool registered: gmail")
        except Exception as e:
            logger.warning("Gmail tool unavailable: %s", e)
    else:
        logger.info("Gmail not configured (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN missing).")

    # Google Drive
    if config.google_configured:
        try:
            from .gdrive_tool import GDriveTool
            tools["google_drive"] = GDriveTool(config)
            logger.info("Tool registered: google_drive")
        except Exception as e:
            logger.warning("Google Drive tool unavailable: %s", e)
    else:
        logger.info("Google Drive not configured.")

    # YouTube
    if config.youtube_configured:
        try:
            from .youtube_tool import YouTubeTool
            tools["youtube"] = YouTubeTool(config)
            logger.info("Tool registered: youtube")
        except Exception as e:
            logger.warning("YouTube tool unavailable: %s", e)
    else:
        logger.info("YouTube not configured (YOUTUBE_API_KEY or Google OAuth missing).")

    # Slack
    if config.slack_configured:
        try:
            from .slack_tool import SlackTool
            tools["slack"] = SlackTool(config)
            logger.info("Tool registered: slack")
        except Exception as e:
            logger.warning("Slack tool unavailable: %s", e)
    else:
        logger.info("Slack not configured (SLACK_BOT_TOKEN missing).")

    # Twitter
    if config.twitter_configured:
        try:
            from .twitter_tool import TwitterTool
            tools["twitter"] = TwitterTool(config)
            logger.info("Tool registered: twitter")
        except Exception as e:
            logger.warning("Twitter tool unavailable: %s", e)
    else:
        logger.info("Twitter not configured (API keys missing).")

    # GitHub
    if config.github_configured:
        try:
            from .github_tool import GitHubTool
            tools["github"] = GitHubTool(config)
            logger.info("Tool registered: github")
        except Exception as e:
            logger.warning("GitHub tool unavailable: %s", e)
    else:
        logger.info("GitHub not configured (GITHUB_TOKEN missing).")

    logger.info("Active tools: %s", list(tools.keys()))
    return tools
