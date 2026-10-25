"""Text helpers: matching business names, domains and quotes the same way everywhere.

Pure functions, no network. Names are compared after folding Latin accents and dropping legal
suffixes and punctuation, so "Gateaux House Co., Ltd." and "gateaux house" are one business.
Marks on non-Latin scripts (Thai, Devanagari, ...) are kept, because there they change meaning.
"""
from __future__ import annotations

import re
import unicodedata
import urllib.parse

LEGAL_SUFFIXES = r"co|ltd|limited|company|plc|inc|llc|gmbh|sarl|pte|pty|bhd|sdn|the"

# Words too common to tell one business from another on their own.
GENERIC_WORDS = {
    "the", "and", "co", "ltd", "limited", "company", "group", "cafe", "café", "coffee", "bakery", "bakeries",
    "bake", "house", "home", "kitchen", "restaurant", "bistro", "bar", "shop", "store", "market", "vegan",
    "veggie", "vegetarian", "plant", "based", "food", "foods", "eatery", "dining", "social", "club", "studio",
    "lab", "by", "of", "at", "official", "branch",
}

FREE_EMAIL = {"gmail.com", "hotmail.com", "yahoo.com", "outlook.com", "icloud.com", "live.com", "msn.com", "me.com", "proton.me"}


def fold(value: str | None) -> str:
    """Lowercase, Latin accents removed ("Café" -> "cafe"), curly quotes straightened."""
    out, prev = [], ""
    for ch in unicodedata.normalize("NFKD", value or ""):
        if unicodedata.combining(ch) and prev.isascii():
            continue
        out.append(ch)
        prev = ch
    text = unicodedata.normalize("NFKC", "".join(out)).lower()
    return text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def words(value: str | None) -> str:
    """Text as single-spaced words with a space at each end, for whole-phrase matching."""
    spaced = " " + re.sub(r"[^\w&']+", " ", fold(value)).strip() + " "
    return spaced.replace(" & ", " and ")


def name_key(name: str | None) -> str:
    """One key per business: legal suffixes, spaces and punctuation don't count."""
    v = re.sub(rf"\b({LEGAL_SUFFIXES})\b\.?", " ", fold(name))
    return re.sub(r"[^\w]+|_", "", v)


def trading_name(name: str) -> str:
    """The name before any legal name or alias: "Nook / Nook Bakery (Nook Foods Ltd)" -> "Nook"."""
    return re.split(r"[(/]", name or "")[0].strip()


def distinctive(name: str | None) -> set[str]:
    """Words of a trading name that could identify it (3+ letters, not generic)."""
    return {w for w in re.findall(r"[\w']+", fold(trading_name(name or ""))) if len(w) >= 3 and w not in GENERIC_WORDS}


def domain(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return (host[4:] if host.startswith("www.") else host) or None


def handle(value: str | None) -> str | None:
    """'@nook.bakes', 'instagram.com/nook.bakes', 'line.me/ti/p/@nook' -> 'nook.bakes' / 'nook'."""
    if not value:
        return None
    v = fold(value).strip()
    m = (re.search(r"(?:instagram\.com|facebook\.com|tiktok\.com/@?|line\.me/R/ti/p|line\.me/ti/p)/@?([\w.]+)", v, re.I)
         or re.search(r"@([\w.]{3,})", v))
    return m.group(1).strip(".") if m else None


def phone_key(value: str | None, country_code: str = "") -> str | None:
    """Digits only, with the country code turned back into a leading 0 when it is given."""
    digits = re.sub(r"\D", "", value or "")
    if country_code and digits.startswith(country_code):
        digits = "0" + digits[len(country_code):]
    return digits if len(digits) >= 8 else None


def squash(value: str | None) -> str:
    """For quote checks: folded, markdown emphasis and list bullets dropped, whitespace collapsed."""
    text = fold(value)
    text = re.sub(r"^[ \t]*(?:[-*+•]|\d+[.)])[ \t]+", "", text, flags=re.M)
    text = re.sub(r"[*_`]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_on_page(quote: str | None, page: str | None) -> bool:
    """The quote really appears on the saved page (ignoring markdown marks and spacing)."""
    q = squash(quote)
    return len(q) >= 8 and q in squash(page)


def quote_names(quote: str | None, name: str | None) -> bool:
    """The quote contains the business's trading name (as a phrase, or every distinctive word)."""
    q = words(quote)
    phrase = words(trading_name(name or ""))
    if phrase.strip() and phrase in q:
        return True
    tokens = distinctive(name)
    return bool(tokens) and all(f" {t} " in q for t in tokens)
