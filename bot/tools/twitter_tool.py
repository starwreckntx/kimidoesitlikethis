import asyncio
import logging
from typing import Any

from .base import BaseTool

logger = logging.getLogger(__name__)


class TwitterTool(BaseTool):
    name = "twitter"
    description = (
        "Interact with Twitter/X. Actions: post_tweet, get_timeline, search_tweets, "
        "get_tweet, reply_tweet, get_user_tweets, get_user_profile."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["post_tweet", "get_timeline", "search_tweets",
                         "get_tweet", "reply_tweet", "get_user_tweets", "get_user_profile"],
                "description": "Twitter action to perform.",
            },
            "text": {"type": "string", "description": "Tweet text (max 280 chars)."},
            "tweet_id": {"type": "string", "description": "Tweet ID."},
            "username": {"type": "string", "description": "Twitter username (without @)."},
            "query": {"type": "string", "description": "Search query."},
            "count": {"type": "integer", "description": "Number of results. Default 10."},
        },
        "required": ["action"],
    }

    def __init__(self, config):
        import tweepy
        # v2 async client
        self._client = tweepy.Client(
            bearer_token=config.TWITTER_BEARER_TOKEN,
            consumer_key=config.TWITTER_API_KEY,
            consumer_secret=config.TWITTER_API_SECRET,
            access_token=config.TWITTER_ACCESS_TOKEN,
            access_token_secret=config.TWITTER_ACCESS_SECRET,
            wait_on_rate_limit=False,
        )

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "post_tweet":
                return await asyncio.to_thread(self._post_tweet, kwargs)
            elif action == "get_timeline":
                return await asyncio.to_thread(self._get_timeline, kwargs)
            elif action == "search_tweets":
                return await asyncio.to_thread(self._search_tweets, kwargs)
            elif action == "get_tweet":
                return await asyncio.to_thread(self._get_tweet, kwargs)
            elif action == "reply_tweet":
                return await asyncio.to_thread(self._reply_tweet, kwargs)
            elif action == "get_user_tweets":
                return await asyncio.to_thread(self._get_user_tweets, kwargs)
            elif action == "get_user_profile":
                return await asyncio.to_thread(self._get_user_profile, kwargs)
            else:
                return f"Unknown Twitter action: {action}"
        except Exception as e:
            logger.error("Twitter tool error", exc_info=True)
            return f"Twitter error: {e}"

    def _fmt_tweet(self, t) -> str:
        if hasattr(t, "data"):
            t = t.data
        return f"[{getattr(t, 'id', '?')}] {getattr(t, 'text', '')}"

    def _post_tweet(self, kwargs: dict) -> str:
        resp = self._client.create_tweet(text=kwargs.get("text", ""))
        tweet_id = resp.data["id"]
        return f"Tweet posted. ID: {tweet_id}"

    def _get_timeline(self, kwargs: dict) -> str:
        # Get authenticated user's timeline (home timeline)
        me = self._client.get_me()
        user_id = me.data.id
        resp = self._client.get_users_tweets(
            id=user_id,
            max_results=min(int(kwargs.get("count", 10)), 100),
            tweet_fields=["created_at", "text"],
        )
        if not resp.data:
            return "No tweets found."
        return "\n".join(self._fmt_tweet(t) for t in resp.data)

    def _search_tweets(self, kwargs: dict) -> str:
        query = kwargs.get("query", "")
        resp = self._client.search_recent_tweets(
            query=query,
            max_results=min(int(kwargs.get("count", 10)), 100),
            tweet_fields=["created_at", "author_id", "text"],
        )
        if not resp.data:
            return f"No tweets found for '{query}'."
        return "\n".join(self._fmt_tweet(t) for t in resp.data)

    def _get_tweet(self, kwargs: dict) -> str:
        resp = self._client.get_tweet(
            id=kwargs.get("tweet_id", ""),
            tweet_fields=["created_at", "author_id", "public_metrics", "text"],
        )
        if not resp.data:
            return "Tweet not found."
        t = resp.data
        metrics = getattr(t, "public_metrics", {}) or {}
        return (
            f"ID: {t.id}\n"
            f"Text: {t.text}\n"
            f"Likes: {metrics.get('like_count', 0)} | "
            f"Retweets: {metrics.get('retweet_count', 0)} | "
            f"Replies: {metrics.get('reply_count', 0)}\n"
            f"Created: {getattr(t, 'created_at', 'N/A')}"
        )

    def _reply_tweet(self, kwargs: dict) -> str:
        resp = self._client.create_tweet(
            text=kwargs.get("text", ""),
            in_reply_to_tweet_id=kwargs.get("tweet_id", ""),
        )
        return f"Reply posted. ID: {resp.data['id']}"

    def _get_user_tweets(self, kwargs: dict) -> str:
        username = kwargs.get("username", "")
        user = self._client.get_user(username=username)
        if not user.data:
            return f"User @{username} not found."
        resp = self._client.get_users_tweets(
            id=user.data.id,
            max_results=min(int(kwargs.get("count", 10)), 100),
            tweet_fields=["created_at", "text"],
        )
        if not resp.data:
            return f"No tweets from @{username}."
        return "\n".join(self._fmt_tweet(t) for t in resp.data)

    def _get_user_profile(self, kwargs: dict) -> str:
        username = kwargs.get("username", "")
        resp = self._client.get_user(
            username=username,
            user_fields=["name", "description", "public_metrics", "created_at", "verified"],
        )
        if not resp.data:
            return f"User @{username} not found."
        u = resp.data
        m = getattr(u, "public_metrics", {}) or {}
        return (
            f"@{username} ({getattr(u, 'name', 'N/A')})\n"
            f"Bio: {getattr(u, 'description', 'N/A')}\n"
            f"Followers: {m.get('followers_count', 0)} | "
            f"Following: {m.get('following_count', 0)} | "
            f"Tweets: {m.get('tweet_count', 0)}"
        )
