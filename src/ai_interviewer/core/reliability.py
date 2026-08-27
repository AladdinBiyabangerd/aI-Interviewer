"""Versioned, bounded populations used by service-level measurements."""

from hashlib import sha256
from typing import Literal

HttpRequestPopulation = Literal["product", "operations", "other"]
HTTP_DURATION_BUCKETS_SECONDS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1,
    2.5,
    5,
    7.5,
    10,
)

# Adding or removing an API route requires an explicit SLI-population decision.
PRODUCT_HTTP_ROUTES = frozenset(
    {
        "/api/v1/identity/me",
        "/api/v1/preparations",
        "/api/v1/preparations/{preparation_id}",
        "/api/v1/preparations/{preparation_id}/archive",
        "/api/v1/preparations/{preparation_id}/documents",
        "/api/v1/preparations/{preparation_id}/documents/{document_id}",
        "/api/v1/preparations/{preparation_id}/documents/{document_type}/upload",
        "/api/v1/preparations/{preparation_id}/documents/{document_type}/paste",
        "/api/v1/preparations/{preparation_id}/document-intakes/{intake_id}",
        "/api/v1/privacy/consents",
        "/api/v1/privacy/consents/{consent_notice_id}",
        "/api/v1/privacy/consents/{consent_record_id}",
        "/api/v1/privacy/profile",
        "/api/v1/privacy/requests",
        "/api/v1/privacy/requests/{privacy_request_id}",
    }
)
OPERATIONAL_HTTP_ROUTES = frozenset(
    {
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }
)


def classify_http_request(route: str) -> HttpRequestPopulation:
    """Classify only reviewed route templates; unknown values fail outside the SLI."""
    if route in PRODUCT_HTTP_ROUTES:
        return "product"
    if route in OPERATIONAL_HTTP_ROUTES:
        return "operations"
    return "other"


def product_route_contract_digest() -> str:
    """Bind baseline evidence to the exact reviewed route-template population."""
    canonical = "\n".join(sorted(PRODUCT_HTTP_ROUTES)).encode()
    return sha256(canonical).hexdigest()
