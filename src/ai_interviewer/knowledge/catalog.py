"""Small application-owned competency and question-concept seed catalog."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from hashlib import sha256

from ai_interviewer.candidate_inputs.models import (
    InterviewRound,
    RoleFamily,
    Seniority,
)
from ai_interviewer.knowledge.contracts import (
    CompetencyNode,
    EvidenceSignal,
    KnowledgeSource,
    QuestionConcept,
    RoleCompetencyGraph,
)

_ALL_SENIORITIES: tuple[Seniority, ...] = (
    "intern",
    "entry",
    "junior",
    "mid",
    "senior",
    "lead",
    "staff",
    "principal",
    "manager",
    "director",
    "executive",
    "other",
)
_TECHNICAL_ROUNDS: tuple[InterviewRound, ...] = (
    "hiring_manager",
    "technical_screen",
    "coding",
    "system_design",
    "case_study",
    "take_home_review",
    "panel",
    "final",
    "other",
)


def _node(
    key: str,
    label: str,
    aliases: tuple[str, ...],
    subtopics: tuple[str, ...],
    weight: float,
) -> CompetencyNode:
    return CompetencyNode(
        key=key,
        label=label,
        aliases=aliases,
        subtopics=subtopics,
        default_weight=weight,
    )


_DATA_AND_AI_NODES = (
    _node(
        "rag",
        "Retrieval-augmented generation",
        ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
        (
            "architecture",
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
        ),
        0.22,
    ),
    _node(
        "python",
        "Python engineering",
        ("python", "asyncio", "fastapi", "django", "flask"),
        ("language_internals", "data_structures", "concurrency", "testing", "performance"),
        0.16,
    ),
    _node(
        "ml_fundamentals",
        "Machine-learning fundamentals",
        ("machine learning", "ml", "classification", "regression", "statistics"),
        ("bias_variance", "feature_engineering", "validation", "metrics", "data_leakage"),
        0.14,
    ),
    _node(
        "model_evaluation",
        "Model evaluation",
        ("model evaluation", "evaluation", "metrics", "experimentation"),
        ("offline_metrics", "ground_truth", "error_analysis", "online_experimentation"),
        0.10,
    ),
    _node(
        "deployment_mlops",
        "Deployment and MLOps",
        ("deployment", "production", "mlops", "docker", "kubernetes", "model serving"),
        ("model_serving", "ci_cd", "observability", "drift", "reliability"),
        0.14,
    ),
    _node(
        "system_design",
        "System design",
        ("system design", "architecture", "scalability", "distributed system"),
        ("tradeoffs", "scalability", "availability", "data_flow", "failure_modes"),
        0.12,
    ),
    _node(
        "data_engineering",
        "Data engineering",
        ("data pipeline", "etl", "sql", "warehouse", "spark", "airflow"),
        ("pipelines", "data_quality", "sql", "batch_streaming"),
        0.07,
    ),
    _node(
        "behavioral",
        "Behavioral competencies",
        ("ownership", "leadership", "collaboration", "communication", "stakeholder"),
        ("ownership", "collaboration", "conflict", "learning"),
        0.05,
    ),
    _node(
        "fraud_risk",
        "Fraud, risk, and responsible ML",
        ("fraud", "imbalanced dataset", "explainability", "model risk"),
        (
            "fraud_detection",
            "class_imbalance",
            "explainability",
            "data_security",
            "risk_monitoring",
            "production_reliability",
        ),
        0.04,
    ),
    _node(
        "recommendation_search",
        "Recommendation, ranking, and search",
        ("recommender", "recommendation", "ranking", "personalization", "search"),
        ("recommendation", "ranking", "experimentation", "personalization", "feature_scale"),
        0.02,
    ),
    _node(
        "customer_analytics",
        "Customer analytics",
        ("churn", "time series", "segmentation", "customer analytics"),
        ("churn", "time_series", "segmentation", "large_customer_datasets"),
        0.02,
    ),
)

_SOFTWARE_NODES = (
    _node(
        "python",
        "Python engineering",
        ("python", "asyncio", "fastapi", "django", "flask"),
        ("language_internals", "data_structures", "concurrency", "testing", "performance"),
        0.22,
    ),
    _node(
        "backend_engineering",
        "Backend engineering",
        ("backend", "api", "rest", "grpc", "microservices"),
        ("api_design", "service_boundaries", "transactions", "idempotency", "security"),
        0.24,
    ),
    _node(
        "databases",
        "Databases",
        ("database", "postgresql", "postgres", "sql", "redis"),
        ("schema_design", "query_plans", "transactions", "indexing", "caching"),
        0.18,
    ),
    _node(
        "system_design",
        "System design",
        ("system design", "architecture", "scalability", "distributed system"),
        ("tradeoffs", "scalability", "availability", "data_flow", "failure_modes"),
        0.20,
    ),
    _node(
        "deployment_mlops",
        "Delivery and operations",
        ("deployment", "production", "docker", "kubernetes", "devops"),
        ("ci_cd", "observability", "reliability"),
        0.10,
    ),
    _node(
        "behavioral",
        "Behavioral competencies",
        ("ownership", "leadership", "collaboration", "communication", "stakeholder"),
        ("ownership", "collaboration", "conflict", "learning"),
        0.06,
    ),
)

_GENERAL_NODES = (
    _node(
        "role_delivery",
        "Role delivery",
        ("delivery", "project", "responsibility", "results", "impact"),
        ("prioritization", "quality", "outcomes", "tradeoffs", "execution"),
        0.55,
    ),
    _node(
        "behavioral",
        "Behavioral competencies",
        ("ownership", "leadership", "collaboration", "communication", "stakeholder"),
        ("ownership", "collaboration", "conflict", "learning", "adaptability"),
        0.45,
    ),
)


def role_competency_graph(role_family: RoleFamily) -> RoleCompetencyGraph:
    """Return a deterministic graph; unsupported families receive a transparent baseline."""
    nodes: tuple[CompetencyNode, ...]
    if role_family == "data_and_ai":
        nodes = _DATA_AND_AI_NODES
    elif role_family == "software_engineering":
        nodes = _SOFTWARE_NODES
    else:
        nodes = _GENERAL_NODES
    return RoleCompetencyGraph(
        graph_id=f"{role_family}_competencies",
        graph_version="v1",
        role_family=role_family,
        nodes=nodes,
    )


_PROBE_OVERRIDES: Mapping[tuple[str, str], tuple[str, ...]] = {
    ("rag", "chunking"): (
        "chunk boundaries and overlap",
        "chunk-size trade-offs",
        "document structure",
        "measured retrieval impact",
    ),
    ("rag", "vector_retrieval"): (
        "index choice",
        "top-k selection",
        "dense versus sparse retrieval",
        "corpus scale",
    ),
    ("rag", "retrieval_evaluation"): (
        "recall@k",
        "precision@k",
        "MRR",
        "ground-truth construction",
        "retrieval versus generation evaluation",
    ),
    ("rag", "failure_scaling"): (
        "observed failure",
        "100x scale",
        "bottleneck measurement",
        "fallback behavior",
    ),
    ("deployment_mlops", "observability"): (
        "service-level indicators",
        "model quality monitoring",
        "alert thresholds",
        "incident response",
    ),
    ("behavioral", "ownership"): (
        "personal decision",
        "measurable outcome",
        "trade-off",
        "lesson learned",
    ),
}

_INDUSTRY_COMPETENCIES: Mapping[str, tuple[tuple[str, str], ...]] = {
    "banking": (
        ("fraud_risk", "Fraud detection under highly imbalanced labels"),
        ("model_evaluation", "Risk-sensitive evaluation and explainability"),
        ("deployment_mlops", "Secure monitoring and production reliability"),
    ),
    "financial_services": (
        ("fraud_risk", "Fraud, explainability, security, and model risk"),
        ("deployment_mlops", "Regulated production monitoring and reliability"),
    ),
    "ecommerce": (
        ("recommendation_search", "Recommendation, ranking, search, and personalization"),
        ("model_evaluation", "Online experimentation for ranking quality"),
        ("data_engineering", "Large-scale feature pipelines"),
    ),
    "telecom": (
        ("customer_analytics", "Churn, time series, segmentation, and customer-scale data"),
        ("data_engineering", "Large customer-data pipelines"),
    ),
}


def _concept(node: CompetencyNode, subtopic: str, role_family: RoleFamily) -> QuestionConcept:
    label = subtopic.replace("_", " ")
    probes = _PROBE_OVERRIDES.get(
        (node.key, subtopic),
        ("decision context", "approach and trade-offs", "measurement", "failure handling"),
    )
    rounds: tuple[InterviewRound, ...] = (
        ("behavioral", "hiring_manager", "panel", "final", "other")
        if node.key == "behavioral"
        else _TECHNICAL_ROUNDS
    )
    return QuestionConcept(
        concept_id=f"{role_family}_{node.key}_{subtopic}",
        role_families=(role_family,),
        competency_key=node.key,
        subtopic=subtopic,
        seniorities=_ALL_SENIORITIES,
        interview_rounds=rounds,
        difficulty="medium",
        question_intent=(
            f"Assess whether the candidate can independently reason about {node.label}: {label}."
        ),
        possible_probes=probes,
    )


def question_concept_catalog(role_family: RoleFamily) -> tuple[QuestionConcept, ...]:
    """Build authored concept coordinates without copying proprietary question text."""
    graph = role_competency_graph(role_family)
    return tuple(
        _concept(node, subtopic, role_family) for node in graph.nodes for subtopic in node.subtopics
    )


def industry_evidence_catalog(
    industry: str | None,
    role_family: RoleFamily,
    retrieved_at: datetime,
) -> tuple[EvidenceSignal, ...]:
    """Return transparent, application-owned industry patterns for supported role contexts."""
    if industry is None or role_family != "data_and_ai":
        return ()
    key = re.sub(r"[^a-z0-9]+", "_", industry.casefold()).strip("_")
    patterns = _INDUSTRY_COMPETENCIES.get(key, ())
    if not patterns:
        return ()
    digest = sha256(b"industry-competency-taxonomy-v1").hexdigest()
    source = KnowledgeSource(
        source_id="industry_taxonomy_v1",
        source_type="industry_taxonomy",
        rights_status="permitted_derived",
        policy_version="internal_derived_v1",
        retrieved_at=retrieved_at,
        content_sha256=digest,
        source_trust=0.8,
        independent_group="internal_industry_taxonomy",
    )
    return tuple(
        EvidenceSignal(
            evidence_id=f"industry_{key}_{competency}",
            layer="industry_pattern",
            competency_key=competency,
            signal=signal,
            sources=(source,),
            confidence=0.8,
            industry=industry,
            role_family=role_family,
        )
        for competency, signal in patterns
    )


def role_evidence_catalog(
    role_family: RoleFamily,
    retrieved_at: datetime,
) -> tuple[EvidenceSignal, ...]:
    """Attach explicit internal-taxonomy provenance to every reusable role competency."""
    graph = role_competency_graph(role_family)
    digest = sha256(f"{graph.graph_id}:{graph.graph_version}".encode()).hexdigest()
    source = KnowledgeSource(
        source_id=f"{role_family}_taxonomy_v1",
        source_type="role_taxonomy",
        rights_status="permitted_derived",
        policy_version="internal_derived_v1",
        retrieved_at=retrieved_at,
        content_sha256=digest,
        source_trust=0.75,
        independent_group="internal_role_taxonomy",
    )
    return tuple(
        EvidenceSignal(
            evidence_id=f"role_{role_family}_{node.key}",
            layer="role_pattern",
            competency_key=node.key,
            signal=f"{node.label} is part of the {role_family} competency graph",
            sources=(source,),
            confidence=0.7,
            role_family=role_family,
        )
        for node in graph.nodes
    )


def find_nodes(
    graph: RoleCompetencyGraph,
    texts: Iterable[str],
) -> dict[str, tuple[CompetencyNode, tuple[str, ...]]]:
    """Match graph aliases as bounded phrases and retain the matched terms for audit."""
    normalized_text = " ".join(text.casefold().replace("-", " ") for text in texts)
    matches: dict[str, tuple[CompetencyNode, tuple[str, ...]]] = {}
    for node in graph.nodes:
        aliases = tuple(
            alias
            for alias in node.aliases
            if _contains_phrase(normalized_text, alias.casefold().replace("-", " "))
        )
        if aliases:
            matches[node.key] = (node, aliases)
    return matches


def _contains_phrase(text: str, phrase: str) -> bool:
    escaped = r"\s+".join(re.escape(part) for part in phrase.split())
    return re.search(rf"(?<!\w){escaped}(?!\w)", text) is not None
