"""Decide suggestions in a terminal, one at a time."""
from __future__ import annotations

from .decisions import decide, message
from .store import Store

LEAD_KEYS = {"a": ("add", None), "s": ("same", None), "c": ("skip", "closed"), "u": ("skip", "customer"), "n": ("skip", "not_fit")}
FACT_KEYS = {"y": ("save", None), "n": ("skip", None)}


def review(store: Store, ask=input) -> None:
    pending = store.pending()
    if not pending:
        print("Nothing waiting.")
        return
    for p in pending:
        print("\n" + message(p))
        if p["kind"] == "new_lead":
            same = " [s] same as known" if p["details"].get("maybe_same") else ""
            prompt, keys = f"[a] add{same} [c] closed [u] customer [n] not a fit [enter] later [q] quit: ", LEAD_KEYS
        else:
            prompt, keys = "[y] save [n] not theirs [enter] later [q] quit: ", FACT_KEYS
        choice = ask(prompt).strip().lower()
        if choice == "q":
            return
        if choice in keys:
            print(decide(store, p["id"], *keys[choice]))
