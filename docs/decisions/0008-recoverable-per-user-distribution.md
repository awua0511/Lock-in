# ADR 0008: Recoverable per-user bundles and presentation-only UI changes

Status: Implemented; pending Milestone 7 user acceptance.

## Context

Personal deployment needs to run without Python, keep Native Messaging registration stable, and survive incomplete upgrades without discarding a working runtime or the user's settings. UI refinement must not reintroduce prompt loops or move policy decisions onto the Qt thread.

## Decision

Build three PyInstaller executables with one shared onedir runtime. Keep desktop console-free and preserve Host binary stdio. Sanitize dependency search paths and reject unexpected DLL provenance. Record dependency versions and SHA-256 payload hashes; these detect accidental damage, not a maliciously replaced unsigned bundle.

Install under the current user's Programs directory with an owner marker, unique version directories, a stable launcher and unpacked-extension directory. Use both registry views for explicit browser extension origins. Journal previous files/registrations before activation and recover interrupted activation before the next operation. Serialize setup against the normal desktop instance. Refuse links/path escapes, unowned roots and cross-schema rollback. Uninstall removes owned runtime state while always preserving the separate user-data profile and newer unrelated registrations.

Keep application behavior in existing services. Use one theme and independently scrollable sidebar pages, with global feedback, objective review cards and confirmation before retention reductions. Website prompts retain Continue only; closing remains the same explicit decision path.

## Verification and consequences

Unit tests exercise damaged payloads, interrupted activation, registration failure, downgrade refusal and data preservation. A packaged harness uses isolated profiles to exercise real executables, IPC, concurrent startup and setup lifecycle. Performance measurements are opt-in, bounded and local. Offscreen previews support visual regression checks but cannot certify real displays or Windows foreground rules.

The candidate remains unsigned and locally tested. No automatic updater, admin permission, account, service or startup task is introduced. Old staged runtimes remain until uninstall, trading disk space for recovery. Broad distribution requires separate platform/security compatibility, project/third-party license review, signing/reputation and browser-publication decisions; user acceptance is recorded separately from automated passes.
