"""Owner search: for leads you approved, find the business's own website, read its about/team/
contact pages and any press interviews, and suggest the owner or decision maker by name.

Small businesses buy when the person who decides hears from you directly. Every suggestion carries
the exact sentence that names the person, and (when configured) a link to look the company up in
your country's official business registry. Registries are linked for you to check by hand, never
scraped: many forbid automated access.
"""
from __future__ import annotations

import re
import urllib.parse

from . import checks, text as t
from .ai import AI
from .config import Config
from .sources import BudgetReached, Page, SourceError, Sources
from .store import Store

ABOUT_PATH = re.compile(r"/(about|about-us|our-story|story|team|people|founder|who-we-are|contact|contact-us)\b", re.I)
PRESS_PER_LEAD = 2


def label(url: str) -> str:
    """The part of a host the business chose: 'nookbakery' for www.nookbakery.co.uk."""
    host = (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "net", "org", "ac", "or", "in"}:
        return re.sub(r"[^a-z0-9]", "", parts[-3])
    return re.sub(r"[^a-z0-9]", "", parts[-2]) if len(parts) >= 2 else ""


def looks_like_own_site(url: str, name: str) -> bool:
    """Not a directory, and the domain carries a distinctive word of the name."""
    if not checks.is_source(url):
        return False
    lab = label(url)
    tokens = [re.sub(r"[^a-z0-9]", "", w) for w in t.distinctive(name) if w.isascii()]
    tokens = [w for w in tokens if len(w) >= 3]
    return bool(tokens) and any(w in lab for w in tokens)


def registry_link(conf: Config, name: str) -> str | None:
    return conf.registry_url.format(name=urllib.parse.quote(t.trading_name(name))) if conf.registry_url else None


def targets(store: Store, limit: int, include_prospects: bool = False) -> list[dict]:
    statuses = ("lead", "prospect") if include_prospects else ("lead",)
    rows = [a for a in store.accounts() if a["status"] in statuses and not a.get("owner_name")]
    pending = {p["account_id"] for p in store.pending() if p["kind"] == "owner"}
    return [a for a in rows if a["id"] not in pending][:limit]


def find_website(account: dict, conf: Config, sources: Sources) -> Page | None:
    place = account.get("area") or (conf.places[0].name if conf.places else "")
    results = sources.search(f'"{t.trading_name(account["name"])}" {place}', recent=False)
    for r in results:
        if looks_like_own_site(r.url, account["name"]):
            home = f"{urllib.parse.urlparse(r.url).scheme}://{urllib.parse.urlparse(r.url).netloc}/"
            page = sources.page(home)
            if t.quote_names(f"{page.title} {page.text[:20000]}", account["name"]):
                return page
    return None


def own_pages(home: Page, sources: Sources, limit: int = 3) -> list[Page]:
    host = urllib.parse.urlparse(home.url).netloc
    picked, seen = [], set()
    for link in home.links:
        absolute = urllib.parse.urljoin(home.url, link).split("#")[0]
        if urllib.parse.urlparse(absolute).netloc != host or absolute in seen or not ABOUT_PATH.search(absolute):
            continue
        seen.add(absolute)
        try:
            picked.append(sources.page(absolute))
        except (BudgetReached, SourceError):
            break
        if len(picked) >= limit:
            break
    return [home, *picked]


def press_pages(account: dict, conf: Config, sources: Sources, own_host: str | None) -> list[Page]:
    query = f'"{t.trading_name(account["name"])}" founder'
    out = []
    for r in sources.search(query, recent=False):
        if len(out) >= PRESS_PER_LEAD:
            break
        if not checks.is_source(r.url) or (own_host and own_host in r.url):
            continue
        if not t.quote_names(f"{r.title} {r.description} {r.url}", account["name"]):
            continue
        try:
            out.append(sources.page(r.url))
        except (BudgetReached, SourceError):
            continue
    return out


def run(conf: Config, store: Store, sources: Sources, ai: AI, *, include_prospects: bool = False) -> dict:
    report = {"leads": [], "notes": []}
    for account in targets(store, conf.owners_per_run, include_prospects):
        row = {"name": account["name"], "status": "no owner found"}
        report["leads"].append(row)
        try:
            home = sources.page(account["website"]) if account.get("website") else find_website(account, conf, sources)
            if home and not account.get("website") and not store.has_pending("website", home.url, account["id"]):
                quote = next((ln.strip() for ln in home.text.splitlines() if t.quote_names(ln, account["name"])), home.title)
                store.propose("website", home.url, quote or home.url, home.url, {"business": account["name"]}, account["id"])
                row["website"] = home.url
            pages = own_pages(home, sources) if home else []
            pages += press_pages(account, conf, sources, urllib.parse.urlparse(home.url).netloc if home else None)
        except BudgetReached:
            row["status"] = "budget reached"
            break
        except SourceError as e:
            row["status"] = f"source failed: {e}"
            continue
        if not pages:
            continue
        answer = ai.owner(account["name"], [(p.url, p.text) for p in pages])
        if not answer or not answer.get("found") or answer.get("page_index") is None:
            continue
        idx = int(answer["page_index"])
        if not 0 <= idx < len(pages):
            continue
        page, person, quote = pages[idx], (answer.get("name") or "").strip(), answer.get("quote") or ""
        if not person or not t.quote_on_page(quote, page.text) or t.words(person).strip() not in t.words(quote):
            row["status"] = "owner answer failed the quote check"
            continue
        details = {"business": account["name"], "role": answer.get("role") or "", "registry": registry_link(conf, account["name"])}
        store.propose("owner", person, quote, page.url, details, account["id"])
        row["status"] = f"suggested {person} ({details['role']})"
    report["notes"] = sources.log + ai.log
    return report
