"""What a decision does, the same from Telegram or the terminal. Nothing is saved without one.

new_lead: add (becomes an account with status 'lead'), same (it is a business you already have:
its name and website are remembered as aliases), or skip with a reason: closed, customer, not_fit.
A source page that leads to shops you mark Closed twice is not read again.
website / owner: save or skip.
"""
from __future__ import annotations

from . import text as t
from .store import Store

REASONS = {"closed": "Closed", "customer": "Already a customer", "not_fit": "Not a fit"}


def message(p: dict) -> str:
    """Plain-text summary of a suggestion (Telegram escapes it; the terminal prints it)."""
    d = p["details"]
    if p["kind"] == "new_lead":
        lines = [f"New lead: {p['name']}", f"{d.get('industry') or ''}{' · ' + d['area'] if d.get('area') else ''}".strip(" ·")]
        if d.get("what_they_make"):
            lines.append(f"Makes: {d['what_they_make']}")
        lines.append(f"Fit: {round((d.get('fit') or 0) * 100)}%. {d.get('fit_reason', '')}")
        lines.append(f"Open: {d.get('open_check', '')}")
        if d.get("maybe_same"):
            lines.append(f"Might be: {d['maybe_same']['name']} ({d['maybe_same']['why']})")
    elif p["kind"] == "owner":
        lines = [f"Owner for {d.get('business')}: {p['name']} ({d.get('role') or 'role not stated'})"]
        if d.get("registry"):
            lines.append(f"Check the registry: {d['registry']}")
    else:
        lines = [f"Website for {d.get('business')}: {p['name']}"]
    lines += [f"“{p['quote']}”", f"Source: {p['source_url']}"]
    return "\n".join(x for x in lines if x)


def decide(store: Store, pid: int, action: str, reason: str | None = None) -> str:
    """Apply one decision; returns a short note. A decided suggestion can't be decided again."""
    p = store.proposal(pid)
    if not p:
        return "not found"
    if p["status"] != "pending":
        return f"already {p['status']}"
    d = p["details"]

    if p["kind"] == "new_lead":
        if action == "add":
            known = [a for a in store.accounts() if t.name_key(a["name"]) == t.name_key(p["name"])]
            if known:
                store.settle(pid, "linked", "customer", known[0]["id"])
                return f"already have {known[0]['name']}"
            notes = f"Found in {p['source_url']}: “{p['quote']}”"
            aid = store.add_account(name=p["name"], status="lead", website=d.get("website"), phone=d.get("phone"),
                                    instagram=d.get("instagram"), line=d.get("line"), industry=d.get("industry"),
                                    area=d.get("area"), notes=notes)
            store.record(aid, "name", p["name"], p["quote"], p["source_url"])
            store.settle(pid, "added", None, aid)
            return "added"
        if action == "same" and d.get("maybe_same"):
            aid = d["maybe_same"]["id"]
            store.add_alias(aid, "name", p["name"])
            if t.domain(d.get("website")):
                store.add_alias(aid, "domain", t.domain(d["website"]))
            store.settle(pid, "linked", "customer", aid)
            return f"linked to {d['maybe_same']['name']}"
        if action == "skip":
            store.settle(pid, "skipped", reason if reason in REASONS else None)
            return f"skipped{': ' + REASONS[reason].lower() if reason in REASONS else ''}"
        return "unknown action"

    if action == "save":
        if p["kind"] == "owner":
            store.set_owner(p["account_id"], p["name"], d.get("role") or "")
            store.record(p["account_id"], "owner", p["name"], p["quote"], p["source_url"])
        elif p["kind"] == "website":
            store.db.execute("UPDATE accounts SET website = coalesce(website, ?) WHERE id = ?", (p["name"], p["account_id"]))
            store.db.commit()
            store.record(p["account_id"], "website", p["name"], p["quote"], p["source_url"])
        store.settle(pid, "added")
        return "saved"
    if action == "skip":
        store.settle(pid, "skipped")
        return "skipped"
    return "unknown action"
