"""ASGI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ai_interviewer import __version__
from ai_interviewer.api.errors import problem_response, request_id_from, validation_problem
from ai_interviewer.api.routes.document_intakes import router as document_intakes_router
from ai_interviewer.api.routes.documents import router as documents_router
from ai_interviewer.api.routes.health import router as health_router
from ai_interviewer.api.routes.identity import router as identity_router
from ai_interviewer.api.routes.preparations import router as preparations_router
from ai_interviewer.api.routes.privacy import router as privacy_router
from ai_interviewer.api.routes.profiles import router as profiles_router
from ai_interviewer.api.routes.source_texts import router as source_texts_router
from ai_interviewer.candidate_inputs import (
    CandidateDocumentIntakeRuntime,
    CandidateDocumentRuntime,
    CandidateExtractionJobRuntime,
    CandidateExtractionWorkerRuntime,
    CandidateInputRuntime,
    CandidateSourceTextRuntime,
    build_candidate_document_intakes,
    build_candidate_documents,
    build_candidate_extraction_jobs,
    build_candidate_extraction_worker,
    build_candidate_inputs,
    build_candidate_source_texts,
)
from ai_interviewer.candidate_inputs.asset_references import (
    CandidateFileAssetReferenceLifecycle,
)
from ai_interviewer.core.config import Settings, get_settings
from ai_interviewer.core.logging import configure_logging
from ai_interviewer.core.middleware import OperationalMiddleware
from ai_interviewer.core.operational_monitor import OperationalMonitor
from ai_interviewer.core.telemetry import TelemetryRuntime, build_telemetry
from ai_interviewer.file_security.lifecycle import (
    DisabledFileSecurity,
    FileSecurityService,
    build_file_security,
)
from ai_interviewer.identity.service import (
    AuthenticationRuntime,
    build_authentication,
)
from ai_interviewer.model_gateway import (
    ModelGatewayRuntime,
    ModelProvider,
    build_model_gateway,
)
from ai_interviewer.persistence.database import Database, DatabaseRuntime
from ai_interviewer.privacy.lifecycle import PrivacyRuntime, build_privacy_service
from ai_interviewer.privacy.policy import (
    JurisdictionPolicyRegistry,
    build_default_jurisdiction_registry,
)
from ai_interviewer.profiling import (
    CandidateProfileRuntime,
    CandidateProfilingJobRuntime,
    CandidateProfilingWorkerRuntime,
    build_candidate_profiles,
    build_candidate_profiling_jobs,
    build_candidate_profiling_worker,
)

logger = logging.getLogger("ai_interviewer.lifecycle")


def create_app(
    settings: Settings | None = None,
    database: DatabaseRuntime | None = None,
    authentication: AuthenticationRuntime | None = None,
    privacy: PrivacyRuntime | None = None,
    file_security: DisabledFileSecurity | FileSecurityService | None = None,
    candidate_inputs: CandidateInputRuntime | None = None,
    candidate_documents: CandidateDocumentRuntime | None = None,
    candidate_document_intakes: CandidateDocumentIntakeRuntime | None = None,
    candidate_extraction_jobs: CandidateExtractionJobRuntime | None = None,
    candidate_extraction_worker: CandidateExtractionWorkerRuntime | None = None,
    candidate_source_texts: CandidateSourceTextRuntime | None = None,
    candidate_profiles: CandidateProfileRuntime | None = None,
    candidate_profiling_jobs: CandidateProfilingJobRuntime | None = None,
    candidate_profiling_worker: CandidateProfilingWorkerRuntime | None = None,
    jurisdiction_registry: JurisdictionPolicyRegistry | None = None,
    telemetry: TelemetryRuntime | None = None,
    model_gateway: ModelGatewayRuntime | None = None,
    model_provider: ModelProvider | None = None,
) -> FastAPI:
    """Create an isolated application instance for runtime and tests."""
    resolved_settings = settings or get_settings()
    resolved_telemetry = telemetry or build_telemetry(resolved_settings)
    resolved_model_gateway = model_gateway or build_model_gateway(
        resolved_settings,
        model_provider,
    )
    resolved_database = database or Database(resolved_settings, resolved_telemetry)
    resolved_authentication = authentication or build_authentication(
        resolved_settings,
        resolved_database,
    )
    resolved_registry = jurisdiction_registry or build_default_jurisdiction_registry()
    resolved_candidate_inputs = candidate_inputs or build_candidate_inputs(
        resolved_settings,
        resolved_database,
    )
    resolved_candidate_documents = candidate_documents or build_candidate_documents(
        resolved_settings,
        resolved_database,
    )
    candidate_file_references = CandidateFileAssetReferenceLifecycle()
    resolved_file_security = file_security or build_file_security(
        resolved_settings,
        resolved_database,
        reference_lifecycle=candidate_file_references,
        telemetry=resolved_telemetry,
    )
    resolved_candidate_document_intakes = (
        candidate_document_intakes
        or build_candidate_document_intakes(
            resolved_settings,
            resolved_database,
            resolved_file_security,
            resolved_candidate_documents,
        )
    )
    resolved_candidate_extraction_jobs = (
        candidate_extraction_jobs
        or build_candidate_extraction_jobs(
            resolved_settings,
            resolved_database,
        )
    )
    resolved_candidate_source_texts = candidate_source_texts or build_candidate_source_texts(
        resolved_settings,
        resolved_database,
    )
    resolved_candidate_extraction_worker = (
        candidate_extraction_worker
        or build_candidate_extraction_worker(
            resolved_settings,
            resolved_candidate_extraction_jobs,
            resolved_file_security,
            resolved_candidate_source_texts,
        )
    )
    resolved_candidate_profiles = candidate_profiles or build_candidate_profiles(
        resolved_settings,
        resolved_database,
    )
    resolved_candidate_profiling_jobs = candidate_profiling_jobs or build_candidate_profiling_jobs(
        resolved_settings,
        resolved_database,
    )
    resolved_privacy = privacy or build_privacy_service(
        resolved_settings,
        resolved_database,
        resolved_registry,
        resolved_file_security,
        resolved_candidate_inputs,
        resolved_candidate_documents,
        resolved_candidate_document_intakes,
        candidate_source_text_lifecycle=resolved_candidate_source_texts,
        candidate_extraction_job_lifecycle=resolved_candidate_extraction_jobs,
        candidate_profile_lifecycle=resolved_candidate_profiles,
        candidate_profiling_job_lifecycle=resolved_candidate_profiling_jobs,
        telemetry=resolved_telemetry,
    )
    resolved_candidate_profiling_worker = (
        candidate_profiling_worker
        or build_candidate_profiling_worker(
            resolved_settings,
            resolved_candidate_profiling_jobs,
            resolved_candidate_source_texts,
            resolved_candidate_profiles,
            resolved_privacy,
            resolved_model_gateway,
        )
    )
    configure_logging(resolved_settings.log_level)
    operational_monitor = (
        OperationalMonitor(
            database=resolved_database,
            telemetry=resolved_telemetry,
            interval_seconds=resolved_settings.telemetry_monitor_interval_seconds,
        )
        if resolved_telemetry.enabled and isinstance(resolved_database, Database)
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        release_context = {
            "release_id": resolved_settings.release_id,
            "release_revision": resolved_settings.release_revision,
        }
        logger.info("Service started", extra=release_context)
        if operational_monitor is not None:
            operational_monitor.start()
        try:
            yield
        finally:
            if operational_monitor is not None:
                await operational_monitor.stop()
            await resolved_database.close()
            if resolved_telemetry.enabled:
                await asyncio.to_thread(resolved_telemetry.shutdown)
            logger.info("Service stopped", extra=release_context)

    app = FastAPI(
        title="AI Interviewer API",
        version=__version__,
        docs_url="/docs" if resolved_settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.authentication = resolved_authentication
    app.state.privacy = resolved_privacy
    app.state.file_security = resolved_file_security
    app.state.candidate_inputs = resolved_candidate_inputs
    app.state.candidate_documents = resolved_candidate_documents
    app.state.candidate_document_intakes = resolved_candidate_document_intakes
    app.state.candidate_extraction_jobs = resolved_candidate_extraction_jobs
    app.state.candidate_extraction_worker = resolved_candidate_extraction_worker
    app.state.candidate_source_texts = resolved_candidate_source_texts
    app.state.candidate_profiles = resolved_candidate_profiles
    app.state.candidate_profiling_jobs = resolved_candidate_profiling_jobs
    app.state.candidate_profiling_worker = resolved_candidate_profiling_worker
    app.state.jurisdiction_registry = resolved_registry
    app.state.telemetry = resolved_telemetry
    app.state.model_gateway = resolved_model_gateway

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(resolved_settings.allowed_hosts),
    )
    app.add_middleware(
        OperationalMiddleware,
        environment=resolved_settings.environment,
        telemetry=resolved_telemetry,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> object:
        detail = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return problem_response(
            status=exc.status_code,
            title="Request failed",
            detail=detail,
            request_id=request_id_from(request),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError) -> object:
        return validation_problem(request, exc)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(identity_router, prefix="/api/v1")
    app.include_router(privacy_router, prefix="/api/v1")
    app.include_router(preparations_router, prefix="/api/v1")
    app.include_router(document_intakes_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(source_texts_router, prefix="/api/v1")
    app.include_router(profiles_router, prefix="/api/v1")
    return app


app = create_app()
