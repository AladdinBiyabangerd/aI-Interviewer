"""Transactional release of candidate-domain references before file-asset deletion."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocument,
    CandidateDocumentVersion,
)
from ai_interviewer.candidate_inputs.intake_models import CandidateDocumentIntake


async def release_candidate_file_asset_references(
    session: AsyncSession,
    *,
    file_asset_id: UUID,
    now: datetime | None = None,
) -> int:
    """Remove all candidate references while the caller holds the asset transaction."""
    released_at = now or datetime.now(UTC)
    removed = 0
    version = await session.scalar(
        select(CandidateDocumentVersion)
        .where(CandidateDocumentVersion.file_asset_id == file_asset_id)
        .with_for_update()
    )
    if version is not None:
        document = await session.scalar(
            select(CandidateDocument)
            .where(CandidateDocument.id == version.document_id)
            .with_for_update()
        )
        await session.delete(version)
        await session.flush()
        removed += 1
        if document is not None:
            latest = await session.scalar(
                select(func.max(CandidateDocumentVersion.version_number)).where(
                    CandidateDocumentVersion.document_id == document.id
                )
            )
            if latest is None:
                await session.delete(document)
            else:
                document.latest_version_number = int(latest)
                document.updated_at = released_at

    intake_result = await session.execute(
        delete(CandidateDocumentIntake)
        .where(
            or_(
                CandidateDocumentIntake.file_asset_id == file_asset_id,
                CandidateDocumentIntake.reserved_file_asset_id == file_asset_id,
            )
        )
        .returning(CandidateDocumentIntake.id)
    )
    removed += len(intake_result.scalars().all())
    return removed


class CandidateFileAssetReferenceLifecycle:
    """Narrow adapter used by the file-security deletion transaction."""

    async def release_file_asset_reference(
        self,
        session: AsyncSession,
        *,
        file_asset_id: UUID,
    ) -> int:
        return await release_candidate_file_asset_references(
            session,
            file_asset_id=file_asset_id,
        )
