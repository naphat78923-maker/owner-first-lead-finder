"""Checks every suggestion must pass before it reaches you. Code decides; the AI never does.

- Already known: same name (legal suffixes ignored), a saved alias, the same website domain,
  social handle or phone as a business you have. Any one holds the lead back.
- Looks like a known business: a distinctive word of one name starts a word of the other
  ("Fern Table" / "Fernleaf"). Not held back, but marked "might be the same as ...".
- Still open: the source must not say it closed; then either the business's own site loads (and
  doesn't say it closed) or the source is dated recently. Old "best of" guides list closed shops.
- Right place: a search result is only read if it names the city you searched for, and its
  title or address names no other city (searches drift abroad).
- Not a directory: social networks, review sites, maps, delivery apps and job boards are never
  read as sources.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import text as t
from .config import Config, Place

CLOSED_MARKERS = re.compile(
    r"permanently closed|temporarily closed|now closed|has closed|have closed|closed down|closed its doors|"
    r"no longer (?:open|operating|in business)|shut down|ปิดกิจการ|ปิดถาวร|ปิดให้บริการถาวร|ปิดตัว", re.I)

NOT_A_SOURCE = re.compile(
    r"(^|\.)(facebook|instagram|tiktok|twitter|x|youtube|linkedin|line|lin\.ee|pinterest|threads|reddit|"
    r"wongnai|tripadvisor|openrice|happycow|yelp|foursquare|google|goo\.gl|maps\.app|restaurantguru|zomato|"
    r"grab|lineman|foodpanda|ubereats|deliveroo|doordash|shopee|lazada|amazon|agoda|booking|klook|"
    r"wikipedia|wikiwand|opencorporates|zoominfo|rocketreach|glassdoor|indeed|jobsdb|jobthai|careerjet|monster)"
    r"\.[a-z.]+$", re.I)
JOB_PATH = re.compile(r"/(jobs?|careers?|vacanc|hiring|recruit)", re.I)

STALE_SOURCE_CLOSED = 2


class Index:
    """Everything you already know, keyed every way a business can be recognised."""

    def __init__(self, accounts: list[dict], aliases: list[dict] | None = None, phone_country_code: str = ""):
        self.cc = phone_country_code
        self.by_id = {a["id"]: a for a in accounts}
        self.names: dict[str, dict] = {}
        self.domains: dict[str, dict] = {}
        self.handles: dict[str, dict] = {}
        self.phones: dict[str, dict] = {}
        for a in accounts:
            self._add(a, "name", a.get("name"))
            self._add(a, "domain", a.get("website"))
            self._add(a, "handle", a.get("instagram"))
            self._add(a, "handle", a.get("line"))
            self._add(a, "phone", a.get("phone"))
        for al in aliases or []:
            a = self.by_id.get(al.get("account_id"))
            if a:
                self._add(a, al.get("kind"), al.get("value"))

    def _add(self, account: dict, kind: str | None, value: str | None) -> None:
        if not value:
            return
        if kind == "name" and t.name_key(value):
            self.names.setdefault(t.name_key(value), account)
        elif kind == "domain" and t.domain(value):
            self.domains.setdefault(t.domain(value), account)
        elif kind == "handle":
            h = t.handle(value) or value.strip("@ ").lower()
            if h:
                self.handles.setdefault(h, account)
        elif kind == "phone" and t.phone_key(value, self.cc):
            self.phones.setdefault(t.phone_key(value, self.cc), account)

    def exact(self, cand: dict) -> tuple[dict, str] | None:
        checks = [
            (self.names.get(t.name_key(cand.get("name"))), "same name"),
            (self.domains.get(t.domain(cand.get("website")) or ""), "same website"),
            (self.handles.get(t.handle(cand.get("instagram")) or ""), "same Instagram"),
            (self.handles.get(t.handle(cand.get("line")) or ""), "same LINE"),
            (self.phones.get(t.phone_key(cand.get("phone"), self.cc) or ""), "same phone"),
        ]
        return next(((a, why) for a, why in checks if a), None)

    def look_alike(self, cand: dict) -> tuple[dict, str] | None:
        mine = t.distinctive(cand.get("name"))
        if not mine:
            return None
        best = None
        for a in self.by_id.values():
            theirs = t.distinctive(a.get("name"))
            shared = [(x, y) for x in mine for y in theirs if len(min(x, y, key=len)) >= 4 and (x.startswith(y) or y.startswith(x))]
            if not shared:
                continue
            score = len(shared) / max(len(mine), len(theirs)) + (0.5 if a.get("status") == "customer" else 0)
            if not best or score > best[0]:
                x, y = shared[0]
                best = (score, a, f'"{x}" in both names' if x == y else f'"{x}" / "{y}"')
        return (best[1], best[2]) if best else None


def is_source(url: str) -> bool:
    """A page worth reading as a source: not social, a directory, delivery or jobs."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    return url.startswith("http") and bool(host) and not NOT_A_SOURCE.search(host) and not JOB_PATH.search(parsed.path)


def names_place(result_text: str, title_and_url: str, place: Place | None, other_places: list[str]) -> bool:
    """The result is about the place searched for, and its title/address names no other city."""
    tu = title_and_url.lower()
    # Plain substring on purpose: "noodlenyc.example" is in New York.
    if any(o in tu for o in other_places):
        return False
    if place is None:
        return True
    hay = f"{result_text} {title_and_url}".lower()
    return any(m.lower() in hay for m in [place.name, *place.match])


REFERS_BACK = re.compile(r"^\s*(it|they|the (shop|store|bakery|cafe|café|restaurant|place|team|owners?))\b", re.I)


def says_closed(page_text: str, name: str) -> bool:
    """A closing phrase in a sentence that names the business, or in the next sentence when it
    refers back ("It has closed..."). A guide's neighbouring entry closing doesn't count. On a
    page that never names the business (its own site), any closing phrase counts."""
    n = t.fold(t.trading_name(name)).strip()
    sentences = [s for s in re.split(r"(?<=[.!?。])\s+|\n+", t.fold(page_text)) if s.strip()]
    hits = [i for i, s in enumerate(sentences) if n and n in s]
    if not hits:
        return bool(CLOSED_MARKERS.search(t.fold(page_text)))
    for i in hits:
        if CLOSED_MARKERS.search(sentences[i]):
            return True
        if i + 1 < len(sentences) and REFERS_BACK.search(sentences[i + 1]) and CLOSED_MARKERS.search(sentences[i + 1]):
            return True
    return False


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc) if m else None


def open_check(cand: dict, source_text: str, source_published: str | None, conf: Config, site, *,
               now: datetime | None = None) -> tuple[bool, str]:
    """(may suggest, how it was checked). `site(url)` returns (loads, page or None)."""
    now = now or datetime.now(timezone.utc)
    name = cand.get("name") or ""
    if says_closed(source_text, name):
        return False, "the source says it closed"
    website = cand.get("website")
    if website:
        loads, page = site(website)
        if loads and not (page and says_closed(page.text, name)):
            return True, f"their site loads ({t.domain(website)})"
        if loads:
            return False, "their own site says it closed"
        return False, f"their own site ({t.domain(website)}) doesn't load: may be closed"
    published = parse_date(source_published)
    if published and now - published <= timedelta(days=30.5 * conf.open_evidence_months):
        return True, f"named in an article from {published:%b %Y}"
    when = f"from {published:%b %Y}" if published else "undated"
    return False, f"can't confirm it's still open (no website; the source is {when})"


def stale_sources(closed_counts: dict[str, int]) -> set[str]:
    """Source pages that led to shops you marked Closed at least twice: not read again."""
    return {url for url, n in closed_counts.items() if n >= STALE_SOURCE_CLOSED}
