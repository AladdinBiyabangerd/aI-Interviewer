from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_interviewer.core.config import Settings
from ai_interviewer.identity.service import Principal
from ai_interviewer.main import create_app
from ai_interviewer.privacy.consent import (
    AdultAttestationRequiredError,
    ConsentNotFoundError,
    ProfileInput,
)
from ai_interviewer.privacy.lifecycle import (
    FailClosedPrivacyService,
    PrivacyRequestConflictError,
    PrivacyRequestResult,
)
from ai_interviewer.privacy.models import ConsentRecord, PrivacyProfile, PrivacyRequestType
from tests.fakes import ReadyDatabase


class ControlledAuthentication:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        del access_token, request_id
        return self.principal


class ControlledPrivacy:
    def __init__(self, account_id: UUID, result: Exception | None = None) -> None:
        self.account_id = account_id
        self.result = result
        self.now = datetime.now(UTC)
        self.policy_id = uuid4()

    def _raise(self) -> None:
        if self.result is not None:
            raise self.result

    async def configure_profile(
        self, account_id: UUID, profile_input: ProfileInput, request_id: str | None
    ) -> PrivacyProfile:
        del request_id
        self._raise()
        return PrivacyProfile(
            account_id=account_id,
            residence_country_code=profile_input.residence_country_code.upper(),
            residence_subdivision_code=profile_input.residence_subdivision_code,
            jurisdiction_codes=["AZERBAIJAN", "GLOBAL_BASELINE"],
            jurisdiction_versions={"AZERBAIJAN": "1", "GLOBAL_BASELINE": "1"},
            storage_region=profile_input.storage_region,
            adult_attested_at=self.now,
            privacy_policy_version_id=profile_input.privacy_policy_version_id,
        )

    async def grant(
        self, account_id: UUID, consent_notice_id: UUID, request_id: str | None
    ) -> ConsentRecord:
        del request_id
        self._raise()
        return ConsentRecord(
            id=uuid4(),
            account_id=account_id,
            consent_notice_id=consent_notice_id,
            granted_at=self.now,
            withdrawn_at=None,
            retain_until=self.now + timedelta(days=30),
            retention_action="delete",
        )

    async def withdraw(
        self, account_id: UUID, consent_record_id: UUID, request_id: str | None
    ) -> ConsentRecord:
        del request_id
        self._raise()
        return ConsentRecord(
            id=consent_record_id,
            account_id=account_id,
            consent_notice_id=uuid4(),
            granted_at=self.now - timedelta(days=1),
            withdrawn_at=self.now,
            retain_until=self.now + timedelta(days=30),
            retention_action="delete",
        )

    async def list_consents(self, account_id: UUID) -> list[ConsentRecord]:
        del account_id
        self._raise()
        return []

    async def create_request(
        self,
        account_id: UUID,
        request_type: PrivacyRequestType,
        idempotency_key: str,
        request_id: str | None,
    ) -> PrivacyRequestResult:
        del account_id, idempotency_key, request_id
        self._raise()
        return PrivacyRequestResult(
            request_id=uuid4(),
            request_type=request_type,
            status="completed",
            requested_at=self.now,
            due_at=self.now + timedelta(days=30),
            completed_at=self.now,
            data={"schema_version": "phase-0c-b.1"} if request_type != "deletion" else None,
        )

    async def get_request(self, account_id: UUID, request_id: UUID) -> PrivacyRequestResult:
        del account_id
        self._raise()
        return PrivacyRequestResult(
            request_id=request_id,
            request_type="access",
            status="completed",
            requested_at=self.now,
            due_at=self.now + timedelta(days=30),
            completed_at=self.now,
        )


def privacy_client(
    scopes: frozenset[str], privacy: ControlledPrivacy | FailClosedPrivacyService
) -> TestClient:
    account_id = privacy.account_id if isinstance(privacy, ControlledPrivacy) else uuid4()
    return TestClient(
        create_app(
            Settings(_env_file=None, environment="test", allowed_hosts=("testserver",)),
            database=ReadyDatabase(),
            authentication=ControlledAuthentication(
                Principal(account_id=account_id, scopes=scopes)
            ),
            privacy=privacy,
        )
    )


def test_privacy_profile_requires_scope_and_never_accepts_underage_attestation() -> None:
    controlled = ControlledPrivacy(uuid4())
    body = {
        "residence_country_code": "AZ",
        "storage_region": "az-primary",
        "adult_attested": True,
        "privacy_policy_version_id": str(controlled.policy_id),
    }
    with privacy_client(frozenset({"privacy:read"}), controlled) as client:
        forbidden = client.put(
            "/api/v1/privacy/profile",
            json=body,
            headers={"authorization": "Bearer valid"},
        )
    with privacy_client(frozenset({"privacy:write"}), controlled) as client:
        underage = client.put(
            "/api/v1/privacy/profile",
            json={**body, "adult_attested": False},
            headers={"authorization": "Bearer valid"},
        )

    assert forbidden.status_code == 403
    assert underage.status_code == 422


def test_privacy_profile_returns_server_resolved_jurisdiction_snapshot() -> None:
    controlled = ControlledPrivacy(uuid4())
    with privacy_client(frozenset({"privacy:write"}), controlled) as client:
        response = client.put(
            "/api/v1/privacy/profile",
            json={
                "residence_country_code": "az",
                "storage_region": "az-primary",
                "adult_attested": True,
                "privacy_policy_version_id": str(controlled.policy_id),
            },
            headers={"authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json()["jurisdiction_codes"] == ["AZERBAIJAN", "GLOBAL_BASELINE"]
    assert response.json()["account_id"] == str(controlled.account_id)


def test_privacy_service_is_fail_closed_when_not_configured() -> None:
    with privacy_client(frozenset({"privacy:read"}), FailClosedPrivacyService()) as client:
        response = client.get(
            "/api/v1/privacy/consents",
            headers={"authorization": "Bearer valid"},
        )

    assert response.status_code == 503


def test_request_scope_depends_on_request_type_and_returns_challenge() -> None:
    controlled = ControlledPrivacy(uuid4())
    with privacy_client(frozenset({"privacy:read"}), controlled) as client:
        response = client.post(
            "/api/v1/privacy/requests",
            json={"request_type": "export"},
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "export-request-001",
            },
        )

    assert response.status_code == 403
    assert response.headers["www-authenticate"] == (
        'Bearer error="insufficient_scope", scope="privacy:export"'
    )


def test_export_request_returns_machine_readable_bundle() -> None:
    controlled = ControlledPrivacy(uuid4())
    with privacy_client(frozenset({"privacy:export"}), controlled) as client:
        response = client.post(
            "/api/v1/privacy/requests",
            json={"request_type": "export"},
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "export-request-002",
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert response.json()["data"]["schema_version"] == "phase-0c-b.1"


def test_policy_conflict_is_opaque() -> None:
    controlled = ControlledPrivacy(uuid4(), PrivacyRequestConflictError("internal policy detail"))
    with privacy_client(frozenset({"privacy:export"}), controlled) as client:
        response = client.post(
            "/api/v1/privacy/requests",
            json={"request_type": "export"},
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "export-request-003",
            },
        )

    assert response.status_code == 409
    assert "internal policy detail" not in response.text


def test_consent_grant_list_withdraw_and_request_lookup_contracts() -> None:
    controlled = ControlledPrivacy(uuid4())
    notice_id = uuid4()
    record_id = uuid4()
    request_id = uuid4()
    with privacy_client(frozenset({"privacy:read", "privacy:write"}), controlled) as client:
        granted = client.post(
            f"/api/v1/privacy/consents/{notice_id}",
            headers={"authorization": "Bearer valid"},
        )
        listed = client.get(
            "/api/v1/privacy/consents",
            headers={"authorization": "Bearer valid"},
        )
        withdrawn = client.delete(
            f"/api/v1/privacy/consents/{record_id}",
            headers={"authorization": "Bearer valid"},
        )
        looked_up = client.get(
            f"/api/v1/privacy/requests/{request_id}",
            headers={"authorization": "Bearer valid"},
        )

    assert granted.status_code == 201
    assert granted.json()["consent_notice_id"] == str(notice_id)
    assert listed.status_code == 200 and listed.json() == []
    assert withdrawn.status_code == 200
    assert withdrawn.json()["consent_record_id"] == str(record_id)
    assert looked_up.status_code == 200
    assert looked_up.json()["request_id"] == str(request_id)


def test_privacy_domain_errors_map_to_opaque_statuses() -> None:
    profile_error = ControlledPrivacy(uuid4(), AdultAttestationRequiredError())
    with privacy_client(frozenset({"privacy:write"}), profile_error) as client:
        forbidden = client.put(
            "/api/v1/privacy/profile",
            json={
                "residence_country_code": "AZ",
                "storage_region": "az-primary",
                "adult_attested": True,
                "privacy_policy_version_id": str(profile_error.policy_id),
            },
            headers={"authorization": "Bearer valid"},
        )

    missing_error = ControlledPrivacy(uuid4(), ConsentNotFoundError())
    with privacy_client(frozenset({"privacy:write"}), missing_error) as client:
        missing = client.delete(
            f"/api/v1/privacy/consents/{uuid4()}",
            headers={"authorization": "Bearer valid"},
        )

    unavailable = ControlledPrivacy(uuid4())
    with privacy_client(frozenset({"privacy:write"}), FailClosedPrivacyService()) as client:
        service_down = client.put(
            "/api/v1/privacy/profile",
            json={
                "residence_country_code": "AZ",
                "storage_region": "az-primary",
                "adult_attested": True,
                "privacy_policy_version_id": str(unavailable.policy_id),
            },
            headers={"authorization": "Bearer valid"},
        )

    assert forbidden.status_code == 403
    assert missing.status_code == 404
    assert service_down.status_code == 503
