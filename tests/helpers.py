"""Fakes for offline tests: no network, no keys. Every business here is made up."""
from __future__ import annotations

import tempfile
from pathlib import Path

from leadfinder.config import Config, Place
from leadfinder.sources import Page, PageCache, Result, Sources
from leadfinder.store import Store


def conf(**over) -> Config:
    base = dict(
        business_name="Test Butter Co.", product="plant-based butter", pitch="", ideal_customers=["bakeries"],
        exclude=["competitors"], country="TH",
        places=[Place("Bangkok", ["bangkok", "bkk", "กรุงเทพ"]), Place("Chiang Mai", ["chiang mai"])],
        queries=["new vegan bakery Bangkok", "patisserie Bangkok guide", "bakery Chiang Mai new"],
        phone_country_code="66", data_dir=Path(tempfile.mkdtemp()),
    )
    base.update(over)
    return Config(**base)


def store(c: Config) -> Store:
    return Store(c.data_dir / "test.db")


class FakeProvider:
    def __init__(self, name="fake", paid=False, results=None, pages=None, fail=None):
        self.name, self.paid = name, paid
        self.results = results or {}
        self.pages = pages or {}
        self.fail = fail
        self.calls: list[str] = []

    def search(self, query, recent_days, limit=8):
        self.calls.append(f"search:{query}")
        if self.fail:
            from leadfinder.sources import SourceError
            raise SourceError(self.fail)
        return [Result(*r) for r in self.results.get(query, [])]

    def fetch(self, url):
        self.calls.append(f"fetch:{url}")
        if self.fail:
            from leadfinder.sources import SourceError
            raise SourceError(self.fail)
        text, published, links = self.pages[url]
        return Page(url, text, url, published, links, self.name)


def sources(c: Config, *providers, budget=12) -> Sources:
    return Sources(list(providers), budget, PageCache(c.data_dir), 365)


class FakeAI:
    def __init__(self, businesses=None, fit=0.8, owner=None):
        self._businesses = businesses or {}
        self._fit = fit
        self._owner = owner
        self.log: list[str] = []

    def businesses(self, page_text, title, url):
        return [dict(b) for b in self._businesses.get(url, [])]

    def fit(self, cand):
        score = self._fit(cand) if callable(self._fit) else self._fit
        return {"score": score, "reason": "makes croissants"}

    def owner(self, business, pages):
        return self._owner(business, pages) if callable(self._owner) else self._owner


def biz(name, quote, **extra):
    row = {"name": name, "industry": "Bakery", "tags": ["vegan"], "area": "Ari", "what_they_make": None,
           "quote": quote, "website": None, "instagram": None, "line": None, "phone": None}
    row.update(extra)
    return row
