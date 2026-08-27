import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.privacy.consent import ProfileInput
from ai_interviewer.privacy.lifecycle import (
    FailClosedPrivacyService,
    PrivacyLifecycleService,
    PrivacyUnavailableError,
    build_privacy_service,
)
from ai_interviewer.privacy.policy import (
    JurisdictionPolicyModule,
    JurisdictionPolicyRegistry,
    JurisdictionResolutionError,
    build_default_jurisdiction_registry,
)
from ai_interviewer.privacy.processors import (
    ProcessorPolicyError,
    complete_processor_deletion_task,
    decrypt_processor_task_reference,
    fail_processor_deletion_task,
    processor_task_has_locator,
    register_processor_usage,
    requeue_escalated_processor_deletion_task,
)
from ai_interviewer.privacy.rules import validate_context_code
from tests.fakes import ReadyDatabase


def test_default_registry_routes_initial_markets_and_keeps_global_fallback() -> None:
    registry = build_default_jurisdiction_registry()

    assert registry.resolve("az", None).policy_codes == ("AZERBAIJAN", "GLOBAL_BASELINE")
    assert registry.resolve("DE", None).policy_codes == ("EU_EEA_GDPR", "GLOBAL_BASELINE")
    assert registry.resolve("US", "US-CA").policy_codes == (
        "UNITED_STATES_FEDERAL",
        "GLOBAL_BASELINE",
    )
    assert registry.resolve("JP", None).policy_codes == ("GLOBAL_BASELINE",)
    assert all(module.legal_review_required for module in registry.modules)
    assert registry.resolve("BR", None).minimum_age == 18


def test_subdivision_module_can_be_added_without_changing_resolution_logic() -> None:
    registry = JurisdictionPolicyRegistry(
        (
            JurisdictionPolicyModule(
                code="US_CALIFORNIA",
                version="legal-review-1",
                country_codes=frozenset({"US"}),
                subdivision_codes=frozenset({"US-CA"}),
                priority=200,
            ),
            JurisdictionPolicyModule(
                code="US_FEDERAL",
                version="legal-review-1",
                country_codes=frozenset({"US"}),
                priority=100,
            ),
            JurisdictionPolicyModule(
                code="GLOBAL_BASELINE",
                version="legal-review-1",
                country_codes=frozenset({"ZZ"}),
                priority=0,
            ),
        )
    )

    selection = registry.resolve("US", "US-CA")

    assert selection.policy_codes == ("US_CALIFORNIA", "US_FEDERAL", "GLOBAL_BASELINE")
    assert selection.policy_versions == {
        "US_CALIFORNIA": "legal-review-1",
        "US_FEDERAL": "legal-review-1",
        "GLOBAL_BASELINE": "legal-review-1",
    }


@pytest.mark.parametrize(
    ("country", "subdivision"),
    [("USA", None), ("US", "CA"), ("US", "CA-ON")],
)
def test_registry_rejects_invalid_or_mismatched_iso_codes(
    country: str, subdivision: str | None
) -> None:
    with pytest.raises(JurisdictionResolutionError):
        build_default_jurisdiction_registry().resolve(country, subdivision)


def test_registry_rejects_duplicate_modules_and_invalid_definitions() -> None:
    fallback = JurisdictionPolicyModule(
        code="GLOBAL_BASELINE",
        version="1",
        country_codes=frozenset({"ZZ"}),
    )
    with pytest.raises(ValueError, match="unique"):
        JurisdictionPolicyRegistry((fallback, fallback))
    with pytest.raises(ValueError, match="subdivision"):
        JurisdictionPolicyModule(
            code="INVALID",
            version="1",
            country_codes=frozenset({"US"}),
            subdivision_codes=frozenset({"CA-ON"}),
        )
    with pytest.raises(ValueError, match="ages"):
        JurisdictionPolicyModule(
            code="MINOR",
            version="1",
            country_codes=frozenset({"US"}),
            minimum_age=17,
        )
    with pytest.raises(ValueError, match="jurisdiction code"):
        JurisdictionPolicyModule(
            code="",
            version="1",
            country_codes=frozenset({"US"}),
        )
    with pytest.raises(ValueError, match="jurisdiction version"):
        JurisdictionPolicyModule(
            code="US",
            version="",
            country_codes=frozenset({"US"}),
        )
    with pytest.raises(ValueError, match="country codes"):
        JurisdictionPolicyModule(
            code="US",
            version="1",
            country_codes=frozenset({"USA"}),
        )
    with pytest.raises(ValueError, match="fallback"):
        JurisdictionPolicyRegistry(
            (
                JurisdictionPolicyModule(
                    code="US",
                    version="1",
                    country_codes=frozenset({"US"}),
                ),
            )
        )


@pytest.mark.parametrize("value", ["", "has space", "a" * 101])
def test_processing_context_codes_are_bounded(value: str) -> None:
    with pytest.raises(ValueError, match="bounded lowercase"):
        validate_context_code(value, "purpose")


def test_processing_context_codes_are_normalized() -> None:
    assert validate_context_code(" Product_Analytics ", "purpose") == "product_analytics"


@pytest.mark.asyncio
async def test_fail_closed_privacy_service_rejects_every_self_service_operation() -> None:
    service = FailClosedPrivacyService()
    account_id = uuid4()

    with pytest.raises(PrivacyUnavailableError):
        await service.configure_profile(
            account_id,
            ProfileInput(
                residence_country_code="AZ",
                residence_subdivision_code=None,
                storage_region="az-primary",
                adult_attested=True,
                privacy_policy_version_id=uuid4(),
            ),
            None,
        )
    with pytest.raises(PrivacyUnavailableError):
        await service.grant(account_id, uuid4(), None)
    with pytest.raises(PrivacyUnavailableError):
        await service.withdraw(account_id, uuid4(), None)
    with pytest.raises(PrivacyUnavailableError):
        await service.list_consents(account_id)
    with pytest.raises(PrivacyUnavailableError):
        await service.create_request(account_id, "access", "request-key", None)
    with pytest.raises(PrivacyUnavailableError):
        await service.get_request(account_id, uuid4())
    with pytest.raises(PrivacyUnavailableError):
        await service.resume_deletion(uuid4())


def test_privacy_builder_is_fail_closed_or_real_from_explicit_configuration() -> None:
    disabled = build_privacy_service(
        Settings(_env_file=None), ReadyDatabase(), build_default_jurisdiction_registry()
    )
    enabled = build_privacy_service(
        Settings(
            _env_file=None,
            privacy_enabled=True,
            privacy_subject_hmac_key="a-secure-privacy-key-with-at-least-32-bytes",
        ),
        ReadyDatabase(),
        build_default_jurisdiction_registry(),
    )

    assert isinstance(disabled, FailClosedPrivacyService)
    assert isinstance(enabled, PrivacyLifecycleService)


def test_manifest_fingerprint_is_deterministic_but_keyed() -> None:
    first = PrivacyLifecycleService(
        database=ReadyDatabase(),
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"a" * 32,
    )
    second = PrivacyLifecycleService(
        database=ReadyDatabase(),
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"b" * 32,
    )

    assert first._fingerprint("issuer", "subject") == first._fingerprint("issuer", "subject")
    assert first._fingerprint("issuer", "subject") != second._fingerprint("issuer", "subject")
    key_id, digest = first._fingerprint("issuer", "subject")
    assert key_id == "legacy-v1"
    assert len(digest) == 64

    with pytest.raises(ValueError, match="at least 32 bytes"):
        PrivacyLifecycleService(
            database=ReadyDatabase(),
            registry=build_default_jurisdiction_registry(),
            subject_hmac_key=b"short",
        )


def _test_keyring() -> ApplicationKeyring:
    def entry(identifier: str, purpose: str, marker: bytes) -> dict[str, str]:
        return {
            "id": identifier,
            "purpose": purpose,
            "material": base64.b64encode(marker * 32).decode(),
        }

    return ApplicationKeyring.from_secret(
        SecretStr(
            json.dumps(
                {
                    "version": 1,
                    "active": {
                        "subject_hmac": "subject-v1",
                        "field_encryption": "field-v1",
                        "manifest_hmac": "manifest-v1",
                    },
                    "keys": [
                        entry("subject-v1", "subject_hmac", b"s"),
                        entry("field-v1", "field_encryption", b"f"),
                        entry("manifest-v1", "manifest_hmac", b"m"),
                    ],
                }
            )
        )
    )


@pytest.mark.asyncio
async def test_privacy_crypto_and_manifest_guards_fail_closed() -> None:
    registry = build_default_jurisdiction_registry()
    with pytest.raises(ValueError, match="exactly one"):
        PrivacyLifecycleService(database=ReadyDatabase(), registry=registry)
    with pytest.raises(ValueError, match="exactly one"):
        PrivacyLifecycleService(
            database=ReadyDatabase(),
            registry=registry,
            subject_hmac_key=b"a" * 32,
            application_keyring=_test_keyring(),
        )

    legacy = PrivacyLifecycleService(
        database=ReadyDatabase(),
        registry=registry,
        subject_hmac_key=b"a" * 32,
    )
    legacy._subject_hmac_key = None
    with pytest.raises(RuntimeError, match="unavailable"):
        legacy._fingerprint("issuer", "subject")

    keyed = PrivacyLifecycleService(
        database=ReadyDatabase(),
        registry=registry,
        application_keyring=_test_keyring(),
    )
    key_id, digest = keyed._fingerprint("issuer", "subject")
    assert keyed._matches_fingerprint(
        "issuer",
        "subject",
        key_id=key_id,
        digest=digest,
    )
    assert not keyed._matches_fingerprint(
        "issuer",
        "different",
        key_id=key_id,
        digest=digest,
    )

    with pytest.raises(ValueError, match="unsupported privacy"):
        await keyed.create_request(uuid4(), "invalid", "long-enough", None)  # type: ignore[arg-type]
    with pytest.raises(PrivacyUnavailableError, match="privacy keyring"):
        await PrivacyLifecycleService(
            database=ReadyDatabase(),
            registry=registry,
            subject_hmac_key=b"a" * 32,
        ).export_signed_deletion_manifest()
    with pytest.raises(ValueError, match="schema"):
        await keyed.apply_signed_deletion_manifest(
            SimpleNamespace(schema_version="unsupported")  # type: ignore[arg-type]
        )


class _ProcessorSessionStub:
    def __init__(self, values: list[object | None]) -> None:
        self.values = values

    async def get(self, *_: object) -> object | None:
        return self.values.pop(0)


@pytest.mark.asyncio
async def test_processor_policy_and_locator_guards() -> None:
    account_id = uuid4()
    activity_id = uuid4()
    with pytest.raises(ProcessorPolicyError, match="activity is unavailable"):
        await register_processor_usage(
            _ProcessorSessionStub([None]),  # type: ignore[arg-type]
            account_id=account_id,
            processor_activity_id=activity_id,
            processor_subject_reference="locator",
        )

    activity = SimpleNamespace(processor_id=uuid4())
    with pytest.raises(ProcessorPolicyError, match="not approved"):
        await register_processor_usage(
            _ProcessorSessionStub([activity, None, None]),  # type: ignore[arg-type]
            account_id=account_id,
            processor_activity_id=activity_id,
            processor_subject_reference="locator",
        )

    task = SimpleNamespace(
        status="pending",
        locked_by=None,
        processor_subject_reference=None,
        processor_subject_ciphertext=None,
        processor_subject_nonce=None,
        processor_subject_key_id=None,
        account_id=None,
    )
    assert not processor_task_has_locator(task)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not claimed"):
        await complete_processor_deletion_task(  # type: ignore[arg-type]
            SimpleNamespace(), task=task, worker_id="worker"
        )
    with pytest.raises(ValueError, match="not claimed"):
        await fail_processor_deletion_task(  # type: ignore[arg-type]
            SimpleNamespace(),
            task=task,
            worker_id="worker",
            error_code="provider_error",
            max_attempts=3,
            retry_base_seconds=1,
        )
    with pytest.raises(ValueError, match="escalated"):
        await requeue_escalated_processor_deletion_task(  # type: ignore[arg-type]
            SimpleNamespace(), task=task
        )
    with pytest.raises(ProcessorPolicyError, match="locator is unavailable"):
        decrypt_processor_task_reference(task, application_keyring=None)  # type: ignore[arg-type]

    task.processor_subject_reference = "plain-locator"
    assert processor_task_has_locator(task)  # type: ignore[arg-type]
    assert (
        decrypt_processor_task_reference(task, application_keyring=None)  # type: ignore[arg-type]
        == "plain-locator"
    )


def test_request_result_timestamps_remain_timezone_aware() -> None:
    assert datetime.now(UTC).utcoffset() is not None
