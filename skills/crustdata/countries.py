"""Country normalization for Crustdata's two country vocabularies.

Company-side fields want ISO alpha-3 ("USA", "GBR"); the person's own location wants the full English
name ("United States", "United Kingdom"). Both are exact-match, so a value in the wrong form matches zero.
"""

import pycountry

US_ABBREVIATED = "USA"
US_FULL = "United States"
US_LONG = "United States of America"
US_ALIASES = {"usa", "us", "u.s.", "u.s.a.", "united states", "united states of america", "u s a", "u s"}

# CLDR short names where pycountry's ISO name differs from what LinkedIn-derived data uses.
_DISPLAY_OVERRIDES = {"RUS": "Russia"}


def _build() -> tuple[dict[str, str], dict[str, str]]:
    iso3_by_key: dict[str, str] = {}
    full_by_iso3: dict[str, str] = {}
    for country in pycountry.countries:
        alpha3 = country.alpha_3
        display = _DISPLAY_OVERRIDES.get(alpha3) or getattr(country, "common_name", None) or country.name
        full_by_iso3[alpha3] = display
        for key in (country.alpha_2, alpha3, country.name, display, getattr(country, "official_name", None)):
            if key:
                iso3_by_key[key.lower()] = alpha3
    for alias in ("uk", "u.k.", "great britain", "britain", "england"):
        iso3_by_key[alias] = "GBR"
    return iso3_by_key, full_by_iso3


ISO3_BY_KEY, FULL_BY_ISO3 = _build()


def to_iso3(value: str) -> str:
    """Canonical alpha-3 for a recognizable name/alpha-2/alpha-3; unknown tokens pass through trimmed."""
    trimmed = (value or "").strip()
    if not trimmed:
        return trimmed
    if trimmed.lower() in US_ALIASES:
        return US_ABBREVIATED
    return ISO3_BY_KEY.get(trimmed.lower(), trimmed)


def to_full(value: str) -> str:
    """Full English country name; unknown tokens pass through trimmed."""
    trimmed = (value or "").strip()
    if not trimmed:
        return trimmed
    if trimmed.lower() in US_ALIASES:
        return US_FULL
    alpha3 = ISO3_BY_KEY.get(trimmed.lower())
    return FULL_BY_ISO3.get(alpha3, trimmed) if alpha3 else trimmed


def is_country_field(field: str) -> bool:
    field = (field or "").strip()
    return field.endswith("headquarters_country") or field in {
        "basic_profile.location.country",
        "professional_network.location.country",
        "education.schools.location.country",
    }


def normalize_for_field(field: str, value):
    """Puts a country value (scalar or list) into the vocabulary ``field`` expects."""
    normalizer = to_iso3 if field.endswith("headquarters_country") else to_full
    if isinstance(value, list):
        return [normalizer(str(v)) for v in value if v is not None and str(v).strip()]
    return normalizer(str(value)) if value is not None else None
