# M7 Release Validation

## Compatibility hotfix 0.1.1

The original 0.1.0 candidate below is superseded for affected legacy profiles by `dist/candidate-20260928-183744/LockIn-0.1.1-windows-x64.zip` (SHA-256 `21d3c5b305c4a5aabe2c0655fae6e1c5eb74e0474018b6ef8f687c8f6ecb1d96`). See [the compatibility repair](FIX_0.1.1.md). Source validation now passes 175 Python tests, 3 JavaScript tests and 6 communication scenarios. The earlier artifact and measurements below remain a historical M7 record.

Status: local implementation candidate; **not approved for public distribution**. Final user acceptance is separate from the checks below. No commit, push, signing purchase or store submission has been made.

## Reproducible checks

From the repository root, follow [M7 build and verification commands](../MILESTONE_07.md). Use a fresh output directory for each packaged run. The harness launches only test-owned processes, redirects data into the output directory, and uses unique IPC namespaces. Its setup lifecycle supplies no extension IDs and checks that existing browser registrations remain unchanged. A separate real-registry unit test uses only a disposable test key.

## Automated results

- Source quality gate: formatting, lint, compilation, Markdown links and generated-artifact checks.
- Python suite: **172 passed** (final gate, 2026-09-28).
- Browser JavaScript: 3 race-regression tests.
- Windows communication harness: 6 scenarios, including timeout/late response and simultaneous Host startup.
- Packaged harness: 10 checks, including real setup install/staging/rollback/uninstall and user-data preservation.
- Visual QA: all six sidebar pages and website prompt at 100%, 150%, 200% offscreen scale; narrow-window layout and keyboard navigation.

## Acceptance artifact

- Bundle: `dist/candidate-20260928-110631/LockIn`.
- ZIP: `dist/candidate-20260928-110631/LockIn-0.1.0-windows-x64.zip`.
- ZIP length: 54,327,613 bytes (approximately 51.81 MiB).
- ZIP SHA-256: `b991b5bebd08c6f2c46d7c0d2f8913f9f55304219e7d54afbe3d81ab41e44768`.
- Version/runtime provenance is included in the bundle's `build-info.json`.
- Build outputs and test profiles are ignored, not staged for Git.

## Measurements

Final candidate run, `build/release-check-final/results.json` (2026-09-28), on Windows 11 x64 build 22621, Python 3.14.3, PySide6 6.11.2, PyInstaller 6.22.3. All ten packaged checks and all four performance smoke budgets passed:

| Measurement | Observed | Smoke budget |
| --- | ---: | ---: |
| Process launch to application-ready log | 569.93 ms | < 5,000 ms |
| GUI peak working set during 15-second sample | 62.31 MiB | < 250 MiB |
| GUI idle CPU, one-core equivalent | 0.000% | < 2% |
| Event queue latency, p95 | 0.105 ms | < 250 ms |
| Native Messaging heartbeat round trip, p95 of 30 | 0.229 ms | Informational |

Zero reported CPU means below the accounting resolution of this short sample, not literally no work. Working set excludes Host processes and OS overhead. Application-ready is a log milestone, not first visible paint. Queue/heartbeat measurements are not end-to-end prompt presentation latency. This is not a long-running soak or clean-machine benchmark.

## Issues caught during packaging

The initial PyInstaller candidate accidentally collected a different ICU library from an unrelated tool on the build machine's PATH. The resulting Qt import failed despite source tests passing. The build now isolates DLL search paths and checks binary provenance; only fresh rebuilt candidates should be used. Earlier failed and diagnostic candidates under ignored `dist` are not release artifacts.

The simultaneous-start test originally counted a rejected second process during frozen-runtime teardown. It now waits for a stable single process and separately requires exactly one successful application-start record. Restart verification waits for a new start record instead of reusing a previous run's log.

## Remaining manual / public-release gates

| Gate | Actual status |
| --- | --- |
| User M7 UI and reminder acceptance | Pending; use the [manual checklist](../MILESTONE_07.md). |
| Real packaged Chrome/Edge multi-profile UI | Pending; protocol clients are not browser acceptance. |
| Windows 10 / separate clean Windows machine | Not tested. |
| Physical mixed DPI / monitors / fullscreen / elevated apps | Not tested in this release run. |
| Physical lock/sleep/resume and visible Windows notification | Not tested in this release run; deterministic logic tests pass. |
| Long-running workload and crash/power-loss soak | Not performed; recovery is tested by deterministic failure injection. |
| Cross-user IPC isolation | Explicit Pipe ACL and peer user/session checks remain architecture requirements, not completed by the current SID-derived Pipe name and standard-library listener. Requires implementation/security validation before broader distribution. |
| Signing, SmartScreen and antivirus on downloaded artifacts | Unsigned; reputation/AV release certification not performed. |
| Project and complete third-party redistribution licensing | Pending; supplied wheel notices alone are not a completed review. |
| Browser stores and automatic updates | Not implemented/published; require a separate release decision. |

Chinese documentation remains archived and unchanged. The English implementation and acceptance documents are authoritative.
