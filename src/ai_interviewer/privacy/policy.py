"""Jurisdiction routing primitives kept separate from product business logic."""

import re
from dataclasses import dataclass

_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_SUBDIVISION_CODE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")


class JurisdictionResolutionError(ValueError):
    """A residence cannot be routed through the configured policy modules."""


@dataclass(frozen=True, slots=True)
class JurisdictionPolicyModule:
    """Versioned routing metadata, not a claim of legal compliance."""

    code: str
    version: str
    country_codes: frozenset[str]
    subdivision_codes: frozenset[str] = frozenset()
    minimum_age: int = 18
    legal_review_required: bool = True
    priority: int = 100

    def __post_init__(self) -> None:
        if not self.code or len(self.code) > 64:
            raise ValueError("jurisdiction code must contain 1-64 characters")
        if not self.version or len(self.version) > 64:
            raise ValueError("jurisdiction version must contain 1-64 characters")
        if self.minimum_age < 18 or self.minimum_age > 120:
            raise ValueError("the product supports only policy ages from 18 to 120")
        if not self.country_codes or any(
            _COUNTRY_CODE.fullmatch(code) is None for code in self.country_codes
        ):
            raise ValueError("jurisdiction country codes must be ISO 3166-1 alpha-2")
        if any(_SUBDIVISION_CODE.fullmatch(code) is None for code in self.subdivision_codes):
            raise ValueError("subdivision codes must use ISO 3166-2 syntax")
        if any(code[:2] not in self.country_codes for code in self.subdivision_codes):
            raise ValueError("subdivision codes must belong to the module countries")


@dataclass(frozen=True, slots=True)
class JurisdictionSelection:
    country_code: str
    subdivision_code: str | None
    modules: tuple[JurisdictionPolicyModule, ...]

    @property
    def policy_codes(self) -> tuple[str, ...]:
        return tuple(module.code for module in self.modules)

    @property
    def policy_versions(self) -> dict[str, str]:
        return {module.code: module.version for module in self.modules}

    @property
    def minimum_age(self) -> int:
        return max(module.minimum_age for module in self.modules)


class JurisdictionPolicyRegistry:
    """Resolve layered country/subdivision modules without jurisdiction conditionals."""

    def __init__(
        self,
        modules: tuple[JurisdictionPolicyModule, ...],
        *,
        fallback_code: str = "GLOBAL_BASELINE",
    ) -> None:
        if not modules:
            raise ValueError("at least one jurisdiction policy module is required")
        codes = [module.code for module in modules]
        if len(codes) != len(set(codes)):
            raise ValueError("jurisdiction policy module codes must be unique")
        if fallback_code not in codes:
            raise ValueError("the configured fallback module does not exist")
        self._modules = modules
        self._fallback = next(module for module in modules if module.code == fallback_code)

    @property
    def modules(self) -> tuple[JurisdictionPolicyModule, ...]:
        return self._modules

    def resolve(self, country_code: str, subdivision_code: str | None) -> JurisdictionSelection:
        country = country_code.strip().upper()
        subdivision = subdivision_code.strip().upper() if subdivision_code else None
        if _COUNTRY_CODE.fullmatch(country) is None:
            raise JurisdictionResolutionError("country_code must be ISO 3166-1 alpha-2")
        if subdivision is not None and (
            _SUBDIVISION_CODE.fullmatch(subdivision) is None or subdivision[:2] != country
        ):
            raise JurisdictionResolutionError("subdivision_code must be a matching ISO 3166-2 code")

        selected = [
            module
            for module in self._modules
            if module is not self._fallback
            and country in module.country_codes
            and (not module.subdivision_codes or subdivision in module.subdivision_codes)
        ]
        selected.sort(key=lambda module: module.priority, reverse=True)
        selected.append(self._fallback)
        return JurisdictionSelection(
            country_code=country,
            subdivision_code=subdivision,
            modules=tuple(selected),
        )


_EU_EEA_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LI",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }
)


def build_default_jurisdiction_registry() -> JurisdictionPolicyRegistry:
    """Build initial routing modules; every module remains pending legal approval."""
    routing_version = "2026-08-23.1"
    country_modules = (
        ("AZERBAIJAN", frozenset({"AZ"})),
        ("EU_EEA_GDPR", _EU_EEA_COUNTRIES),
        ("UNITED_KINGDOM", frozenset({"GB"})),
        ("UNITED_STATES_FEDERAL", frozenset({"US"})),
        ("CANADA", frozenset({"CA"})),
        ("TURKEY", frozenset({"TR"})),
        ("BRAZIL", frozenset({"BR"})),
        ("INDIA", frozenset({"IN"})),
        ("AUSTRALIA", frozenset({"AU"})),
        ("SINGAPORE", frozenset({"SG"})),
        ("UAE", frozenset({"AE"})),
    )
    modules = (
        *(
            JurisdictionPolicyModule(
                code=code,
                version=routing_version,
                country_codes=countries,
                priority=100,
            )
            for code, countries in country_modules
        ),
        JurisdictionPolicyModule(
            code="GLOBAL_BASELINE",
            version=routing_version,
            country_codes=frozenset({"ZZ"}),
            priority=0,
        ),
    )
    return JurisdictionPolicyRegistry(modules)
