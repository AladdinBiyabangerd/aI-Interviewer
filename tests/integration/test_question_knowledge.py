import pytest

from ai_interviewer.knowledge import (
    QUESTION_CATALOG_VERSION,
    QuestionConceptRepository,
    question_concept_catalog,
)
from ai_interviewer.persistence.database import Database

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_question_concept_catalog_persists_idempotently(database: Database) -> None:
    repository = QuestionConceptRepository(database)
    expected = question_concept_catalog("data_and_ai")

    first = await repository.sync_role_catalog("data_and_ai")
    second = await repository.sync_role_catalog("data_and_ai")
    persisted = await repository.list_role_concepts("data_and_ai")

    assert first.inserted == len(expected)
    assert first.available == len(expected)
    assert second.inserted == 0
    assert second.available == len(expected)
    assert persisted == tuple(sorted(expected, key=lambda item: item.concept_id))
    assert QUESTION_CATALOG_VERSION == "v1"
    assert all("question" not in concept.model_dump() for concept in persisted)
