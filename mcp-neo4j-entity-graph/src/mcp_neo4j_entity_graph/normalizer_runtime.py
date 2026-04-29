"""Runtime normalization helpers used by ontology-generated extraction schemas.

Generated Pydantic schema files import these helpers via:

    from mcp_neo4j_entity_graph.normalizer_runtime import _ws, _normalise_date, ...

This keeps the generated files compact (no helper duplication per file) and
keeps the normalization logic centralized and tested in one place.

The helpers are intentionally domain-agnostic. Domain-specific normalization
(e.g. legal case number formats, EU title prefixes) is expressed via the
parameterized normalizers (alias_map, blocklist, regex_normalize, regex_skip,
enum_validate) configured on the Ontology DB graph nodes.

The `__SKIP__` sentinel: when a normalizer returns this string, the extraction
pipeline filters out the containing entity before writing to Neo4j.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Optional

# Sentinel value used by validators to signal "drop this entity".
SKIP = "__SKIP__"


# ── Compiled regexes (module-level for speed) ────────────────────────────────

_WS = re.compile(r"\s+")
_THE_PREFIX = re.compile(r"^[Tt]he\s+")
_ACRONYM_SUFFIX = re.compile(r"\s*\([A-Z][A-Z0-9\- ]{1,9}\)\s*$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_ONLY = re.compile(r"^\d{4}$")
_INTEGER_CHARS = re.compile(r"[^\d\-]")


# ── Generic string normalizers ───────────────────────────────────────────────

def _ws(v: Any) -> str:
    """Collapse internal whitespace and strip."""
    return _WS.sub(" ", str(v)).strip()


def _strip_the(v: Any) -> str:
    """Remove leading 'the ' / 'The '."""
    return _THE_PREFIX.sub("", _ws(v)).strip()


def _strip_acronym_suffix(v: Any) -> str:
    """Remove trailing parenthetical acronym, e.g. 'Foo Bar (FB)' -> 'Foo Bar'."""
    return _ACRONYM_SUFFIX.sub("", _ws(v)).strip()


def _lowercase(v: Any) -> str:
    return _ws(v).lower()


def _uppercase(v: Any) -> str:
    return _ws(v).upper()


def _titlecase(v: Any) -> str:
    return _ws(v).title()


# ── Format-specific normalizers ──────────────────────────────────────────────

def _normalise_email(v: Any) -> Optional[str]:
    s = _ws(v).lower()
    return s if "@" in s else None


def _normalise_url(v: Any) -> Optional[str]:
    s = _ws(v).rstrip("/")
    if not s:
        return None
    # Lowercase the scheme + domain only (preserve path case)
    m = re.match(r"^(https?://)([^/]+)(.*)$", s, re.IGNORECASE)
    if m:
        return f"{m.group(1).lower()}{m.group(2).lower()}{m.group(3)}"
    return s


def _normalise_phone(v: Any) -> Optional[str]:
    """Strip formatting from phone numbers. Returns digits only with optional leading '+'."""
    s = _ws(v)
    if not s:
        return None
    leading_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    return f"+{digits}" if leading_plus else digits


def _normalise_percentage(v: Any) -> Optional[float]:
    """Parse '15%' or '15.5' or 15 -> 15.0. Returns the number as a float (not divided)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%").strip()
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _normalise_integer(v: Any) -> Optional[int]:
    """Parse an integer, handling commas and stray non-digit chars."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    # Allow optional leading minus sign
    m = re.match(r"^-?\d+$", s)
    if m:
        try:
            return int(s)
        except ValueError:
            return None
    return None


# ── Date normalization ───────────────────────────────────────────────────────

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%d %B %Y",
    "%Y/%m/%d",
)


def _normalise_date(v: Any) -> Optional[str]:
    """Accept None, ISO string, or various date formats; return 'YYYY-MM-DD', year-only, or None."""
    if v is None:
        return None
    s = _ws(str(v))
    if not s:
        return None
    if _ISO_DATE.match(s):
        return s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    if _YEAR_ONLY.match(s):
        return s
    return None


# ── Currency + monetary amount ───────────────────────────────────────────────

CURRENCY_ALIASES: dict[str, str] = {
    "euro": "EUR",
    "euros": "EUR",
    "€": "EUR",
    "dollar": "USD",
    "dollars": "USD",
    "$": "USD",
    "pound": "GBP",
    "pounds": "GBP",
    "£": "GBP",
    "yuan": "CNY",
    "renminbi": "CNY",
    "yen": "JPY",
    "ruble": "RUB",
    "rubles": "RUB",
}


def _normalise_currency(v: Any) -> Optional[str]:
    """Map currency symbols and names to ISO 4217 codes."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return CURRENCY_ALIASES.get(s.lower(), s.upper())


def _parse_amount(v: Any) -> Optional[float]:
    """Parse monetary amounts: floats, '€1.3 billion', '23-30 million EUR', etc.

    For ranges, takes the lower bound. Returns a positive float or None.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if float(v) > 0 else None
    s = str(v).strip()
    s = re.sub(r"[€$£¥]", "", s)
    s = re.sub(r"\b(EUR|USD|GBP|JPY|CNY|RUB)\b", "", s, flags=re.IGNORECASE)
    s = s.strip()
    range_match = re.match(r"([\d,.]+)\s*[-–]\s*[\d,.]+", s)
    if range_match:
        s = range_match.group(1) + " " + s[range_match.end():]
    num_match = re.search(r"([\d][,\d]*\.?\d*)", s)
    if not num_match:
        return None
    try:
        num = float(num_match.group(1).replace(",", ""))
    except ValueError:
        return None
    # Detect scale word/suffix in what's left after stripping the leading number.
    # Use word-boundary regex so suffixes like "k", "m", "bn" attach correctly
    # whether or not there's a space (e.g. "$500K", "1.3 billion", "23m").
    tail = s[num_match.end():].lower()
    if re.search(r"\btrillion\b", tail):
        num *= 1e12
    elif re.search(r"(?:\bbillion\b|\bbn\b)", tail):
        num *= 1e9
    elif re.search(r"(?:\bmillion\b|\bmn\b|\bmln\b|\bm\b)", tail):
        num *= 1e6
    elif re.search(r"(?:\bthousand\b|\bk\b)", tail):
        num *= 1e3
    return num if num > 0 else None


# ── Parameterized normalizer helpers (used by generated code) ────────────────

def _apply_alias_map(v: Any, aliases: dict[str, str]) -> Any:
    """Look up v in aliases; return the canonical form or v unchanged."""
    if v is None:
        return None
    s = _ws(v)
    return aliases.get(s, s)


def _apply_blocklist(v: Any, blocked: frozenset[str]) -> Any:
    """If v is in the blocklist, return the SKIP sentinel; else return v unchanged."""
    if v is None:
        return None
    s = _ws(v)
    return SKIP if s in blocked else s


def _apply_regex_normalize(v: Any, pattern: re.Pattern[str], replacement: str) -> Any:
    """Apply a regex substitution to v."""
    if v is None:
        return None
    return pattern.sub(replacement, str(v))


def _apply_regex_skip(v: Any, pattern: re.Pattern[str]) -> Any:
    """If v matches the pattern, return SKIP; else return v unchanged."""
    if v is None:
        return None
    s = str(v)
    return SKIP if pattern.search(s) else s


def _apply_enum_validate(v: Any, allowed: frozenset[str]) -> Any:
    """If v is not in allowed, return SKIP; else return v unchanged."""
    if v is None:
        return None
    s = _ws(v)
    return s if s in allowed else SKIP
