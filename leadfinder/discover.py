"""Weekly discovery: search, read the best guides, list the businesses they name, check each one
in code, and suggest at most a handful for you to approve.

Searches rotate week by week through your query list, so the same guides aren't re-read.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import checks, text as t
from .ai import AI
from .config import Config
from .sources import BudgetReached, Page, SourceError, Sources, plain_get
from .store import Store


def queries_for_week(queries: list[str], week: int, count: int) -> list[str]:
    if not queries:
        return []
    start = (week * count) % len(queries)
    return [queries[(start + i) % len(queries)] for i in range(min(count, len(queries)))]


def check_candidate(cand: dict, page: Page, index: checks.Index, store: Store, conf: Config, ai: AI,
                    site=plain_get, now: datetime | None = None) -> tuple[str | None, dict]:
    """(why it is held back, or None) and the details a suggestion carries."""
    name = (cand.get("name") or "").strip()
    quote = cand.get("quote") or ""
    if not name:
        return "no name", {}
    if not t.quote_on_page(quote, page.text):
        return "the quote isn't on the page", {}
    if not t.quote_names(quote, name):
        return "the quote doesn't name it", {}
    known = index.exact(cand)
    if known:
        account, why = known
        return f"already have it: {account['name']} ({why})", {}
    if store.has_pending("new_lead", name):
        return "already suggested", {}
    may, how = checks.open_check(cand, page.text, page.published, conf, site, now=now)
    if not may:
        return how, {}
    fit = ai.fit(cand)
    if fit is None:
        return "fit could not be judged this time", {}
    score = max(0.0, min(1.0, float(fit.get("score", 0))))
    if score < conf.fit_cutoff:
        return f"not a fit ({round(score * 100)}%: {fit.get('reason', '')})", {}
    details = {k: cand.get(k) for k in ("industry", "tags", "area", "what_they_make", "website", "instagram", "line", "phone")}
    details.update({"fit": round(score, 3), "fit_reason": fit.get("reason", ""), "open_check": how,
                    "source_title": page.title})
    alike = index.look_alike(cand)
    if alike:
        account, why = alike
        details["maybe_same"] = {"id": account["id"], "name": account["name"], "why": why}
    return None, details


def run(conf: Config, store: Store, sources: Sources, ai: AI, *, week: int | None = None,
        site=plain_get, now: datetime | None = None) -> dict:
    week = week if week is not None else datetime.now(timezone.utc).isocalendar().week
    index = checks.Index(store.accounts(), store.aliases(), conf.phone_country_code)
    stale = checks.stale_sources(store.closed_counts())
    report = {"week": week, "searches": [], "suggested": [], "held": []}
    suggested = 0
    for query in queries_for_week(conf.queries, week, conf.searches_per_run):
        place = conf.place_for(query)
        row = {"query": query, "pages": [], "status": "ok"}
        report["searches"].append(row)
        try:
            results = sources.search(query)
        except (BudgetReached, SourceError) as e:
            row["status"] = f"search failed: {e}"
            continue
        pages: list[Page] = []
        for r in results:
            if len(pages) >= conf.pages_per_search:
                break
            if not checks.is_source(r.url) or r.url in stale:
                continue
            if not checks.names_place(f"{r.title} {r.description}", f"{r.title} {r.url}", place, conf.other_places):
                continue
            try:
                pages.append(sources.page(r.url))
            except (BudgetReached, SourceError) as e:
                row.setdefault("failed", []).append(f"{r.url}: {e}")
        for page in pages:
            row["pages"].append(page.url)
            for cand in ai.businesses(page.text, page.title, page.url):
                if suggested >= conf.max_proposals:
                    break
                held, details = check_candidate(cand, page, index, store, conf, ai, site, now)
                if held:
                    report["held"].append({"name": cand.get("name"), "why": held, "source": page.url})
                    continue
                pid = store.propose("new_lead", cand["name"].strip(), cand["quote"], page.url, details)
                index.names.setdefault(t.name_key(cand["name"]), {"id": -pid, "name": cand["name"]})
                report["suggested"].append({"id": pid, "name": cand["name"], "fit": details["fit"]})
                suggested += 1
    report["notes"] = sources.log + ai.log
    return report
