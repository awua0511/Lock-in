# Milestone 7: Hardening, Distribution and UI

Implementation candidate; manual release acceptance is still required. No signing certificate is purchased, no browser-store submission is made, and no commit/push is performed.

## Build and run

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,build]"
.\.venv\Scripts\python scripts/build_release.py
```

The build creates a timestamped folder under `dist` containing a `LockIn` onedir bundle and a ZIP. Extract the whole folder; do not move the EXE files away from `_internal`. `lock-in.exe` starts without Python or a console window. The Native Host retains binary standard input/output. `lock-in-setup.exe` is a command-line deployment tool. Closing the main window hides it when the tray is available; use the tray's **Exit** action to stop it.

`build-info.json` records runtime/build versions. Wheel-supplied license notices are copied under `THIRD_PARTY_LICENSES`; this is not a completed public-redistribution license review. The build restricts DLL search paths and refuses dependencies outside Python/Windows to avoid bundling unrelated tools' DLLs.

## Per-user installation

Exit the existing tray instance first. From the extracted bundle:

```powershell
.\lock-in-setup.exe install
```

Launch `%LOCALAPPDATA%\Programs\LockIn\Start Lock-In.cmd`. The installed extension has a stable path at `%LOCALAPPDATA%\Programs\LockIn\extension`. Load that folder as an unpacked extension in each Chrome/Edge profile. Copy the ID shown by that installation (moving an unpacked extension can change its ID), exit Lock-In from the tray, then run setup again:

```powershell
.\lock-in-setup.exe install --chrome-extension-id YOUR_32_CHARACTER_ID
# Add --edge-extension-id YOUR_EDGE_ID when required. Repeat options for multiple IDs.
```

Each install validates file hashes before activation, stages a new version without overwriting the active runtime, and journals changed manifests, registrations, launcher, extension files and installation state. An interrupted activation is rolled back on the next setup operation. Setup refuses to change the installation while the normal tray instance owns its mutex. User settings and history remain in `%LOCALAPPDATA%\LockIn`, outside the install root.

Restart the installed application after registration and reload the extension. Do not leave both the old source-path extension and the installed copy enabled in the same profile. Installing without browser-ID options does not register new browsers; later installs preserve configured IDs. The packaged app shares the existing production user profile: it is **not** a data-isolated portable mode.

To upgrade, exit the tray and run `install` from the new extracted bundle. Browser IDs are preserved unless explicitly replaced; reload the extension after an update. The previous runtime remains available:

```powershell
.\lock-in-setup.exe rollback
.\lock-in-setup.exe uninstall
```

Run uninstall from the extracted download, not the installed runtime. It removes only owned runtime directories and browser registrations, restores pre-existing registrations when appropriate, and **always keeps user data**. The browser extension itself must be removed from Chrome/Edge manually. Rollback is refused across different schema versions; it never overwrites a newer database with an old backup. Unknown or corrupted installation state is not silently deleted.

No administrator privileges, auto-start task, service, or firewall changes are requested. This is an unsigned per-user test distribution, not a signed MSI or Store release. Hashes detect damaged payloads; they do not authenticate the publisher.

## UI acceptance

- Sidebar navigation, work-period overview, separate app/site allowlists, review metric cards and shared reminder styling.
- Feedback and service-failure messages stay visible on every page, including failed configuration/database startup.
- Forms remain keyboard accessible and scroll on small/high-DPI displays. Focus outlines and disabled states remain visible.
- Destructive retention reductions require confirmation. Website prompts still have only Continue; X/Escape remain Continue. No scores, penalties or forced blocking are added.

Verify every navigation page, create/delete a schedule, capture and add an application, add/remove a website, save settings, view multiple review dates and confirm real prompt decisions. Check long names, keyboard-only navigation, narrow windows and mixed-DPI monitors.

## Automated and release acceptance

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -IncludeWindowsIntegration
.\.venv\Scripts\python scripts/verify_release.py `
    dist/CANDIDATE_FOLDER/LockIn --output build/NEW_CHECK_FOLDER --seconds 15
.\.venv\Scripts\python scripts/preview_ui.py
.\.venv\Scripts\python scripts/preview_ui.py --scale 1.5 --output build/ui-preview-150
.\.venv\Scripts\python scripts/preview_ui.py --scale 2 --output build/ui-preview-200
```

Replace both placeholder folders; the release-check output directory must not already exist. The packaged check uses disposable data and unique Pipe/mutex namespaces. Exit the normal tray app first so setup can acquire the normal installation guard. Installer unit tests use a fake registry; one adapter test writes and removes only a unique test key. The packaged setup test supplies no browser IDs and verifies that real Chrome/Edge registrations remain unchanged. It stages the same candidate twice to exercise upgrade mechanics; compatibility between two different public releases is not claimed.

Packaged checks cover startup/shutdown, one instance, simultaneous Chrome/Edge-style clients and profiles, duplicate/out-of-order messages, Host crash, reconnect, concurrent Host auto-start, corrupt-database preservation, and setup install/staging/rollback/uninstall. Source tests additionally cover timeouts, migration rollback, corrupted settings, damaged bundles, interrupted activation, registration failure and schema rollback refusal. Packaged browser clients are protocol clients, **not real browser UI sessions**. See `docs/RELEASE_VALIDATION.md` in the repository for results and untested release gates.

Performance checks sample startup-to-ready, GUI CPU/working set, event-queue latency and Native Messaging round trips. They are local smoke measurements, not UI-presentation latency, a long-running soak test or a clean-machine guarantee. Offscreen UI renders at three scale factors do not substitute for mixed-monitor hardware tests.

## Your manual acceptance checklist

1. Exit the old tray process; launch the new `lock-in.exe`. Confirm all six sidebar pages open, keyboard arrows navigate, and a narrow window scrolls without hiding controls permanently.
2. Create a short work period spanning now. Add a work app by switching to it, and add `github.com` as a website. Restart Lock-In and confirm all saved settings remain.
3. Enter another app: Continue, X and Escape must each dismiss the prompt without an immediate repeat. Leave and re-enter to get a new entry prompt. Application Return remains best-effort under Windows restrictions.
4. With the Host and extension connected, switch between allowed/unlisted sites. Website prompts must have **only Continue anyway**. Check Continue/X/Escape and follow-up timing in Chrome, Edge and another profile. Unknown/disconnected context must not generate a guessed website prompt.
5. View Reviews for today and another date. Confirm counts, details and empty dates agree with your actions. Test the scheduled Windows notification separately; OS settings can suppress its banner.
6. Reduce history retention in Settings and choose **No**: nothing should be saved or deleted. Test component failure only with disposable data, never by damaging the real database.
7. Optionally perform the installation lifecycle above. Check that uninstall leaves `%LOCALAPPDATA%\LockIn` untouched. Do not delete that directory to reset testing.

Record pass/fail before marking M7 accepted and pushing. These steps deliberately repeat the previous prompt-loop and website-Return regressions after the visual changes.

Before broad distribution, explicitly record Windows 10 and Windows 11, 100/150/200% DPI and mixed monitors, fullscreen/elevated apps, real Chrome/Edge profiles, lock/sleep/resume, Windows notifications and antivirus results. Unavailable machines and services must remain **not tested**, not marked passed.

## Signing and stores

No paid services are required for local use. An unsigned download may trigger Windows reputation warnings. Signing identifies a publisher but does not guarantee immediate SmartScreen reputation; never instruct users to disable Windows protection. Evaluate [Microsoft's signing and reputation guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation) before public distribution. Chrome/Edge store publication requires developer-account choices, privacy disclosures, extension review and production IDs; those external actions need a separate release decision. Project licensing and complete third-party redistribution notices/source obligations must also be reviewed before distributing beyond personal acceptance testing.
