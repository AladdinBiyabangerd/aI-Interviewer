import base64
import json
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_interviewer.candidate_inputs.source_text_models import MAX_SOURCE_TEXT_CHARACTERS
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextService,
    CandidateSourceTextUnavailableError,
    FailClosedCandidateSourceTextService,
    ParserExecutionIdentity,
    build_candidate_source_texts,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.persistence.database import DatabaseRuntime
from tests.fakes import ReadyDatabase


def _keyring_document() -> str:
    def entry(key_id: str, purpose: str, marker: bytes) -> dict[str, str]:
        return {
            "id": key_id,
            "purpose": purpose,
            "material": base64.b64encode(marker * 32).decode(),
        }

    return json.dumps(
        {
            "version": 1,
            "active": {
                "field_encryption": "field-v1",
                "manifest_hmac": "manifest-v1",
                "subject_hmac": "subject-v1",
            },
            "keys": [
                entry("field-v1", "field_encryption", b"f"),
                entry("manifest-v1", "manifest_hmac", b"m"),
                entry("subject-v1", "subject_hmac", b"s"),
            ],
        }
    )


def _service() -> CandidateSourceTextService:
    return CandidateSourceTextService(
        cast(DatabaseRuntime, ReadyDatabase()),
        ApplicationKeyring.from_secret(SecretStr(_keyring_document())),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "empty"),
        (" \n\t", "empty"),
        ("line one\r\nline two", "LF newlines"),
        ("line one\x00line two", "unsafe Unicode"),
        ("line one\u202eline two", "unsafe Unicode"),
        ("x" * (MAX_SOURCE_TEXT_CHARACTERS + 1), "character limit"),
        ("😀" * 500_001, "character limit"),
    ],
    ids=(
        "empty",
        "whitespace",
        "crlf",
        "nul",
        "bidi-control",
        "character-limit",
        "unicode-limit",
    ),
)
async def test_source_text_validation_fails_before_database_access(
    content: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await _service().store_parser_extraction(
            uuid4(),
            uuid4(),
            content,
            ParserExecutionIdentity(uuid4(), "parser", "1", "no-network-v1"),
            None,
        )


@pytest.mark.asyncio
async def test_parser_identity_validation_fails_before_database_access() -> None:
    with pytest.raises(ValueError, match="parser_adapter"):
        await _service().store_parser_extraction(
            uuid4(),
            uuid4(),
            "valid text",
            ParserExecutionIdentity(uuid4(), " parser ", "1", "no-network-v1"),
            None,
        )


@pytest.mark.asyncio
async def test_correction_content_validation_fails_before_database_access() -> None:
    with pytest.raises(ValueError, match="empty"):
        await _service().append_correction(uuid4(), uuid4(), uuid4(), "   ", 1, None)
    with pytest.raises(ValueError, match="LF newlines"):
        await _service().append_correction(
            uuid4(),
            uuid4(),
            uuid4(),
            "one\r\ntwo",
            1,
            None,
        )


@pytest.mark.asyncio
async def test_source_text_builder_and_disabled_runtime_fail_closed() -> None:
    disabled = build_candidate_source_texts(
        Settings(_env_file=None, environment="test"),
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(disabled, FailClosedCandidateSourceTextService)

    with pytest.raises(CandidateSourceTextUnavailableError):
        await disabled.store_parser_extraction(
            uuid4(),
            uuid4(),
            "valid text",
            ParserExecutionIdentity(uuid4(), "parser", "1", "no-network-v1"),
            None,
        )
    with pytest.raises(CandidateSourceTextUnavailableError):
        await disabled.get_source_text(uuid4(), uuid4(), uuid4())
    with pytest.raises(CandidateSourceTextUnavailableError):
        await disabled.append_correction(uuid4(), uuid4(), uuid4(), "valid text", 1, None)

    enabled_settings = Settings(_env_file=None, environment="test").model_copy(
        update={
            "privacy_enabled": True,
            "file_security_enabled": True,
            "privacy_keyring": SecretStr(_keyring_document()),
        }
    )
    enabled = build_candidate_source_texts(
        enabled_settings,
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(enabled, CandidateSourceTextService)
