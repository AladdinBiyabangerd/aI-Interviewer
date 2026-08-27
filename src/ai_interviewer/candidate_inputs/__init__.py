"""Candidate onboarding and preparation-context domain."""

from ai_interviewer.candidate_inputs.documents import (
    CandidateDocumentRuntime,
    CandidateDocumentService,
    FailClosedCandidateDocumentService,
    build_candidate_documents,
)
from ai_interviewer.candidate_inputs.intakes import (
    CandidateDocumentIntakeRuntime,
    CandidateDocumentIntakeService,
    FailClosedCandidateDocumentIntakeService,
    build_candidate_document_intakes,
)
from ai_interviewer.candidate_inputs.service import (
    CandidateInputRuntime,
    CandidateInputService,
    FailClosedCandidateInputService,
    build_candidate_inputs,
)

__all__ = [
    "CandidateDocumentIntakeRuntime",
    "CandidateDocumentIntakeService",
    "CandidateDocumentRuntime",
    "CandidateDocumentService",
    "CandidateInputRuntime",
    "CandidateInputService",
    "FailClosedCandidateDocumentIntakeService",
    "FailClosedCandidateDocumentService",
    "FailClosedCandidateInputService",
    "build_candidate_document_intakes",
    "build_candidate_documents",
    "build_candidate_inputs",
]
