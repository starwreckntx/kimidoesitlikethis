#!/usr/bin/env python3
"""
One-time Google OAuth2 token generator.

Run this script ONCE to authorise Gmail + Drive + YouTube access.
It will print a GOOGLE_REFRESH_TOKEN that you paste into your .env file.

Prerequisites:
  1. Create a project at https://console.cloud.google.com
  2. Enable Gmail API, Drive API, and YouTube Data API v3
  3. Create an OAuth 2.0 Client ID (Desktop App type)
  4. Download the JSON and note your client_id and client_secret

Usage:
    python get_google_token.py \
        --client-id YOUR_CLIENT_ID \
        --client-secret YOUR_CLIENT_SECRET
"""

import argparse
import json
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:8765"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube",
]

_auth_code: list[str] = []


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            _auth_code.append(code)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Authorised! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>No code received.</h2>")

    def log_message(self, *args):
        pass  # silence access logs


def _get_auth_code(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    url = AUTH_URI + "?" + urllib.parse.urlencode(params)

    server = HTTPServer(("localhost", 8765), _CallbackHandler)
    t = Thread(target=server.handle_request)
    t.start()

    print(f"\nOpening browser for Google authorisation…\n{url}\n")
    webbrowser.open(url)
    t.join(timeout=120)
    server.server_close()

    if not _auth_code:
        raise RuntimeError("No auth code received within 120 seconds.")
    return _auth_code[0]


def _exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URI, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(description="Generate Google OAuth2 refresh token")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    code = _get_auth_code(args.client_id)
    tokens = _exchange_code(args.client_id, args.client_secret, code)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("ERROR: No refresh_token in response:", tokens)
        return

    print("\n" + "=" * 60)
    print("Add the following to your .env file:")
    print("=" * 60)
    print(f"GOOGLE_CLIENT_ID={args.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={args.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
    print("=" * 60)


if __name__ == "__main__":
    main()
