# kimidoesitlikethis

A **Telegram-triggered personal assistant daemon** powered by Anthropic's Claude DeepAgent (extended thinking) with integrations for Gmail, Google Drive, Slack, Twitter/X, YouTube, GitHub, and a web browser.

## How it works

```
Telegram message
      │
      ▼
  ┌─────────────────────────────────┐
  │      Telegram Bot Handler       │
  │  • Authorise user               │
  │  • Acknowledge immediately      │
  │  • Queue if busy                │
  └─────────────┬───────────────────┘
                │
                ▼
  ┌─────────────────────────────────┐
  │         DeepAgent Loop          │
  │  Claude (extended thinking)     │
  │                                 │
  │  ┌──────────┐  ┌─────────────┐  │
  │  │ Reasoning│  │  Tool calls │  │
  │  │ (thinking│→ │  (parallel) │  │
  │  │  blocks) │  └──────┬──────┘  │
  │  └──────────┘         │         │
  └─────────────────────  │ ────────┘
                          │
           ┌──────────────┼──────────────────────┐
           │              │                      │
      ask_user      parallel tools          browser
      (pauses,      (Gmail, Drive,          (web search,
       awaits       Slack, Twitter,          page fetch,
       Telegram     YouTube, GitHub)         form fill)
       reply)
           │
           ▼
  Final response → Telegram chat
```

### Key behaviours

- **Immediate acknowledgement** – you get a "Working on it…" message within seconds, even for complex tasks.
- **Extended thinking** – Claude reasons deeply (configurable token budget) before acting.
- **ask_user tool** – the agent can pause mid-task and ask you a clarifying question via Telegram.
- **Task queuing** – if you send a second message while one task is running, it's queued and processed next.
- **Conversation memory** – the bot remembers context within a 30-minute window; `/clear` resets it.
- **Graceful degradation** – tools with missing credentials are silently skipped; the bot still runs with whatever is configured.

---

## Quick start

### 1. Clone & set up

```bash
git clone https://github.com/starwreckntx/kimidoesitlikethis
cd kimidoesitlikethis
bash setup.sh
```

### 2. Configure `.env`

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. (Google only) Generate OAuth refresh token

```bash
python get_google_token.py \
  --client-id YOUR_CLIENT_ID \
  --client-secret YOUR_CLIENT_SECRET
# Paste the printed GOOGLE_REFRESH_TOKEN into .env
```

### 4. Start the daemon

```bash
source .venv/bin/activate
python main.py
```

---

## Credentials required

| Service        | What you need                                                                 |
|----------------|-------------------------------------------------------------------------------|
| **Telegram**   | Bot token from [@BotFather](https://t.me/BotFather); your Telegram user ID   |
| **Anthropic**  | API key from [console.anthropic.com](https://console.anthropic.com)           |
| **Gmail/Drive/YouTube** | Google Cloud project with APIs enabled + OAuth2 client credentials |
| **Slack**      | Bot token (`xoxb-…`) from [api.slack.com](https://api.slack.com/apps)        |
| **Twitter/X**  | Developer app credentials from [developer.x.com](https://developer.x.com)    |
| **GitHub**     | Personal access token from GitHub settings                                    |

---

## Available tools

| Tool           | Capabilities |
|----------------|--------------|
| `gmail`        | List / read / send / reply / draft / trash emails |
| `google_drive` | List / search / read / create / share files & folders |
| `youtube`      | Search videos, get video/channel info, trending, playlists |
| `slack`        | Send messages, list channels, search, get user info |
| `twitter`      | Post / search / read tweets, get user profiles |
| `github`       | Manage repos, issues, PRs, search code, notifications |
| `browser`      | DuckDuckGo web search, fetch & parse any webpage, Playwright forms/screenshots |

---

## Example requests

```
"Summarise my last 5 unread emails"
"Send a Slack message to #engineering: deployment scheduled for Friday"
"Search YouTube for LangChain tutorials and give me the top 3"
"Post a tweet: Just shipped a new feature! #python #ai"
"Open a GitHub issue in myrepo: 'Login fails on Safari'"
"What's trending on Hacker News today?"  (browser)
"Search my Drive for the Q4 report and email it to bob@example.com"
```

---

## Architecture

```
kimidoesitlikethis/
├── main.py                    # Entry point / daemon start
├── config.py                  # Environment-based config
├── requirements.txt
├── .env.example
├── setup.sh                   # One-command setup
├── get_google_token.py        # OAuth2 helper
└── bot/
    ├── telegram_bot.py        # Telegram handler (ack, queue, ask_user flow)
    ├── agent.py               # DeepAgent – Claude tool-use loop
    └── tools/
        ├── registry.py        # Builds only configured tools
        ├── base.py            # BaseTool ABC
        ├── gmail_tool.py
        ├── gdrive_tool.py
        ├── slack_tool.py
        ├── twitter_tool.py
        ├── youtube_tool.py
        ├── github_tool.py
        └── browser_tool.py
```

---

## Running as a systemd service (Linux)

```ini
# /etc/systemd/system/kimidoesitlikethis.service
[Unit]
Description=kimidoesitlikethis Telegram Assistant
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/kimidoesitlikethis
ExecStart=/path/to/kimidoesitlikethis/.venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/path/to/kimidoesitlikethis/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now kimidoesitlikethis
sudo journalctl -fu kimidoesitlikethis
```
