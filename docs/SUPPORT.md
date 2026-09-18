# Supported Platforms

This document defines the support target for the first Lock-In release. It is a compatibility policy, not a claim that every listed combination is already production-tested.

## Operating System

| Platform | Policy |
| --- | --- |
| Windows 11 | Supported on Microsoft-supported consumer releases. |
| Windows 10 | Supported on version 22H2 while it remains practical for the project to test and package. |
| Windows Server | Not supported for the first release. |
| macOS and Linux | Not supported by the Windows client. |

Lock-In targets interactive per-user desktop sessions. Remote Desktop, kiosk, service-session, and enterprise enforcement scenarios are outside the first-release support boundary.

## Python

- Minimum source-development version: Python 3.12.
- The automated baseline currently also runs on Python 3.14.
- Production packages will bundle their runtime; end users should not need to install Python.

Dropping a Python version requires an architecture decision and a documented packaging reason.

## Browsers

The first release targets:

- Google Chrome stable.
- Microsoft Edge stable.

The project aims to test the current stable major version and the immediately previous stable major version. Brave and other Chromium browsers remain experimental until they receive their own Native Messaging registration and release tests.

Firefox, browser-sync services, mobile browsers, and managed enterprise policies are outside the first release.

## Development Tooling

- PowerShell is required for the Windows baseline verification command.
- Node.js 20 or newer is required to syntax-check the browser extension.
- Ruff and pytest are installed through the `dev` optional dependency with bounded version ranges.

## Display and Session Coverage

Before release, manual testing must include:

- One and multiple monitors.
- Mixed DPI scaling.
- Full-screen windows.
- Standard and elevated target applications.
- Lock, unlock, sleep, resume, sign-out, and shutdown.

## Degraded Behavior

Unsupported, inaccessible, or ambiguous contexts must fail open. Lock-In may report component health, but it must not block input, close applications, or classify an unknown browser page as non-allowlisted.
