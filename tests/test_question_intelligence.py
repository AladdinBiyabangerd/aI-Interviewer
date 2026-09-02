from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from ai_interviewer.knowledge import (
    CompanyInterviewFingerprint,
    CompetencyNode,
    EvidenceSignal,
    FingerprintDistribution,
    KnowledgeSource,
    QuestionConcept,
    RightsStatus,
    RoleCompetencyGraph,
    SourceType,
    derive_company_interview_fingerprint,
    find_nodes,
    industry_evidence_catalog,
    question_concept_catalog,
    role_competency_graph,
    role_evidence_catalog,
)
from ai_interviewer.profiling import (
    CvProfileOutput,
    CvProjectClaim,
    CvSkillClaim,
    JobDescriptionProfileOutput,
    JobRequirementClaim,
    SourceSpan,
)
from ai_interviewer.retrieval import (
    InterviewIntelligenceRequest,
    RankingWeights,
    build_interview_question_blueprint,
)

NOW = datetime(2026, 9, 2, 12, tzinfo=UTC)


def _span(source: str, quote: str, *, start_at: int = 0) -> SourceSpan:
    start = source.index(quote, start_at)
    return SourceSpan(start=start, end=start + len(quote), quote=quote)


def _jd_profile(source: str) -> JobDescriptionProfileOutput:
    return JobDescriptionProfileOutput(
        document_type="job_description",
        languages=("en",),
        must_have=(
            JobRequirementClaim(
                claim_id="must_rag",
                statement="Develop and deploy RAG systems in production",
                assertion_kind="explicit",
                evidence=(_span(source, "RAG systems in production"),),
                category="skill",
            ),
            JobRequirementClaim(
                claim_id="must_python",
                statement="Strong Python engineering",
                assertion_kind="explicit",
                evidence=(_span(source, "Python engineering"),),
                category="skill",
            ),
        ),
        nice_to_have=(
            JobRequirementClaim(
                claim_id="nice_mlops",
                statement="MLOps and Docker experience",
                assertion_kind="explicit",
                evidence=(_span(source, "MLOps and Docker"),),
                category="skill",
            ),
        ),
    )


def _cv_profile(source: str) -> CvProfileOutput:
    return CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Uses Python professionally",
                assertion_kind="explicit",
                evidence=(_span(source, "Python"),),
                name="Python",
                category="programming_language",
            ),
        ),
        projects=(
            CvProjectClaim(
                claim_id="project_rag",
                statement="Built a RAG system with FAISS and OpenAI",
                assertion_kind="explicit",
                evidence=(_span(source, "Built a RAG system with FAISS and OpenAI"),),
                name="Knowledge assistant",
                technologies=("FAISS", "OpenAI"),
            ),
        ),
    )


def _request(
    *,
    evidence: tuple[EvidenceSignal, ...] = (),
    industry: str | None = "banking",
    budget: int = 12,
) -> InterviewIntelligenceRequest:
    jd_source = (
        "We need experience developing RAG systems in production, strong Python engineering, "
        "and ideally MLOps and Docker knowledge."
    )
    cv_source = "Python engineer. Built a RAG system with FAISS and OpenAI."
    return InterviewIntelligenceRequest(
        company_name="Example Bank",
        role_title="AI Engineer",
        role_family="data_and_ai",
        seniority="mid",
        interview_round="technical_screen",
        interview_language="en",
        country_code="AZ",
        industry=industry,
        question_budget=budget,
        jd_profile=_jd_profile(jd_source),
        cv_profile=_cv_profile(cv_source),
        evidence=evidence,
    )


def _source(
    source_id: str,
    *,
    rights: RightsStatus = "permitted_derived",
    trust: float = 0.9,
    independent_group: str | None = None,
    source_type: SourceType = "official_site",
) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=source_id,
        source_type=source_type,
        source_url=f"https://example.com/{source_id}",
        rights_status=rights,
        policy_version="source_policy_v1",
        retrieved_at=NOW,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        content_sha256=sha256(source_id.encode()).hexdigest(),
        source_trust=trust,
        independent_group=independent_group or source_id,
    )


def _company_evidence(*sources: KnowledgeSource, confidence: float = 0.85) -> EvidenceSignal:
    return EvidenceSignal(
        evidence_id="example_bank_system_design",
        layer="company_official",
        competency_key="system_design",
        signal="The role emphasizes scalable production architecture",
        sources=sources,
        confidence=confidence,
        frequency=5,
        company_name="Example Bank",
        role_family="data_and_ai",
        interview_round="technical_screen",
    )


def test_rag_requirement_activates_deep_competency_map_and_cv_probe_tree() -> None:
    graph = role_competency_graph("data_and_ai")
    rag = next(node for node in graph.nodes if node.key == "rag")

    assert {
        "document_ingestion",
        "chunking",
        "embedding_selection",
        "vector_retrieval",
        "metadata_filtering",
        "hybrid_search",
        "reranking",
        "context_construction",
        "hallucination_mitigation",
        "retrieval_evaluation",
        "generation_evaluation",
        "latency_cost",
        "production_monitoring",
        "failure_scaling",
    }.issubset(rag.subtopics)
    concepts = question_concept_catalog("data_and_ai")
    retrieval_evaluation = next(
        concept for concept in concepts if concept.subtopic == "retrieval_evaluation"
    )
    assert {"recall@k", "precision@k", "MRR"}.issubset(retrieval_evaluation.possible_probes)

    blueprint = build_interview_question_blueprint(_request(), now=NOW)
    rag_activation = next(
        item for item in blueprint.competency_plan if item.competency_key == "rag"
    )
    rag_questions = [item for item in blueprint.questions if item.concept.competency_key == "rag"]

    assert rag_activation.jd_importance == 1.0
    assert rag_activation.matched_jd_claim_ids == ("must_rag",)
    assert rag_activation.matched_cv_claim_ids == ("project_rag",)
    assert len(rag_questions) >= 3
    assert all("vacancy_driven" in item.origins for item in rag_questions)
    assert all("cv_probe" in item.origins for item in rag_questions)


def test_banking_cold_start_is_industry_and_vacancy_driven_not_generic() -> None:
    blueprint = build_interview_question_blueprint(_request(), now=NOW)

    assert blueprint.cold_start is True
    assert blueprint.specificity == "limited"
    assert blueprint.fallback_path == (
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
    fraud_questions = [
        item for item in blueprint.questions if item.concept.competency_key == "fraud_risk"
    ]
    assert fraud_questions
    assert all("industry_derived" in item.origins for item in fraud_questions)
    assert all("company_supported" not in item.origins for item in fraud_questions)
    assert "not a claim about private questions" in blueprint.user_notice


def test_corroborated_official_company_evidence_can_reach_high_specificity() -> None:
    official = _source("official_hiring_page", independent_group="company")
    report = _source(
        "approved_user_report",
        independent_group="reporter_42",
        source_type="user_interview_report",
    )
    blueprint = build_interview_question_blueprint(
        _request(evidence=(_company_evidence(official, report),)),
        now=NOW,
    )

    assert blueprint.cold_start is False
    assert blueprint.specificity == "high"
    assert blueprint.fallback_path[0] == "company_evidence"
    company_questions = [
        item for item in blueprint.questions if "company_supported" in item.origins
    ]
    assert company_questions
    assert all("example_bank_system_design" in item.evidence_ids for item in company_questions)
    assert blueprint.metrics.company_specificity_precision == 1.0

    fingerprint = derive_company_interview_fingerprint(
        company_name="Example Bank",
        role_family="data_and_ai",
        seniority="mid",
        country_code="AZ",
        interview_round="technical_screen",
        evidence=(_company_evidence(official, report),),
    )
    assert fingerprint.specificity == "high"
    assert fingerprint.competency_distribution[0].competency_key == "system_design"
    assert fingerprint.competency_distribution[0].share == 1.0


def test_one_weak_or_rights_blocked_source_cannot_claim_company_specificity() -> None:
    weak = _source(
        "anonymous_report",
        trust=0.2,
        source_type="user_interview_report",
    )
    weak_blueprint = build_interview_question_blueprint(
        _request(evidence=(_company_evidence(weak, confidence=0.35),)),
        now=NOW,
    )
    blocked = _source("metadata_only_page", rights="metadata_only")
    blocked_blueprint = build_interview_question_blueprint(
        _request(evidence=(_company_evidence(blocked),)),
        now=NOW,
    )

    assert weak_blueprint.specificity == "limited"
    assert weak_blueprint.cold_start is True
    assert weak_blueprint.fallback_path[0] == "limited_company_evidence"
    assert blocked_blueprint.specificity == "limited"
    assert blocked_blueprint.cold_start is True
    assert all("company_supported" not in item.origins for item in blocked_blueprint.questions)
    with pytest.raises(ValueError, match="rights-cleared"):
        derive_company_interview_fingerprint(
            company_name="Example Bank",
            role_family="data_and_ai",
            seniority="mid",
            country_code="AZ",
            interview_round="technical_screen",
            evidence=(_company_evidence(blocked),),
        )


def test_coverage_is_budget_complete_diverse_and_duplicate_free() -> None:
    blueprint = build_interview_question_blueprint(_request(budget=20), now=NOW)
    competency_counts: dict[str, int] = {}
    for item in blueprint.questions:
        key = item.concept.competency_key
        competency_counts[key] = competency_counts.get(key, 0) + 1

    assert len(blueprint.questions) == 20
    assert len(competency_counts) >= 5
    assert competency_counts["rag"] < 10
    assert blueprint.metrics.duplicate_rate == 0.0
    assert blueprint.metrics.question_diversity >= 0.6
    assert blueprint.metrics.major_jd_competency_coverage == 1.0


def test_ranker_uses_configurable_component_weights_and_probabilistic_labels() -> None:
    custom = RankingWeights(
        vacancy_importance=0.4,
        role_relevance=0.1,
        company_evidence=0.05,
        round_relevance=0.1,
        seniority_relevance=0.05,
        industry_relevance=0.1,
        cv_relevance=0.1,
        source_confidence=0.04,
        frequency=0.02,
        recency=0.02,
        corroboration=0.02,
    )
    blueprint = build_interview_question_blueprint(_request(), weights=custom, now=NOW)

    assert blueprint.weights == custom
    assert all(
        item.likelihood in {"high_likelihood", "strong_match", "worth_preparing"}
        for item in blueprint.questions
    )
    assert all("will be asked" not in item.rationale.casefold() for item in blueprint.questions)
    with pytest.raises(ValidationError, match="sum to one"):
        RankingWeights(vacancy_importance=0.5)


def test_knowledge_contracts_fail_closed_on_rights_provenance_and_fingerprint_shape() -> None:
    with pytest.raises(ValidationError, match="after retrieval"):
        KnowledgeSource(
            source_id="future_source",
            source_type="official_site",
            rights_status="permitted_derived",
            policy_version="policy_v1",
            retrieved_at=NOW,
            published_at=datetime(2027, 1, 1, tzinfo=UTC),
            content_sha256="a" * 64,
            source_trust=0.9,
            independent_group="future_source",
        )
    with pytest.raises(ValidationError, match="identify the company"):
        EvidenceSignal(
            evidence_id="missing_company",
            layer="company_public",
            competency_key="python",
            signal="Python is emphasized",
            sources=(_source("source_one"),),
            confidence=0.5,
        )
    with pytest.raises(ValidationError, match="corroboration"):
        CompanyInterviewFingerprint(
            company_name="Example Bank",
            role_family="data_and_ai",
            seniority="mid",
            country_code="AZ",
            interview_round="technical_screen",
            competency_distribution=(FingerprintDistribution(competency_key="rag", share=1.0),),
            evidence_ids=("evidence_one",),
            evidence_count=1,
            independent_source_count=1,
            specificity="high",
        )


def test_catalog_matcher_uses_bounded_aliases_and_general_roles_remain_usable() -> None:
    graph = role_competency_graph("data_and_ai")
    matches = find_nodes(graph, ("Production RAG and Python",))

    assert {"rag", "python", "deployment_mlops"}.issubset(matches)
    assert "ml_fundamentals" not in find_nodes(graph, ("HTML templates",))
    assert len(question_concept_catalog("product")) >= 10
    assert industry_evidence_catalog(None, "data_and_ai", NOW) == ()
    assert industry_evidence_catalog("unknown", "data_and_ai", NOW) == ()
    assert industry_evidence_catalog("banking", "software_engineering", NOW) == ()
    role_evidence = role_evidence_catalog("data_and_ai", NOW)
    assert len(role_evidence) == len(graph.nodes)
    assert all(item.layer == "role_pattern" for item in role_evidence)


def test_contracts_reject_duplicate_graph_concepts_and_bad_ranking_inputs() -> None:
    node = CompetencyNode(
        key="python",
        label="Python",
        aliases=("python",),
        subtopics=("testing",),
        default_weight=1.0,
    )
    with pytest.raises(ValidationError, match="node keys"):
        RoleCompetencyGraph(
            graph_id="duplicate_graph",
            graph_version="v1",
            role_family="software_engineering",
            nodes=(node, node),
        )
    with pytest.raises(ValidationError, match="probes must be unique"):
        QuestionConcept(
            concept_id="duplicate_probes",
            role_families=("software_engineering",),
            competency_key="python",
            subtopic="testing",
            seniorities=("mid",),
            interview_rounds=("technical_screen",),
            difficulty="medium",
            question_intent="Assess testing depth.",
            possible_probes=("pytest", "PyTest"),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_interview_question_blueprint(_request(), now=datetime(2026, 9, 2))
    with pytest.raises(ValueError, match="must not be empty"):
        build_interview_question_blueprint(_request(), concepts=(), now=NOW)
