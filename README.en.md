# Lock-In

English | [简体中文](README.md)

Lock-In is a local focus assistant for Windows. Users define work periods and create allowlists of work-related applications and websites. During a work period, Lock-In displays a prompt whenever the user switches to an application or website outside the allowlist, giving them a moment to reconsider whether they want to continue.

Lock-In does not forcibly block software. Its purpose is to provide an external wake-up signal when unconscious avoidance occurs, turning an automatic action into a conscious choice.

> The project is currently in the product design and prototyping stage. This document describes the planned product functionality.

## Core Principles

- Do not forcibly block applications or websites.
- Do not use entertainment time, points, or streaks as rewards.
- Do not shame or punish the user.
- Always leave the final decision with the user.
- Use objective reviews to help users understand their distraction patterns.
- Store user settings and behavior records locally by default.

## Work Schedules

Users can create one or more work periods, for example:

```text
Start: 13:00
End:   13:40
```

Work schedules support:

- One-time work periods.
- Weekly recurring work periods.
- Enabling, disabling, or deleting a schedule.
- Different application and website allowlists for different schedules.
- Automatically enabling prompts when a work period begins.
- Automatically disabling prompts when a work period ends.

## Application Allowlist

Users can add applications required for work to an allowlist, for example:

```text
Microsoft Word
Microsoft Excel
Visual Studio Code
Notion
```

Applications can be added by:

1. Selecting from recently used applications.
2. Browsing for a local program.
3. Switching to a target window and letting Lock-In identify it.

Allowlisted applications can be used normally during a work period without triggering a prompt.

## Website Allowlist

Users can add work-related website domains to an allowlist, for example:

```text
docs.google.com
github.com
stackoverflow.com
*.company.example
```

Website rules are evaluated by domain and can optionally include subdomains. Lock-In does not inspect page content or record anything the user types into a page.

## Distraction Prompts

When the user switches to a non-allowlisted application or website during a work period, Lock-In displays a prompt:

```text
This application is not on your current work allowlist.

Currently open: Steam
Work period: 13:00–13:40

[Return to previous window]  [Continue anyway]
```

Prompt behavior follows these rules:

- Prompt again whenever the user re-enters a non-allowlisted application.
- Prompt again whenever the user switches to a non-allowlisted website.
- Let the user return to their previous work context.
- Let the user continue using the current application or website.
- Continuing does not cause a penalty or cancel the current work schedule.
- If usage continues for a configured duration, Lock-In can prompt again.
- Stop the current distraction timer when the user returns to allowlisted content.

## Follow-up Prompts During Use

After the user chooses to continue with non-allowlisted content, Lock-In tracks its foreground usage time.

When the configured duration is reached, Lock-In asks again:

```text
You have spent 5 minutes on YouTube.

[Return to work]  [Continue anyway]
```

Time accumulates only while the application or website is actually in the foreground. Leaving it pauses the timer; entering it again triggers a new entry prompt.

## Evening Review

Lock-In sends a local review notification at a user-configured time each day, for example:

```text
Today's work review

Scheduled work time: 80 minutes
Non-allowlisted entries: 7
Returned after a prompt: 5
Chose to continue: 2
Non-allowlisted foreground time: 12 minutes
```

Opening the review shows the day's event history:

```text
13:08  YouTube  Continued, used for 5 minutes
13:20  Steam    Returned after prompt
14:16  Reddit   Returned after prompt
```

The review presents facts only and does not judge the user's choices as good or bad.

## Functional Decision Rules

```text
Is a work period currently active?
        │
        ├── No  → Do not prompt
        │
        └── Yes
             │
             ├── Current content is allowlisted     → Do not prompt
             │
             └── Current content is not allowlisted → Show a prompt
```

Windows system components, File Explorer, Task Manager, password managers, and Lock-In itself do not trigger prompts by default. Users can manage this base system allowlist.

## Settings

Users can configure:

- The default follow-up prompt interval.
- The evening review notification time.
- Whether Lock-In starts with Windows.
- Whether work schedules start automatically.
- Whether system notifications are shown.
- Whether detailed event history is retained.
- How long local data is retained.

## Privacy

- All settings and review records are stored locally by default.
- Complete browsing history is not uploaded.
- Website decisions use only domains and do not read page content.
- Keyboard input, passwords, forms, and page text are never recorded.
- Users can delete all stored records at any time.

## Not Included in the First Release

- Forcibly closing or blocking applications.
- Preventing users from exiting Lock-In.
- Reading web page content or user input.
- Cloud accounts or cross-device synchronization.
- iOS or macOS integration.
- Rewards, points, leaderboards, or streaks.
- AI-based judgments about whether the user is genuinely working.
- Enterprise administrator controls or anti-circumvention features.

For technical design and implementation details, see [ARCHITECTURE.en.md](ARCHITECTURE.en.md).

