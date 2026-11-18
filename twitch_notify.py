#!/usr/bin/env python3
"""
Twitch go-live notifier for GitHub Actions.

Runs ONE check each time it's called (the workflow calls it every few minutes),
alerts for anyone who has newly gone live, and remembers who it already alerted
in state.json so you never get duplicate alerts.

Secrets (set in GitHub: Settings > Secrets and variables > Actions):
  TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET   (required)
  DISCORD_WEBHOOK_URL                      (optional)
  NTFY_TOPIC                               (optional)

Run with --test to send a test alert and exit.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

STREAMERS = {
    "kaicenat": "Kai Cenat",
    "lacy": "Lacy",
    "clix": "Clix",
    "stableronaldo": "StableRonaldo",
}

STATE_FILE = "state.json"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
STREAMS_URL = "https://api.twitch.tv/helix/streams"
UA = "twitch-notifier/1.0"

CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()


def http(url, headers=None, data=None, parse=True):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode()
        return json.loads(body) if parse else body


def send_discord(text):
    if not DISCORD_WEBHOOK:
        return
    try:
        http(
            DISCORD_WEBHOOK,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"content": text}).encode(),
            parse=False,
        )
    except Exception as e:
        print(f"Discord alert failed: {e}")


def send_phone(title, text, url=""):
    if not NTFY_TOPIC:
        return
    headers = {"Title": title, "Priority": "high"}
    if url:
        headers["Click"] = url
    try:
        http(
            f"https://ntfy.sh/{urllib.parse.quote(NTFY_TOPIC)}",
            headers=headers,
            data=text.encode("utf-8"),
            parse=False,
        )
    except Exception as e:
        print(f"Phone alert failed: {e}")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f), True
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, False


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def main():
    if "--test" in sys.argv:
        print("Sending test alert...")
        send_discord("✅ Test alert: your Twitch notifier is connected.")
        send_phone("Twitch notifier test", "Your Twitch notifier is connected.")
        print("Done. Check Discord / your phone.")
        return

    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("Missing TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET secret.")

    try:
        token_data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        }).encode()
        token = http(TOKEN_URL, data=token_data)["access_token"]

        headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {token}"}
        qs = "&".join(f"user_login={urllib.parse.quote(l)}" for l in STREAMERS)
        live = {s["user_login"]: s for s in http(f"{STREAMS_URL}?{qs}", headers=headers)["data"]}
    except urllib.error.HTTPError as e:
        sys.exit(f"Twitch API error {e.code}: {e.read().decode(errors='replace')}")
    except Exception as e:
        sys.exit(f"Check failed: {e}")

    state, had_state = load_state()
    new_state = dict(state)

    for login, stream in live.items():
        stream_id = stream["id"]
        if state.get(login) == stream_id:
            continue  # already alerted for this stream
        new_state[login] = stream_id

        if not had_state:
            # First ever run: record who's live but don't alert for them
            print(f"First run - noting {STREAMERS[login]} is already live (no alert).")
            continue

        name = STREAMERS[login]
        url = f"https://twitch.tv/{login}"
        game = stream.get("game_name") or "Unknown category"
        title = stream.get("title") or ""
        print(f"ALERT: {name} is live - {game} - {title}")
        send_discord(f"🔴 **{name}** just went live!\n{game} - {title}\n{url}")
        send_phone(f"{name} is live", f"{game} - {title}", url)

    if not live:
        print("Nobody is live.")

    if new_state != state or not had_state:
        save_state(new_state)


if __name__ == "__main__":
    main()
