# Experiment 2: Entry Prompt and Window Restoration

This experiment validates the highest-risk interaction in Lock-In's application flow: showing one prompt when a non-allowlisted application enters the foreground, then safely returning to the prior work window or continuing without an immediate prompt loop.

It intentionally excludes schedules, persistence, follow-up timers, browser domains, and production UI styling.

## Behaviors Under Test

- An allowlisted application does not trigger a prompt.
- Entering a non-allowlisted application triggers exactly one prompt.
- Duplicate foreground events do not create duplicate prompts.
- The Lock-In prompt process does not prompt for itself.
- **Return** attempts to restore the most recent allowlisted window.
- **Continue anyway** restores the selected application without immediately prompting again.
- Leaving a continued application and entering it again creates a new prompt.
- Closing the prompt is treated as **Continue anyway**, so the experiment never traps the user.
- Unresolved or inaccessible processes are ignored instead of treated as distractions.

## Automated Tests

```powershell
.venv\Scripts\python -m pytest -v
```

The pure state-machine tests do not open windows. They verify deduplication, self-exclusion, return targets, continue suppression, re-entry behavior, and normalized path comparison.

## Interactive Test

Use the full executable path reported by Experiment 1 for one work application. For example:

```powershell
.venv\Scripts\lock-in-entry-prompt `
    --allow "C:\Windows\System32\notepad.exe" `
    --json `
    --duration 120
```

The command leaves all applications except the listed paths outside the experiment allowlist and stops after two minutes. Omit `--duration 120` to run until `Ctrl+C` in the launching terminal.

Run these checks:

1. Activate the allowlisted application. No prompt should appear.
2. Activate a different application. Exactly one prompt should appear.
3. Choose **Continue anyway**. The target application should regain focus and no second prompt should appear immediately.
4. Switch to the allowlisted application, then back to the same non-allowlisted application. A new prompt should appear.
5. Choose **Return**. The allowlisted application should regain focus.
6. Repeat with a minimized allowlisted window. **Return** should restore it.
7. Rapidly switch among two non-allowlisted applications and confirm that prompts never multiply or form a loop.
8. Try a full-screen application and an elevated application. Record any `activationSucceeded=False` result; Windows may restrict foreground activation across privilege boundaries.
9. Use Task Manager to confirm the prototype is effectively idle when the foreground does not change.

Do not use sensitive application names in a capture you plan to share. Executable paths are used for comparisons but are not emitted by this prototype.

## Acceptance Criteria

The experiment succeeds when:

- The normal allowlisted/non-allowlisted flow behaves correctly in every checklist repetition.
- Neither decision produces an immediate duplicate prompt.
- Re-entering a non-allowlisted application always creates a fresh prompt.
- **Return** reliably restores ordinary, same-privilege desktop applications.
- Failure to restore a protected or elevated window is reported without crashing or blocking input.
- The prototype exits cleanly and leaves no background process.

An elevated target failing to regain focus is not itself a failure of the experiment. The production UI must document and gracefully handle Windows foreground-activation restrictions.
