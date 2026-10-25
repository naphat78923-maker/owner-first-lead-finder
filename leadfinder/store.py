"""A small SQLite database: the businesses you already know, suggestions waiting for you, and
where every saved fact came from.

Bring your own list with `leadfinder import accounts.csv` so the finder never suggests a shop you
already sell to; take approved leads to your CRM or spreadsheet with `leadfinder export`.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'prospect',   -- customer | prospect | lead
  website TEXT, phone TEXT, instagram TEXT, line TEXT,
  industry TEXT, area TEXT, notes TEXT,
  owner_name TEXT, owner_role TEXT,
  source TEXT,                                -- 'import' or 'leadfinder'
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aliases (
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                         -- name | domain | handle | phone
  value TEXT NOT NULL,
  UNIQUE (account_id, kind, value)
);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                         -- new_lead | owner
  account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                         -- the business (new_lead) or the person (owner)
  details TEXT NOT NULL DEFAULT '{}',         -- JSON
  quote TEXT NOT NULL,
  source_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',     -- pending | added | skipped | linked
  reason TEXT,                                -- why it was skipped: closed | customer | not_fit
  message_id INTEGER,                         -- Telegram message, when sent there
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  field TEXT NOT NULL, value TEXT NOT NULL,
  quote TEXT NOT NULL, source_url TEXT NOT NULL, method TEXT,
  created_at TEXT NOT NULL
);
"""

ACCOUNT_FIELDS = ("name", "status", "website", "phone", "instagram", "line", "industry", "area", "notes")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    # ── accounts ──
    def accounts(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM accounts")]

    def aliases(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM aliases")]

    def add_account(self, **fields) -> int:
        row = {k: fields.get(k) for k in ACCOUNT_FIELDS}
        row["status"] = row["status"] or "prospect"
        cur = self.db.execute(
            f"INSERT INTO accounts ({', '.join(row)}, source, created_at) VALUES ({', '.join('?' * len(row))}, ?, ?)",
            [*row.values(), fields.get("source", "leadfinder"), now()])
        self.db.commit()
        return int(cur.lastrowid)

    def add_alias(self, account_id: int, kind: str, value: str) -> None:
        if value:
            self.db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?, ?)", (account_id, kind, value))
            self.db.commit()

    def set_owner(self, account_id: int, name: str, role: str) -> None:
        self.db.execute("UPDATE accounts SET owner_name = ?, owner_role = ? WHERE id = ?", (name, role, account_id))
        self.db.commit()

    def import_csv(self, path: Path) -> int:
        """Columns (header row, any order): name, status, website, phone, instagram, line, industry, area, notes."""
        n = 0
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                self.add_account(**{k: (row.get(k) or "").strip() or None for k in ACCOUNT_FIELDS if k != "name"},
                                 name=name, source="import")
                n += 1
        return n

    def export_csv(self, path: Path, status: str = "lead") -> int:
        rows = [dict(r) for r in self.db.execute("SELECT * FROM accounts WHERE status = ? ORDER BY created_at", (status,))]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["name", "industry", "area", "website", "phone", "instagram", "line",
                                              "owner_name", "owner_role", "notes", "created_at"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    # ── proposals ──
    def propose(self, kind: str, name: str, quote: str, source_url: str, details: dict, account_id: int | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO proposals (kind, account_id, name, details, quote, source_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, account_id, name, json.dumps(details, ensure_ascii=False), quote, source_url, now()))
        self.db.commit()
        return int(cur.lastrowid)

    def proposal(self, pid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
        return _proposal(r) if r else None

    def pending(self, unsent_only: bool = False) -> list[dict]:
        q = "SELECT * FROM proposals WHERE status = 'pending'" + (" AND message_id IS NULL" if unsent_only else "") + " ORDER BY id"
        return [_proposal(r) for r in self.db.execute(q)]

    def has_pending(self, kind: str, name: str, account_id: int | None = None) -> bool:
        return self.db.execute(
            "SELECT 1 FROM proposals WHERE kind = ? AND name = ? AND coalesce(account_id, 0) = ? AND status IN ('pending', 'added')",
            (kind, name, account_id or 0)).fetchone() is not None

    def mark_sent(self, pid: int, message_id: int) -> None:
        self.db.execute("UPDATE proposals SET message_id = ? WHERE id = ?", (message_id, pid))
        self.db.commit()

    def settle(self, pid: int, status: str, reason: str | None = None, account_id: int | None = None) -> None:
        self.db.execute("UPDATE proposals SET status = ?, reason = ?, decided_at = ?, account_id = coalesce(?, account_id) WHERE id = ?",
                        (status, reason, now(), account_id, pid))
        self.db.commit()

    def closed_counts(self) -> dict[str, int]:
        """How many times each source page led to a shop you marked Closed."""
        rows = self.db.execute("SELECT source_url, count(*) n FROM proposals WHERE reason = 'closed' GROUP BY source_url")
        return {r["source_url"]: r["n"] for r in rows}

    # ── evidence ──
    def record(self, account_id: int, field: str, value: str, quote: str, source_url: str, method: str = "") -> None:
        self.db.execute("INSERT INTO evidence (account_id, field, value, quote, source_url, method, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (account_id, field, value, quote, source_url, method, now()))
        self.db.commit()


def _proposal(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["details"] = json.loads(d["details"] or "{}")
    return d
