# Validated Experiment Baseline

This baseline captures the four completed risk-validation experiments before production application assembly begins.

## Included Experiments

1. Windows foreground application monitoring.
2. Entry prompt behavior and window restoration.
3. Browser Native Messaging and Named Pipe round trip.
4. Deterministic foreground/browser context aggregation.

## Clean-Checkout Verification

From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Run the Windows process-integration test separately from an unrestricted local PowerShell session:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -IncludeWindowsIntegration
```

The integration switch starts temporary Native Hosts and single-instance Pipe servers and shuts them down before returning.

## Acceptance Record

Milestone 0 is ready for acceptance when:

- The verification script prints `Baseline verification passed.`
- The communication harness reports every check as passed.
- `git status --short --ignored` shows generated files only under documented ignore rules.
- No capture, log, database, virtual environment, cache, or build output is tracked.
- The commands documented for all four experiments match installed console entry points.

## Git Baseline After User Acceptance

The baseline commit and tag are intentionally created only after user acceptance. A suggested local sequence is:

```powershell
git add --all
git commit -m "Establish validated experiment baseline"
git tag experiments-v1
```

Review the staged diff before committing. Push the commit and tag only when the user chooses to publish them.
