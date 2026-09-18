[CmdletBinding()]
param(
    [switch]$IncludeWindowsIntegration
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entryPointDirectory = Join-Path $projectRoot ".venv\Scripts"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run: py -m venv .venv"
}

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Push-Location $projectRoot
try {
    & $python -m ruff format --check src tests
    Assert-LastExitCode "Ruff format check"

    & $python -m ruff check src tests
    Assert-LastExitCode "Ruff lint check"

    & $python -m compileall -q src tests
    Assert-LastExitCode "Python compile check"

    & $python -m pytest
    Assert-LastExitCode "Pytest"

    & git diff --check
    Assert-LastExitCode "Git whitespace check"

    $deletedTrackedFiles = @{}
    & git ls-files --deleted | ForEach-Object { $deletedTrackedFiles[$_] = $true }
    $trackedArtifacts = & git ls-files | Where-Object {
        -not $deletedTrackedFiles.ContainsKey($_) -and (
            $_ -match "(^|/)(\.venv|build|dist|htmlcov|\.ruff_cache|\.pytest_cache)(/|$)" -or
            $_ -match "(capture\.jsonl$|\.log$|\.db(-shm|-wal)?$|\.py[co]$)"
        )
    }
    if ($trackedArtifacts) {
        throw "Generated artifacts are tracked by Git: $($trackedArtifacts -join ', ')"
    }

    $missingLinks = @()
    Get-ChildItem -LiteralPath $projectRoot -Recurse -Filter "*.md" |
        Where-Object { $_.FullName -notlike "$projectRoot\.venv\*" } |
        ForEach-Object {
            $markdownFile = $_
            $content = Get-Content -Raw -LiteralPath $markdownFile.FullName
            [regex]::Matches($content, "\]\(([^)]+)\)") | ForEach-Object {
                $target = $_.Groups[1].Value
                if ($target -notmatch "^(https?://|mailto:|#)") {
                    $pathPart = ($target -split "#")[0]
                    if ($pathPart -and -not (Test-Path -LiteralPath (Join-Path $markdownFile.DirectoryName $pathPart))) {
                        $missingLinks += "$($markdownFile.FullName) -> $target"
                    }
                }
            }
        }
    if ($missingLinks) {
        throw "Broken local Markdown links: $($missingLinks -join '; ')"
    }

    $expectedEntryPoints = @(
        "lock-in-foreground-monitor.exe",
        "lock-in-entry-prompt.exe",
        "lock-in-native-host.exe",
        "lock-in-communication-tray.exe",
        "lock-in-communication-harness.exe",
        "lock-in-context-replay.exe",
        "lock-in-register-native-host.exe"
    )
    foreach ($entryPoint in $expectedEntryPoints) {
        $entryPointPath = Join-Path $entryPointDirectory $entryPoint
        if (-not (Test-Path -LiteralPath $entryPointPath)) {
            throw "Missing installed entry point: $entryPoint"
        }
    }

    Get-ChildItem -LiteralPath "browser_extension\experiment3" -Filter "*.json" |
        ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json | Out-Null }
    Get-ChildItem -LiteralPath "scenarios" -Filter "*.json" |
        ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json | Out-Null }

    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($null -eq $node) {
        throw "Node.js is required for browser-extension syntax checks."
    }
    & $node.Source --check "browser_extension\experiment3\service-worker.js"
    Assert-LastExitCode "Service worker JavaScript syntax check"
    & $node.Source --check "browser_extension\experiment3\popup.js"
    Assert-LastExitCode "Popup JavaScript syntax check"

    if ($IncludeWindowsIntegration) {
        & (Join-Path $entryPointDirectory "lock-in-communication-harness.exe")
        Assert-LastExitCode "Windows communication harness"
    }

    Write-Host "Baseline verification passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
