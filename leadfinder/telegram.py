"""Approve suggestions from your phone with a Telegram bot you create (optional; `leadfinder review`
does the same in a terminal).

Create a bot with @BotFather, put its token in TELEGRAM_BOT_TOKEN and your chat id in
TELEGRAM_CHAT_ID. `leadfinder telegram send` posts new suggestions with buttons; `leadfinder
telegram listen` waits for taps (long polling: no web server or public URL needed). Only button
presses from your chat are acted on.
"""
from __future__ import annotations

import html
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config as cfg
from .decisions import REASONS, decide, message
from .store import Store

CODES = {"a": ("add", None), "s": ("same", None), "v": ("save", None), "x": ("skip", None),
         "c": ("skip", "closed"), "u": ("skip", "customer"), "n": ("skip", "not_fit")}


class Bot:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)

    def call(self, method: str, payload: dict, timeout: int = 40) -> dict:
        req = urllib.request.Request(f"{self.base}/{method}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Telegram {method} failed: HTTP {e.code}") from None
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed")
        return data["result"]

    @classmethod
    def from_env(cls) -> "Bot":
        token, chat = cfg.secret("TELEGRAM_BOT_TOKEN"), cfg.secret("TELEGRAM_CHAT_ID")
        if not token or not chat:
            raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (see README).")
        return cls(token, chat)


def buttons(p: dict) -> list[list[dict]]:
    b = lambda text, code: {"text": text, "callback_data": f"lf:{p['id']}:{code}"}
    if p["kind"] == "new_lead":
        first = [b("Add", "a")]
        if p["details"].get("maybe_same"):
            first.append(b(f"Same as {p['details']['maybe_same']['name'][:24]}", "s"))
        return [first, [b(REASONS["closed"], "c"), b(REASONS["customer"], "u"), b(REASONS["not_fit"], "n")]]
    return [[b("Save", "v"), b("Not theirs", "x")]]


def send(store: Store, bot: Bot, limit: int = 8) -> int:
    sent = 0
    for p in store.pending(unsent_only=True)[:limit]:
        result = bot.call("sendMessage", {"chat_id": bot.chat_id, "text": html.escape(message(p)), "parse_mode": "HTML",
                                          "disable_web_page_preview": True, "reply_markup": {"inline_keyboard": buttons(p)}})
        store.mark_sent(p["id"], result["message_id"])
        sent += 1
    return sent


def handle(update: dict, store: Store, bot: Bot) -> str:
    q = update.get("callback_query")
    if not q:
        return "ignored"
    if str((q.get("message") or {}).get("chat", {}).get("id")) != bot.chat_id:
        return "ignored: another chat"
    parts = (q.get("data") or "").split(":")
    if len(parts) != 3 or parts[0] != "lf" or not parts[1].isdigit() or parts[2] not in CODES:
        bot.call("answerCallbackQuery", {"callback_query_id": q["id"], "text": "Unknown button"})
        return "ignored: unknown button"
    action, reason = CODES[parts[2]]
    note = decide(store, int(parts[1]), action, reason)
    bot.call("answerCallbackQuery", {"callback_query_id": q["id"], "text": note[:180]})
    p = store.proposal(int(parts[1]))
    if p and q.get("message"):
        bot.call("editMessageText", {"chat_id": bot.chat_id, "message_id": q["message"]["message_id"], "parse_mode": "HTML",
                                     "disable_web_page_preview": True,
                                     "text": html.escape(message(p)) + f"\n\n<b>{html.escape(note.capitalize())}</b>"})
    return note


def listen(store: Store, bot: Bot, offset_file: Path, once: bool = False) -> None:
    offset = int(offset_file.read_text()) if offset_file.exists() else 0
    while True:
        updates = bot.call("getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["callback_query"]}, timeout=45)
        for u in updates:
            offset = max(offset, u["update_id"] + 1)
            try:
                print(handle(u, store, bot))
            except RuntimeError as e:
                print(f"error: {e}")
            offset_file.write_text(str(offset))
        if once:
            return
        if not updates:
            time.sleep(1)
