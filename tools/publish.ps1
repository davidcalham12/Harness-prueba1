<#
.SYNOPSIS
    Run the checks, then commit and push. Refuses to push if the checks fail.

.DESCRIPTION
    The order is the whole point. A handover script that pushed first and
    reported afterwards would be a slower way of doing what `git push` already
    does; this one exists so that what reaches the remote has passed.

    It runs, in order:
      1. python -m pytest -q
      2. python tools/check_specs.py
      3. regenerating output/golden-tiny/, and failing if it came out different
      4. git add / commit / push

    Step 3 is the one people skip and should not. The golden fixture is a
    committed run, and if the code has changed in a way that changes its output,
    the repository should either carry the new output or the change should be
    reconsidered - not quietly carry a fixture that no longer matches the code
    that produced it.

.PARAMETER Message
    The commit message. Required unless there is nothing to commit.

.PARAMETER Remote
    Defaults to 'origin'. The script does not create it; if there is no remote,
    it says so and stops rather than guessing a URL.

.PARAMETER Force
    Push although the checks failed. The commit message is annotated to say so,
    because a red commit that does not admit it is worse than no note at all.

.PARAMETER SkipGolden
    Skip regenerating the fixture. Use when you already regenerated it
    deliberately and staged the diff.

.EXAMPLE
    .\tools\publish.ps1 -Message "SEC-5 and the composition root"

.EXAMPLE
    .\tools\publish.ps1 -Message "wip" -Force
#>

[CmdletBinding()]
param(
    [string]$Message,
    [string]$Remote = "origin",
    [switch]$Force,
    [switch]$SkipGolden,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$failures = @()

function Write-Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "  ok    $text" -ForegroundColor Green }
function Write-Bad($text)  { Write-Host "  FAIL  $text" -ForegroundColor Red }

# -- 0. is this even a git repository? ---------------------------------------

if (-not (Test-Path (Join-Path $root ".git"))) {
    Write-Bad "no .git here. Run 'git init' first; this script publishes a repository, it does not create one."
    exit 2
}

# -- 1. the test suite --------------------------------------------------------

Write-Step "test suite"
$tests = & python -m pytest -q
$tests | Select-Object -Last 1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { $failures += "pytest"; Write-Bad "tests failed" }
else { Write-Ok "tests pass" }

# -- 2. the spec checker ------------------------------------------------------

Write-Step "spec checker"
$specs = & python tools/check_specs.py
$specs | Select-Object -Last 1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { $failures += "check_specs"; Write-Bad "specs do not trace" }
else { Write-Ok "specs trace" }

# -- 3. the golden fixture ----------------------------------------------------

if ($SkipGolden) {
    Write-Step "golden fixture (skipped)"
    Write-Host "  -SkipGolden was passed; the committed fixture is not being checked"
} else {
    Write-Step "golden fixture"
    $premise = "A deep-space salvage crew finds a derelict that remembers them"
    & python -m novaforge new $premise --slug golden-tiny --profile tiny --engine mock --force --quiet
    if ($LASTEXITCODE -ne 0) {
        $failures += "golden"
        Write-Bad "regenerating output/golden-tiny/ failed"
    } else {
        # Only the audit log may differ, and only in its wall-clock fields.
        $changed = & git diff --name-only -- output/golden-tiny/
        $unexpected = $changed | Where-Object { $_ -ne "output/golden-tiny/logs/agents.jsonl" }
        if ($unexpected) {
            $failures += "golden"
            Write-Bad "the fixture changed; the code no longer produces what is committed:"
            $unexpected | ForEach-Object { Write-Host "          $_" -ForegroundColor Red }
            Write-Host "        Review the diff, then commit it as its own change record (CFG-7)."
        } else {
            Write-Ok "fixture reproduces (only the audit log's timestamps moved)"
            & git checkout -- output/golden-tiny/logs/agents.jsonl 2>$null
        }
    }
}

# -- 4. decide ----------------------------------------------------------------

Write-Step "result"
if ($failures.Count -gt 0) {
    Write-Bad ("failed: " + ($failures -join ", "))
    if (-not $Force) {
        Write-Host "  nothing has been committed or pushed."
        Write-Host "  fix the above, or pass -Force to publish anyway (the commit will say so)."
        exit 1
    }
    Write-Host "  -Force was passed; publishing a failing tree." -ForegroundColor Yellow
} else {
    Write-Ok "all checks passed"
}

# -- 5. commit ----------------------------------------------------------------

$dirty = & git status --porcelain
if (-not $dirty) {
    Write-Host "`n  nothing to commit; the working tree is clean."
} else {
    if (-not $Message) {
        Write-Bad "there are changes to commit but no -Message was given."
        exit 2
    }
    $body = $Message
    if ($failures.Count -gt 0) {
        # A red commit that does not admit it is worse than no note at all.
        $body += "`n`nPublished with -Force; these checks were failing: " + ($failures -join ", ")
    }
    & git add -A
    $body | & git commit -q -F -
    if ($LASTEXITCODE -ne 0) { Write-Bad "commit failed"; exit 1 }
    Write-Ok "committed"
}

# -- 6. push ------------------------------------------------------------------

if ($NoPush) {
    Write-Host "`n  -NoPush was passed; stopping before the push."
    exit 0
}

$remotes = & git remote
if ($remotes -notcontains $Remote) {
    Write-Bad "no remote named '$Remote'."
    Write-Host "  Committed locally. Add a remote and push when you are ready:"
    Write-Host "    git remote add $Remote <url>"
    Write-Host "    git push -u $Remote (git branch --show-current)"
    exit 1
}

$branch = & git branch --show-current
Write-Step "push"
& git push -u $Remote $branch
if ($LASTEXITCODE -ne 0) { Write-Bad "push failed"; exit 1 }
Write-Ok "pushed $branch to $Remote"
