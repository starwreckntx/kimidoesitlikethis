import asyncio
import logging
from typing import Any

from .base import BaseTool

logger = logging.getLogger(__name__)


class SlackTool(BaseTool):
    name = "slack"
    description = (
        "Interact with Slack. Actions: send_message, list_channels, get_channel_messages, "
        "search_messages, get_user_info, list_users."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send_message", "list_channels", "get_channel_messages",
                         "search_messages", "get_user_info", "list_users"],
                "description": "Slack action to perform.",
            },
            "channel": {"type": "string", "description": "Channel name or ID (e.g. #general)."},
            "text": {"type": "string", "description": "Message text to send."},
            "query": {"type": "string", "description": "Search query."},
            "user_id": {"type": "string", "description": "Slack user ID."},
            "limit": {"type": "integer", "description": "Max items to return. Default 20."},
        },
        "required": ["action"],
    }

    def __init__(self, config):
        from slack_sdk.web.async_client import AsyncWebClient
        self._client = AsyncWebClient(token=config.SLACK_BOT_TOKEN)

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "send_message":
                return await self._send_message(kwargs)
            elif action == "list_channels":
                return await self._list_channels(kwargs)
            elif action == "get_channel_messages":
                return await self._get_channel_messages(kwargs)
            elif action == "search_messages":
                return await self._search_messages(kwargs)
            elif action == "get_user_info":
                return await self._get_user_info(kwargs)
            elif action == "list_users":
                return await self._list_users(kwargs)
            else:
                return f"Unknown Slack action: {action}"
        except Exception as e:
            logger.error("Slack tool error", exc_info=True)
            return f"Slack error: {e}"

    async def _send_message(self, kwargs: dict) -> str:
        channel = kwargs.get("channel", "")
        text = kwargs.get("text", "")
        resp = await self._client.chat_postMessage(channel=channel, text=text)
        ts = resp["ts"]
        return f"Message sent to {channel} (ts={ts})."

    async def _list_channels(self, kwargs: dict) -> str:
        limit = int(kwargs.get("limit", 50))
        resp = await self._client.conversations_list(limit=limit, types="public_channel,private_channel")
        channels = resp.get("channels", [])
        if not channels:
            return "No channels found."
        lines = [f"#{c['name']} (ID: {c['id']}, members: {c.get('num_members', '?')})" for c in channels]
        return "\n".join(lines)

    async def _get_channel_messages(self, kwargs: dict) -> str:
        channel = kwargs.get("channel", "")
        limit = int(kwargs.get("limit", 20))
        resp = await self._client.conversations_history(channel=channel, limit=limit)
        messages = resp.get("messages", [])
        if not messages:
            return "No messages found."
        lines = []
        for m in reversed(messages):
            user = m.get("user", "bot")
            text = m.get("text", "")
            ts = m.get("ts", "")
            lines.append(f"[{ts}] {user}: {text}")
        return "\n".join(lines)

    async def _search_messages(self, kwargs: dict) -> str:
        query = kwargs.get("query", "")
        resp = await self._client.search_messages(query=query, count=int(kwargs.get("limit", 10)))
        matches = resp.get("messages", {}).get("matches", [])
        if not matches:
            return f"No messages found for '{query}'."
        lines = [
            f"#{m.get('channel', {}).get('name', '?')} [{m.get('ts', '')}]: {m.get('text', '')}"
            for m in matches
        ]
        return "\n".join(lines)

    async def _get_user_info(self, kwargs: dict) -> str:
        resp = await self._client.users_info(user=kwargs.get("user_id", ""))
        user = resp.get("user", {})
        profile = user.get("profile", {})
        return (
            f"Name: {profile.get('real_name', user.get('name'))}\n"
            f"Email: {profile.get('email', 'N/A')}\n"
            f"Title: {profile.get('title', 'N/A')}\n"
            f"Status: {profile.get('status_text', 'N/A')}"
        )

    async def _list_users(self, kwargs: dict) -> str:
        resp = await self._client.users_list(limit=int(kwargs.get("limit", 30)))
        members = [m for m in resp.get("members", []) if not m.get("is_bot") and not m.get("deleted")]
        lines = [
            f"{m.get('real_name', m['name'])} (@{m['name']}) – ID: {m['id']}"
            for m in members
        ]
        return "\n".join(lines) if lines else "No users found."
