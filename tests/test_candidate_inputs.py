from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.candidate_inputs.service import (
    CandidateInputUnavailableError,
    CandidatePreparationConflictError,
    CandidatePreparationNotFoundError,
    CandidatePreparationPreconditionError,
    CreatePreparationResult,
    FailClosedCandidateInputService,
    PreparationInput,
    PreparationPage,
    build_candidate_inputs,
    normalize_preparation_input,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.identity.service import Principal
from ai_interviewer.main import create_app
from tests.fakes import ReadyDatabase


class ControlledAuthentication:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        del access_token, request_id
        return self.principal


def _input(**changes: object) -> PreparationInput:
    values: dict[str, object] = {
        "company_name": "Example Company",
        "role_family": "software_engineering",
        "role_family_other": None,
        "role_title": "Backend Engineer",
        "seniority": "senior",
        "seniority_other": None,
        "target_country_code": "AZ",
        "target_office": "Baku",
        "interview_round": "system_design",
        "interview_round_other": None,
        "interview_language": "az",
    }
    values.update(changes)
    return PreparationInput(**values)  # type: ignore[arg-type]


def _payload(**changes: object) -> dict[str, object]:
    value = _input(**changes)
    return {
        "company_name": value.company_name,
        "role_family": value.role_family,
        "role_family_other": value.role_family_other,
        "role_title": value.role_title,
        "seniority": value.seniority,
        "seniority_other": value.seniority_other,
        "target_country_code": value.target_country_code,
        "target_office": value.target_office,
        "interview_round": value.interview_round,
        "interview_round_other": value.interview_round_other,
        "interview_language": value.interview_language,
    }


def _preparation(account_id: UUID, **changes: object) -> CandidatePreparation:
    now = datetime.now(UTC)
    value = _input(**changes)
    return CandidatePreparation(
        id=uuid4(),
        owner_id=account_id,
        company_name=value.company_name,
        role_family=value.role_family,
        role_family_other=value.role_family_other,
        role_title=value.role_title,
        seniority=value.seniority,
        seniority_other=value.seniority_other,
        target_country_code=value.target_country_code,
        target_office=value.target_office,
        interview_round=value.interview_round,
        interview_round_other=value.interview_round_other,
        interview_language=value.interview_language,
        status="draft",
        privacy_policy_version_id=uuid4(),
        jurisdiction_code="AZERBAIJAN",
        legal_basis="contract",
        retention_rule_id=uuid4(),
        retain_until=now + timedelta(days=30),
        retention_action="delete",
        idempotency_key_hash="a" * 64,
        created_at=now,
        updated_at=now,
        version=1,
    )


class ControlledCandidateInputs:
    def __init__(self, account_id: UUID, error: Exception | None = None) -> None:
        self.account_id = account_id
        self.error = error
        self.item = _preparation(account_id)
        self.reused = False
        self.received_input: PreparationInput | None = None
        self.received_version: int | None = None

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def create_preparation(
        self,
        account_id: UUID,
        preparation_input: PreparationInput,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CreatePreparationResult:
        del account_id, idempotency_key, request_id, now
        self._raise()
        self.received_input = preparation_input
        self.item.company_name = preparation_input.company_name
        self.item.target_country_code = preparation_input.target_country_code
        return CreatePreparationResult(self.item, not self.reused)

    async def list_preparations(
        self, account_id: UUID, *, limit: int, after: UUID | None
    ) -> PreparationPage:
        del account_id, limit, after
        self._raise()
        return PreparationPage((self.item,), self.item.id)

    async def get_preparation(self, account_id: UUID, preparation_id: UUID) -> CandidatePreparation:
        del account_id, preparation_id
        self._raise()
        return self.item

    async def replace_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        preparation_input: PreparationInput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation:
        del account_id, preparation_id, request_id, now
        self._raise()
        self.received_input = preparation_input
        self.received_version = expected_version
        self.item.company_name = preparation_input.company_name
        self.item.version += 1
        return self.item

    async def archive_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation:
        del account_id, preparation_id, request_id, now
        self._raise()
        self.received_version = expected_version
        self.item.status = "archived"
        self.item.version += 1
        return self.item

    async def export_account_metadata(self, session: object, *, account_id: UUID) -> list[object]:
        del session, account_id
        return []

    async def erase_account_metadata(self, session: object, *, account_id: UUID) -> int:
        del session, account_id
        return 0


def _client(
    scopes: frozenset[str],
    service: ControlledCandidateInputs | FailClosedCandidateInputService,
) -> TestClient:
    account_id = service.account_id if isinstance(service, ControlledCandidateInputs) else uuid4()
    return TestClient(
        create_app(
            Settings(_env_file=None, environment="test", allowed_hosts=("testserver",)),
            database=ReadyDatabase(),
            authentication=ControlledAuthentication(Principal(account_id, scopes)),
            candidate_inputs=service,
        )
    )


def test_domain_normalizes_bounded_text_and_requires_exact_fallbacks() -> None:
    normalized = normalize_preparation_input(
        _input(
            company_name="  Example\u3000Company  ",
            target_country_code="az",
            target_office="  Baku  ",
        )
    )

    assert normalized.company_name == "Example Company"
    assert normalized.target_country_code == "AZ"
    assert normalized.target_office == "Baku"
    with pytest.raises(ValueError, match="required only"):
        normalize_preparation_input(_input(role_family="other"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="control"):
        normalize_preparation_input(_input(company_name="hidden\u200bcompany"))
    with pytest.raises(ValueError, match="control"):
        normalize_preparation_input(_input(company_name="Visible Company\n"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"company_name": " "}, "company_name"),
        ({"role_family": "unknown"}, "role_family"),
        ({"seniority": "unknown"}, "seniority"),
        ({"interview_round": "unknown"}, "interview_round"),
        ({"interview_language": "fr"}, "interview_language"),
        ({"target_country_code": "A1"}, "country"),
        ({"seniority_other": "custom"}, "required only"),
        ({"interview_round": "other"}, "required only"),
    ],
)
def test_domain_rejects_unknown_or_inconsistent_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_preparation_input(_input(**changes))


def test_create_requires_scope_and_returns_etag_with_idempotent_status() -> None:
    controlled = ControlledCandidateInputs(uuid4())
    with _client(frozenset({"preparation:read"}), controlled) as client:
        forbidden = client.post(
            "/api/v1/preparations",
            json=_payload(),
            headers={"authorization": "Bearer valid", "idempotency-key": "prep-key-001"},
        )
    with _client(frozenset({"preparation:write"}), controlled) as client:
        created = client.post(
            "/api/v1/preparations",
            json=_payload(company_name="  Example Company  ", target_country_code="az"),
            headers={"authorization": "Bearer valid", "idempotency-key": "prep-key-001"},
        )
        controlled.reused = True
        repeated = client.post(
            "/api/v1/preparations",
            json=_payload(),
            headers={"authorization": "Bearer valid", "idempotency-key": "prep-key-001"},
        )

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    assert created.json()["target_country_code"] == "AZ"
    assert controlled.received_input is not None
    assert controlled.received_input.company_name == "Example Company"
    assert repeated.status_code == 200


def test_list_get_replace_and_archive_contracts() -> None:
    controlled = ControlledCandidateInputs(uuid4())
    scopes = frozenset({"preparation:read", "preparation:write"})
    with _client(scopes, controlled) as client:
        listed = client.get(
            "/api/v1/preparations?limit=10",
            headers={"authorization": "Bearer valid"},
        )
        fetched = client.get(
            f"/api/v1/preparations/{controlled.item.id}",
            headers={"authorization": "Bearer valid"},
        )
        replaced = client.put(
            f"/api/v1/preparations/{controlled.item.id}",
            json=_payload(company_name="Updated Company"),
            headers={"authorization": "Bearer valid", "if-match": '"1"'},
        )
        archived = client.post(
            f"/api/v1/preparations/{controlled.item.id}/archive",
            headers={"authorization": "Bearer valid", "if-match": '"2"'},
        )

    assert listed.status_code == 200
    assert listed.json()["next_after"] == str(controlled.item.id)
    assert fetched.status_code == 200 and fetched.headers["etag"] == '"1"'
    assert replaced.status_code == 200 and replaced.json()["company_name"] == "Updated Company"
    assert controlled.received_version == 2
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert archived.headers["etag"] == '"3"'


def test_write_preconditions_and_opaque_domain_errors() -> None:
    controlled = ControlledCandidateInputs(uuid4())
    with _client(frozenset({"preparation:write"}), controlled) as client:
        missing = client.put(
            f"/api/v1/preparations/{controlled.item.id}",
            json=_payload(),
            headers={"authorization": "Bearer valid"},
        )
        malformed = client.put(
            f"/api/v1/preparations/{controlled.item.id}",
            json=_payload(),
            headers={"authorization": "Bearer valid", "if-match": "1"},
        )
        invalid_input = client.post(
            "/api/v1/preparations",
            json=_payload(role_family="other"),
            headers={"authorization": "Bearer valid", "idempotency-key": "prep-key-002"},
        )

    assert missing.status_code == 428
    assert malformed.status_code == 400
    assert invalid_input.status_code == 422

    cases = (
        (CandidatePreparationNotFoundError("private detail"), 404),
        (CandidatePreparationConflictError("private detail"), 409),
        (CandidatePreparationPreconditionError("private detail"), 412),
        (CandidateInputUnavailableError("private detail"), 503),
    )
    for error, expected_status in cases:
        failing = ControlledCandidateInputs(uuid4(), error)
        with _client(frozenset({"preparation:read"}), failing) as client:
            response = client.get(
                f"/api/v1/preparations/{uuid4()}",
                headers={"authorization": "Bearer valid"},
            )
        assert response.status_code == expected_status
        assert "private detail" not in response.text


def test_candidate_input_boundary_is_fail_closed_by_default() -> None:
    with _client(frozenset({"preparation:read"}), FailClosedCandidateInputService()) as client:
        response = client.get(
            "/api/v1/preparations",
            headers={"authorization": "Bearer valid"},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_fail_closed_runtime_covers_every_command_and_safe_lifecycle_noops() -> None:
    service = FailClosedCandidateInputService()
    account_id = uuid4()
    preparation_id = uuid4()
    commands = (
        service.create_preparation(account_id, _input(), "valid-key-001", None),
        service.list_preparations(account_id, limit=20, after=None),
        service.get_preparation(account_id, preparation_id),
        service.replace_preparation(
            account_id, preparation_id, _input(), expected_version=1, request_id=None
        ),
        service.archive_preparation(
            account_id, preparation_id, expected_version=1, request_id=None
        ),
    )
    for command in commands:
        with pytest.raises(CandidateInputUnavailableError):
            await command

    assert await service.export_account_metadata(object(), account_id=account_id) == []  # type: ignore[arg-type]
    assert await service.erase_account_metadata(object(), account_id=account_id) == 0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_service_bounds_commands_before_database_access() -> None:
    service = build_candidate_inputs(
        Settings(_env_file=None, environment="test", privacy_enabled=False), ReadyDatabase()
    )
    assert isinstance(service, FailClosedCandidateInputService)
    enabled = build_candidate_inputs(
        Settings(
            _env_file=None,
            environment="test",
            privacy_enabled=True,
            privacy_subject_hmac_key=SecretStr("x" * 32),
        ),
        ReadyDatabase(),
    )
    with pytest.raises(ValueError, match="idempotency"):
        await enabled.create_preparation(uuid4(), _input(), "short", None)
    with pytest.raises(ValueError, match="limit"):
        await enabled.list_preparations(uuid4(), limit=0, after=None)
