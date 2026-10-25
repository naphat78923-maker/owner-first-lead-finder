"""Web search and page fetching, with a paid provider first and a free one as backup.

- Firecrawl (paid, https://firecrawl.dev): search + clean page markdown.
- TinyFish (free Search/Fetch tier, https://tinyfish.ai): the backup when Firecrawl has no key,
  runs out of credits, or fails.
- Plain HTTP: fetches a page without any provider (used to check a business's own site loads).

Every page that is read is saved under data/pages and reused for 30 days, so quotes can always be
checked against exactly what was read. API keys are sent only to their own host: redirects are not
followed on API calls.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import config as cfg

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_BYTES = 4_000_000


class SourceError(RuntimeError):
    pass


class BudgetReached(RuntimeError):
    pass


@dataclass
class Result:
    url: str
    title: str = ""
    description: str = ""


@dataclass
class Page:
    url: str
    text: str
    title: str = ""
    published: str | None = None
    links: list[str] = field(default_factory=list)
    method: str = ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api(url: str, *, headers: dict, body: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **headers},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        kind = "auth" if e.code in (401, 403) else "credits or rate limit" if e.code in (402, 429) else f"HTTP {e.code}"
        raise SourceError(kind) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise SourceError(f"network: {type(e).__name__}") from None
    if len(raw) > MAX_BYTES:
        raise SourceError("response too large")
    return json.loads(raw)


class Firecrawl:
    name = "firecrawl"
    paid = True
    base = "https://api.firecrawl.dev/v2"

    def __init__(self, key: str):
        self.headers = {"Authorization": f"Bearer {key}"}

    def search(self, query: str, recent_days: int | None, limit: int = 8) -> list[Result]:
        body: dict = {"query": query, "limit": limit}
        if recent_days and recent_days <= 366:
            body["tbs"] = "qdr:y"
        data = _api(f"{self.base}/search", headers=self.headers, body=body)
        if data.get("success") is False:
            raise SourceError("search failed")
        rows = data.get("data")
        rows = rows.get("web", []) if isinstance(rows, dict) else rows or []
        return [Result(r.get("url", ""), r.get("title") or "", r.get("description") or "") for r in rows if r.get("url")]

    def fetch(self, url: str) -> Page:
        data = _api(f"{self.base}/scrape", headers=self.headers,
                    body={"url": url, "formats": ["markdown", "links"], "onlyMainContent": False}, timeout=90)
        d = data.get("data") or {}
        meta = d.get("metadata") or {}
        status = meta.get("statusCode")
        if data.get("success") is False or (status and int(status) >= 400) or not (d.get("markdown") or "").strip():
            raise SourceError("page failed")
        return Page(url, d["markdown"], meta.get("title") or "", meta.get("publishedTime") or meta.get("modifiedTime"),
                    [l for l in d.get("links") or [] if isinstance(l, str)], self.name)


class TinyFish:
    name = "tinyfish"
    paid = False

    def __init__(self, key: str, country: str = ""):
        self.headers = {"X-API-Key": key}
        self.country = country

    def search(self, query: str, recent_days: int | None, limit: int = 8) -> list[Result]:
        params = {"query": query}
        if self.country:
            params["location"] = self.country
        if recent_days:
            params["after_date"] = (datetime.now(timezone.utc) - timedelta(days=recent_days)).date().isoformat()
        data = _api("https://api.search.tinyfish.ai?" + urllib.parse.urlencode(params), headers=self.headers, timeout=40)
        if not isinstance(data.get("results"), list):
            raise SourceError("search failed")
        return [Result(r.get("url", ""), r.get("title") or "", r.get("snippet") or r.get("description") or "")
                for r in data["results"][:limit] if r.get("url")]

    def fetch(self, url: str) -> Page:
        data = _api("https://api.fetch.tinyfish.ai", headers=self.headers,
                    body={"urls": [url], "format": "markdown", "links": True}, timeout=90)
        items = data.get("results") or []
        if not items:
            raise SourceError("page failed")
        item = items[0]
        text = item.get("text") or item.get("content") or item.get("markdown") or ""
        status = item.get("status_code") or item.get("statusCode")
        final = item.get("final_url") or url
        if not text.strip() or (status and int(status) >= 400) or _host(final) != _host(url):
            raise SourceError("page failed or redirected away")
        links = [l if isinstance(l, str) else l.get("url") or l.get("href") or "" for l in item.get("links") or []]
        return Page(url, text, item.get("title") or "", item.get("published_date") or item.get("last_modified"),
                    [l for l in links if l], self.name)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def plain_get(url: str, timeout: int = 15) -> tuple[bool, Page | None]:
    """(loads, page) with plain HTTP and no provider: used for "is their own site still up"."""
    req = urllib.request.Request(url if "://" in url else "https://" + url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(600_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
            ok = r.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 400, None
    except Exception:  # noqa: BLE001 - DNS, TLS, timeout: the site does not load
        return False, None
    parser = _Text()
    parser.feed(body)
    text = re.sub(r"\n\s*\n+", "\n\n", html.unescape("".join(parser.parts))).strip()
    links = [urllib.parse.urljoin(url, l) for l in parser.links]
    return ok, Page(url, text, parser.title.strip(), None, links, "plain")


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


class PageCache:
    """Saved copies of every page read, so a quote can be checked against exactly what was read."""

    def __init__(self, root: Path):
        self.root = root / "pages"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.index: dict = json.loads(self.index_path.read_text()) if self.index_path.exists() else {}

    @staticmethod
    def _id(url: str) -> str:
        return hashlib.sha256(url.split("#")[0].rstrip("/").encode()).hexdigest()[:16]

    def get(self, url: str, max_age_days: float = 30) -> Page | None:
        entry = self.index.get(self._id(url))
        if not entry or time.time() - entry["saved"] > max_age_days * 86400:
            return None
        path = self.root / f"{self._id(url)}.md"
        if not path.exists():
            return None
        return Page(entry["url"], path.read_text(), entry.get("title", ""), entry.get("published"),
                    entry.get("links", []), entry.get("method", ""))

    def put(self, page: Page) -> Page:
        (self.root / f"{self._id(page.url)}.md").write_text(page.text)
        self.index[self._id(page.url)] = {"url": page.url, "title": page.title, "published": page.published,
                                           "links": page.links[:300], "method": page.method, "saved": time.time()}
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=1))
        return page


class Sources:
    """Tries each configured provider in order. A paid provider stops being used for the rest of
    the run once it fails for auth or credits, or once the run's budget is spent (search = 2 units,
    page = 1). Free calls are capped too, so a run can never loop forever."""

    def __init__(self, providers: list, budget: int, cache: PageCache, recent_days: int, free_call_cap: int = 40):
        self.providers = providers
        self.budget = budget
        self.spent = 0
        self.free_calls = 0
        self.free_call_cap = free_call_cap
        self.cache = cache
        self.recent_days = recent_days
        self.disabled: set[str] = set()
        self.log: list[str] = []

    @classmethod
    def from_config(cls, conf: cfg.Config, cache: PageCache) -> "Sources":
        made = []
        for name in conf.source_order:
            if name == "firecrawl" and cfg.secret("FIRECRAWL_API_KEY"):
                made.append(Firecrawl(cfg.secret("FIRECRAWL_API_KEY")))
            elif name == "tinyfish" and cfg.secret("TINYFISH_API_KEY"):
                made.append(TinyFish(cfg.secret("TINYFISH_API_KEY"), conf.country))
        if not made:
            raise SystemExit("No search provider: set FIRECRAWL_API_KEY and/or TINYFISH_API_KEY in .env.")
        return cls(made, conf.budget, cache, conf.recent_days)

    def _run(self, cost: int, call):
        last = "no provider available"
        for p in self.providers:
            if p.name in self.disabled:
                continue
            if p.paid and self.spent + cost > self.budget:
                continue
            if not p.paid and self.free_calls >= self.free_call_cap:
                continue
            try:
                if p.paid:
                    self.spent += cost
                else:
                    self.free_calls += 1
                return call(p)
            except SourceError as e:
                last = f"{p.name}: {e}"
                self.log.append(last)
                if "auth" in str(e) or "credits" in str(e):
                    self.disabled.add(p.name)
        raise BudgetReached(last) if "available" in last else SourceError(last)

    def search(self, query: str, recent: bool = True) -> list[Result]:
        return self._run(2, lambda p: p.search(query, self.recent_days if recent else None))

    def page(self, url: str, max_age_days: float = 30) -> Page:
        saved = self.cache.get(url, max_age_days)
        if saved:
            return saved
        return self.cache.put(self._run(1, lambda p: p.fetch(url)))
