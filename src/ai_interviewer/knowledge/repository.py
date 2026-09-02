"""PostgreSQL catalog adapter kept separate from retrieval and model orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ai_interviewer.candidate_inputs.models import InterviewRound, RoleFamily, Seniority
from ai_interviewer.knowledge.catalog import question_concept_catalog
from ai_interviewer.knowledge.contracts import Difficulty, QuestionConcept
from ai_interviewer.knowledge.models import QuestionConceptRecord
from ai_interviewer.persistence.database import DatabaseRuntime

QUESTION_CATALOG_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class CatalogSyncResult:
    inserted: int
    available: int


class QuestionConceptRepository:
    """Idempotently persist and query application-authored concept releases."""

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def sync_role_catalog(self, role_family: RoleFamily) -> CatalogSyncResult:
        concepts = question_concept_catalog(role_family)
        values = [
            {
                "concept_key": concept.concept_id,
                "catalog_version": QUESTION_CATALOG_VERSION,
                "competency_key": concept.competency_key,
                "subtopic": concept.subtopic,
                "role_families": list(concept.role_families),
                "seniorities": list(concept.seniorities),
                "interview_rounds": list(concept.interview_rounds),
                "difficulty": concept.difficulty,
                "question_intent": concept.question_intent,
                "possible_probes": list(concept.possible_probes),
                "active": True,
            }
            for concept in concepts
        ]
        async with self._database.transaction() as session:
            statement = (
                insert(QuestionConceptRecord)
                .values(values)
                .on_conflict_do_nothing(constraint="uq_question_concept_release")
                .returning(QuestionConceptRecord.id)
            )
            inserted = len((await session.scalars(statement)).all())
            available = len(
                (
                    await session.scalars(
                        select(QuestionConceptRecord).where(
                            QuestionConceptRecord.catalog_version == QUESTION_CATALOG_VERSION,
                            QuestionConceptRecord.active.is_(True),
                            QuestionConceptRecord.role_families.contains([role_family]),
                        )
                    )
                ).all()
            )
        return CatalogSyncResult(inserted=inserted, available=available)

    async def list_role_concepts(
        self,
        role_family: RoleFamily,
    ) -> tuple[QuestionConcept, ...]:
        async with self._database.transaction() as session:
            records = (
                await session.scalars(
                    select(QuestionConceptRecord)
                    .where(
                        QuestionConceptRecord.catalog_version == QUESTION_CATALOG_VERSION,
                        QuestionConceptRecord.active.is_(True),
                        QuestionConceptRecord.role_families.contains([role_family]),
                    )
                    .order_by(QuestionConceptRecord.concept_key)
                )
            ).all()
        return tuple(_domain_concept(record) for record in records)


def _domain_concept(record: QuestionConceptRecord) -> QuestionConcept:
    return QuestionConcept(
        concept_id=record.concept_key,
        role_families=cast(tuple[RoleFamily, ...], tuple(record.role_families)),
        competency_key=record.competency_key,
        subtopic=record.subtopic,
        seniorities=cast(tuple[Seniority, ...], tuple(record.seniorities)),
        interview_rounds=cast(tuple[InterviewRound, ...], tuple(record.interview_rounds)),
        difficulty=cast(Difficulty, record.difficulty),
        question_intent=record.question_intent,
        possible_probes=tuple(record.possible_probes),
    )
