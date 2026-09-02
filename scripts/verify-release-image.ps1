param(
    [string]$Image = "ai-interviewer-platform:local",
    [string]$ExpectedVersion = "0.1.0",
    [string]$ExpectedRevision = "unknown"
)

$ErrorActionPreference = "Stop"
$expectedSchemaRevision = "20260902_0014"
$expectedProfilePromptContractSha256 = "c62321d636cba9cf8ffd8115b6318bd05c8b8c67d58bdaef3c78bfdac924e9d2"

$rawInspection = docker image inspect $Image
if ($LASTEXITCODE -ne 0) {
    throw "Release image inspection failed"
}
$inspection = $rawInspection | ConvertFrom-Json
if ($inspection.Count -ne 1) {
    throw "Release image inspection returned an unexpected result"
}

$imageConfig = $inspection[0].Config
if ($imageConfig.User -ne "10001:10001") {
    throw "Release image must run as numeric identity 10001:10001"
}
if ($imageConfig.Labels."org.opencontainers.image.title" -ne "AI Interviewer Platform API") {
    throw "Release image title label is missing or invalid"
}
if ($imageConfig.Labels."org.opencontainers.image.version" -ne $ExpectedVersion) {
    throw "Release image version label does not match the expected version"
}
if ($imageConfig.Labels."org.opencontainers.image.revision" -ne $ExpectedRevision) {
    throw "Release image revision label does not match the expected source revision"
}
$createdAt = [DateTimeOffset]::MinValue
if (-not [DateTimeOffset]::TryParse(
    $imageConfig.Labels."org.opencontainers.image.created",
    [ref]$createdAt
)) {
    throw "Release image created label is not a timestamp"
}

$artifactOutput = docker run --rm --read-only --cap-drop ALL `
    --security-opt no-new-privileges:true `
    --entrypoint ai-interviewer-migrate `
    $Image check-artifact
if ($LASTEXITCODE -ne 0) {
    throw "Release image migration artifact verification failed"
}
$artifact = $artifactOutput | ConvertFrom-Json
if (
    $artifact.event -ne "migration_artifact_verified" -or
    $artifact.schema_revision -ne $expectedSchemaRevision
) {
    throw "Release image contains an unexpected migration artifact"
}

$baselineSchemaOutput = docker run --rm --read-only --cap-drop ALL `
    --security-opt no-new-privileges:true `
    --entrypoint ai-interviewer-baseline `
    $Image schema
if ($LASTEXITCODE -ne 0) {
    throw "Release image baseline evidence schema verification failed"
}
$baselineSchema = $baselineSchemaOutput | ConvertFrom-Json
if (
    $baselineSchema.title -ne "BaselineEvidence" -or
    $baselineSchema.additionalProperties -ne $false
) {
    throw "Release image contains an unexpected baseline evidence contract"
}

$profileEvidenceSchemaOutput = docker run --rm --read-only --cap-drop ALL `
    --security-opt no-new-privileges:true `
    --entrypoint ai-interviewer-profile-quality `
    $Image schema evidence
if ($LASTEXITCODE -ne 0) {
    throw "Release image profile quality evidence schema verification failed"
}
$profileEvidenceSchema = $profileEvidenceSchemaOutput | ConvertFrom-Json
if (
    $profileEvidenceSchema.title -ne "ProfileQualityEvidence" -or
    $profileEvidenceSchema.additionalProperties -ne $false
) {
    throw "Release image contains an unexpected profile quality evidence contract"
}

$profileApprovalSchemaOutput = docker run --rm --read-only --cap-drop ALL `
    --security-opt no-new-privileges:true `
    --entrypoint ai-interviewer-profile-quality `
    $Image schema approval
if ($LASTEXITCODE -ne 0) {
    throw "Release image profile quality approval schema verification failed"
}
$profileApprovalSchema = $profileApprovalSchemaOutput | ConvertFrom-Json
if (
    $profileApprovalSchema.title -ne "ProfileQualityApproval" -or
    $profileApprovalSchema.additionalProperties -ne $false
) {
    throw "Release image contains an unexpected profile quality approval contract"
}

$profilePromptContractSha256 = docker run --rm --read-only --cap-drop ALL `
    --security-opt no-new-privileges:true `
    --entrypoint ai-interviewer-profile-quality `
    $Image prompt-digest
if (
    $LASTEXITCODE -ne 0 -or
    $profilePromptContractSha256 -ne $expectedProfilePromptContractSha256
) {
    throw "Release image contains an unexpected profile prompt contract"
}

[ordered]@{
    image = $Image
    release_version = $ExpectedVersion
    release_revision = $ExpectedRevision
    schema_revision = $expectedSchemaRevision
    baseline_schema = $baselineSchema.title
    profile_quality_evidence_schema = $profileEvidenceSchema.title
    profile_quality_approval_schema = $profileApprovalSchema.title
    profile_prompt_contract_sha256 = $profilePromptContractSha256
    runtime_user = $imageConfig.User
} | ConvertTo-Json -Compress
