$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

$originalDatabaseUrl = $env:AI_INTERVIEWER_DATABASE_URL
$originalTestDatabaseUrl = $env:AI_INTERVIEWER_TEST_DATABASE_URL
$startedPostgres = $false
$temporaryDatabase = $null

try {
    if (-not $env:AI_INTERVIEWER_TEST_DATABASE_URL) {
        $runningServices = docker compose ps --status running --services
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect the local PostgreSQL service"
        }
        if ($runningServices -notcontains "postgres") {
            Invoke-Checked -Description "PostgreSQL startup" -Command {
                docker compose up --detach --wait --wait-timeout 60 postgres
            }
            $startedPostgres = $true
        }

        $temporaryDatabase = "ai_interviewer_test_$($PID)_$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"
        Invoke-Checked -Description "Temporary test database creation" -Command {
            docker compose exec -T postgres createdb --username ai_interviewer $temporaryDatabase
        }
        $localTestUrl = "postgresql+psycopg://ai_interviewer:local-only@127.0.0.1:55432/$temporaryDatabase"
        $env:AI_INTERVIEWER_DATABASE_URL = $localTestUrl
        $env:AI_INTERVIEWER_TEST_DATABASE_URL = $localTestUrl
    }
    elseif (-not $env:AI_INTERVIEWER_DATABASE_URL) {
        $env:AI_INTERVIEWER_DATABASE_URL = $env:AI_INTERVIEWER_TEST_DATABASE_URL
    }

    Invoke-Checked -Description "Dependency lock check" -Command { uv lock --check }
    Invoke-Checked -Description "Lint" -Command { uv run ruff check . }
    Invoke-Checked -Description "Format check" -Command { uv run ruff format --check . }
    Invoke-Checked -Description "Static type check" -Command { uv run mypy }
    Invoke-Checked -Description "Migration" -Command { uv run alembic upgrade head }
    Invoke-Checked -Description "Tests" -Command { uv run pytest }
    Invoke-Checked -Description "Dependency compatibility check" -Command { uv pip check }
    Invoke-Checked -Description "Dependency vulnerability audit" -Command {
        $sitePackages = uv run python -c "import site; print(site.getsitepackages()[0])"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not locate the virtual environment site-packages directory"
        }
        $originalUvLinkMode = $env:UV_LINK_MODE
        try {
            # OneDrive-backed Windows workspaces can reject uv cache hardlinks.
            # Copy mode changes only tool installation mechanics, not the audited environment.
            $env:UV_LINK_MODE = "copy"
            uvx pip-audit==2.10.1 --path $sitePackages.Trim() --progress-spinner off
        }
        finally {
            if ($null -eq $originalUvLinkMode) {
                Remove-Item Env:UV_LINK_MODE -ErrorAction SilentlyContinue
            }
            else {
                $env:UV_LINK_MODE = $originalUvLinkMode
            }
        }
    }
}
finally {
    if ($temporaryDatabase) {
        docker compose exec -T postgres dropdb --force --if-exists --username ai_interviewer $temporaryDatabase | Out-Null
    }
    if ($null -eq $originalDatabaseUrl) {
        Remove-Item Env:AI_INTERVIEWER_DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:AI_INTERVIEWER_DATABASE_URL = $originalDatabaseUrl
    }
    if ($null -eq $originalTestDatabaseUrl) {
        Remove-Item Env:AI_INTERVIEWER_TEST_DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:AI_INTERVIEWER_TEST_DATABASE_URL = $originalTestDatabaseUrl
    }
    if ($startedPostgres) {
        docker compose stop --timeout 10 postgres | Out-Null
    }
}
