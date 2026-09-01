"""Exact source-text verification required before a profile may be persisted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ai_interviewer.candidate_inputs.document_models import CandidateDocumentType
from ai_interviewer.candidate_inputs.source_text_models import MAX_SOURCE_TEXT_CHARACTERS
from ai_interviewer.profiling.contracts import (
    CandidateProfileOutput,
    CvProfileOutput,
    JobDescriptionProfileOutput,
)

ProfileEvidenceFailureCode = Literal[
    "profile_type_invalid",
    "document_type_mismatch",
    "source_text_invalid",
    "span_out_of_bounds",
    "quote_mismatch",
]


class ProfileEvidenceError(ValueError):
    """Payload-free evidence failure safe to persist as a bounded job code."""

    def __init__(self, code: ProfileEvidenceFailureCode) -> None:
        self.code = code
        super().__init__(f"profile evidence validation failed: {code}")


@dataclass(frozen=True, slots=True)
class VerifiedProfile[ProfileT: CandidateProfileOutput]:
    """Profile proven against one in-memory exact source-text version."""

    profile: ProfileT = field(repr=False)
    document_type: CandidateDocumentType
    claim_count: int
    evidence_span_count: int
    evidence_character_count: int


def validate_profile_evidence[ProfileT: CandidateProfileOutput](
    profile: ProfileT,
    source_text: str,
    expected_document_type: CandidateDocumentType,
) -> VerifiedProfile[ProfileT]:
    """Verify every model quote against exact Python code-point source offsets."""
    if not isinstance(profile, (CvProfileOutput, JobDescriptionProfileOutput)):
        raise ProfileEvidenceError("profile_type_invalid")
    if profile.document_type != expected_document_type:
        raise ProfileEvidenceError("document_type_mismatch")
    if not isinstance(source_text, str) or not 1 <= len(source_text) <= MAX_SOURCE_TEXT_CHARACTERS:
        raise ProfileEvidenceError("source_text_invalid")

    claims = profile.evidence_claims()
    intervals: list[tuple[int, int]] = []
    evidence_span_count = 0
    for claim in claims:
        for span in claim.evidence:
            if span.end > len(source_text):
                raise ProfileEvidenceError("span_out_of_bounds")
            if source_text[span.start : span.end] != span.quote:
                raise ProfileEvidenceError("quote_mismatch")
            intervals.append((span.start, span.end))
            evidence_span_count += 1

    evidence_character_count = _covered_characters(intervals)
    return VerifiedProfile(
        profile=profile,
        document_type=expected_document_type,
        claim_count=len(claims),
        evidence_span_count=evidence_span_count,
        evidence_character_count=evidence_character_count,
    )


def _covered_characters(intervals: list[tuple[int, int]]) -> int:
    ordered = sorted(intervals)
    start, end = ordered[0]
    total = 0
    for next_start, next_end in ordered[1:]:
        if next_start > end:
            total += end - start
            start, end = next_start, next_end
        else:
            end = max(end, next_end)
    return total + end - start
