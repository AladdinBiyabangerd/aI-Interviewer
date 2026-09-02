"""Deterministic company-interview fingerprint derivation from stored evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ai_interviewer.candidate_inputs.models import InterviewRound, RoleFamily, Seniority
from ai_interviewer.knowledge.contracts import (
    CompanyInterviewFingerprint,
    EvidenceSignal,
    FingerprintDistribution,
    Specificity,
)

_COMPANY_LAYERS = {"company_official", "company_public", "user_report"}


def derive_company_interview_fingerprint(
    *,
    company_name: str,
    role_family: RoleFamily,
    seniority: Seniority,
    country_code: str,
    interview_round: InterviewRound,
    evidence: Iterable[EvidenceSignal],
) -> CompanyInterviewFingerprint:
    """Aggregate only rights-cleared, matching evidence into a normalized distribution."""
    matching = tuple(
        item
        for item in evidence
        if item.layer in _COMPANY_LAYERS
        and item.company_name is not None
        and item.company_name.casefold() == company_name.casefold()
        and (item.role_family is None or item.role_family == role_family)
        and (item.seniority is None or item.seniority == seniority)
        and (item.interview_round is None or item.interview_round == interview_round)
        and item.eligible_sources
    )
    if not matching:
        raise ValueError("company fingerprint requires matching rights-cleared evidence")

    competency_scores: defaultdict[str, float] = defaultdict(float)
    groups: set[str] = set()
    has_official = False
    for item in matching:
        trust = sum(source.source_trust for source in item.eligible_sources) / len(
            item.eligible_sources
        )
        competency_scores[item.competency_key] += item.confidence * trust * item.frequency
        groups.update(source.independent_group for source in item.eligible_sources)
        has_official = has_official or item.layer == "company_official"
    total = sum(competency_scores.values())
    distribution = tuple(
        FingerprintDistribution(competency_key=key, share=score / total)
        for key, score in sorted(competency_scores.items(), key=lambda pair: (-pair[1], pair[0]))
    )
    strongest_confidence = max(item.confidence for item in matching)
    specificity: Specificity
    if len(groups) >= 2 and has_official and strongest_confidence >= 0.75:
        specificity = "high"
    elif (len(groups) >= 2 or has_official) and strongest_confidence >= 0.6:
        specificity = "medium"
    else:
        specificity = "limited"
    evidence_count = max(sum(item.frequency for item in matching), len(groups))
    return CompanyInterviewFingerprint(
        company_name=company_name,
        role_family=role_family,
        seniority=seniority,
        country_code=country_code,
        interview_round=interview_round,
        competency_distribution=distribution,
        evidence_ids=tuple(sorted(item.evidence_id for item in matching)),
        evidence_count=evidence_count,
        independent_source_count=len(groups),
        specificity=specificity,
    )
