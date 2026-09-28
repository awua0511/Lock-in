# Milestone 5: Production Browser Integration

Milestone 5 connects Chrome and Edge browser context to Lock-In's existing focus and website-allowlist flow. It does not add reviews, scheduled notifications, or packaging.

## Delivered Scope

- Production MV3 extension, Native Messaging relay, per-user Named Pipe server, and browser registration commands are separate from Experiment 3.
- The tray process requests a fresh browser snapshot for every foreground epoch. A snapshot must echo both its request ID and epoch before it can be used.
- Changed unsolicited snapshots trigger revalidation; they cannot directly replace the currently bound domain. Extension sampling generations discard older asynchronous reads.
- Browser/Windows correlation is serialized through the application event queue and `ContextAggregator`.
- Browser profile connections are visible in the Overview health line. Disconnecting the currently bound profile invalidates its context.
- Website rules compare normalized hostnames, with an explicit option to include subdomains.
- Website prompts provide only **Continue anyway**. They do not offer a Return action because Lock-In cannot reliably restore the previously active browser tab/window from a website prompt.
- Unknown, malformed, stale, late, duplicate, or ambiguous website context fails open and does not trigger a website prompt.
- If a transient browser update makes the active context unknown, the next proactive event requests a fresh correlated snapshot; it does not reuse the old domain or remain stuck unknown indefinitely.

## Automated Acceptance

Run the repository gate after installing the development dependencies:

```powershell
.\scripts\verify.ps1
```

The gate checks formatting, lint, Python compilation, unit/replay tests, docs links, production/experiment manifest JSON, and both JavaScript service-worker syntax checks. The Windows Named Pipe harness remains available with `-IncludeWindowsIntegration`.

## Manual Acceptance

These checks require a Windows 10/11 machine, unpacked Chrome and Edge extensions, and a development installation of Lock-In. Chrome and Edge extension IDs must be registered separately; use the IDs shown by each browser's extension management page.

### 1. Install and connect both browsers

1. Load `browser_extension/production` as an unpacked extension in Chrome and Edge. Copy each displayed extension ID.
2. From the project virtual environment run `lock-in-register-production-native-host --chrome-extension-id <CHROME_ID> --edge-extension-id <EDGE_ID>` (repeat each option for every profile's extension ID, if IDs differ).
3. Start Lock-In, then open one regular browser window in each browser. Overview should show one connected profile for Chrome and one for Edge.
4. Repeat in a second browser profile. The profile count should increase, and closing one profile must decrement it without dropping the others.

### 2. Verify safe website decisions

1. Add `github.com` to the website allowlist with subdomains disabled. During an active schedule, visit `https://github.com/`; no website prompt should appear.
2. Visit `https://www.github.com/`; it should be treated as a different hostname and prompt if not separately allowlisted.
3. Enable subdomains for `github.com`; `www.github.com` should now be allowed, while `github.com.evil.test` must still prompt.
4. Switch rapidly between browser windows, tabs, and a non-browser application. A stale tab/domain must never be assigned to the new foreground window. Internal browser pages and unresolved pages must not cause a website prompt.

### 3. Verify recovery and failure behavior

1. With a browser foregrounded, restart Lock-In. The extension/Host should reconnect and the next foreground activation should request a fresh snapshot rather than reuse the old domain.
2. Reload the extension and confirm the profile reconnects without duplicate prompts.
3. Close a browser profile and confirm only that profile disconnects. Open it again and confirm it reconnects.
4. Stop the tray process while a browser remains open, then activate a browser tab. The Host should start the tray process; the first decision must wait for a correlated fresh snapshot.
5. Terminate a Host process, or temporarily disable/unregister one extension. The remaining app stays usable; health status reflects the missing profile and unknown site context does not trigger an allowlist decision.
6. Choose **Exit** from the tray while Chrome remains open. Lock-In must stay closed while the extension reports disconnected; manually launching Lock-In again must restore normal Host auto-start behavior.

### 4. Verify prompt decisions

1. Open a normal allowed application, then switch to Chrome during an active schedule and visit an unallowed site.
2. Confirm the website prompt shows **Continue anyway** and has no **Return to previous window** button.
3. Choose **Continue anyway**. The prompt should close after the decision is processed and should not immediately return for that same website context.
4. Open a different unallowed domain; it should produce a new prompt. Returning to the previously continued domain later should prompt again after genuinely leaving that website context.

## Acceptance Boundary

Accept Milestone 5 only after the automated gate and the manual checks above pass on Windows. Browser extension loading and Native Messaging registration are developer setup steps, not end-user packaging; installer and upgrade/uninstall coverage remains in Milestone 7.
