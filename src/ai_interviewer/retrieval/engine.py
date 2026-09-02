"""Deterministic evidence-aware ranking and competency coverage optimization."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime

from ai_interviewer.knowledge import (
    CompetencyNode,
    EvidenceSignal,
    QuestionConcept,
    find_nodes,
    industry_evidence_catalog,
    question_concept_catalog,
    role_competency_graph,
    role_evidence_catalog,
)
from ai_interviewer.profiling import CvProfileOutput, JobDescriptionProfileOutput
from ai_interviewer.retrieval.contracts import (
    BlueprintMetrics,
    CompetencyActivation,
    InterviewIntelligenceRequest,
    InterviewQuestionBlueprint,
    LikelihoodLabel,
    QuestionOrigin,
    RankedQuestionConcept,
    RankingWeights,
    ScoreBreakdown,
    Specificity,
)

_TOKEN_PATTERN = re.compile(r"[\w@]+", re.UNICODE)
_COMPANY_LAYERS = {"company_official", "company_public", "user_report"}
_FALLBACK_PATH = (
    "deep_jd_analysis",
    "role_family_identification",
    "seniority_alignment",
    "industry_context",
    "role_competency_graph",
    "global_role_patterns",
    "industry_patterns",
    "cv_deep_probes",
    "grounded_question_concepts",
)


def build_interview_question_blueprint(
    request: InterviewIntelligenceRequest,
    *,
    weights: RankingWeights | None = None,
    concepts: Sequence[QuestionConcept] | None = None,
    now: datetime | None = None,
) -> InterviewQuestionBlueprint:
    """Rank concepts and allocate a diverse, budget-complete interview blueprint."""
    policy = weights or RankingWeights()
    catalog = tuple(question_concept_catalog(request.role_family) if concepts is None else concepts)
    if not catalog:
        raise ValueError("question concept catalog must not be empty")
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("ranking time must be timezone-aware")

    derived_industry_evidence = industry_evidence_catalog(
        request.industry, request.role_family, current_time
    )
    derived_role_evidence = role_evidence_catalog(request.role_family, current_time)
    effective_request = request.model_copy(
        update={
            "evidence": (
                *request.evidence,
                *derived_role_evidence,
                *derived_industry_evidence,
            )
        }
    )

    activations = _build_activations(effective_request)
    ranked = tuple(
        _rank_concept(effective_request, concept, activations, policy, current_time)
        for concept in catalog
        if request.role_family in concept.role_families
    )
    if not ranked:
        raise ValueError("question concept catalog has no concepts for the requested role")
    selected = _select_for_coverage(ranked, activations, request.question_budget)
    if len(selected) != request.question_budget:
        raise ValueError("question concept catalog cannot satisfy the requested budget")

    company_evidence = _matching_company_evidence(effective_request, effective_request.evidence)
    specificity = _specificity(company_evidence)
    cold_start = specificity == "limited"
    fallback_path: tuple[str, ...]
    if not company_evidence:
        fallback_path = _FALLBACK_PATH
    elif cold_start:
        fallback_path = ("limited_company_evidence", *_FALLBACK_PATH)
    else:
        fallback_path = ("company_evidence", *_FALLBACK_PATH)
    return InterviewQuestionBlueprint(
        questions=selected,
        competency_plan=activations,
        specificity=specificity,
        cold_start=cold_start,
        fallback_path=fallback_path,
        weights=policy,
        metrics=_metrics(selected, activations),
        user_notice=(
            "These are evidence-ranked preparation areas, not a claim about private questions. "
            + (
                "Company specificity is Limited; ranking is vacancy, role, industry, and CV driven."
                if specificity == "limited"
                else f"Company specificity is {specificity.title()} and remains probabilistic."
            )
        ),
    )


def _profile_claims(
    profile: JobDescriptionProfileOutput | CvProfileOutput | None,
) -> tuple[tuple[str, str, float], ...]:
    if profile is None:
        return ()
    if isinstance(profile, JobDescriptionProfileOutput):
        claims = [
            *((claim.claim_id, claim.statement, 1.0) for claim in profile.must_have),
            *((claim.claim_id, claim.statement, 0.65) for claim in profile.nice_to_have),
            *((claim.claim_id, claim.statement, 0.55) for claim in profile.responsibilities),
        ]
        return tuple(claims)
    return tuple((claim.claim_id, claim.statement, 1.0) for claim in profile.evidence_claims())


def _build_activations(
    request: InterviewIntelligenceRequest,
) -> tuple[CompetencyActivation, ...]:
    graph = role_competency_graph(request.role_family)
    jd_claims = _profile_claims(request.jd_profile)
    cv_claims = _profile_claims(request.cv_profile)
    jd_matches = find_nodes(graph, (statement for _, statement, _ in jd_claims))
    cv_matches = find_nodes(graph, (statement for _, statement, _ in cv_claims))
    relevant_evidence = tuple(
        signal
        for signal in request.evidence
        if signal.eligible_sources
        and (signal.role_family is None or signal.role_family == request.role_family)
    )
    raw: list[
        tuple[CompetencyNode, float, float, float, float, tuple[str, ...], tuple[str, ...]]
    ] = []
    for node in graph.nodes:
        jd_ids = tuple(
            claim_id
            for claim_id, statement, _ in jd_claims
            if node.key in find_nodes(graph, (statement,))
        )
        cv_ids = tuple(
            claim_id
            for claim_id, statement, _ in cv_claims
            if node.key in find_nodes(graph, (statement,))
        )
        jd_importance = max(
            (importance for claim_id, _, importance in jd_claims if claim_id in set(jd_ids)),
            default=0.0,
        )
        signal_boost = 0.0
        if node.key in jd_matches:
            signal_boost += 1.2 * jd_importance
        if node.key in cv_matches:
            signal_boost += 0.25
        industry_confidence = max(
            (
                signal.confidence
                for signal in relevant_evidence
                if signal.layer == "industry_pattern"
                and signal.competency_key == node.key
                and request.industry is not None
                and signal.industry is not None
                and signal.industry.casefold() == request.industry.casefold()
            ),
            default=0.0,
        )
        company_confidence = max(
            (
                signal.confidence
                for signal in _matching_company_evidence(request, relevant_evidence)
                if signal.competency_key == node.key
            ),
            default=0.0,
        )
        signal_boost += 0.6 * industry_confidence + 0.7 * company_confidence
        raw_weight = node.default_weight * (1.0 + signal_boost)
        raw.append(
            (
                node,
                raw_weight,
                jd_importance,
                industry_confidence,
                company_confidence,
                jd_ids,
                cv_ids,
            )
        )
    total = sum(item[1] for item in raw)
    return tuple(
        CompetencyActivation(
            competency_key=node.key,
            label=node.label,
            target_share=raw_weight / total,
            jd_importance=jd_importance,
            industry_relevance=industry_confidence,
            company_relevance=company_confidence,
            matched_jd_claim_ids=jd_ids,
            matched_cv_claim_ids=cv_ids,
        )
        for (
            node,
            raw_weight,
            jd_importance,
            industry_confidence,
            company_confidence,
            jd_ids,
            cv_ids,
        ) in raw
    )


def _matching_evidence(
    request: InterviewIntelligenceRequest,
    concept: QuestionConcept,
) -> tuple[EvidenceSignal, ...]:
    return tuple(
        signal
        for signal in request.evidence
        if signal.eligible_sources
        and signal.competency_key == concept.competency_key
        and (signal.role_family is None or signal.role_family == request.role_family)
    )


def _matching_company_evidence(
    request: InterviewIntelligenceRequest,
    evidence: Iterable[EvidenceSignal],
) -> tuple[EvidenceSignal, ...]:
    company = request.company_name.casefold()
    return tuple(
        signal
        for signal in evidence
        if signal.layer in _COMPANY_LAYERS
        and signal.company_name is not None
        and signal.company_name.casefold() == company
        and signal.eligible_sources
    )


def _rank_concept(
    request: InterviewIntelligenceRequest,
    concept: QuestionConcept,
    activations: Sequence[CompetencyActivation],
    weights: RankingWeights,
    now: datetime,
) -> RankedQuestionConcept:
    activation = next(item for item in activations if item.competency_key == concept.competency_key)
    evidence = _matching_evidence(request, concept)
    company_evidence = _matching_company_evidence(request, evidence)
    industry_evidence = tuple(
        item
        for item in evidence
        if item.layer == "industry_pattern"
        and request.industry is not None
        and item.industry is not None
        and item.industry.casefold() == request.industry.casefold()
    )
    source_values = [source.source_trust for item in evidence for source in item.eligible_sources]
    independent_groups = {
        source.independent_group for item in evidence for source in item.eligible_sources
    }
    recencies = [
        _recency(source.published_at or source.retrieved_at, now)
        for item in evidence
        for source in item.eligible_sources
    ]
    company_confidence = max((item.confidence for item in company_evidence), default=0.0)
    company_corroboration = min(
        1.0,
        len(
            {
                source.independent_group
                for item in company_evidence
                for source in item.eligible_sources
            }
        )
        / 2.0,
    )
    breakdown = ScoreBreakdown(
        vacancy_importance=activation.jd_importance,
        role_relevance=1.0,
        company_evidence=company_confidence * company_corroboration,
        round_relevance=1.0 if request.interview_round in concept.interview_rounds else 0.15,
        seniority_relevance=1.0 if request.seniority in concept.seniorities else 0.0,
        industry_relevance=max((item.confidence for item in industry_evidence), default=0.0),
        cv_relevance=1.0 if activation.matched_cv_claim_ids else 0.0,
        source_confidence=sum(source_values) / len(source_values) if source_values else 0.0,
        frequency=min(1.0, math.log1p(sum(item.frequency for item in evidence)) / math.log(11)),
        recency=sum(recencies) / len(recencies) if recencies else 0.5,
        corroboration=min(1.0, len(independent_groups) / 3.0),
    )
    score = sum(
        getattr(breakdown, field) * getattr(weights, field) for field in ScoreBreakdown.model_fields
    )
    origins: list[QuestionOrigin] = ["role_derived"]
    if activation.matched_jd_claim_ids:
        origins.insert(0, "vacancy_driven")
    if industry_evidence:
        origins.append("industry_derived")
    if activation.matched_cv_claim_ids:
        origins.append("cv_probe")
    if company_evidence:
        origins.append("company_supported")
    likelihood: LikelihoodLabel = (
        "high_likelihood"
        if score >= 0.72
        else "strong_match"
        if score >= 0.48
        else "worth_preparing"
    )
    rationale_parts = [origin.replace("_", " ") for origin in origins]
    return RankedQuestionConcept(
        concept=concept,
        score=round(score, 6),
        score_breakdown=breakdown,
        origins=tuple(origins),
        evidence_ids=tuple(sorted(item.evidence_id for item in evidence)),
        likelihood=likelihood,
        rationale="Ranked as " + ", ".join(rationale_parts) + "; usefulness remains probabilistic.",
    )


def _recency(observed_at: datetime, now: datetime) -> float:
    if observed_at.tzinfo is None:
        return 0.0
    age_days = max(0.0, (now - observed_at).total_seconds() / 86_400)
    return 1.0 / (1.0 + age_days / 365.0)


def _select_for_coverage(
    ranked: Sequence[RankedQuestionConcept],
    activations: Sequence[CompetencyActivation],
    budget: int,
) -> tuple[RankedQuestionConcept, ...]:
    ordered = sorted(ranked, key=lambda item: (-item.score, item.concept.concept_id))
    quotas = _allocate_quotas(activations, budget)
    selected: list[RankedQuestionConcept] = []
    counts: defaultdict[str, int] = defaultdict(int)
    for candidate in ordered:
        key = candidate.concept.competency_key
        if counts[key] >= quotas.get(key, 0) or _is_redundant(candidate, selected):
            continue
        selected.append(candidate)
        counts[key] += 1
    for candidate in ordered:
        if len(selected) >= budget:
            break
        if candidate in selected or _is_redundant(candidate, selected):
            continue
        selected.append(candidate)
    return tuple(selected)


def _allocate_quotas(
    activations: Sequence[CompetencyActivation],
    budget: int,
) -> dict[str, int]:
    exact = {item.competency_key: item.target_share * budget for item in activations}
    quotas = {key: int(value) for key, value in exact.items()}
    remaining = budget - sum(quotas.values())
    order = sorted(exact, key=lambda key: (-(exact[key] - quotas[key]), key))
    for key in order[:remaining]:
        quotas[key] += 1
    required = [
        item.competency_key
        for item in sorted(activations, key=lambda item: -item.target_share)
        if item.jd_importance > 0
        or item.matched_cv_claim_ids
        or item.industry_relevance > 0
        or item.company_relevance > 0
    ]
    for key in required[:budget]:
        if quotas[key] > 0:
            continue
        donors = sorted(
            (candidate for candidate, quota in quotas.items() if quota > 1),
            key=lambda candidate: (-quotas[candidate], candidate),
        )
        if not donors:
            break
        quotas[donors[0]] -= 1
        quotas[key] = 1
    return quotas


def _tokens(item: RankedQuestionConcept) -> set[str]:
    text = " ".join(
        (item.concept.question_intent, item.concept.subtopic, *item.concept.possible_probes)
    )
    return {token.casefold() for token in _TOKEN_PATTERN.findall(text) if len(token) > 2}


def _is_redundant(
    candidate: RankedQuestionConcept,
    selected: Sequence[RankedQuestionConcept],
) -> bool:
    candidate_tokens = _tokens(candidate)
    for existing in selected:
        if candidate.concept.subtopic == existing.concept.subtopic:
            return True
        existing_tokens = _tokens(existing)
        union = candidate_tokens | existing_tokens
        if union and len(candidate_tokens & existing_tokens) / len(union) >= 0.82:
            return True
    return False


def _specificity(company_evidence: Sequence[EvidenceSignal]) -> Specificity:
    if not company_evidence:
        return "limited"
    groups = {
        source.independent_group for item in company_evidence for source in item.eligible_sources
    }
    confidence = max(item.confidence for item in company_evidence)
    has_official = any(item.layer == "company_official" for item in company_evidence)
    if len(groups) >= 2 and confidence >= 0.75 and has_official:
        return "high"
    if confidence >= 0.6 and (has_official or len(groups) >= 2):
        return "medium"
    return "limited"


def _mean(
    items: Sequence[RankedQuestionConcept],
    value: Callable[[RankedQuestionConcept], float],
) -> float:
    return sum(value(item) for item in items) / len(items)


def _metrics(
    selected: Sequence[RankedQuestionConcept],
    activations: Sequence[CompetencyActivation],
) -> BlueprintMetrics:
    concepts = [item.concept for item in selected]
    unique_competencies = len({item.competency_key for item in concepts})
    unique_subtopics = len({(item.competency_key, item.subtopic) for item in concepts})
    duplicate_pairs = 0
    pair_count = 0
    for index, item in enumerate(selected):
        for other in selected[index + 1 :]:
            pair_count += 1
            duplicate_pairs += int(_is_redundant(item, (other,)))
    major = {item.competency_key for item in activations if item.jd_importance >= 0.55}
    selected_keys = {item.competency_key for item in concepts}
    company_claims = [item for item in selected if "company_supported" in item.origins]
    sourced_company_claims = [item for item in company_claims if item.evidence_ids]
    return BlueprintMetrics(
        question_jd_relevance=round(
            _mean(selected, lambda item: item.score_breakdown.vacancy_importance), 6
        ),
        question_role_relevance=round(
            _mean(selected, lambda item: item.score_breakdown.role_relevance), 6
        ),
        question_round_relevance=round(
            _mean(selected, lambda item: item.score_breakdown.round_relevance), 6
        ),
        company_specificity_precision=(
            len(sourced_company_claims) / len(company_claims) if company_claims else 1.0
        ),
        question_diversity=round(
            ((unique_competencies / len(selected)) + (unique_subtopics / len(selected))) / 2,
            6,
        ),
        duplicate_rate=round(duplicate_pairs / pair_count if pair_count else 0.0, 6),
        retrieval_precision_at_budget=round(
            sum(item.score >= 0.40 for item in selected) / len(selected), 6
        ),
        source_confidence=round(
            _mean(selected, lambda item: item.score_breakdown.source_confidence), 6
        ),
        major_jd_competency_coverage=(len(major & selected_keys) / len(major) if major else 1.0),
    )
