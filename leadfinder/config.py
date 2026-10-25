"""Settings: one config.toml describes your business; secrets stay in the environment (.env).

Keys are never read from config.toml, never written to the database and never logged.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_OTHER_PLACES = [
    "new york", "nyc", "london", "los angeles", "san francisco", "chicago", "toronto", "sydney", "melbourne",
    "singapore", "hong kong", "tokyo", "seoul", "paris", "berlin", "dubai", "bali", "kuala lumpur",
]


@dataclass
class Place:
    name: str
    match: list[str]
    """words that show a page is about this place (any language)"""


@dataclass
class Config:
    business_name: str
    product: str
    pitch: str
    ideal_customers: list[str]
    exclude: list[str]
    country: str
    places: list[Place]
    queries: list[str]
    other_places: list[str] = field(default_factory=lambda: list(DEFAULT_OTHER_PLACES))
    phone_country_code: str = ""
    searches_per_run: int = 2
    pages_per_search: int = 2
    max_proposals: int = 5
    recent_days: int = 365
    open_evidence_months: int = 18
    owners_per_run: int = 10
    registry_url: str = ""
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    fit_cutoff: float = 0.5
    source_order: list[str] = field(default_factory=lambda: ["firecrawl", "tinyfish"])
    budget: int = 12
    data_dir: Path = Path("data")

    def place_for(self, query: str) -> Place | None:
        q = query.lower()
        return next((p for p in self.places if any(m.lower() in q for m in [p.name, *p.match])), None)


def load_env(path: Path = Path(".env")) -> None:
    """Load KEY=value lines into the environment without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


def secret(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load(path: Path = Path("config.toml")) -> Config:
    if not path.exists():
        raise SystemExit(f"No {path}. Copy config.example.toml to config.toml and describe your business.")
    raw = tomllib.loads(path.read_text())
    b, s, o, ai, src = (raw.get(k, {}) for k in ("business", "search", "owners", "ai", "sources"))
    places = [Place(name=p["name"], match=list(p.get("match", []))) for p in s.get("places", [])]
    if not places:
        raise SystemExit("config.toml: add at least one [[search.places]] entry.")
    queries = list(s.get("queries", []))
    if not queries:
        raise SystemExit("config.toml: add search.queries (use {place} where the city goes).")
    # A query template with {place} becomes one query per place.
    expanded = [q.replace("{place}", p.name) for q in queries for p in places] if any("{place}" in q for q in queries) else queries
    return Config(
        business_name=b.get("name", "Your business"),
        product=b.get("product", ""),
        pitch=b.get("pitch", ""),
        ideal_customers=list(b.get("ideal_customers", [])),
        exclude=list(b.get("exclude", [])),
        country=s.get("country", ""),
        places=places,
        queries=expanded,
        other_places=[x.lower() for x in s.get("other_places", DEFAULT_OTHER_PLACES)],
        phone_country_code=str(s.get("phone_country_code", "")),
        searches_per_run=int(s.get("searches_per_run", 2)),
        pages_per_search=int(s.get("pages_per_search", 2)),
        max_proposals=int(s.get("max_proposals", 5)),
        recent_days=int(s.get("recent_days", 365)),
        open_evidence_months=int(s.get("open_evidence_months", 18)),
        owners_per_run=int(o.get("per_run", 10)),
        registry_url=o.get("registry_url", ""),
        model=ai.get("model", "claude-opus-5-5"),
        effort=ai.get("effort", "medium"),
        fit_cutoff=float(ai.get("fit_cutoff", 0.5)),
        source_order=list(src.get("order", ["firecrawl", "tinyfish"])),
        budget=int(src.get("budget", 12)),
        data_dir=Path(raw.get("data_dir", "data")),
    )
